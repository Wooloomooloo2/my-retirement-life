"""
FastAPI application — routes and middleware.
"""
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse

from src.config import settings
from src.api.routes import profile, accounts, budget

app = FastAPI(title=settings.app_name)

# Mount static files (CSS, JS)
app.mount("/static", StaticFiles(directory=settings.static_dir), name="static")

# Jinja2 templates
templates = Jinja2Templates(directory=settings.templates_dir)

# Register routers
app.include_router(profile.router)
app.include_router(accounts.router)
app.include_router(budget.router)


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Main dashboard view."""
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={"app_name": settings.app_name, "active": "dashboard"}
    )


@app.get("/health")
async def health():
    return {"status": "ok", "app": settings.app_name}


@app.get("/ontology/status")
async def ontology_status():
    from src.store.graph import store
    from src.store.ontology_loader import ONTOLOGY_GRAPH, ontology_triple_count
    ontology_count = ontology_triple_count(store.store)
    total_count = len(store)
    return {
        "ontology_graph": str(ONTOLOGY_GRAPH),
        "ontology_triples": ontology_count,
        "total_triples": total_count
    }


@app.get("/debug/data")
async def debug_data():
    from src.store.graph import store, DATA_GRAPH
    quads = list(store.store.quads_for_pattern(None, None, None, DATA_GRAPH))
    triples = [
        {
            "s": str(q.subject.value),
            "p": str(q.predicate.value),
            "o": str(q.object.value),
        }
        for q in quads
    ]
    return {"count": len(triples), "triples": triples}
