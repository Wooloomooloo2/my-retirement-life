"""
Investment accounts routes — manage the user's investment accounts.

GET  /investments              — list all investment accounts + add form
POST /investments              — create a new investment account
GET  /investments/{n}/edit     — load edit form for investment account N
POST /investments/{n}/edit     — save edits to investment account N
POST /investments/{n}/delete   — delete investment account N
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
ONTOLOGY_GRAPH = og.NamedNode("https://myretirementlife.app/ontology/graph")

INVESTMENT_ACCOUNT_TYPES = {
    "InvestmentAccountType_StocksShares": "Stocks and shares",
    "InvestmentAccountType_TaxAdvantaged": "Tax-advantaged (ISA / Roth / TFSA)",
    "InvestmentAccountType_Pension": "Self-directed pension (SIPP / 401k)",
    "InvestmentAccountType_UnitTrust": "Unit trust / mutual fund",
    "InvestmentAccountType_Bonds": "Bond portfolio",
    "InvestmentAccountType_Other": "Other",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _currency_code(local: str) -> str:
    if not local:
        return ""
    iri = og.NamedNode(f"{MRL}{local}")
    qs = list(store.store.quads_for_pattern(
        iri, og.NamedNode(f"{MRL}currencyCode"), None, ONTOLOGY_GRAPH))
    return str(qs[0].object.value) if qs else local


def _currency_symbol(local: str) -> str:
    if not local:
        return ""
    iri = og.NamedNode(f"{MRL}{local}")
    qs = list(store.store.quads_for_pattern(
        iri, og.NamedNode(f"{MRL}currencySymbol"), None, ONTOLOGY_GRAPH))
    return str(qs[0].object.value) if qs else ""


def get_all_investment_accounts() -> list:
    """Return all InvestmentAccount instances from the data graph."""
    type_node = og.NamedNode(f"{MRL}InvestmentAccount")
    quads = store.store.quads_for_pattern(
        None, og.NamedNode(RDF_TYPE), type_node, DATA_GRAPH)
    accounts = []
    for q in quads:
        iri = q.subject
        n = str(iri.value).split("InvestmentAccount_")[-1]

        def get_val(prop):
            qs = list(store.store.quads_for_pattern(
                iri, og.NamedNode(f"{MRL}{prop}"), None, DATA_GRAPH))
            return str(qs[0].object.value) if qs else ""

        def get_local(prop):
            v = get_val(prop)
            return v.split("#")[-1] if "#" in v else v

        reinvest_raw = get_val("reinvestDividends")
        reinvest = reinvest_raw.lower() not in ("false", "0", "no") if reinvest_raw else True

        account_type = get_local("accountType")
        accounts.append({
            "n": n,
            "iri": str(iri.value),
            "name": get_val("accountName"),
            "balance": get_val("accountBalance"),
            "balanceDate": get_val("balanceDate"),
            "currency": get_local("accountCurrency"),
            "currencyCode": _currency_code(get_local("accountCurrency")),
            "currencySymbol": _currency_symbol(get_local("accountCurrency")),
            "growthRate": get_val("annualGrowthRate"),
            "dividendRate": get_val("annualDividendRate"),
            "reinvestDividends": reinvest,
            "jurisdiction": get_local("accountJurisdiction"),
            "accountType": account_type,
            "accountTypeLabel": INVESTMENT_ACCOUNT_TYPES.get(account_type, account_type),
            "exchangeRate": get_val("exchangeRateToBase"),
            "exchangeRateDate": get_val("exchangeRateDate"),
            "notes": get_val("accountNotes"),
        })
    accounts.sort(key=lambda a: int(a["n"]) if a["n"].isdigit() else 0)
    return accounts


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


def save_investment_account(
    n: int, name: str, balance: float, balance_date: str,
    currency_local: str, growth_rate: float, dividend_rate: float,
    reinvest_dividends: bool, jurisdiction_local: str, account_type: str,
    exchange_rate: float, exchange_rate_date: str, notes: str,
) -> None:
    """Write or overwrite an InvestmentAccount_N instance in the data graph."""
    account_iri = f"{MRL}InvestmentAccount_{n}"
    person_iri = f"{MRL}Person_1"
    reinvest_str = "true" if reinvest_dividends else "false"

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
                <{account_iri}> a mrl:InvestmentAccount ;
                    mrl:accountName "{name}" ;
                    mrl:accountBalance "{balance}"^^xsd:decimal ;
                    mrl:balanceDate "{balance_date}"^^xsd:date ;
                    mrl:accountCurrency mrl:{currency_local} ;
                    mrl:annualGrowthRate "{growth_rate}"^^xsd:decimal ;
                    mrl:annualDividendRate "{dividend_rate}"^^xsd:decimal ;
                    mrl:reinvestDividends "{reinvest_str}"^^xsd:boolean ;
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


def _page_context(request, accounts, edit_account=None, **kwargs):
    today = date.today().isoformat()
    currencies = get_currencies()
    jurisdictions = get_jurisdictions()
    total_balance = sum(float(a["balance"]) for a in accounts if a["balance"])
    return {
        "app_name": settings.app_name,
        "active": "investments",
        "accounts": accounts,
        "currencies": currencies,
        "jurisdictions": jurisdictions,
        "today": today,
        "edit_account": edit_account,
        "total_balance": total_balance,
        "account_types": INVESTMENT_ACCOUNT_TYPES,
        **kwargs,
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/investments", response_class=HTMLResponse)
async def investments_page(request: Request):
    accounts = get_all_investment_accounts()
    return templates.TemplateResponse(
        request=request,
        name="investments.html",
        context=_page_context(request, accounts),
    )


@router.post("/investments", response_class=HTMLResponse)
async def add_investment_account(
    request: Request,
    accountName: str = Form(...),
    accountBalance: float = Form(...),
    balanceDate: str = Form(...),
    accountCurrency: str = Form(...),
    annualGrowthRate: float = Form(0.0),
    annualDividendRate: float = Form(0.0),
    reinvestDividends: Optional[str] = Form(None),
    accountJurisdiction: str = Form(...),
    accountType: str = Form("InvestmentAccountType_StocksShares"),
    exchangeRateToBase: float = Form(1.0),
    exchangeRateDate: str = Form(""),
    accountNotes: str = Form(""),
):
    existing = get_all_investment_accounts()
    next_n = max([int(a["n"]) for a in existing if a["n"].isdigit()], default=0) + 1
    if not exchangeRateDate:
        exchangeRateDate = date.today().isoformat()
    reinvest = reinvestDividends is not None  # checkbox: present = True, absent = False

    save_investment_account(
        next_n, accountName, accountBalance, balanceDate,
        accountCurrency, annualGrowthRate, annualDividendRate,
        reinvest, accountJurisdiction, accountType,
        exchangeRateToBase, exchangeRateDate, accountNotes,
    )
    accounts = get_all_investment_accounts()
    return templates.TemplateResponse(
        request=request,
        name="investments.html",
        context=_page_context(request, accounts, saved=True),
    )


@router.get("/investments/{n}/edit", response_class=HTMLResponse)
async def edit_investment_account_form(request: Request, n: int):
    accounts = get_all_investment_accounts()
    account = next((a for a in accounts if a["n"] == str(n)), None)
    return templates.TemplateResponse(
        request=request,
        name="investments.html",
        context=_page_context(request, accounts, edit_account=account),
    )


@router.post("/investments/{n}/edit", response_class=HTMLResponse)
async def save_edit_investment_account(
    request: Request,
    n: int,
    accountName: str = Form(...),
    accountBalance: float = Form(...),
    balanceDate: str = Form(...),
    accountCurrency: str = Form(...),
    annualGrowthRate: float = Form(0.0),
    annualDividendRate: float = Form(0.0),
    reinvestDividends: Optional[str] = Form(None),
    accountJurisdiction: str = Form(...),
    accountType: str = Form("InvestmentAccountType_StocksShares"),
    exchangeRateToBase: float = Form(1.0),
    exchangeRateDate: str = Form(""),
    accountNotes: str = Form(""),
):
    if not exchangeRateDate:
        exchangeRateDate = date.today().isoformat()
    reinvest = reinvestDividends is not None

    save_investment_account(
        n, accountName, accountBalance, balanceDate,
        accountCurrency, annualGrowthRate, annualDividendRate,
        reinvest, accountJurisdiction, accountType,
        exchangeRateToBase, exchangeRateDate, accountNotes,
    )
    accounts = get_all_investment_accounts()
    return templates.TemplateResponse(
        request=request,
        name="investments.html",
        context=_page_context(request, accounts, saved=True),
    )


@router.post("/investments/{n}/delete", response_class=HTMLResponse)
async def delete_investment_account(request: Request, n: int):
    account_iri = f"{MRL}InvestmentAccount_{n}"
    store.update(f"""
        DELETE WHERE {{
            GRAPH <{DATA_GRAPH.value}> {{
                <{account_iri}> ?p ?o .
            }}
        }}
    """)
    accounts = get_all_investment_accounts()
    return templates.TemplateResponse(
        request=request,
        name="investments.html",
        context=_page_context(request, accounts, deleted=True),
    )
