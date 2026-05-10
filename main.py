"""
My Retirement Life - Main application entry point
"""
import webbrowser
import threading
import uvicorn
from src.api.app import app
from src.config import settings


def open_browser():
    """Open the browser after a short delay to allow the server to start."""
    import time
    time.sleep(1.5)
    webbrowser.open(f"http://{settings.app_host}:{settings.app_port}")


if __name__ == "__main__":
    # Open browser automatically when running locally
    threading.Thread(target=open_browser, daemon=True).start()

    uvicorn.run(
        app,
        host=settings.app_host,
        port=settings.app_port,
        reload=False,
    )
