"""
Accounts routes — manage the user's cash accounts.

GET  /accounts              — list all accounts + add form
POST /accounts              — create a new account
GET  /accounts/{n}/edit     — load edit form for account N (HTMX partial)
POST /accounts/{n}/edit     — save edits to account N
POST /accounts/{n}/delete   — delete account N
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_all_accounts() -> list:
    """Return all CashAccount instances from the data graph."""
    type_node = og.NamedNode(f"{MRL}CashAccount")
    quads = store.store.quads_for_pattern(None, og.NamedNode(RDF_TYPE), type_node, DATA_GRAPH)
    accounts = []
    for q in quads:
        iri = q.subject
        n = str(iri.value).split("CashAccount_")[-1]

        def get_val(prop):
            qs = list(store.store.quads_for_pattern(iri, og.NamedNode(f"{MRL}{prop}"), None, DATA_GRAPH))
            return str(qs[0].object.value) if qs else ""

        def get_local(prop):
            v = get_val(prop)
            return v.split("#")[-1] if "#" in v else v

        accounts.append({
            "n": n,
            "iri": str(iri.value),
            "name": get_val("accountName"),
            "balance": get_val("accountBalance"),
            "balanceDate": get_val("balanceDate"),
            "currency": get_local("accountCurrency"),
            "currencyCode": _currency_code(get_local("accountCurrency")),
            "currencySymbol": _currency_symbol(get_local("accountCurrency")),
            "interestRate": get_val("annualInterestRate"),
            "jurisdiction": get_local("accountJurisdiction"),
            "accountType": get_local("accountType"),
            "exchangeRate": get_val("exchangeRateToBase"),
            "exchangeRateDate": get_val("exchangeRateDate"),
            "notes": get_val("accountNotes"),
        })
    accounts.sort(key=lambda a: int(a["n"]) if a["n"].isdigit() else 0)
    return accounts


def _currency_code(local: str) -> str:
    if not local:
        return ""
    iri = og.NamedNode(f"{MRL}{local}")
    qs = list(store.store.quads_for_pattern(
        iri, og.NamedNode(f"{MRL}currencyCode"), None,
        og.NamedNode("https://myretirementlife.app/ontology/graph")))
    return str(qs[0].object.value) if qs else local


def _currency_symbol(local: str) -> str:
    if not local:
        return ""
    iri = og.NamedNode(f"{MRL}{local}")
    qs = list(store.store.quads_for_pattern(
        iri, og.NamedNode(f"{MRL}currencySymbol"), None,
        og.NamedNode("https://myretirementlife.app/ontology/graph")))
    return str(qs[0].object.value) if qs else ""


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


def save_account(n: int, name: str, balance: float, balance_date: str,
                 currency_local: str, interest_rate: float,
                 jurisdiction_local: str, account_type: str,
                 exchange_rate: float, exchange_rate_date: str, notes: str) -> None:
    """Write or overwrite a CashAccount_N instance in the data graph."""
    account_iri = f"{MRL}CashAccount_{n}"
    person_iri = f"{MRL}Person_1"

    store.update(f"""
        DELETE WHERE {{
            GRAPH <{DATA_GRAPH.value}> {{
                <{account_iri}> ?p ?o .
            }}
        }}
    """)

    store.update(f"""
        PREFIX mrl:  <{MRL}>
        PREFIX mrlx: <https://myretirementlife.app/ontology/ext#>
        PREFIX xsd:  <http://www.w3.org/2001/XMLSchema#>

        INSERT DATA {{
            GRAPH <{DATA_GRAPH.value}> {{
                <{account_iri}> a mrl:CashAccount ;
                    mrl:accountName "{name}" ;
                    mrl:accountBalance "{balance}"^^xsd:decimal ;
                    mrl:balanceDate "{balance_date}"^^xsd:date ;
                    mrl:accountCurrency mrl:{currency_local} ;
                    mrl:annualInterestRate "{interest_rate}"^^xsd:decimal ;
                    mrl:accountJurisdiction mrl:{jurisdiction_local} ;
                    mrl:accountType mrlx:{account_type} ;
                    mrl:ownedBy <{person_iri}> .
            }}
        }}
    """)

    if exchange_rate and float(exchange_rate) != 1.0:
        store.update(f"""
            PREFIX mrl: <{MRL}>
            PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
            INSERT DATA {{
                GRAPH <{DATA_GRAPH.value}> {{
                    <{account_iri}> mrl:exchangeRateToBase "{exchange_rate}"^^xsd:decimal ;
                                    mrl:exchangeRateDate "{exchange_rate_date}"^^xsd:date .
                }}
            }}
        """)

    if notes.strip():
        store.update(f"""
            PREFIX mrl: <{MRL}>
            INSERT DATA {{
                GRAPH <{DATA_GRAPH.value}> {{
                    <{account_iri}> mrl:accountNotes "{notes}" .
                }}
            }}
        """)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/accounts", response_class=HTMLResponse)
async def accounts_page(request: Request):
    accounts = get_all_accounts()
    currencies = get_currencies()
    jurisdictions = get_jurisdictions()
    today = date.today().isoformat()
    return templates.TemplateResponse(
        request=request,
        name="accounts.html",
        context={
            "app_name": settings.app_name,
            "active": "accounts",
            "accounts": accounts,
            "currencies": currencies,
            "jurisdictions": jurisdictions,
            "today": today,
            "edit_account": None,
        }
    )


@router.post("/accounts", response_class=HTMLResponse)
async def add_account(
    request: Request,
    accountName: str = Form(...),
    accountBalance: float = Form(...),
    balanceDate: str = Form(...),
    accountCurrency: str = Form(...),
    annualInterestRate: float = Form(0.0),
    accountJurisdiction: str = Form(...),
    accountType: str = Form("CashAccountType_Current"),
    exchangeRateToBase: float = Form(1.0),
    exchangeRateDate: str = Form(""),
    accountNotes: str = Form(""),
):
    # Get next N
    existing = get_all_accounts()
    next_n = max([int(a["n"]) for a in existing if a["n"].isdigit()], default=0) + 1
    if not exchangeRateDate:
        from datetime import date as _date
        exchangeRateDate = _date.today().isoformat()

    save_account(next_n, accountName, accountBalance, balanceDate,
                 accountCurrency, annualInterestRate, accountJurisdiction,
                 accountType, exchangeRateToBase, exchangeRateDate, accountNotes)

    accounts = get_all_accounts()
    currencies = get_currencies()
    jurisdictions = get_jurisdictions()
    today = date.today().isoformat()
    return templates.TemplateResponse(
        request=request,
        name="accounts.html",
        context={
            "app_name": settings.app_name,
            "active": "accounts",
            "accounts": accounts,
            "currencies": currencies,
            "jurisdictions": jurisdictions,
            "today": today,
            "edit_account": None,
            "saved": True,
        }
    )


@router.get("/accounts/{n}/edit", response_class=HTMLResponse)
async def edit_account_form(request: Request, n: int):
    """Return the form pre-filled for editing — loaded inline via HTMX."""
    accounts = get_all_accounts()
    account = next((a for a in accounts if a["n"] == str(n)), None)
    currencies = get_currencies()
    jurisdictions = get_jurisdictions()
    today = date.today().isoformat()
    return templates.TemplateResponse(
        request=request,
        name="accounts.html",
        context={
            "app_name": settings.app_name,
            "active": "accounts",
            "accounts": accounts,
            "currencies": currencies,
            "jurisdictions": jurisdictions,
            "today": today,
            "edit_account": account,
        }
    )


@router.post("/accounts/{n}/edit", response_class=HTMLResponse)
async def save_edit_account(
    request: Request,
    n: int,
    accountName: str = Form(...),
    accountBalance: float = Form(...),
    balanceDate: str = Form(...),
    accountCurrency: str = Form(...),
    annualInterestRate: float = Form(0.0),
    accountJurisdiction: str = Form(...),
    accountType: str = Form("CashAccountType_Current"),
    exchangeRateToBase: float = Form(1.0),
    exchangeRateDate: str = Form(""),
    accountNotes: str = Form(""),
):
    if not exchangeRateDate:
        from datetime import date as _date
        exchangeRateDate = _date.today().isoformat()
    save_account(n, accountName, accountBalance, balanceDate,
                 accountCurrency, annualInterestRate, accountJurisdiction,
                 accountType, exchangeRateToBase, exchangeRateDate, accountNotes)

    accounts = get_all_accounts()
    currencies = get_currencies()
    jurisdictions = get_jurisdictions()
    today = date.today().isoformat()
    return templates.TemplateResponse(
        request=request,
        name="accounts.html",
        context={
            "app_name": settings.app_name,
            "active": "accounts",
            "accounts": accounts,
            "currencies": currencies,
            "jurisdictions": jurisdictions,
            "today": today,
            "edit_account": None,
            "saved": True,
        }
    )


@router.post("/accounts/{n}/delete", response_class=HTMLResponse)
async def delete_account(request: Request, n: int):
    account_iri = f"{MRL}CashAccount_{n}"
    store.update(f"""
        DELETE WHERE {{
            GRAPH <{DATA_GRAPH.value}> {{
                <{account_iri}> ?p ?o .
            }}
        }}
    """)
    accounts = get_all_accounts()
    currencies = get_currencies()
    jurisdictions = get_jurisdictions()
    today = date.today().isoformat()
    return templates.TemplateResponse(
        request=request,
        name="accounts.html",
        context={
            "app_name": settings.app_name,
            "active": "accounts",
            "accounts": accounts,
            "currencies": currencies,
            "jurisdictions": jurisdictions,
            "today": today,
            "edit_account": None,
            "deleted": True,
        }
    )
