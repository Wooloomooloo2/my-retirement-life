"""
Accounts routes — manage the user's cash AND investment accounts.

The /accounts and /investments URLs both render the unified accounts.html
template. /investments GETs redirect to /accounts; the legacy
/investments/{n}/... POST URLs are still served by investments.py for
backwards compatibility, but they too render accounts.html.

GET  /accounts                       — list all accounts (cash + invest) + form
POST /accounts                       — create a new CASH account
GET  /accounts/{n}/edit              — edit cash account N
POST /accounts/{n}/edit              — save edits to cash account N
POST /accounts/{n}/delete            — delete cash account N
GET  /accounts/{n}/projection        — per-account detail (cash)
POST /accounts/{n}/contribution(...) — contribution CRUD (cash)
POST /accounts/refresh-rates         — refresh BOTH cash AND investment FX rates

Changes (ADR-011, ADR-013, ADR-015, ADR-016, backlog #3):
  Page renders combined cash + invest list via get_all_accounts_combined().
  Refresh-rates updates both classes in one pass.
"""
from datetime import date
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse
from src.api.templates import templates
from typing import Optional
import pyoxigraph as og

from src.config import settings
from src.store.graph import store, MRL, DATA_GRAPH
from src.fx import fetch_rates, FxError

router = APIRouter()

# Cash account subtype labels for the unified form's Type dropdown.
CASH_ACCOUNT_TYPES = {
    "CashAccountType_Current":       "Current account",
    "CashAccountType_Savings":       "Savings account",
    "CashAccountType_FixedTerm":     "Fixed term deposit",
    "CashAccountType_TaxAdvantaged": "Tax-advantaged account",
    "CashAccountType_Other":         "Other",
}

RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
MRL_EXT  = "https://myretirementlife.app/ontology#"    # unused but kept for symmetry
MRL_EXT  = "https://myretirementlife.app/ontology/ext#"
ONTOLOGY_GRAPH = og.NamedNode("https://myretirementlife.app/ontology/graph")

FREQUENCY_MULTIPLIERS = {
    "FrequencyType_Weekly":       52,
    "FrequencyType_Fortnightly":  26,
    "FrequencyType_TwiceMonthly": 24,
    "FrequencyType_Monthly":      12,
    "FrequencyType_Quarterly":     4,
    "FrequencyType_Annually":      1,
}

FREQUENCY_LABELS = {
    "FrequencyType_Weekly":       "Weekly",
    "FrequencyType_Fortnightly":  "Fortnightly",
    "FrequencyType_TwiceMonthly": "Twice monthly",
    "FrequencyType_Monthly":      "Monthly",
    "FrequencyType_Quarterly":    "Quarterly",
    "FrequencyType_Annually":     "Annually",
}


# ---------------------------------------------------------------------------
# Contribution helpers (ADR-015)
# ---------------------------------------------------------------------------

def _next_contribution_n() -> int:
    """Return the next available AccountContribution N."""
    sparql = f"""
        PREFIX mrl: <{MRL}>
        PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
        SELECT (MAX(?n) AS ?maxN)
        WHERE {{
            GRAPH <{DATA_GRAPH.value}> {{
                ?s a mrl:AccountContribution .
                BIND(xsd:integer(STRAFTER(STR(?s), "AccountContribution_")) AS ?n)
            }}
        }}
    """
    results = list(store.query(sparql))
    try:
        max_n = int(str(results[0]["maxN"].value)) if results and results[0].get("maxN") else 0
    except (ValueError, AttributeError, TypeError):
        max_n = 0
    return max_n + 1


def get_contribution(account_iri_str: str) -> dict | None:
    """Return the single contribution for a given account IRI string, or None."""
    account_iri = og.NamedNode(account_iri_str)
    qs = list(store.store.quads_for_pattern(
        None, og.NamedNode(f"{MRL}contributionOwner"), account_iri, DATA_GRAPH))
    if not qs:
        return None
    c_iri = qs[0].subject

    def gv(prop):
        r = list(store.store.quads_for_pattern(
            c_iri, og.NamedNode(f"{MRL}{prop}"), None, DATA_GRAPH))
        return str(r[0].object.value) if r else ""

    def gl(prop):
        v = gv(prop)
        return v.split("#")[-1] if "#" in v else v

    freq = gl("contributionFrequency")
    amount_str = gv("contributionAmount")
    try:
        amount = float(amount_str)
    except (ValueError, TypeError):
        amount = 0.0
    multiplier  = FREQUENCY_MULTIPLIERS.get(freq, 12)
    annual      = round(amount * multiplier, 2)

    return {
        "iri":         str(c_iri.value),
        "amount":      amount_str,
        "frequency":   freq,
        "annualAmount": annual,
        "startYear":   gv("contributionStartYear"),
        "endYear":     gv("contributionEndYear"),
        "note":        gv("contributionNote"),
        "growthRate":  gv("contributionGrowthRate"),
    }


def save_contribution(
    account_iri_str: str,
    amount: float,
    frequency: str,
    start_year: Optional[int],
    end_year: Optional[int],
    note: str,
    growth_rate: float = 0.0,
) -> None:
    """Delete any existing contribution for this account and write a new one."""
    MRL_EXT_FULL = "https://myretirementlife.app/ontology/ext#"
    delete_contribution(account_iri_str)
    n     = _next_contribution_n()
    c_iri = f"{MRL}AccountContribution_{n}"

    triples = f"""
        <{c_iri}> a mrl:AccountContribution ;
            mrl:contributionAmount    "{amount}"^^xsd:decimal ;
            mrl:contributionFrequency mrlx:{frequency} ;
            mrl:contributionOwner     <{account_iri_str}> .
    """
    if start_year:
        triples += f'\n        <{c_iri}> mrl:contributionStartYear "{start_year}"^^xsd:integer .'
    if end_year:
        triples += f'\n        <{c_iri}> mrl:contributionEndYear "{end_year}"^^xsd:integer .'
    if note and note.strip():
        safe = note.replace('"', '\\"')
        triples += f'\n        <{c_iri}> mrl:contributionNote "{safe}" .'
    if growth_rate and growth_rate != 0.0:
        triples += f'\n        <{c_iri}> mrl:contributionGrowthRate "{growth_rate}"^^xsd:decimal .'

    store.update(f"""
        PREFIX mrl:  <{MRL}>
        PREFIX mrlx: <{MRL_EXT_FULL}>
        PREFIX xsd:  <http://www.w3.org/2001/XMLSchema#>
        INSERT DATA {{ GRAPH <{DATA_GRAPH.value}> {{ {triples} }} }}
    """)


def delete_contribution(account_iri_str: str) -> None:
    """Delete all contributions for a given account IRI string."""
    store.update(f"""
        PREFIX mrl: <{MRL}>
        DELETE {{ GRAPH <{DATA_GRAPH.value}> {{ ?c ?p ?o . }} }}
        WHERE  {{ GRAPH <{DATA_GRAPH.value}> {{ ?c mrl:contributionOwner <{account_iri_str}> ; ?p ?o . }} }}
    """)


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
            # ADR-015: contribution
            "contribution": get_contribution(str(iri.value)),
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
    return _render_accounts(request)


# ---------------------------------------------------------------------------
# Live exchange-rate refresh (ADR-016)
#
# Fetches today's rates from open.er-api.com for the person's base currency
# and writes each account's mrl:exchangeRateToBase + mrl:exchangeRateDate.
# This route triggers the application's ONLY outbound network call, and only
# the base currency code is transmitted — see src/fx.py for the details.
# ---------------------------------------------------------------------------

def _update_account_rate(account_iri_str: str, rate_to_base: float, rate_date: str) -> None:
    """Overwrite only the two exchange-rate properties on a single account,
    leaving every other triple on that account untouched."""
    store.update(f"""
        PREFIX mrl: <{MRL}>
        DELETE WHERE {{
            GRAPH <{DATA_GRAPH.value}> {{
                <{account_iri_str}> mrl:exchangeRateToBase ?r .
            }}
        }}
    """)
    store.update(f"""
        PREFIX mrl: <{MRL}>
        DELETE WHERE {{
            GRAPH <{DATA_GRAPH.value}> {{
                <{account_iri_str}> mrl:exchangeRateDate ?d .
            }}
        }}
    """)
    store.update(f"""
        PREFIX mrl: <{MRL}>
        PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
        INSERT DATA {{
            GRAPH <{DATA_GRAPH.value}> {{
                <{account_iri_str}> mrl:exchangeRateToBase "{rate_to_base}"^^xsd:decimal ;
                                    mrl:exchangeRateDate   "{rate_date}"^^xsd:date .
            }}
        }}
    """)


def get_all_accounts_combined() -> list:
    """Return cash + investment accounts merged into one list, each annotated
    with `account_class` ('CashAccount' or 'InvestmentAccount').

    Cash-only fields (interestRate) and investment-only fields (growthRate,
    dividendRate, reinvestDividends) are present where applicable; the
    template branches on `account_class` to decide which subset to show.
    """
    from src.api.routes.investments import (
        get_all_investment_accounts,
        INVESTMENT_ACCOUNT_TYPES,
        INVESTMENT_ACCOUNT_TYPES_SHORT,
    )

    cash = []
    for a in get_all_accounts():
        a["account_class"] = "CashAccount"
        a["accountTypeLabel"] = CASH_ACCOUNT_TYPES.get(
            a.get("accountType", ""),
            (a.get("accountType") or "").replace("CashAccountType_", ""),
        )
        a["accountTypeShort"] = a["accountTypeLabel"]
        cash.append(a)

    invest = []
    for a in get_all_investment_accounts():
        a["account_class"] = "InvestmentAccount"
        # accountTypeLabel / accountTypeShort are already set by get_all_investment_accounts()
        invest.append(a)

    # Cash first, then investment, both ordered by N ascending (existing semantics)
    return cash + invest


def _render_accounts(request: Request, **extra) -> HTMLResponse:
    """Render the unified accounts page, with optional extra context such as a
    rate-refresh result banner."""
    from src.api.routes.investments import (
        INVESTMENT_ACCOUNT_TYPES,
        INVESTMENT_ACCOUNT_TYPES_SHORT,
    )

    accounts = get_all_accounts_combined()

    # Header totals are displayed in the user's base currency, so each account's
    # balance must be FX-converted via mrl:exchangeRateToBase before summing.
    # Same-currency accounts have an empty FX field, which defaults to 1.0.
    def _base_balance(a: dict) -> float:
        raw = a.get("balance") or 0
        try:
            bal = float(raw)
        except (TypeError, ValueError):
            return 0.0
        fx_raw = a.get("exchangeRate") or ""
        try:
            fx = float(fx_raw) if fx_raw else 1.0
        except (TypeError, ValueError):
            fx = 1.0
        return bal * fx

    cash_total   = sum(_base_balance(a) for a in accounts
                       if a["account_class"] == "CashAccount")
    invest_total = sum(_base_balance(a) for a in accounts
                       if a["account_class"] == "InvestmentAccount")

    context = {
        "app_name":            settings.app_name,
        "active":              "accounts",
        "accounts":            accounts,
        "currencies":          get_currencies(),
        "jurisdictions":       get_jurisdictions(),
        "today":               date.today().isoformat(),
        "edit_account":        None,
        "cash_account_types":  CASH_ACCOUNT_TYPES,
        "invest_account_types": INVESTMENT_ACCOUNT_TYPES,
        "cash_total_balance":   cash_total,
        "invest_total_balance": invest_total,
        "total_balance":        cash_total + invest_total,
    }
    context.update(extra)
    return templates.TemplateResponse(
        request=request, name="accounts.html", context=context)


@router.post("/accounts/refresh-rates", response_class=HTMLResponse)
async def refresh_exchange_rates(request: Request):
    """Fetch today's live rates and update every account's exchange rate —
    BOTH cash AND investment accounts in a single pass.

    The rate stored on each account is mrl:exchangeRateToBase, defined as
    "1 unit of account currency = N units of base currency". The provider
    returns the inverse orientation (1 base = N foreign), so the value written
    is 1 / rate[account_code]. Accounts already in the base currency get 1.0.

    Transparency: this is the app's only outbound network call (to
    open.er-api.com), sending just the base currency code. See ADR-016.
    """
    from src.api.routes.profile import get_profile
    from src.api.routes.investments import (
        _update_investment_rate, get_all_investment_accounts,
    )

    base_local = (get_profile() or {}).get("baseCurrency", "")
    base_code  = _currency_code(base_local) if base_local else ""

    if not base_code:
        return _render_accounts(
            request,
            rate_refresh_error="Set your base currency on the Profile page "
                               "before refreshing exchange rates.",
        )

    try:
        data  = fetch_rates(base_code)
        rates = data["rates"]
    except FxError as exc:
        return _render_accounts(
            request,
            rate_refresh_error=f"Live rates unavailable — {exc}. "
                               "Existing rates were left unchanged.",
        )

    today   = date.today().isoformat()
    updated = 0
    skipped = []

    def _apply(updater, accs):
        nonlocal updated
        for acc in accs:
            code = acc.get("currencyCode", "")
            if not code:
                continue
            if code == base_code:
                updater(acc["iri"], 1.0, today)
                updated += 1
            elif code in rates and rates[code]:
                rate_to_base = round(1.0 / float(rates[code]), 6)
                updater(acc["iri"], rate_to_base, today)
                updated += 1
            else:
                skipped.append(code)

    _apply(_update_account_rate,    get_all_accounts())
    _apply(_update_investment_rate, get_all_investment_accounts())

    return _render_accounts(
        request,
        rate_refresh_count=updated,
        rate_refresh_base=base_code,
        rate_refresh_as_of=data.get("as_of", ""),
        rate_refresh_provider=data.get("provider", ""),
        rate_refresh_skipped=sorted(set(skipped)),
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
    # Redirect to edit so the contribution section is immediately available
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url=f"/accounts/{next_n}/edit", status_code=303)


@router.get("/accounts/{n}/edit", response_class=HTMLResponse)
async def edit_account_form(request: Request, n: int):
    """Return the form pre-filled for editing — loaded inline via HTMX."""
    combined = get_all_accounts_combined()
    account  = next(
        (a for a in combined if a["account_class"] == "CashAccount" and a["n"] == str(n)),
        None,
    )
    return _render_accounts(request, edit_account=account)


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
    return _render_accounts(request, saved=True)


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
    contributions_data = projection.get("account_contributions", {}).get(label, [0] * len(years))

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
            "app_name":           settings.app_name,
            "active":             "accounts",
            "account":            account,
            "back_url":           "/accounts",
            "back_label":         "Back to accounts",
            "years":              years,
            "balances":           balances,
            "withdrawals":        withdrawals,
            "returns_data":       returns_data,
            "contributions_data": contributions_data,
            "total_return":       total_return,
            "total_withdrawn":    total_withdrawn,
            "opening_balance":    opening_balance,
            "final_balance":      final_balance,
            "peak_balance":       peak_balance,
            "crossover_year":     crossover_year,
            "depletion_year":     depletion_year,
            "retirement_year":    projection["retirement_year"],
            "no_data":            False,
        }
    )


@router.post("/accounts/{n}/delete", response_class=HTMLResponse)
async def delete_account(request: Request, n: int):
    account_iri = f"{MRL}CashAccount_{n}"
    # Delete the account and any associated contributions
    delete_contribution(account_iri)
    store.update(f"""
        DELETE WHERE {{
            GRAPH <{DATA_GRAPH.value}> {{
                <{account_iri}> ?p ?o .
            }}
        }}
    """)
    return _render_accounts(request, deleted=True)


# ---------------------------------------------------------------------------
# Contribution routes (ADR-015)
# ---------------------------------------------------------------------------

@router.post("/accounts/{n}/contribution", response_class=HTMLResponse)
async def save_account_contribution(
    request: Request,
    n: int,
    contributionAmount:    float        = Form(...),
    contributionFrequency: str          = Form("FrequencyType_Monthly"),
    contributionStartYear: Optional[int] = Form(None),
    contributionEndYear:   Optional[int] = Form(None),
    contributionNote:      str          = Form(""),
    contributionGrowthRate: float       = Form(0.0),
):
    """Save (or replace) the contribution for cash account N."""
    account_iri = f"{MRL}CashAccount_{n}"
    save_contribution(
        account_iri,
        contributionAmount,
        contributionFrequency,
        contributionStartYear,
        contributionEndYear,
        contributionNote,
        growth_rate=contributionGrowthRate,
    )
    combined = get_all_accounts_combined()
    account  = next(
        (a for a in combined if a["account_class"] == "CashAccount" and a["n"] == str(n)),
        None,
    )
    return _render_accounts(request, edit_account=account, contribution_saved=True)


@router.post("/accounts/{n}/contribution/delete", response_class=HTMLResponse)
async def delete_account_contribution(request: Request, n: int):
    """Delete the contribution for cash account N."""
    account_iri = f"{MRL}CashAccount_{n}"
    delete_contribution(account_iri)
    combined = get_all_accounts_combined()
    account  = next(
        (a for a in combined if a["account_class"] == "CashAccount" and a["n"] == str(n)),
        None,
    )
    return _render_accounts(request, edit_account=account, contribution_deleted=True)