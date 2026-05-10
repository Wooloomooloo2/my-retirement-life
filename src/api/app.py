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

@app.get("/ontology/status")
async def ontology_status():
    """Show how many triples are in each named graph."""
    from src.store.graph import store
    from src.store.ontology_loader import ONTOLOGY_GRAPH, ontology_triple_count
    ontology_count = ontology_triple_count(store.store)
    total_count = len(store)
    return {
        "ontology_graph": str(ONTOLOGY_GRAPH),
        "ontology_triples": ontology_count,
        "total_triples": total_count
    }