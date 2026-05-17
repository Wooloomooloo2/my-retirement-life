"""
Life events routes — manage significant future financial events.

GET  /life-events              — list all life events + add form
POST /life-events              — create a new life event
GET  /life-events/{n}/edit     — load edit form for life event N
POST /life-events/{n}/edit     — save edits to life event N
POST /life-events/{n}/delete   — delete life event N

Changes (ADR-011):
  get_all_events() reads fundedByAccount and receivedByAccount.
  save_event() persists those optional account routing fields.
  _page_context() runs run_projection() to supply per-account balance
  histories to the template for the live affordability hint in the form.
"""
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse
from src.api.templates import templates
import pyoxigraph as og

from src.config import settings
from src.store.graph import store, MRL, DATA_GRAPH

router = APIRouter()

RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
MRL_EXT  = "https://myretirementlife.app/ontology/ext#"

EVENT_TYPE_LABELS = {
    "LifeEventType_LargeExpenditure":   "Large expenditure",
    "LifeEventType_Windfall":           "Windfall (receipt)",
    "LifeEventType_PropertyTransaction":"Property transaction",
    "LifeEventType_RelocationAbroad":   "Relocation abroad",
    "LifeEventType_CaringResponsibility":"Caring responsibility",
}


# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------

def _iri_local(full_iri: str) -> str:
    return full_iri.split("#")[-1] if "#" in full_iri else full_iri


def get_all_events() -> list:
    """Return all LifeEvent instances, including account routing fields (ADR-011)."""
    type_node = og.NamedNode(f"{MRL}LifeEvent")
    quads = store.store.quads_for_pattern(
        None, og.NamedNode(RDF_TYPE), type_node, DATA_GRAPH)
    events = []
    for q in quads:
        iri = q.subject
        n   = str(iri.value).split("LifeEvent_")[-1]

        def get_val(prop):
            qs = list(store.store.quads_for_pattern(
                iri, og.NamedNode(f"{MRL}{prop}"), None, DATA_GRAPH))
            return str(qs[0].object.value) if qs else ""

        def get_local(prop):
            v = get_val(prop)
            return v.split("#")[-1] if "#" in v else v

        funded_qs   = list(store.store.quads_for_pattern(
            iri, og.NamedNode(f"{MRL}fundedByAccount"),   None, DATA_GRAPH))
        received_qs = list(store.store.quads_for_pattern(
            iri, og.NamedNode(f"{MRL}receivedByAccount"), None, DATA_GRAPH))

        event_type = get_local("lifeEventType")
        events.append({
            "n":               n,
            "iri":             str(iri.value),
            "name":            get_val("lifeEventName"),
            "year":            get_val("lifeEventYear"),
            "amount":          get_val("lifeEventAmount"),
            "eventType":       event_type,
            "eventTypeLabel":  EVENT_TYPE_LABELS.get(event_type, ""),
            "notes":           get_val("lifeEventNotes"),
            # ADR-011: account routing
            "fundedByAccount":   _iri_local(str(funded_qs[0].object.value))   if funded_qs   else "",
            "receivedByAccount": _iri_local(str(received_qs[0].object.value)) if received_qs else "",
        })
    events.sort(key=lambda e: int(e["year"]) if e["year"].isdigit() else 0)
    return events


def save_event(
    n: int,
    name: str,
    year: int,
    amount: float,
    event_type: str,
    notes: str,
    funded_by_account: str   = "",
    received_by_account: str = "",
) -> None:
    """Write or overwrite a LifeEvent_N instance in the data graph.

    funded_by_account and received_by_account are account labels
    (e.g. "CashAccount_1") or empty strings to clear the routing.
    """
    event_iri  = f"{MRL}LifeEvent_{n}"
    person_iri = f"{MRL}Person_1"

    store.update(f"""
        DELETE WHERE {{
            GRAPH <{DATA_GRAPH.value}> {{
                <{event_iri}> ?p ?o .
            }}
        }}
    """)

    triples = f"""
        <{event_iri}> a mrl:LifeEvent ;
            mrl:lifeEventName   "{name}" ;
            mrl:lifeEventYear   "{year}"^^xsd:integer ;
            mrl:lifeEventAmount "{amount}"^^xsd:decimal ;
            mrl:lifeEventType   mrlx:{event_type} ;
            mrl:lifeEventOwner  <{person_iri}> .
    """

    if notes and notes.strip():
        safe_notes = notes.replace('"', '\\"')
        triples += f'\n        <{event_iri}> mrl:lifeEventNotes "{safe_notes}" .'

    if funded_by_account and funded_by_account.strip():
        triples += f'\n        <{event_iri}> mrl:fundedByAccount mrl:{funded_by_account.strip()} .'

    if received_by_account and received_by_account.strip():
        triples += f'\n        <{event_iri}> mrl:receivedByAccount mrl:{received_by_account.strip()} .'

    store.update(f"""
        PREFIX mrl:  <{MRL}>
        PREFIX mrlx: <{MRL_EXT}>
        PREFIX xsd:  <http://www.w3.org/2001/XMLSchema#>
        INSERT DATA {{
            GRAPH <{DATA_GRAPH.value}> {{
                {triples}
            }}
        }}
    """)


def _get_projection_data() -> dict | None:
    """Run a deterministic projection and return the data needed for balance hints.

    Returns None if no profile or accounts are set up yet — the template
    gracefully hides the account pickers in that case.
    """
    try:
        from src.api.routes.projection import (
            run_projection, get_projection_settings,
        )
        proj_settings = get_projection_settings()
        projection    = run_projection(proj_settings["inflation_rate"], proj_settings)
        if not projection:
            return None
        return {
            "account_balances": projection["account_balances"],  # {label: [y0, y1, ...]}
            "account_names":    projection["account_names"],     # {label: human name}
            "account_classes":  projection["account_classes"],   # {label: class string}
            "current_year":     projection["current_year"],
            "end_year":         projection["end_year"],
            # Flat list for the select options (sorted by draw priority via load_all_accounts)
            "accounts": [
                {"label": label, "name": name,
                 "account_class": projection["account_classes"][label]}
                for label, name in projection["account_names"].items()
            ],
        }
    except Exception:
        return None


def _page_context(request, events, edit_event=None, **kwargs):
    proj_data = _get_projection_data()
    return {
        "app_name":           settings.app_name,
        "active":             "life-events",
        "events":             events,
        "event_type_options": EVENT_TYPE_LABELS,
        "edit_event":         edit_event,
        "proj_data":          proj_data,
        **kwargs,
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/life-events", response_class=HTMLResponse)
async def life_events_page(request: Request):
    events = get_all_events()
    return templates.TemplateResponse(
        request=request,
        name="life_events.html",
        context=_page_context(request, events),
    )


@router.post("/life-events", response_class=HTMLResponse)
async def add_life_event(
    request: Request,
    lifeEventName:       str   = Form(...),
    lifeEventYear:       int   = Form(...),
    lifeEventAmount:     float = Form(...),
    lifeEventType:       str   = Form("LifeEventType_LargeExpenditure"),
    lifeEventNotes:      str   = Form(""),
    fundedByAccount:     str   = Form(""),
    receivedByAccount:   str   = Form(""),
):
    existing = get_all_events()
    next_n   = max([int(e["n"]) for e in existing if e["n"].isdigit()], default=0) + 1
    save_event(
        next_n, lifeEventName, lifeEventYear,
        lifeEventAmount, lifeEventType, lifeEventNotes,
        funded_by_account=fundedByAccount,
        received_by_account=receivedByAccount,
    )
    events = get_all_events()
    return templates.TemplateResponse(
        request=request,
        name="life_events.html",
        context=_page_context(request, events, saved=True),
    )


@router.get("/life-events/{n}/edit", response_class=HTMLResponse)
async def edit_event_form(request: Request, n: int):
    events     = get_all_events()
    edit_event = next((e for e in events if e["n"] == str(n)), None)
    return templates.TemplateResponse(
        request=request,
        name="life_events.html",
        context=_page_context(request, events, edit_event=edit_event),
    )


@router.post("/life-events/{n}/edit", response_class=HTMLResponse)
async def save_edit_event(
    request: Request,
    n: int,
    lifeEventName:       str   = Form(...),
    lifeEventYear:       int   = Form(...),
    lifeEventAmount:     float = Form(...),
    lifeEventType:       str   = Form("LifeEventType_LargeExpenditure"),
    lifeEventNotes:      str   = Form(""),
    fundedByAccount:     str   = Form(""),
    receivedByAccount:   str   = Form(""),
):
    save_event(
        n, lifeEventName, lifeEventYear,
        lifeEventAmount, lifeEventType, lifeEventNotes,
        funded_by_account=fundedByAccount,
        received_by_account=receivedByAccount,
    )
    events = get_all_events()
    return templates.TemplateResponse(
        request=request,
        name="life_events.html",
        context=_page_context(request, events, saved=True),
    )


@router.post("/life-events/{n}/delete", response_class=HTMLResponse)
async def delete_event(request: Request, n: int):
    event_iri = f"{MRL}LifeEvent_{n}"
    store.update(f"""
        DELETE WHERE {{
            GRAPH <{DATA_GRAPH.value}> {{
                <{event_iri}> ?p ?o .
            }}
        }}
    """)
    events = get_all_events()
    return templates.TemplateResponse(
        request=request,
        name="life_events.html",
        context=_page_context(request, events, deleted=True),
    )