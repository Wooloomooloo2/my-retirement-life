"""
Accounts routes — manage the user's cash accounts.

GET  /accounts              — list all accounts + add form
POST /accounts              — create a new account
GET  /accounts/{n}/edit     — load edit form for account N (HTMX partial)
POST /accounts/{n}/edit     — save edits to account N
POST /accounts/{n}/delete   — delete account N

Changes (ADR-011, ADR-013):
  get_all_accounts() now reads drawdown eligibility properties and tax fields.
  save_account() now accepts and persists all new optional fields.
  Route handlers pass new form params through to save_account().
  All new fields are optional — existing accounts saved without them are unaffected.
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
MRL_EXT  = "https://myretirementlife.app/ontology/ext#"
ONTOLOGY_GRAPH = og.NamedNode("https://myretirementlife.app/ontology/graph")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_all_accounts() -> list:
    """Return all CashAccount instances from the data graph, including
    drawdown eligibility (ADR-011) and tax treatment (ADR-013) fields.
    """
    type_node = og.NamedNode(f"{MRL}CashAccount")
    quads = store.store.quads_for_pattern(None, og.NamedNode(RDF_TYPE), type_node, DATA_GRAPH)
    accounts = []
    for q in quads:
        iri = q.subject
        n = str(iri.value).split("CashAccount_")[-1]

        def get_val(prop):
            qs = list(store.store.quads_for_pattern(
                iri, og.NamedNode(f"{MRL}{prop}"), None, DATA_GRAPH))
            return str(qs[0].object.value) if qs else ""

        def get_local(prop):
            v = get_val(prop)
            return v.split("#")[-1] if "#" in v else v

        accounts.append({
            # Existing fields
            "n":                n,
            "iri":              str(iri.value),
            "name":             get_val("accountName"),
            "balance":          get_val("accountBalance"),
            "balanceDate":      get_val("balanceDate"),
            "currency":         get_local("accountCurrency"),
            "currencyCode":     _currency_code(get_local("accountCurrency")),
            "currencySymbol":   _currency_symbol(get_local("accountCurrency")),
            "interestRate":     get_val("annualInterestRate"),
            "jurisdiction":     get_local("accountJurisdiction"),
            "accountType":      get_local("accountType"),
            "exchangeRate":     get_val("exchangeRateToBase"),
            "exchangeRateDate": get_val("exchangeRateDate"),
            "notes":            get_val("accountNotes"),
            # ADR-011: drawdown eligibility and ordering
            "drawdownPriority":     get_val("drawdownPriority"),
            "drawdownRatio":        get_val("drawdownRatio"),
            "drawdownMinAge":       get_val("drawdownMinAge"),
            "drawdownMaxAge":       get_val("drawdownMaxAge"),
            "drawdownEarliestDate": get_val("drawdownEarliestDate"),
            "drawdownLatestDate":   get_val("drawdownLatestDate"),
            # ADR-013: tax treatment
            "taxTreatment":                  get_local("taxTreatment"),
            "effectiveWithdrawalTaxRate":    get_val("effectiveWithdrawalTaxRate"),
            "annualTaxFreeWithdrawal":       get_val("annualTaxFreeWithdrawal"),
        })
    accounts.sort(key=lambda a: int(a["n"]) if a["n"].isdigit() else 0)
    return accounts


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
                "iri":   str(r["iri"].value),
                "local": str(r["iri"].value).split("#")[-1],
                "code":  str(r["code"].value),
                "name":  str(r["name"].value),
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
                "iri":   str(r["iri"].value),
                "local": str(r["iri"].value).split("#")[-1],
                "code":  str(r["code"].value),
                "name":  str(r["name"].value),
            })
        except Exception:
            pass
    return jurisdictions


def save_account(
    n: int,
    name: str,
    balance: float,
    balance_date: str,
    currency_local: str,
    interest_rate: float,
    jurisdiction_local: str,
    account_type: str,
    exchange_rate: float,
    exchange_rate_date: str,
    notes: str,
    # ADR-011: drawdown eligibility and ordering (all optional)
    drawdown_priority: str      = "",
    drawdown_ratio: str         = "",
    drawdown_min_age: str       = "",
    drawdown_max_age: str       = "",
    drawdown_earliest_date: str = "",
    drawdown_latest_date: str   = "",
    # ADR-013: tax treatment (all optional)
    tax_treatment: str                  = "",
    effective_withdrawal_tax_rate: str  = "",
    annual_tax_free_withdrawal: str     = "",
) -> None:
    """Write or overwrite a CashAccount_N instance in the data graph.

    All drawdown and tax fields are optional. Absent or blank values are not
    persisted — the projection engine treats absent properties as unrestricted.
    """
    account_iri = f"{MRL}CashAccount_{n}"
    person_iri  = f"{MRL}Person_1"

    # Wipe the existing instance first
    store.update(f"""
        DELETE WHERE {{
            GRAPH <{DATA_GRAPH.value}> {{
                <{account_iri}> ?p ?o .
            }}
        }}
    """)

    # --- Build required triple block ---
    # All required fields go into a single INSERT DATA block.
    # Optional fields are appended only when present and valid.
    triples = f"""
        <{account_iri}> a mrl:CashAccount ;
            mrl:accountName        "{name}" ;
            mrl:accountBalance     "{balance}"^^xsd:decimal ;
            mrl:balanceDate        "{balance_date}"^^xsd:date ;
            mrl:accountCurrency    mrl:{currency_local} ;
            mrl:annualInterestRate "{interest_rate}"^^xsd:decimal ;
            mrl:accountJurisdiction mrl:{jurisdiction_local} ;
            mrl:accountType        mrlx:{account_type} ;
            mrl:ownedBy            <{person_iri}> .
    """

    # --- Exchange rate (existing optional block) ---
    if exchange_rate and float(exchange_rate) != 1.0:
        triples += f"""
        <{account_iri}> mrl:exchangeRateToBase "{exchange_rate}"^^xsd:decimal ;
                        mrl:exchangeRateDate   "{exchange_rate_date}"^^xsd:date .
        """

    # --- Notes ---
    if notes and notes.strip():
        safe_notes = notes.replace('"', '\\"')
        triples += f'\n        <{account_iri}> mrl:accountNotes "{safe_notes}" .'

    # --- ADR-011: drawdown eligibility and ordering ---
    if drawdown_priority.strip():
        try:
            p = int(drawdown_priority.strip())
            triples += f'\n        <{account_iri}> mrl:drawdownPriority "{p}"^^xsd:integer .'
        except ValueError:
            pass

    if drawdown_ratio.strip():
        try:
            r = float(drawdown_ratio.strip())
            if 0.0 <= r <= 1.0:
                triples += f'\n        <{account_iri}> mrl:drawdownRatio "{r}"^^xsd:decimal .'
        except ValueError:
            pass

    if drawdown_min_age.strip():
        try:
            a = float(drawdown_min_age.strip())
            triples += f'\n        <{account_iri}> mrl:drawdownMinAge "{a}"^^xsd:decimal .'
        except ValueError:
            pass

    if drawdown_max_age.strip():
        try:
            a = float(drawdown_max_age.strip())
            triples += f'\n        <{account_iri}> mrl:drawdownMaxAge "{a}"^^xsd:decimal .'
        except ValueError:
            pass

    if drawdown_earliest_date.strip():
        triples += f'\n        <{account_iri}> mrl:drawdownEarliestDate "{drawdown_earliest_date.strip()}"^^xsd:date .'

    if drawdown_latest_date.strip():
        triples += f'\n        <{account_iri}> mrl:drawdownLatestDate "{drawdown_latest_date.strip()}"^^xsd:date .'

    # --- ADR-013: tax treatment ---
    # taxTreatment is an object property pointing to a mrlx: individual
    if tax_treatment.strip():
        triples += f'\n        <{account_iri}> mrl:taxTreatment mrlx:{tax_treatment.strip()} .'

    if effective_withdrawal_tax_rate.strip():
        try:
            rate_pct = float(effective_withdrawal_tax_rate.strip())
            if 0.0 <= rate_pct <= 100.0:
                triples += f'\n        <{account_iri}> mrl:effectiveWithdrawalTaxRate "{rate_pct / 100.0}"^^xsd:decimal .'
        except ValueError:
            pass

    if annual_tax_free_withdrawal.strip():
        try:
            amt = float(annual_tax_free_withdrawal.strip())
            if amt >= 0:
                triples += f'\n        <{account_iri}> mrl:annualTaxFreeWithdrawal "{amt}"^^xsd:decimal .'
        except ValueError:
            pass

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
# Routes
# ---------------------------------------------------------------------------

@router.get("/accounts", response_class=HTMLResponse)
async def accounts_page(request: Request):
    accounts      = get_all_accounts()
    currencies    = get_currencies()
    jurisdictions = get_jurisdictions()
    today         = date.today().isoformat()
    return templates.TemplateResponse(
        request=request,
        name="accounts.html",
        context={
            "app_name":     settings.app_name,
            "active":       "accounts",
            "accounts":     accounts,
            "currencies":   currencies,
            "jurisdictions": jurisdictions,
            "today":        today,
            "edit_account": None,
        }
    )


@router.post("/accounts", response_class=HTMLResponse)
async def add_account(
    request: Request,
    # Existing required fields
    accountName:         str   = Form(...),
    accountBalance:      float = Form(...),
    balanceDate:         str   = Form(...),
    accountCurrency:     str   = Form(...),
    annualInterestRate:  float = Form(0.0),
    accountJurisdiction: str   = Form(...),
    accountType:         str   = Form("CashAccountType_Current"),
    exchangeRateToBase:  float = Form(1.0),
    exchangeRateDate:    str   = Form(""),
    accountNotes:        str   = Form(""),
    # ADR-011: drawdown eligibility (all optional)
    drawdownPriority:     str  = Form(""),
    drawdownRatio:        str  = Form(""),
    drawdownMinAge:       str  = Form(""),
    drawdownMaxAge:       str  = Form(""),
    drawdownEarliestDate: str  = Form(""),
    drawdownLatestDate:   str  = Form(""),
    # ADR-013: tax treatment (all optional)
    taxTreatment:                str = Form(""),
    effectiveWithdrawalTaxRate:  str = Form(""),
    annualTaxFreeWithdrawal:     str = Form(""),
):
    existing = get_all_accounts()
    next_n   = max([int(a["n"]) for a in existing if a["n"].isdigit()], default=0) + 1
    if not exchangeRateDate:
        exchangeRateDate = date.today().isoformat()

    save_account(
        next_n, accountName, accountBalance, balanceDate,
        accountCurrency, annualInterestRate, accountJurisdiction,
        accountType, exchangeRateToBase, exchangeRateDate, accountNotes,
        drawdown_priority=drawdownPriority,
        drawdown_ratio=drawdownRatio,
        drawdown_min_age=drawdownMinAge,
        drawdown_max_age=drawdownMaxAge,
        drawdown_earliest_date=drawdownEarliestDate,
        drawdown_latest_date=drawdownLatestDate,
        tax_treatment=taxTreatment,
        effective_withdrawal_tax_rate=effectiveWithdrawalTaxRate,
        annual_tax_free_withdrawal=annualTaxFreeWithdrawal,
    )

    accounts      = get_all_accounts()
    currencies    = get_currencies()
    jurisdictions = get_jurisdictions()
    today         = date.today().isoformat()
    return templates.TemplateResponse(
        request=request,
        name="accounts.html",
        context={
            "app_name":     settings.app_name,
            "active":       "accounts",
            "accounts":     accounts,
            "currencies":   currencies,
            "jurisdictions": jurisdictions,
            "today":        today,
            "edit_account": None,
            "saved":        True,
        }
    )


@router.get("/accounts/{n}/edit", response_class=HTMLResponse)
async def edit_account_form(request: Request, n: int):
    """Return the form pre-filled for editing — loaded inline via HTMX."""
    accounts      = get_all_accounts()
    account       = next((a for a in accounts if a["n"] == str(n)), None)
    currencies    = get_currencies()
    jurisdictions = get_jurisdictions()
    today         = date.today().isoformat()
    return templates.TemplateResponse(
        request=request,
        name="accounts.html",
        context={
            "app_name":     settings.app_name,
            "active":       "accounts",
            "accounts":     accounts,
            "currencies":   currencies,
            "jurisdictions": jurisdictions,
            "today":        today,
            "edit_account": account,
        }
    )


@router.post("/accounts/{n}/edit", response_class=HTMLResponse)
async def save_edit_account(
    request: Request,
    n: int,
    # Existing required fields
    accountName:         str   = Form(...),
    accountBalance:      float = Form(...),
    balanceDate:         str   = Form(...),
    accountCurrency:     str   = Form(...),
    annualInterestRate:  float = Form(0.0),
    accountJurisdiction: str   = Form(...),
    accountType:         str   = Form("CashAccountType_Current"),
    exchangeRateToBase:  float = Form(1.0),
    exchangeRateDate:    str   = Form(""),
    accountNotes:        str   = Form(""),
    # ADR-011: drawdown eligibility (all optional)
    drawdownPriority:     str  = Form(""),
    drawdownRatio:        str  = Form(""),
    drawdownMinAge:       str  = Form(""),
    drawdownMaxAge:       str  = Form(""),
    drawdownEarliestDate: str  = Form(""),
    drawdownLatestDate:   str  = Form(""),
    # ADR-013: tax treatment (all optional)
    taxTreatment:                str = Form(""),
    effectiveWithdrawalTaxRate:  str = Form(""),
    annualTaxFreeWithdrawal:     str = Form(""),
):
    if not exchangeRateDate:
        exchangeRateDate = date.today().isoformat()

    save_account(
        n, accountName, accountBalance, balanceDate,
        accountCurrency, annualInterestRate, accountJurisdiction,
        accountType, exchangeRateToBase, exchangeRateDate, accountNotes,
        drawdown_priority=drawdownPriority,
        drawdown_ratio=drawdownRatio,
        drawdown_min_age=drawdownMinAge,
        drawdown_max_age=drawdownMaxAge,
        drawdown_earliest_date=drawdownEarliestDate,
        drawdown_latest_date=drawdownLatestDate,
        tax_treatment=taxTreatment,
        effective_withdrawal_tax_rate=effectiveWithdrawalTaxRate,
        annual_tax_free_withdrawal=annualTaxFreeWithdrawal,
    )

    accounts      = get_all_accounts()
    currencies    = get_currencies()
    jurisdictions = get_jurisdictions()
    today         = date.today().isoformat()
    return templates.TemplateResponse(
        request=request,
        name="accounts.html",
        context={
            "app_name":     settings.app_name,
            "active":       "accounts",
            "accounts":     accounts,
            "currencies":   currencies,
            "jurisdictions": jurisdictions,
            "today":        today,
            "edit_account": None,
            "saved":        True,
        }
    )


@router.get("/accounts/{n}/projection", response_class=HTMLResponse)
async def account_projection_detail(request: Request, n: int):
    """Per-account growth-vs-drawdown detail chart for cash accounts."""
    from fastapi.responses import RedirectResponse
    from src.api.routes.projection import run_projection, get_projection_settings

    accounts      = get_all_accounts()
    account       = next((a for a in accounts if a["n"] == str(n)), None)
    if not account:
        return RedirectResponse("/accounts", status_code=303)

    label         = f"CashAccount_{n}"
    proj_settings = get_projection_settings()
    projection    = run_projection(proj_settings["inflation_rate"], proj_settings)

    no_data = not projection or label not in projection.get("account_balances", {})
    if no_data:
        return templates.TemplateResponse(
            request=request,
            name="investment_projection.html",
            context={
                "app_name":   settings.app_name,
                "active":     "accounts",
                "account":    account,
                "back_url":   "/accounts",
                "back_label": "Back to accounts",
                "no_data":    True,
            }
        )

    years        = [y["year"] for y in projection["years"]]
    balances     = projection["account_balances"][label]
    withdrawals  = projection["account_withdrawals"][label]
    returns_data = projection["account_returns"][label]

    total_return    = round(sum(r for r in returns_data if r > 0), 0)
    total_withdrawn = round(sum(w for w in withdrawals  if w > 0), 0)
    opening_balance = balances[0]  if balances else 0
    final_balance   = balances[-1] if balances else 0
    peak_balance    = max(balances) if balances else 0

    crossover_year = next(
        (years[i] for i, (r, w) in enumerate(zip(returns_data, withdrawals)) if w > r and w > 0),
        None
    )
    depletion_year = next(
        (years[i] for i, b in enumerate(balances) if b <= 0),
        None
    )

    return templates.TemplateResponse(
        request=request,
        name="investment_projection.html",
        context={
            "app_name":        settings.app_name,
            "active":          "accounts",
            "account":         account,
            "back_url":        "/accounts",
            "back_label":      "Back to accounts",
            "years":           years,
            "balances":        balances,
            "withdrawals":     withdrawals,
            "returns_data":    returns_data,
            "total_return":    total_return,
            "total_withdrawn": total_withdrawn,
            "opening_balance": opening_balance,
            "final_balance":   final_balance,
            "peak_balance":    peak_balance,
            "crossover_year":  crossover_year,
            "depletion_year":  depletion_year,
            "retirement_year": projection["retirement_year"],
            "no_data":         False,
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
    accounts      = get_all_accounts()
    currencies    = get_currencies()
    jurisdictions = get_jurisdictions()
    today         = date.today().isoformat()
    return templates.TemplateResponse(
        request=request,
        name="accounts.html",
        context={
            "app_name":     settings.app_name,
            "active":       "accounts",
            "accounts":     accounts,
            "currencies":   currencies,
            "jurisdictions": jurisdictions,
            "today":        today,
            "edit_account": None,
            "deleted":      True,
        }
    )