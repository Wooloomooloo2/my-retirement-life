"""
Profile routes — view and save the user's personal profile.

GET  /profile  — render the profile form (pre-filled if data exists)
POST /profile  — save profile data to the triple store
"""
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse
from src.api.templates import templates
from typing import Optional
import pyoxigraph as og

from src.config import settings
from src.store.graph import store, MRL, DATA_GRAPH

router = APIRouter()

MRL_EXT = "https://myretirementlife.app/ontology/ext#"
RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"


def get_profile() -> Optional[dict]:
    """Read Person_1 directly from the data graph using quad patterns."""
    person_iri = og.NamedNode(f"{MRL}Person_1")

    type_quads = list(store.store.quads_for_pattern(
        person_iri, og.NamedNode(RDF_TYPE), None, DATA_GRAPH))
    if not type_quads:
        return None

    def get_val(prop: str) -> str:
        quads = list(store.store.quads_for_pattern(
            person_iri, og.NamedNode(f"{MRL}{prop}"), None, DATA_GRAPH))
        return str(quads[0].object.value) if quads else ""

    def get_local(prop: str) -> str:
        v = get_val(prop)
        return v.split("#")[-1] if "#" in v else v

    return {
        "firstName": get_val("firstName"),
        "lastName": get_val("lastName"),
        "dateOfBirth": get_val("dateOfBirth"),
        "employmentStatus": get_local("employmentStatus"),
        "targetRetirementAge": get_val("targetRetirementAge"),
        "lifeExpectancy": get_val("lifeExpectancy"),
        "baseCurrency": get_local("baseCurrency"),
        "jurisdiction": get_local("residesIn"),
    }


def get_income_source() -> Optional[dict]:
    """Read IncomeSource_1 directly from the data graph using quad patterns."""
    income_iri = og.NamedNode(f"{MRL}IncomeSource_1")

    type_quads = list(store.store.quads_for_pattern(
        income_iri, og.NamedNode(RDF_TYPE), None, DATA_GRAPH))
    if not type_quads:
        return None

    def get_val(prop: str) -> str:
        quads = list(store.store.quads_for_pattern(
            income_iri, og.NamedNode(f"{MRL}{prop}"), None, DATA_GRAPH))
        return str(quads[0].object.value) if quads else ""

    return {
        "annualAmount": get_val("incomeAnnualAmount"),
        "growthRate": get_val("incomeGrowthRate"),
        "isNetOfTax": get_val("incomeIsNetOfTax"),
    }


def get_currencies() -> list:
    sparql = f"""
        PREFIX mrl: <{MRL}>
        SELECT ?iri ?code ?name
        WHERE {{
            GRAPH <https://myretirementlife.app/ontology/graph> {{
                ?iri a mrl:Currency ;
                     mrl:currencyCode ?code ;
                     mrl:currencyName ?name .
            }}
        }}
        ORDER BY ?code
    """
    results = list(store.query(sparql))
    currencies = []
    for r in results:
        try:
            currencies.append({
                "iri": str(r["iri"].value),
                "local": str(r["iri"].value).split("#")[-1],
                "code": str(r["code"].value),
                "name": str(r["name"].value),
            })
        except Exception:
            pass
    return currencies


def get_jurisdictions() -> list:
    sparql = f"""
        PREFIX mrl: <{MRL}>
        SELECT ?iri ?code ?name
        WHERE {{
            GRAPH <https://myretirementlife.app/ontology/graph> {{
                ?iri a mrl:Jurisdiction ;
                     mrl:jurisdictionCode ?code ;
                     mrl:jurisdictionName ?name .
            }}
        }}
        ORDER BY ?name
    """
    results = list(store.query(sparql))
    jurisdictions = []
    for r in results:
        try:
            jurisdictions.append({
                "iri": str(r["iri"].value),
                "local": str(r["iri"].value).split("#")[-1],
                "code": str(r["code"].value),
                "name": str(r["name"].value),
            })
        except Exception:
            pass
    return jurisdictions


@router.get("/profile", response_class=HTMLResponse)
async def profile_page(request: Request):
    profile = get_profile()
    income = get_income_source()
    currencies = get_currencies()
    jurisdictions = get_jurisdictions()
    return templates.TemplateResponse(
        request=request,
        name="profile.html",
        context={
            "app_name": settings.app_name,
            "profile": profile,
            "income": income,
            "currencies": currencies,
            "jurisdictions": jurisdictions,
            "active": "profile",
            "is_new": profile is None,
        }
    )


@router.post("/profile", response_class=HTMLResponse)
async def save_profile(
    request: Request,
    firstName: str = Form(...),
    lastName: str = Form(...),
    dateOfBirth: str = Form(...),
    employmentStatus: str = Form(...),
    targetRetirementAge: int = Form(...),
    lifeExpectancy: int = Form(...),
    baseCurrency: str = Form(...),
    jurisdiction: str = Form(...),
    annualIncome: float = Form(...),
    incomeGrowthRate: float = Form(0.0),
    incomeIsNetOfTax: bool = Form(True),
):
    person_iri = f"{MRL}Person_1"
    income_iri = f"{MRL}IncomeSource_1"

    store.update(f"""
        DELETE WHERE {{
            GRAPH <{DATA_GRAPH.value}> {{
                <{person_iri}> ?p ?o .
            }}
        }}
    """)
    store.update(f"""
        DELETE WHERE {{
            GRAPH <{DATA_GRAPH.value}> {{
                <{income_iri}> ?p ?o .
            }}
        }}
    """)

    store.update(f"""
        PREFIX mrl:  <{MRL}>
        PREFIX mrlx: <{MRL_EXT}>
        PREFIX xsd:  <http://www.w3.org/2001/XMLSchema#>

        INSERT DATA {{
            GRAPH <{DATA_GRAPH.value}> {{
                <{person_iri}> a mrl:Person ;
                    mrl:firstName "{firstName}" ;
                    mrl:lastName "{lastName}" ;
                    mrl:dateOfBirth "{dateOfBirth}"^^xsd:date ;
                    mrl:employmentStatus mrlx:{employmentStatus} ;
                    mrl:targetRetirementAge {targetRetirementAge} ;
                    mrl:lifeExpectancy {lifeExpectancy} ;
                    mrl:baseCurrency mrl:{baseCurrency} ;
                    mrl:residesIn mrl:{jurisdiction} .
            }}
        }}
    """)

    store.update(f"""
        PREFIX mrl:  <{MRL}>
        PREFIX mrlx: <{MRL_EXT}>
        PREFIX xsd:  <http://www.w3.org/2001/XMLSchema#>

        INSERT DATA {{
            GRAPH <{DATA_GRAPH.value}> {{
                <{income_iri}> a mrl:IncomeSource ;
                    mrl:incomeSourceName "Employment income" ;
                    mrl:incomeSourceType mrlx:IncomeSourceType_Employment ;
                    mrl:incomeAnnualAmount "{annualIncome}"^^xsd:decimal ;
                    mrl:incomeGrowthRate "{incomeGrowthRate}"^^xsd:decimal ;
                    mrl:incomeIsNetOfTax "{str(incomeIsNetOfTax).lower()}"^^xsd:boolean ;
                    mrl:incomeEndYear {targetRetirementAge} ;
                    mrl:incomeOwner <{person_iri}> .
            }}
        }}
    """)

    profile = get_profile()
    income = get_income_source()
    currencies = get_currencies()
    jurisdictions = get_jurisdictions()

    return templates.TemplateResponse(
        request=request,
        name="profile.html",
        context={
            "app_name": settings.app_name,
            "profile": profile,
            "income": income,
            "currencies": currencies,
            "jurisdictions": jurisdictions,
            "active": "profile",
            "is_new": False,
            "saved": True,
        }
    )
