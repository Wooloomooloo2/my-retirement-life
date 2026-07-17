"""
My Retirement Life — application entry point.

Startup sequence:
  1. Load ontology TTL into Oxigraph store
  2. Bind the listening socket on the main thread, so a port conflict is a
     fatal, legible error rather than a silent failure inside a daemon thread
  3. Hand the bound socket to uvicorn, running in a background daemon thread
  4. Poll /health until the server is ready AND identifies itself as this app
  5. Open the dashboard in a native OS webview window (blocks main thread)

The webview library uses each platform's native engine:
  - macOS:   WKWebView (via pyobjc)
  - Windows: WebView2 (via pythonnet + Edge runtime)
  - Linux:   WebKitGTK (via PyGObject)

webview.start() must run on the main thread on macOS, so uvicorn lives in a
daemon thread instead. When the window closes, the process exits and the
daemon thread is torn down with it.
"""
import json
import logging
import socket
import threading
import time
from urllib.error import URLError
from urllib.request import urlopen

import uvicorn
import webview

from src.config import APP_ID, settings
from src.store.graph import store
from src.store.ontology_loader import load_ontology

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


def _identify(url: str, timeout: float = 0.5) -> str | None:
    """Return the service id reported by /health at url, or None if unknown."""
    try:
        with urlopen(f"{url}/health", timeout=timeout) as r:
            if r.status != 200:
                return None
            return json.load(r).get("service")
    except (URLError, ConnectionError, TimeoutError, OSError, ValueError):
        return None


def _bind_or_die(host: str, port: int) -> socket.socket:
    """
    Bind the server's listening socket on the main thread.

    uvicorn binds inside its own run loop, so when it runs in a daemon thread a
    failed bind kills only that thread — the launcher sails on and opens a
    window against whatever else already holds the port. Binding here instead
    makes the conflict fatal and tells the user who took the port.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind((host, port))
    except OSError as e:
        sock.close()
        url = f"http://{host}:{port}"
        squatter = _identify(url)
        if squatter == APP_ID:
            who = f"another copy of {settings.app_name} is already running there"
        elif squatter:
            who = f"it is held by a different app identifying itself as {squatter!r}"
        else:
            who = "it is held by another process"
        raise SystemExit(
            f"Cannot start {settings.app_name}: {host}:{port} is unavailable — "
            f"{who} ({e}).\n"
            f"Find it with:  lsof -nP -iTCP:{port} -sTCP:LISTEN\n"
            f"Or run this app on a free port by setting APP_PORT in .env"
        ) from e
    sock.listen(128)
    return sock


def _wait_for_server(
    url: str, thread: threading.Thread, timeout: float = 15.0
) -> None:
    """
    Poll /health until our own server answers, or we exceed the timeout.

    A 200 alone is not proof of life: sibling apps on this machine serve their
    own /health, so the probe also requires the response to identify itself as
    APP_ID before we point a window at it.
    """
    deadline = time.monotonic() + timeout
    seen: str | None = None
    while time.monotonic() < deadline:
        seen = _identify(url)
        if seen == APP_ID:
            return
        if not thread.is_alive():
            raise SystemExit(
                "Server thread exited before becoming ready; "
                "see the traceback above."
            )
        time.sleep(0.1)
    detail = (
        f"a server identifying as {seen!r} answered instead"
        if seen
        else "nothing answered"
    )
    raise SystemExit(
        f"Server did not become ready at {url} within {timeout}s — {detail}."
    )


if __name__ == "__main__":
    logger.info("Initialising triple store...")
    load_ontology(store.store)

    # Eager import so any startup-time import failure surfaces here, not
    # silently inside the daemon thread.
    from src.api.app import app

    sock = _bind_or_die(settings.app_host, settings.app_port)

    server = uvicorn.Server(
        uvicorn.Config(app, reload=False, log_level="info")
    )

    def _serve() -> None:
        try:
            server.run(sockets=[sock])
        except BaseException:
            logger.exception("Server thread died")

    thread = threading.Thread(target=_serve, daemon=True)
    thread.start()

    url = f"http://{settings.app_host}:{settings.app_port}"
    logger.info("Waiting for server at %s", url)
    _wait_for_server(url, thread)

    logger.info("Opening application window")
    webview.create_window(
        title=settings.app_name,
        url=url,
        width=1400,
        height=900,
        min_size=(900, 600),
        resizable=True,
    )
    webview.start()
