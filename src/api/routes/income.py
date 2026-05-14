"""
Income routes — manage the user's income sources.

GET  /income              — list all income sources + add form
POST /income              — create a new income source
GET  /income/{n}/edit     — load edit form for income source N
POST /income/{n}/edit     — save edits to income source N
POST /income/{n}/delete   — delete income source N
"""
from datetime import date
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse
from src.api.templates import templates
from typing import Optional
import pyoxigraph as og

from src.config import settings
from src.store.graph import store, MRL, DATA_GRAPH

router = APIRouter()

RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
MRL_EXT = "https://myretirementlife.app/ontology/ext#"

INCOME_TYPE_LABELS = {
    "IncomeSourceType_Employment": "Employment (salary / wages)",
    "IncomeSourceType_BusinessIncome": "Business income",
    "IncomeSourceType_InterestIncome": "Interest income (cash)",
    "IncomeSourceType_Property": "Property (rental income)",
    "IncomeSourceType_Retirement": "Retirement income (pension)",
    "IncomeSourceType_Investment": "Investment income",
    "IncomeSourceType_Other": "Other",
}


def get_all_income_sources() -> list:
    """Return all IncomeSource instances from the data graph."""
    type_node = og.NamedNode(f"{MRL}IncomeSource")
    quads = store.store.quads_for_pattern(
        None, og.NamedNode(RDF_TYPE), type_node, DATA_GRAPH)
    sources = []
    for q in quads:
        iri = q.subject
        n = str(iri.value).split("IncomeSource_")[-1]

        def get_val(prop):
            qs = list(store.store.quads_for_pattern(
                iri, og.NamedNode(f"{MRL}{prop}"), None, DATA_GRAPH))
            return str(qs[0].object.value) if qs else ""

        def get_local(prop):
            v = get_val(prop)
            return v.split("#")[-1] if "#" in v else v

        income_type = get_local("incomeSourceType")
        sources.append({
            "n": n,
            "iri": str(iri.value),
            "name": get_val("incomeSourceName"),
            "incomeType": income_type,
            "incomeTypeLabel": INCOME_TYPE_LABELS.get(income_type, income_type),
            "annualAmount": get_val("incomeAnnualAmount"),
            "growthRate": get_val("incomeGrowthRate"),
            "isNetOfTax": get_val("incomeIsNetOfTax"),
            "startYear": get_val("incomeStartYear"),
            "endYear": get_val("incomeEndYear"),
        })
    sources.sort(key=lambda s: int(s["n"]) if s["n"].isdigit() else 0)
    return sources


def save_income_source(n: int, name: str, income_type: str,
                       annual_amount: float, growth_rate: float,
                       is_net_of_tax: bool,
                       start_year: Optional[int],
                       end_year: Optional[int]) -> None:
    """Write or overwrite an IncomeSource_N instance in the data graph."""
    source_iri = f"{MRL}IncomeSource_{n}"
    person_iri = f"{MRL}Person_1"

    store.update(f"""
        DELETE WHERE {{
            GRAPH <{DATA_GRAPH.value}> {{
                <{source_iri}> ?p ?o .
            }}
        }}
    """)

    store.update(f"""
        PREFIX mrl:  <{MRL}>
        PREFIX mrlx: <{MRL_EXT}>
        PREFIX xsd:  <http://www.w3.org/2001/XMLSchema#>

        INSERT DATA {{
            GRAPH <{DATA_GRAPH.value}> {{
                <{source_iri}> a mrl:IncomeSource ;
                    mrl:incomeSourceName "{name}" ;
                    mrl:incomeSourceType mrlx:{income_type} ;
                    mrl:incomeAnnualAmount "{annual_amount}"^^xsd:decimal ;
                    mrl:incomeGrowthRate "{growth_rate}"^^xsd:decimal ;
                    mrl:incomeIsNetOfTax "{str(is_net_of_tax).lower()}"^^xsd:boolean ;
                    mrl:incomeOwner <{person_iri}> .
            }}
        }}
    """)

    if start_year:
        store.update(f"""
            PREFIX mrl: <{MRL}>
            PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
            INSERT DATA {{
                GRAPH <{DATA_GRAPH.value}> {{
                    <{source_iri}> mrl:incomeStartYear "{start_year}"^^xsd:integer .
                }}
            }}
        """)

    if end_year:
        store.update(f"""
            PREFIX mrl: <{MRL}>
            PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
            INSERT DATA {{
                GRAPH <{DATA_GRAPH.value}> {{
                    <{source_iri}> mrl:incomeEndYear "{end_year}"^^xsd:integer .
                }}
            }}
        """)


def _page_context(request, sources, edit_source=None, **kwargs):
    current_year = date.today().year
    return {
        "app_name": settings.app_name,
        "active": "income",
        "sources": sources,
        "income_type_options": INCOME_TYPE_LABELS,
        "edit_source": edit_source,
        "current_year": current_year,
        **kwargs,
    }


@router.get("/income", response_class=HTMLResponse)
async def income_page(request: Request):
    sources = get_all_income_sources()
    return templates.TemplateResponse(
        request=request,
        name="income.html",
        context=_page_context(request, sources),
    )


@router.post("/income", response_class=HTMLResponse)
async def add_income_source(
    request: Request,
    incomeSourceName: str = Form(...),
    incomeSourceType: str = Form("IncomeSourceType_Employment"),
    incomeAnnualAmount: float = Form(...),
    incomeGrowthRate: float = Form(0.0),
    incomeIsNetOfTax: bool = Form(True),
    incomeStartYear: Optional[int] = Form(None),
    incomeEndYear: Optional[int] = Form(None),
):
    existing = get_all_income_sources()
    next_n = max([int(s["n"]) for s in existing if s["n"].isdigit()], default=0) + 1
    save_income_source(next_n, incomeSourceName, incomeSourceType,
                       incomeAnnualAmount, incomeGrowthRate,
                       incomeIsNetOfTax, incomeStartYear, incomeEndYear)
    sources = get_all_income_sources()
    return templates.TemplateResponse(
        request=request,
        name="income.html",
        context=_page_context(request, sources, saved=True),
    )


@router.get("/income/{n}/edit", response_class=HTMLResponse)
async def edit_income_form(request: Request, n: int):
    sources = get_all_income_sources()
    edit_source = next((s for s in sources if s["n"] == str(n)), None)
    return templates.TemplateResponse(
        request=request,
        name="income.html",
        context=_page_context(request, sources, edit_source=edit_source),
    )


@router.post("/income/{n}/edit", response_class=HTMLResponse)
async def save_edit_income(
    request: Request,
    n: int,
    incomeSourceName: str = Form(...),
    incomeSourceType: str = Form("IncomeSourceType_Employment"),
    incomeAnnualAmount: float = Form(...),
    incomeGrowthRate: float = Form(0.0),
    incomeIsNetOfTax: bool = Form(True),
    incomeStartYear: Optional[int] = Form(None),
    incomeEndYear: Optional[int] = Form(None),
):
    save_income_source(n, incomeSourceName, incomeSourceType,
                       incomeAnnualAmount, incomeGrowthRate,
                       incomeIsNetOfTax, incomeStartYear, incomeEndYear)
    sources = get_all_income_sources()
    return templates.TemplateResponse(
        request=request,
        name="income.html",
        context=_page_context(request, sources, saved=True),
    )


@router.post("/income/{n}/delete", response_class=HTMLResponse)
async def delete_income_source(request: Request, n: int):
    source_iri = f"{MRL}IncomeSource_{n}"
    store.update(f"""
        DELETE WHERE {{
            GRAPH <{DATA_GRAPH.value}> {{
                <{source_iri}> ?p ?o .
            }}
        }}
    """)
    sources = get_all_income_sources()
    return templates.TemplateResponse(
        request=request,
        name="income.html",
        context=_page_context(request, sources, deleted=True),
    )
