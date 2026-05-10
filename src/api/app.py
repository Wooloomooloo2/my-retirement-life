"""
FastAPI application - routes and middleware.
"""
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from src.config import settings

app = FastAPI(title=settings.app_name)

# Mount static files (CSS, JS)
app.mount("/static", StaticFiles(directory=settings.static_dir), name="static")

# Jinja2 templates
templates = Jinja2Templates(directory=settings.templates_dir)


@app.get("/")
async def dashboard(request: Request):
    """Main dashboard view."""
    return templates.TemplateResponse(
    request=request,
    name="dashboard.html",
    context={"app_name": settings.app_name}
)


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok", "app": settings.app_name}
