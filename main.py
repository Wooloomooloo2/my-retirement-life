"""
My Retirement Life — application entry point.

Startup sequence:
  1. Load ontology TTL into Oxigraph store
  2. Start FastAPI server via uvicorn in a background daemon thread
  3. Poll /health until the server is ready
  4. Open the dashboard in a native OS webview window (blocks main thread)

The webview library uses each platform's native engine:
  - macOS:   WKWebView (via pyobjc)
  - Windows: WebView2 (via pythonnet + Edge runtime)
  - Linux:   WebKitGTK (via PyGObject)

webview.start() must run on the main thread on macOS, so uvicorn lives in a
daemon thread instead. When the window closes, the process exits and the
daemon thread is torn down with it.
"""
import logging
import threading
import time
from urllib.error import URLError
from urllib.request import urlopen

import uvicorn
import webview

from src.config import settings
from src.store.graph import store
from src.store.ontology_loader import load_ontology

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


def _wait_for_server(url: str, timeout: float = 15.0) -> None:
    """Poll /health until it 200s or we exceed the timeout."""
    deadline = time.monotonic() + timeout
    last_err: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urlopen(f"{url}/health", timeout=0.5) as r:
                if r.status == 200:
                    return
        except (URLError, ConnectionError, TimeoutError, OSError) as e:
            last_err = e
        time.sleep(0.1)
    raise RuntimeError(
        f"Server did not become ready at {url} within {timeout}s "
        f"(last error: {last_err})"
    )


if __name__ == "__main__":
    logger.info("Initialising triple store...")
    load_ontology(store.store)

    # Eager import so any startup-time import failure surfaces here, not
    # silently inside the daemon thread.
    from src.api.app import app

    def _serve() -> None:
        uvicorn.run(
            app,
            host=settings.app_host,
            port=settings.app_port,
            reload=False,
            log_level="info",
        )

    threading.Thread(target=_serve, daemon=True).start()

    url = f"http://{settings.app_host}:{settings.app_port}"
    logger.info("Waiting for server at %s", url)
    _wait_for_server(url)

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
