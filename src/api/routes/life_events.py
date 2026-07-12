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
    "LifeEventType_BuyAsset":           "Buy asset",
    "LifeEventType_Windfall":           "Windfall (receipt)",
    "LifeEventType_AssetSale":          "Sell asset",
    "LifeEventType_RelocationAbroad":   "Relocation abroad",
    "LifeEventType_CaringResponsibility":"Caring responsibility",
    # Deprecated 1.0.11 — kept only so pre-existing data still renders a label.
    # Migrated to BuyAsset on load; never offered in the form.
    "LifeEventType_PropertyTransaction":"Property transaction (deprecated)",
}

# The type the deprecated "Property transaction" becomes. It was never in
# RECEIPT_EVENT_TYPES, so it always stored a POSITIVE amount — it could only ever
# model a purchase, despite its name suggesting it covered both. Migrating it to
# BuyAsset preserves the sign and therefore the projection, exactly.
LEGACY_TYPE_MIGRATION = {
    "LifeEventType_PropertyTransaction": "LifeEventType_BuyAsset",
}

# Types offered in the user's add/edit form.
#
# "Sell asset" (AssetSale) IS offered now (1.0.11), but it does not create an
# event directly: the handler writes the sale through to the chosen PhysicalAsset,
# and the asset's existing auto-managed event is what appears. The asset stays the
# single source of truth — the engine zeroes it from its sale year, and two
# independent records of one sale would double-count the proceeds.
USER_EVENT_TYPE_OPTIONS = {
    k: v for k, v in EVENT_TYPE_LABELS.items()
    if k not in ("LifeEventType_PropertyTransaction",)
}

# The type whose form writes through to an asset rather than saving an event.
ASSET_SALE_TYPE = "LifeEventType_AssetSale"

# Event types that represent money flowing IN. The projection engine's
# convention (set up in projection.py year-loop step 5) is:
#   amount >= 0 → cost  (debited from funded_by_account, or general_costs)
#   amount <  0 → receipt (credited to received_by_account, or general_receipts)
# We normalise on the server so the convention can't be violated by a
# missed client-side sign-flip — the user types a positive number; the
# server stores it with the right sign for the event type.
RECEIPT_EVENT_TYPES = {
    "LifeEventType_Windfall",
    "LifeEventType_AssetSale",
}


def migrate_legacy_event_types() -> int:
    """Rewrite deprecated life-event types in place (ontology 1.0.11).

    PropertyTransaction → BuyAsset. Idempotent, and projection-neutral: the sign
    convention is unchanged (both are costs), so the migrated event debits exactly
    what it debited before. Runs on the Life Events page render, matching the
    ADR-017 legacy-budget-line and ADR-018 drawdownMaxAge precedents.
    """
    migrated = 0
    for old_type, new_type in LEGACY_TYPE_MIGRATION.items():
        quads = list(store.store.quads_for_pattern(
            None,
            og.NamedNode(f"{MRL}lifeEventType"),
            og.NamedNode(f"{MRL_EXT}{old_type}"),
            DATA_GRAPH,
        ))
        for q in quads:
            store.update(f"""
                PREFIX mrl:  <{MRL}>
                PREFIX mrlx: <{MRL_EXT}>
                DELETE {{ GRAPH <{DATA_GRAPH.value}> {{
                    <{q.subject.value}> mrl:lifeEventType mrlx:{old_type} . }} }}
                INSERT {{ GRAPH <{DATA_GRAPH.value}> {{
                    <{q.subject.value}> mrl:lifeEventType mrlx:{new_type} . }} }}
                WHERE {{ }}
            """)
            migrated += 1
    return migrated


def _normalise_event_amount(amount: float, event_type: str) -> float:
    """Force the sign of a life-event amount to match the engine's convention.

    Receipts (Windfall, AssetSale) must be stored negative; everything else
    must be stored positive. The user types a positive number; this function
    flips the sign when needed.
    """
    magnitude = abs(amount)
    return -magnitude if event_type in RECEIPT_EVENT_TYPES else magnitude


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

        # Phase 2: source asset back-link for auto-managed asset-sale events
        source_qs = list(store.store.quads_for_pattern(
            iri, og.NamedNode(f"{MRL}sourceAsset"), None, DATA_GRAPH))
        source_asset_iri   = str(source_qs[0].object.value) if source_qs else ""
        source_asset_label = _iri_local(source_asset_iri) if source_asset_iri else ""
        source_asset_name  = ""
        if source_asset_iri:
            # Resolve the asset's display name so the template can show
            # "Source: {asset name}" without a second SPARQL trip from the view layer.
            name_qs = list(store.store.quads_for_pattern(
                og.NamedNode(source_asset_iri),
                og.NamedNode(f"{MRL}accountName"),
                None, DATA_GRAPH))
            source_asset_name = str(name_qs[0].object.value) if name_qs else source_asset_label

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
            # Phase 2: auto-managed marker — empty for user-created events
            "sourceAsset":       source_asset_label,
            "sourceAssetName":   source_asset_name,
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
    source_asset_label: str  = "",
) -> None:
    """Write or overwrite a LifeEvent_N instance in the data graph.

    funded_by_account and received_by_account are account labels
    (e.g. "CashAccount_1") or empty strings to clear the routing.

    source_asset_label, when set, links this event back to a mrl:PhysicalAsset
    instance via mrl:sourceAsset. Used by Phase 2 for auto-managed asset-sale
    events.
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

    safe_name = name.replace('"', '\\"')
    triples = f"""
        <{event_iri}> a mrl:LifeEvent ;
            mrl:lifeEventName   "{safe_name}" ;
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

    if source_asset_label and source_asset_label.strip():
        triples += f'\n        <{event_iri}> mrl:sourceAsset mrl:{source_asset_label.strip()} .'

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


# ---------------------------------------------------------------------------
# Asset-sourced event helpers (Phase 2)
#
# Auto-managed events use mrl:sourceAsset → the PhysicalAsset that generated
# them. These helpers let accounts.py sync the event lifecycle with the asset's
# without needing to know LifeEvent's N counter or SPARQL details.
# ---------------------------------------------------------------------------

def find_event_n_by_source_asset(source_asset_label: str) -> int | None:
    """Return the N of the LifeEvent linked to the given asset, or None.

    Assets have at most one managed sale event; this lookup is unique.
    """
    if not source_asset_label:
        return None
    source_iri = og.NamedNode(f"{MRL}{source_asset_label}")
    quads = list(store.store.quads_for_pattern(
        None, og.NamedNode(f"{MRL}sourceAsset"), source_iri, DATA_GRAPH))
    for q in quads:
        ev_iri = str(q.subject.value)
        if "LifeEvent_" in ev_iri:
            tail = ev_iri.rsplit("LifeEvent_", 1)[-1]
            try:
                return int(tail)
            except ValueError:
                continue
    return None


def delete_event_by_source_asset(source_asset_label: str) -> None:
    """Delete the auto-managed LifeEvent linked to the given asset, if any."""
    if not source_asset_label:
        return
    source_iri_str = f"{MRL}{source_asset_label}"
    store.update(f"""
        PREFIX mrl: <{MRL}>
        DELETE {{ GRAPH <{DATA_GRAPH.value}> {{ ?ev ?p ?o . }} }}
        WHERE  {{ GRAPH <{DATA_GRAPH.value}> {{ ?ev mrl:sourceAsset <{source_iri_str}> ; ?p ?o . }} }}
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
    from src.api.routes.accounts import get_all_asset_accounts
    proj_data = _get_projection_data()
    assets = get_all_asset_accounts()
    return {
        "app_name":           settings.app_name,
        "active":             "life-events",
        "events":             events,
        # "Sell asset" is offered (1.0.11) but writes through to the asset rather
        # than creating an event; "Property transaction" is deprecated and hidden.
        "event_type_options": USER_EVENT_TYPE_OPTIONS,
        "asset_sale_type":    ASSET_SALE_TYPE,
        # Assets the user can sell, and whether each already has a planned sale.
        "sellable_assets":    assets,
        "has_assets":         bool(assets),
        "edit_event":         edit_event,
        "proj_data":          proj_data,
        **kwargs,
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/life-events", response_class=HTMLResponse)
async def life_events_page(request: Request):
    migrate_legacy_event_types()   # PropertyTransaction -> BuyAsset, idempotent
    events = get_all_events()
    return templates.TemplateResponse(
        request=request,
        name="life_events.html",
        context=_page_context(request, events),
    )


@router.post("/life-events", response_class=HTMLResponse)
async def add_life_event(
    request: Request,
    lifeEventName:       str   = Form(""),
    lifeEventYear:       int   = Form(...),
    # Optional: a "Sell asset" derives its amount from the asset, so the form
    # doesn't ask for one.
    lifeEventAmount:     float = Form(0.0),
    lifeEventType:       str   = Form("LifeEventType_LargeExpenditure"),
    lifeEventNotes:      str   = Form(""),
    fundedByAccount:     str   = Form(""),
    receivedByAccount:   str   = Form(""),
    # "Sell asset" only:
    saleAsset:           str   = Form(""),
    saleValue:           str   = Form(""),
):
    # "Sell asset" does NOT create a life event. It writes the sale through to the
    # chosen PhysicalAsset — the engine reads the asset's sale year to zero its
    # value from that year on, and derives the proceeds event from it. Storing a
    # second, independent copy here would credit the proceeds twice.
    if lifeEventType == ASSET_SALE_TYPE:
        from src.api.routes.accounts import set_asset_sale
        if not saleAsset:
            events = get_all_events()
            return templates.TemplateResponse(
                request=request, name="life_events.html",
                context=_page_context(
                    request, events,
                    error="Choose which asset you're selling."),
            )
        ok = set_asset_sale(
            asset_label=saleAsset,
            sale_year=str(lifeEventYear),
            sale_value=saleValue,
            proceeds_account=receivedByAccount,
        )
        events = get_all_events()
        if not ok:
            return templates.TemplateResponse(
                request=request, name="life_events.html",
                context=_page_context(
                    request, events, error="That asset no longer exists."),
            )
        return templates.TemplateResponse(
            request=request, name="life_events.html",
            context=_page_context(request, events, saved=True),
        )

    existing = get_all_events()
    next_n   = max([int(e["n"]) for e in existing if e["n"].isdigit()], default=0) + 1
    save_event(
        next_n, lifeEventName, lifeEventYear,
        _normalise_event_amount(lifeEventAmount, lifeEventType),
        lifeEventType, lifeEventNotes,
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

    # Asset-sourced events are managed by the asset; redirect to the asset's
    # edit page so the user changes the sale year / value / proceeds there.
    if edit_event and edit_event.get("sourceAsset"):
        from fastapi.responses import RedirectResponse
        return RedirectResponse(
            url=f"/accounts/asset/{edit_event['sourceAsset']}/edit",
            status_code=303,
        )

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
    # Reject direct edits to asset-sourced events — bounce to the asset.
    existing = get_all_events()
    target = next((e for e in existing if e["n"] == str(n)), None)
    if target and target.get("sourceAsset"):
        from fastapi.responses import RedirectResponse
        return RedirectResponse(
            url=f"/accounts/asset/{target['sourceAsset']}/edit",
            status_code=303,
        )

    save_event(
        n, lifeEventName, lifeEventYear,
        _normalise_event_amount(lifeEventAmount, lifeEventType),
        lifeEventType, lifeEventNotes,
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
    # Asset-sourced events can't be deleted directly — the user must delete
    # the asset (which auto-deletes the linked event).
    existing = get_all_events()
    target = next((e for e in existing if e["n"] == str(n)), None)
    if target and target.get("sourceAsset"):
        from fastapi.responses import RedirectResponse
        return RedirectResponse(
            url=f"/accounts/asset/{target['sourceAsset']}/edit",
            status_code=303,
        )

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