"""
Budget routes — manage the user's budget lines.

GET  /budget              — list all budget lines + add form
POST /budget              — create a new budget line
GET  /budget/{n}/edit     — load edit form for budget line N
POST /budget/{n}/edit     — save edits to budget line N
POST /budget/{n}/delete   — delete budget line N
"""
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from typing import Optional
import pyoxigraph as og

from src.config import settings
from src.store.graph import store, MRL, DATA_GRAPH

router = APIRouter()
templates = Jinja2Templates(directory=settings.templates_dir)

RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
MRL_EXT = "https://myretirementlife.app/ontology/ext#"

# Frequency multipliers for normalising to annual amounts
FREQUENCY_MULTIPLIERS = {
    "FrequencyType_Weekly": 52,
    "FrequencyType_Fortnightly": 26,
    "FrequencyType_TwiceMonthly": 24,
    "FrequencyType_Monthly": 12,
    "FrequencyType_Quarterly": 4,
    "FrequencyType_Annually": 1,
}

FREQUENCY_LABELS = {
    "FrequencyType_Weekly": "Weekly",
    "FrequencyType_Fortnightly": "Fortnightly (every 2 weeks)",
    "FrequencyType_TwiceMonthly": "Twice monthly",
    "FrequencyType_Monthly": "Monthly",
    "FrequencyType_Quarterly": "Quarterly",
    "FrequencyType_Annually": "Annually",
}


def to_annual(amount: float, frequency_local: str) -> float:
    """Convert an amount at a given frequency to its annual equivalent."""
    multiplier = FREQUENCY_MULTIPLIERS.get(frequency_local, 12)
    return round(amount * multiplier, 2)


def get_all_budget_lines() -> list:
    """Return all BudgetLine instances from the data graph."""
    type_node = og.NamedNode(f"{MRL}BudgetLine")
    quads = store.store.quads_for_pattern(
        None, og.NamedNode(RDF_TYPE), type_node, DATA_GRAPH)
    lines = []
    for q in quads:
        iri = q.subject
        n = str(iri.value).split("BudgetLine_")[-1]

        def get_val(prop):
            qs = list(store.store.quads_for_pattern(
                iri, og.NamedNode(f"{MRL}{prop}"), None, DATA_GRAPH))
            return str(qs[0].object.value) if qs else ""

        def get_local(prop):
            v = get_val(prop)
            return v.split("#")[-1] if "#" in v else v

        freq = get_local("budgetLineFrequency")
        amount = get_val("budgetLineAmount")
        annual = to_annual(float(amount), freq) if amount else 0

        lines.append({
            "n": n,
            "iri": str(iri.value),
            "name": get_val("budgetLineName"),
            "amount": amount,
            "frequency": freq,
            "frequencyLabel": FREQUENCY_LABELS.get(freq, freq),
            "annualAmount": annual,
            "lineType": get_local("budgetLineType"),
            "changeRate": get_val("annualChangeRate"),
            "loanEndYear": get_val("loanEndYear"),
        })
    lines.sort(key=lambda l: int(l["n"]) if l["n"].isdigit() else 0)
    return lines


def get_budget_summary(lines: list) -> dict:
    """Calculate totals by type."""
    mandatory = sum(l["annualAmount"] for l in lines
                    if l["lineType"] == "BudgetLineType_Mandatory")
    discretionary = sum(l["annualAmount"] for l in lines
                        if l["lineType"] == "BudgetLineType_Discretionary")
    loans = sum(l["annualAmount"] for l in lines
                if l["lineType"] == "BudgetLineType_Loan")
    return {
        "mandatory": mandatory,
        "discretionary": discretionary,
        "loans": loans,
        "total": mandatory + discretionary + loans,
    }


def save_budget_line(n: int, name: str, amount: float, frequency: str,
                     line_type: str, change_rate: float,
                     loan_end_year: Optional[int]) -> None:
    """Write or overwrite a BudgetLine_N instance in the data graph."""
    line_iri = f"{MRL}BudgetLine_{n}"
    person_iri = f"{MRL}Person_1"

    store.update(f"""
        DELETE WHERE {{
            GRAPH <{DATA_GRAPH.value}> {{
                <{line_iri}> ?p ?o .
            }}
        }}
    """)

    store.update(f"""
        PREFIX mrl:  <{MRL}>
        PREFIX mrlx: <{MRL_EXT}>
        PREFIX xsd:  <http://www.w3.org/2001/XMLSchema#>

        INSERT DATA {{
            GRAPH <{DATA_GRAPH.value}> {{
                <{line_iri}> a mrl:BudgetLine ;
                    mrl:budgetLineName "{name}" ;
                    mrl:budgetLineAmount "{amount}"^^xsd:decimal ;
                    mrl:budgetLineFrequency mrlx:{frequency} ;
                    mrl:budgetLineType mrlx:{line_type} ;
                    mrl:annualChangeRate "{change_rate}"^^xsd:decimal ;
                    mrl:budgetOwner <{person_iri}> .
            }}
        }}
    """)

    if loan_end_year:
        store.update(f"""
            PREFIX mrl: <{MRL}>
            PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
            INSERT DATA {{
                GRAPH <{DATA_GRAPH.value}> {{
                    <{line_iri}> mrl:loanEndYear "{loan_end_year}"^^xsd:integer .
                }}
            }}
        """)


def _page_context(request, lines, edit_line=None, **kwargs):
    summary = get_budget_summary(lines)
    return {
        "app_name": settings.app_name,
        "active": "budget",
        "lines": lines,
        "summary": summary,
        "frequency_options": FREQUENCY_LABELS,
        "edit_line": edit_line,
        **kwargs,
    }


@router.get("/budget", response_class=HTMLResponse)
async def budget_page(request: Request):
    lines = get_all_budget_lines()
    return templates.TemplateResponse(
        request=request,
        name="budget.html",
        context=_page_context(request, lines),
    )


@router.post("/budget", response_class=HTMLResponse)
async def add_budget_line(
    request: Request,
    budgetLineName: str = Form(...),
    budgetLineAmount: float = Form(...),
    budgetLineFrequency: str = Form("FrequencyType_Monthly"),
    budgetLineType: str = Form(...),
    annualChangeRate: float = Form(0.0),
    loanEndYear: Optional[int] = Form(None),
):
    existing = get_all_budget_lines()
    next_n = max([int(l["n"]) for l in existing if l["n"].isdigit()], default=0) + 1
    save_budget_line(next_n, budgetLineName, budgetLineAmount,
                     budgetLineFrequency, budgetLineType,
                     annualChangeRate, loanEndYear)
    lines = get_all_budget_lines()
    return templates.TemplateResponse(
        request=request,
        name="budget.html",
        context=_page_context(request, lines, saved=True),
    )


@router.get("/budget/{n}/edit", response_class=HTMLResponse)
async def edit_budget_line_form(request: Request, n: int):
    lines = get_all_budget_lines()
    edit_line = next((l for l in lines if l["n"] == str(n)), None)
    return templates.TemplateResponse(
        request=request,
        name="budget.html",
        context=_page_context(request, lines, edit_line=edit_line),
    )


@router.post("/budget/{n}/edit", response_class=HTMLResponse)
async def save_edit_budget_line(
    request: Request,
    n: int,
    budgetLineName: str = Form(...),
    budgetLineAmount: float = Form(...),
    budgetLineFrequency: str = Form("FrequencyType_Monthly"),
    budgetLineType: str = Form(...),
    annualChangeRate: float = Form(0.0),
    loanEndYear: Optional[int] = Form(None),
):
    save_budget_line(n, budgetLineName, budgetLineAmount,
                     budgetLineFrequency, budgetLineType,
                     annualChangeRate, loanEndYear)
    lines = get_all_budget_lines()
    return templates.TemplateResponse(
        request=request,
        name="budget.html",
        context=_page_context(request, lines, saved=True),
    )


@router.post("/budget/{n}/delete", response_class=HTMLResponse)
async def delete_budget_line(request: Request, n: int):
    line_iri = f"{MRL}BudgetLine_{n}"
    store.update(f"""
        DELETE WHERE {{
            GRAPH <{DATA_GRAPH.value}> {{
                <{line_iri}> ?p ?o .
            }}
        }}
    """)
    lines = get_all_budget_lines()
    return templates.TemplateResponse(
        request=request,
        name="budget.html",
        context=_page_context(request, lines, deleted=True),
    )
