"""
Scenarios routes — named session management.

GET  /scenarios              — scenarios management page
POST /scenarios/save         — overwrite current scenario file
POST /scenarios/save-as      — save current data with a new name
POST /scenarios/load         — load a saved scenario into the data graph
POST /scenarios/new          — clear the data graph and start fresh
POST /scenarios/rename       — rename a scenario file
POST /scenarios/delete       — delete a scenario file
"""
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from src.api.templates import templates
from src.config import settings

router = APIRouter()


def _mgr():
    """Lazy accessor so the singleton is always the current one."""
    from src.store.scenario_manager import scenario_manager
    return scenario_manager


def _page(request: Request, message: str = "", message_type: str = ""):
    """Render the scenarios page with fresh state."""
    mgr = _mgr()
    return templates.TemplateResponse(
        request=request,
        name="scenarios.html",
        context={
            "app_name":       settings.app_name,
            "active":         "settings",
            "scenario_state": mgr.get_state(),
            "scenarios":      mgr.list_scenarios(),
            "message":        message,
            "message_type":   message_type,
        }
    )


# ---------------------------------------------------------------------------
# GET
# ---------------------------------------------------------------------------

@router.get("/scenarios", response_class=HTMLResponse)
async def scenarios_page(request: Request):
    return _page(request)


# ---------------------------------------------------------------------------
# Save / Save As
# ---------------------------------------------------------------------------

@router.post("/scenarios/save", response_class=HTMLResponse)
async def save_scenario(request: Request):
    """Overwrite the current named scenario file with the latest data."""
    mgr   = _mgr()
    state = mgr.get_state()

    if not state["is_named"]:
        # No name yet — redirect to the page so the user fills in Save As
        return _page(request,
                     "No scenario name set. Use 'Save As' to name this session.",
                     "warning")

    from src.api.routes.settings_route import export_all_data
    success, msg = mgr.save(state["name"], export_all_data())
    return _page(request, msg, "success" if success else "error")


@router.post("/scenarios/save-as", response_class=HTMLResponse)
async def save_as_scenario(
    request: Request,
    scenario_name: str = Form(...),
):
    """Save current data as a new or existing scenario name."""
    name = scenario_name.strip()
    if not name:
        return _page(request, "Please enter a scenario name.", "warning")

    from src.api.routes.settings_route import export_all_data
    success, msg = _mgr().save(name, export_all_data())
    return _page(request, msg, "success" if success else "error")


# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------

@router.post("/scenarios/load", response_class=HTMLResponse)
async def load_scenario(
    request: Request,
    scenario_name: str = Form(...),
):
    """Restore a saved scenario into the data graph."""
    mgr  = _mgr()
    data, msg = mgr.load(scenario_name)

    if data is None:
        return _page(request, msg, "error")

    from src.api.routes.settings_route import restore_all_data
    success, restore_msg = restore_all_data(data)

    if success:
        mgr.mark_loaded(scenario_name)
        return _page(request, f"Loaded '{scenario_name}'.", "success")
    else:
        return _page(request, f"Restore failed: {restore_msg}", "error")


# ---------------------------------------------------------------------------
# New
# ---------------------------------------------------------------------------

@router.post("/scenarios/new", response_class=HTMLResponse)
async def new_scenario(request: Request):
    """Clear the data graph and begin a fresh unnamed session."""
    from src.store.graph import store, DATA_GRAPH

    store.update(f"""
        DELETE WHERE {{
            GRAPH <{DATA_GRAPH.value}> {{
                ?s ?p ?o .
            }}
        }}
    """)
    _mgr().set_new_session()

    return _page(
        request,
        "New session started — all previous data has been cleared. "
        "Complete the setup steps to begin a new scenario.",
        "info",
    )


# ---------------------------------------------------------------------------
# Rename
# ---------------------------------------------------------------------------

@router.post("/scenarios/rename", response_class=HTMLResponse)
async def rename_scenario(
    request: Request,
    old_name: str = Form(...),
    new_name: str = Form(...),
):
    success, msg = _mgr().rename(old_name.strip(), new_name.strip())
    return _page(request, msg, "success" if success else "error")


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

@router.post("/scenarios/delete", response_class=HTMLResponse)
async def delete_scenario(
    request: Request,
    scenario_name: str = Form(...),
):
    success, msg = _mgr().delete(scenario_name)
    return _page(request, msg, "success" if success else "error")
