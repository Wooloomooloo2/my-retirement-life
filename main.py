"""
My Retirement Life — application entry point.

Startup sequence:
  1. Load ontology TTL into Oxigraph store
  2. Start FastAPI server via uvicorn
  3. Open browser automatically
"""
import logging
import threading
import webbrowser

import uvicorn

from src.config import settings
from src.store.graph import store
from src.store.ontology_loader import load_ontology

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


def open_browser():
    """Open the browser after a short delay to allow the server to start."""
    import time
    time.sleep(1.5)
    webbrowser.open(f"http://{settings.app_host}:{settings.app_port}")


if __name__ == "__main__":
    # Load ontology into the triple store before starting the server
    logger.info("Initialising triple store...")
    load_ontology(store.store)

    # Open browser automatically
    threading.Thread(target=open_browser, daemon=True).start()

    # Start the server
    from src.api.app import app
    uvicorn.run(
        app,
        host=settings.app_host,
        port=settings.app_port,
        reload=False,
    )
