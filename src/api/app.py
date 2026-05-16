"""
FastAPI application — routes and middleware.
"""
from datetime import date
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse

from src.config import settings
from src.api.routes import profile, accounts, budget, life_events, projection, income, settings_route
from starlette.exceptions import HTTPException as StarletteHTTPException

from src.api.routes import investments
import logging
logger = logging.getLogger(__name__)

app = FastAPI(title=settings.app_name)

# Mount static files
app.mount("/static", StaticFiles(directory=settings.static_dir), name="static")

# Use shared templates instance and register globals after helpers are defined

# Register routers
app.include_router(profile.router)
app.include_router(accounts.router)
app.include_router(budget.router)
app.include_router(life_events.router)
app.include_router(income.router)
app.include_router(settings_route.router)
app.include_router(projection.router)
app.include_router(investments.router)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_user_initials() -> str:
    """Read first and last name from Person_1 and return initials."""
    from src.store.graph import store, MRL, DATA_GRAPH
    import pyoxigraph as og
    person = og.NamedNode(f"{MRL}Person_1")
    def _val(prop):
        qs = list(store.store.quads_for_pattern(
            person, og.NamedNode(f"{MRL}{prop}"), None, DATA_GRAPH))
        return str(qs[0].object.value) if qs else ""
    first = _val("firstName")
    last = _val("lastName")
    initials = ""
    if first:
        initials += first[0].upper()
    if last:
        initials += last[0].upper()
    return initials or "?"


# Register user_initials as a Jinja2 global on the shared templates instance
# Must be after get_user_initials is defined
from src.api.templates import templates as _shared_templates
_shared_templates.env.globals["user_initials"] = get_user_initials


def get_setup_state() -> dict:
    from src.store.graph import store, MRL, DATA_GRAPH
    from src.api.routes.projection import load_all_income_sources, load_accounts
    from src.api.routes.investments import get_all_investment_accounts
    from src.api.routes.profile import get_profile
    import pyoxigraph as og

    RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
    prof = get_profile()
    has_profile = prof is not None
    has_income = len(load_all_income_sources()) > 0
    has_accounts = len(load_accounts()) > 0
    has_investments = len(get_all_investment_accounts()) > 0
    type_node = og.NamedNode(f"{MRL}BudgetLine")
    has_budget = len(list(store.store.quads_for_pattern(
        None, og.NamedNode(RDF_TYPE), type_node, DATA_GRAPH))) > 0
    all_done = has_profile and has_income and has_accounts and has_investments and has_budget
    if not has_profile:
        next_url, next_label = "/profile", "Set up your profile"
    elif not has_income:
        next_url, next_label = "/income", "Add your income"
    elif not has_accounts:
        next_url, next_label = "/accounts", "Add a cash account"
    elif not has_investments:
        next_url, next_label = "/investments", "Add an investment account"
    elif not has_budget:
        next_url, next_label = "/budget", "Add your budget"
    else:
        next_url, next_label = "/projection", "View your projection"
    return {
        "setup_all_done": all_done,
        "setup_steps_done": sum([has_profile, has_income, has_accounts,
                                  has_investments, has_budget]),
        "setup_next_url": next_url,
        "setup_next_label": next_label,
        "setup_has_profile": has_profile,
        "setup_has_income": has_income,
        "setup_has_accounts": has_accounts,
        "setup_has_investments": has_investments,
        "setup_has_budget": has_budget,
    }


_shared_templates.env.globals["setup_state"] = get_setup_state


def get_dashboard_data() -> dict:
    """Load all data needed for the dashboard."""
    from src.store.graph import store, MRL, DATA_GRAPH
    from src.api.routes.projection import (
        run_projection, get_projection_settings,
        load_accounts as _load_accounts,
        load_budget_lines as _load_budget_lines,
        load_all_income_sources as _load_income,
    )
    from src.api.routes.profile import get_profile
    import pyoxigraph as og

    RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"

    # Profile
    prof = get_profile()

    # Income sources
    income_sources = _load_income()
    income_count = len(income_sources)

    # Accounts
    accs = _load_accounts()
    account_count = len(accs)
    total_balance = sum(a["balance"] for a in accs)

    # Budget lines
    lines = _load_budget_lines()
    budget_line_count = len(lines)
    annual_spending = sum(l["annual_amount"] for l in lines)

    # Life event count
    type_node = og.NamedNode(f"{MRL}LifeEvent")
    life_event_count = len(list(store.store.quads_for_pattern(
        None, og.NamedNode(RDF_TYPE), type_node, DATA_GRAPH)))

    # Years to retirement
    years_to_retirement = None
    if prof:
        try:
            dob = date.fromisoformat(prof.get("dateOfBirth", ""))
            birth_year = dob.year
            retirement_age = int(prof.get("targetRetirementAge", 67))
            retirement_year = birth_year + retirement_age
            years_to_retirement = max(0, retirement_year - date.today().year)
        except (ValueError, TypeError):
            pass

    # Projection
    proj_settings = get_projection_settings()
    proj = run_projection(proj_settings["inflation_rate"]) if prof and accs else None

    return {
        "profile": prof,
        "income_count": income_count,
        "account_count": account_count,
        "total_balance": round(total_balance, 0) if total_balance else 0,
        "budget_line_count": budget_line_count,
        "annual_spending": round(annual_spending, 0) if annual_spending else 0,
        "life_event_count": life_event_count,
        "years_to_retirement": years_to_retirement,
        "projection": proj,
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Exception handlers
# ---------------------------------------------------------------------------

@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    from src.api.templates import templates
    if exc.status_code == 404:
        return templates.TemplateResponse(
            request=request,
            name="error.html",
            status_code=404,
            context={
                "app_name": settings.app_name,
                "active": "",
                "error_detail": f"Page not found: {request.url.path}",
            }
        )
    return templates.TemplateResponse(
        request=request,
        name="error.html",
        status_code=exc.status_code,
        context={
            "app_name": settings.app_name,
            "active": "",
            "error_detail": str(exc.detail),
        }
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception on {request.url.path}: {exc}", exc_info=True)
    from src.api.templates import templates
    return templates.TemplateResponse(
        request=request,
        name="error.html",
        status_code=500,
        context={
            "app_name": settings.app_name,
            "active": "",
            "error_detail": str(exc),
        }
    )


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Main dashboard view."""
    data = get_dashboard_data()
    from src.api.templates import templates
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "app_name": settings.app_name,
            "active": "dashboard",
            **data,
        }
    )


@app.get("/health")
async def health():
    return {"status": "ok", "app": settings.app_name}


@app.get("/ontology/status")
async def ontology_status():
    from src.store.graph import store
    from src.store.ontology_loader import ONTOLOGY_GRAPH, ontology_triple_count
    return {
        "ontology_graph": str(ONTOLOGY_GRAPH),
        "ontology_triples": ontology_triple_count(store.store),
        "total_triples": len(store),
    }