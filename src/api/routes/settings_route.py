"""
Settings routes — app configuration, data export and import.

GET  /settings         — settings page
GET  /settings/export  — download all user data as JSON
POST /settings/import  — restore data from a JSON backup file
POST /settings/inflation — update the default inflation rate
"""
import json
from datetime import date, datetime
from fastapi import APIRouter, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse, Response
from src.api.templates import templates
from typing import Optional
import pyoxigraph as og

from src.config import settings as app_settings
from src.store.graph import store, MRL, DATA_GRAPH

router = APIRouter()

RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
MRL_EXT = "https://myretirementlife.app/ontology/ext#"
ONTOLOGY_GRAPH = og.NamedNode("https://myretirementlife.app/ontology/graph")

APP_VERSION = "0.1.0-mvp"


# ---------------------------------------------------------------------------
# Export helpers
# ---------------------------------------------------------------------------

def _quads(subject, prop):
    return list(store.store.quads_for_pattern(
        subject, og.NamedNode(f"{MRL}{prop}"), None, DATA_GRAPH))

def _val(subject, prop, default=""):
    qs = _quads(subject, prop)
    return str(qs[0].object.value) if qs else default

def _local(subject, prop):
    v = _val(subject, prop)
    return v.split("#")[-1] if "#" in v else v

def _float_val(subject, prop, default=0.0):
    try:
        return float(_val(subject, prop, str(default)))
    except ValueError:
        return default

def _int_val(subject, prop, default=0):
    try:
        v = _val(subject, prop, "")
        return int(v) if v else None
    except ValueError:
        return None


def export_all_data() -> dict:
    """Serialise all user data from the triple store to a dict."""

    # Profile
    person = og.NamedNode(f"{MRL}Person_1")
    type_check = list(store.store.quads_for_pattern(
        person, og.NamedNode(RDF_TYPE), None, DATA_GRAPH))
    profile = None
    if type_check:
        profile = {
            "firstName": _val(person, "firstName"),
            "lastName": _val(person, "lastName"),
            "dateOfBirth": _val(person, "dateOfBirth"),
            "employmentStatus": _local(person, "employmentStatus"),
            "targetRetirementAge": _int_val(person, "targetRetirementAge"),
            "lifeExpectancy": _int_val(person, "lifeExpectancy"),
            "baseCurrency": _local(person, "baseCurrency"),
            "jurisdiction": _local(person, "residesIn"),
        }

    # Income sources
    income_sources = []
    type_node = og.NamedNode(f"{MRL}IncomeSource")
    for q in store.store.quads_for_pattern(
            None, og.NamedNode(RDF_TYPE), type_node, DATA_GRAPH):
        iri = q.subject
        n = str(iri.value).split("IncomeSource_")[-1]
        income_sources.append({
            "n": n,
            "name": _val(iri, "incomeSourceName"),
            "incomeType": _local(iri, "incomeSourceType"),
            "annualAmount": _float_val(iri, "incomeAnnualAmount"),
            "growthRate": _float_val(iri, "incomeGrowthRate"),
            "isNetOfTax": _val(iri, "incomeIsNetOfTax", "true"),
            "startYear": _int_val(iri, "incomeStartYear"),
            "endYear": _int_val(iri, "incomeEndYear"),
        })
    income_sources.sort(key=lambda x: int(x["n"]) if x["n"].isdigit() else 0)

    # Cash accounts
    accounts = []
    type_node = og.NamedNode(f"{MRL}CashAccount")
    for q in store.store.quads_for_pattern(
            None, og.NamedNode(RDF_TYPE), type_node, DATA_GRAPH):
        iri = q.subject
        n = str(iri.value).split("CashAccount_")[-1]
        accounts.append({
            "n": n,
            "name": _val(iri, "accountName"),
            "balance": _float_val(iri, "accountBalance"),
            "balanceDate": _val(iri, "balanceDate"),
            "currency": _local(iri, "accountCurrency"),
            "interestRate": _float_val(iri, "annualInterestRate"),
            "jurisdiction": _local(iri, "accountJurisdiction"),
            "accountType": _local(iri, "accountType"),
            "exchangeRate": _float_val(iri, "exchangeRateToBase", 1.0),
            "exchangeRateDate": _val(iri, "exchangeRateDate"),
            "notes": _val(iri, "accountNotes"),
        })
    accounts.sort(key=lambda x: int(x["n"]) if x["n"].isdigit() else 0)

    # Budget lines
    budget_lines = []
    type_node = og.NamedNode(f"{MRL}BudgetLine")
    for q in store.store.quads_for_pattern(
            None, og.NamedNode(RDF_TYPE), type_node, DATA_GRAPH):
        iri = q.subject
        n = str(iri.value).split("BudgetLine_")[-1]
        budget_lines.append({
            "n": n,
            "name": _val(iri, "budgetLineName"),
            "amount": _float_val(iri, "budgetLineAmount"),
            "frequency": _local(iri, "budgetLineFrequency"),
            "lineType": _local(iri, "budgetLineType"),
            "changeRate": _float_val(iri, "annualChangeRate"),
            "loanEndYear": _int_val(iri, "loanEndYear"),
        })
    budget_lines.sort(key=lambda x: int(x["n"]) if x["n"].isdigit() else 0)

    # Life events
    life_events = []
    type_node = og.NamedNode(f"{MRL}LifeEvent")
    for q in store.store.quads_for_pattern(
            None, og.NamedNode(RDF_TYPE), type_node, DATA_GRAPH):
        iri = q.subject
        n = str(iri.value).split("LifeEvent_")[-1]
        life_events.append({
            "n": n,
            "name": _val(iri, "lifeEventName"),
            "year": _int_val(iri, "lifeEventYear"),
            "amount": _float_val(iri, "lifeEventAmount"),
            "eventType": _local(iri, "lifeEventType"),
            "notes": _val(iri, "lifeEventNotes"),
        })
    life_events.sort(key=lambda x: x["year"] or 0)

    # Projection settings
    ps = og.NamedNode(f"{MRL}ProjectionSettings_1")
    ps_check = list(store.store.quads_for_pattern(
        ps, og.NamedNode(RDF_TYPE), None, DATA_GRAPH))
    projection_settings = None
    if ps_check:
        projection_settings = {
            "inflationRate": _float_val(ps, "inflationRate", 2.5),
        }

    return {
        "version": APP_VERSION,
        "exported": date.today().isoformat(),
        "app": "My Retirement Life",
        "data": {
            "profile": profile,
            "income_sources": income_sources,
            "accounts": accounts,
            "budget_lines": budget_lines,
            "life_events": life_events,
            "projection_settings": projection_settings,
        }
    }


# ---------------------------------------------------------------------------
# Import helpers
# ---------------------------------------------------------------------------

def restore_all_data(backup: dict) -> tuple[bool, str]:
    """
    Restore data from a backup dict. Clears all existing user data first.
    Returns (success, message).
    """
    try:
        data = backup.get("data", {})

        # Clear all existing user data
        store.update(f"""
            DELETE WHERE {{
                GRAPH <{DATA_GRAPH.value}> {{
                    ?s ?p ?o .
                }}
            }}
        """)

        person_iri = f"{MRL}Person_1"

        # Restore profile
        profile = data.get("profile")
        if profile:
            store.update(f"""
                PREFIX mrl:  <{MRL}>
                PREFIX mrlx: <{MRL_EXT}>
                PREFIX xsd:  <http://www.w3.org/2001/XMLSchema#>
                INSERT DATA {{
                    GRAPH <{DATA_GRAPH.value}> {{
                        <{person_iri}> a mrl:Person ;
                            mrl:firstName "{profile.get('firstName', '')}" ;
                            mrl:lastName "{profile.get('lastName', '')}" ;
                            mrl:dateOfBirth "{profile.get('dateOfBirth', '')}"^^xsd:date ;
                            mrl:employmentStatus mrlx:{profile.get('employmentStatus', 'EmploymentStatus_Employed')} ;
                            mrl:targetRetirementAge {profile.get('targetRetirementAge', 67)} ;
                            mrl:lifeExpectancy {profile.get('lifeExpectancy', 85)} ;
                            mrl:baseCurrency mrl:{profile.get('baseCurrency', 'Currency_GBP')} ;
                            mrl:residesIn mrl:{profile.get('jurisdiction', 'Jurisdiction_GB')} .
                    }}
                }}
            """)

        # Restore income sources
        for src in data.get("income_sources", []):
            n = src.get("n", "1")
            src_iri = f"{MRL}IncomeSource_{n}"
            store.update(f"""
                PREFIX mrl:  <{MRL}>
                PREFIX mrlx: <{MRL_EXT}>
                PREFIX xsd:  <http://www.w3.org/2001/XMLSchema#>
                INSERT DATA {{
                    GRAPH <{DATA_GRAPH.value}> {{
                        <{src_iri}> a mrl:IncomeSource ;
                            mrl:incomeSourceName "{src.get('name', '')}" ;
                            mrl:incomeSourceType mrlx:{src.get('incomeType', 'IncomeSourceType_Employment')} ;
                            mrl:incomeAnnualAmount "{src.get('annualAmount', 0)}"^^xsd:decimal ;
                            mrl:incomeGrowthRate "{src.get('growthRate', 0)}"^^xsd:decimal ;
                            mrl:incomeIsNetOfTax "{src.get('isNetOfTax', 'true')}"^^xsd:boolean ;
                            mrl:incomeOwner <{person_iri}> .
                    }}
                }}
            """)
            if src.get("startYear"):
                store.update(f"""
                    PREFIX mrl: <{MRL}> PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
                    INSERT DATA {{ GRAPH <{DATA_GRAPH.value}> {{
                        <{src_iri}> mrl:incomeStartYear "{src['startYear']}"^^xsd:integer . }} }}
                """)
            if src.get("endYear"):
                store.update(f"""
                    PREFIX mrl: <{MRL}> PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
                    INSERT DATA {{ GRAPH <{DATA_GRAPH.value}> {{
                        <{src_iri}> mrl:incomeEndYear "{src['endYear']}"^^xsd:integer . }} }}
                """)

        # Restore accounts
        for acc in data.get("accounts", []):
            n = acc.get("n", "1")
            acc_iri = f"{MRL}CashAccount_{n}"
            store.update(f"""
                PREFIX mrl:  <{MRL}>
                PREFIX mrlx: <{MRL_EXT}>
                PREFIX xsd:  <http://www.w3.org/2001/XMLSchema#>
                INSERT DATA {{
                    GRAPH <{DATA_GRAPH.value}> {{
                        <{acc_iri}> a mrl:CashAccount ;
                            mrl:accountName "{acc.get('name', '')}" ;
                            mrl:accountBalance "{acc.get('balance', 0)}"^^xsd:decimal ;
                            mrl:balanceDate "{acc.get('balanceDate', date.today().isoformat())}"^^xsd:date ;
                            mrl:accountCurrency mrl:{acc.get('currency', 'Currency_GBP')} ;
                            mrl:annualInterestRate "{acc.get('interestRate', 0)}"^^xsd:decimal ;
                            mrl:accountJurisdiction mrl:{acc.get('jurisdiction', 'Jurisdiction_GB')} ;
                            mrl:accountType mrlx:{acc.get('accountType', 'CashAccountType_Current')} ;
                            mrl:ownedBy <{person_iri}> .
                    }}
                }}
            """)
            if acc.get("exchangeRate") and float(acc.get("exchangeRate", 1.0)) != 1.0:
                store.update(f"""
                    PREFIX mrl: <{MRL}> PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
                    INSERT DATA {{ GRAPH <{DATA_GRAPH.value}> {{
                        <{acc_iri}> mrl:exchangeRateToBase "{acc['exchangeRate']}"^^xsd:decimal ;
                                    mrl:exchangeRateDate "{acc.get('exchangeRateDate', date.today().isoformat())}"^^xsd:date . }} }}
                """)
            if acc.get("notes"):
                store.update(f"""
                    PREFIX mrl: <{MRL}>
                    INSERT DATA {{ GRAPH <{DATA_GRAPH.value}> {{
                        <{acc_iri}> mrl:accountNotes "{acc['notes']}" . }} }}
                """)

        # Restore budget lines
        for line in data.get("budget_lines", []):
            n = line.get("n", "1")
            line_iri = f"{MRL}BudgetLine_{n}"
            store.update(f"""
                PREFIX mrl:  <{MRL}>
                PREFIX mrlx: <{MRL_EXT}>
                PREFIX xsd:  <http://www.w3.org/2001/XMLSchema#>
                INSERT DATA {{
                    GRAPH <{DATA_GRAPH.value}> {{
                        <{line_iri}> a mrl:BudgetLine ;
                            mrl:budgetLineName "{line.get('name', '')}" ;
                            mrl:budgetLineAmount "{line.get('amount', 0)}"^^xsd:decimal ;
                            mrl:budgetLineFrequency mrlx:{line.get('frequency', 'FrequencyType_Monthly')} ;
                            mrl:budgetLineType mrlx:{line.get('lineType', 'BudgetLineType_Mandatory')} ;
                            mrl:annualChangeRate "{line.get('changeRate', 0)}"^^xsd:decimal ;
                            mrl:budgetOwner <{person_iri}> .
                    }}
                }}
            """)
            if line.get("loanEndYear"):
                store.update(f"""
                    PREFIX mrl: <{MRL}> PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
                    INSERT DATA {{ GRAPH <{DATA_GRAPH.value}> {{
                        <{line_iri}> mrl:loanEndYear "{line['loanEndYear']}"^^xsd:integer . }} }}
                """)

        # Restore life events
        for event in data.get("life_events", []):
            n = event.get("n", "1")
            event_iri = f"{MRL}LifeEvent_{n}"
            store.update(f"""
                PREFIX mrl:  <{MRL}>
                PREFIX mrlx: <{MRL_EXT}>
                PREFIX xsd:  <http://www.w3.org/2001/XMLSchema#>
                INSERT DATA {{
                    GRAPH <{DATA_GRAPH.value}> {{
                        <{event_iri}> a mrl:LifeEvent ;
                            mrl:lifeEventName "{event.get('name', '')}" ;
                            mrl:lifeEventYear "{event.get('year', 2030)}"^^xsd:integer ;
                            mrl:lifeEventAmount "{event.get('amount', 0)}"^^xsd:decimal ;
                            mrl:lifeEventType mrlx:{event.get('eventType', 'LifeEventType_LargeExpenditure')} ;
                            mrl:lifeEventOwner <{person_iri}> .
                    }}
                }}
            """)
            if event.get("notes"):
                store.update(f"""
                    PREFIX mrl: <{MRL}>
                    INSERT DATA {{ GRAPH <{DATA_GRAPH.value}> {{
                        <{event_iri}> mrl:lifeEventNotes "{event['notes']}" . }} }}
                """)

        # Restore projection settings
        ps_data = data.get("projection_settings")
        if ps_data:
            ps_iri = f"{MRL}ProjectionSettings_1"
            store.update(f"""
                PREFIX mrl: <{MRL}> PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
                INSERT DATA {{ GRAPH <{DATA_GRAPH.value}> {{
                    <{ps_iri}> a mrl:ProjectionSettings ;
                        mrl:inflationRate "{ps_data.get('inflationRate', 2.5)}"^^xsd:decimal ;
                        mrl:projectionOwner <{person_iri}> . }} }}
            """)

        return True, "Data restored successfully."

    except Exception as e:
        return False, f"Restore failed: {str(e)}"


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    from src.store.ontology_loader import ontology_triple_count
    data_count = len(list(store.store.quads_for_pattern(
        None, None, None, DATA_GRAPH)))
    ontology_count = ontology_triple_count(store.store)
    data_dir = str(app_settings.data_dir)

    # Get current inflation rate
    ps = og.NamedNode(f"{MRL}ProjectionSettings_1")
    ps_check = list(store.store.quads_for_pattern(
        ps, og.NamedNode(RDF_TYPE), None, DATA_GRAPH))
    inflation_rate = 2.5
    if ps_check:
        try:
            qs = list(store.store.quads_for_pattern(
                ps, og.NamedNode(f"{MRL}inflationRate"), None, DATA_GRAPH))
            if qs:
                inflation_rate = float(qs[0].object.value)
        except Exception:
            pass

    return templates.TemplateResponse(
        request=request,
        name="settings.html",
        context={
            "app_name": app_settings.app_name,
            "active": "settings",
            "app_version": APP_VERSION,
            "data_dir": data_dir,
            "data_triple_count": data_count,
            "ontology_triple_count": ontology_count,
            "inflation_rate": inflation_rate,
            "today": date.today().isoformat(),
        }
    )


@router.get("/settings/export")
async def export_data():
    """Download all user data as a JSON backup file."""
    data = export_all_data()
    filename = f"my-retirement-life-backup-{date.today().isoformat()}.json"
    return Response(
        content=json.dumps(data, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


@router.post("/settings/import", response_class=HTMLResponse)
async def import_data(request: Request, backup_file: UploadFile = File(...)):
    """Restore data from an uploaded JSON backup file."""
    from src.store.ontology_loader import ontology_triple_count

    try:
        content = await backup_file.read()
        backup = json.loads(content)
        if backup.get("app") != "My Retirement Life":
            raise ValueError("File does not appear to be a My Retirement Life backup.")
        success, message = restore_all_data(backup)
    except json.JSONDecodeError:
        success, message = False, "File is not valid JSON."
    except Exception as e:
        success, message = False, str(e)

    data_count = len(list(store.store.quads_for_pattern(
        None, None, None, DATA_GRAPH)))
    ontology_count = ontology_triple_count(store.store)

    ps = og.NamedNode(f"{MRL}ProjectionSettings_1")
    inflation_rate = 2.5
    try:
        qs = list(store.store.quads_for_pattern(
            ps, og.NamedNode(f"{MRL}inflationRate"), None, DATA_GRAPH))
        if qs:
            inflation_rate = float(qs[0].object.value)
    except Exception:
        pass

    return templates.TemplateResponse(
        request=request,
        name="settings.html",
        context={
            "app_name": app_settings.app_name,
            "active": "settings",
            "app_version": APP_VERSION,
            "data_dir": str(app_settings.data_dir),
            "data_triple_count": data_count,
            "ontology_triple_count": ontology_count,
            "inflation_rate": inflation_rate,
            "today": date.today().isoformat(),
            "import_success": success,
            "import_message": message,
        }
    )


@router.post("/settings/inflation", response_class=HTMLResponse)
async def update_inflation(
    request: Request,
    inflationRate: float = Form(2.5),
):
    """Update the default inflation rate."""
    from src.store.ontology_loader import ontology_triple_count

    person_iri = f"{MRL}Person_1"
    ps_iri = f"{MRL}ProjectionSettings_1"
    store.update(f"""
        DELETE WHERE {{
            GRAPH <{DATA_GRAPH.value}> {{
                <{ps_iri}> ?p ?o .
            }}
        }}
    """)
    store.update(f"""
        PREFIX mrl: <{MRL}> PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
        INSERT DATA {{ GRAPH <{DATA_GRAPH.value}> {{
            <{ps_iri}> a mrl:ProjectionSettings ;
                mrl:inflationRate "{inflationRate}"^^xsd:decimal ;
                mrl:projectionOwner <{person_iri}> . }} }}
    """)

    data_count = len(list(store.store.quads_for_pattern(
        None, None, None, DATA_GRAPH)))

    return templates.TemplateResponse(
        request=request,
        name="settings.html",
        context={
            "app_name": app_settings.app_name,
            "active": "settings",
            "app_version": APP_VERSION,
            "data_dir": str(app_settings.data_dir),
            "data_triple_count": data_count,
            "ontology_triple_count": ontology_triple_count(store.store),
            "inflation_rate": inflationRate,
            "today": date.today().isoformat(),
            "inflation_saved": True,
        }
    )
