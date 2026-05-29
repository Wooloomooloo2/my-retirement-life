"""
Investment accounts routes — handlers for investment-class CRUD.

After backlog #3 (Accounts ↔ Investments IA unification): /investments GETs
redirect to /accounts; all POST routes still live here for backwards
compatibility but render the unified accounts.html template via the shared
_render_accounts() helper from accounts.py.

GET  /investments                       → 301 → /accounts
POST /investments                       — create a new investment account
GET  /investments/{n}/edit              → renders accounts.html with edit form
POST /investments/{n}/edit              — save edits to investment account N
POST /investments/{n}/delete            — delete investment account N
GET  /investments/{n}/projection        — per-account growth/drawdown detail
POST /investments/{n}/contribution(...) — contribution CRUD
POST /investments/refresh-rates         → 307 → /accounts/refresh-rates

Changes (ADR-011, ADR-013):
  get_all_investment_accounts() now reads drawdown eligibility and tax fields.
  save_investment_account() accepts and persists all new optional fields.
  Route handlers pass new form params through.
  All new fields are optional — existing accounts are unaffected.
"""
from datetime import date
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from src.api.templates import templates
from typing import Optional
import pyoxigraph as og

from src.config import settings
from src.store.graph import store, MRL, DATA_GRAPH
from src.fx import fetch_rates, FxError

router = APIRouter()

RDF_TYPE       = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
MRL_EXT        = "https://myretirementlife.app/ontology/ext#"
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
    """Return the next available AccountContribution N (shared namespace with accounts.py)."""
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
    employer_str = gv("employerContributionAmount")
    try:
        employer_amount = float(employer_str) if employer_str else 0.0
    except (ValueError, TypeError):
        employer_amount = 0.0
    multiplier      = FREQUENCY_MULTIPLIERS.get(freq, 12)
    annual          = round(amount * multiplier, 2)
    employer_annual = round(employer_amount * multiplier, 2)

    return {
        "iri":            str(c_iri.value),
        "amount":         amount_str,
        "frequency":      freq,
        "annualAmount":   annual,
        "employerAmount": employer_str,
        "employerAnnual": employer_annual,
        "fromPayroll":  gv("contributionFromPayroll") == "true",
        "startYear":    gv("contributionStartYear"),
        "endYear":      gv("contributionEndYear"),
        "note":         gv("contributionNote"),
        "growthRate":   gv("contributionGrowthRate"),
    }


def save_contribution(
    account_iri_str: str,
    amount: float,
    frequency: str,
    start_year: Optional[int],
    end_year: Optional[int],
    note: str,
    growth_rate: float = 0.0,
    employer_amount: float = 0.0,
    from_payroll: bool = False,
) -> None:
    """Delete any existing contribution for this account and write a new one."""
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
    if employer_amount and employer_amount != 0.0:
        triples += f'\n        <{c_iri}> mrl:employerContributionAmount "{employer_amount}"^^xsd:decimal .'
    if from_payroll:
        triples += f'\n        <{c_iri}> mrl:contributionFromPayroll "true"^^xsd:boolean .'

    store.update(f"""
        PREFIX mrl:  <{MRL}>
        PREFIX mrlx: <{MRL_EXT}>
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

INVESTMENT_ACCOUNT_TYPES = {
    "InvestmentAccountType_StocksShares":  "Stocks and shares",
    "InvestmentAccountType_TaxAdvantaged": "Tax-advantaged (ISA / Roth / TFSA)",
    "InvestmentAccountType_Pension":       "Self-directed pension (SIPP / IRA)",
    "InvestmentAccountType_WorkPension":   "Workplace pension (401(k) / auto-enrolment)",
    "InvestmentAccountType_UnitTrust":     "Unit trust / mutual fund",
    "InvestmentAccountType_Bonds":         "Bond portfolio",
    "InvestmentAccountType_Other":         "Other",
}

# Abbreviated labels for table display — full labels stay in the form dropdown
INVESTMENT_ACCOUNT_TYPES_SHORT = {
    "InvestmentAccountType_StocksShares":  "Stocks & shares",
    "InvestmentAccountType_TaxAdvantaged": "Tax-advantaged",
    "InvestmentAccountType_Pension":       "Pension",
    "InvestmentAccountType_WorkPension":   "Workplace pension",
    "InvestmentAccountType_UnitTrust":     "Unit trust",
    "InvestmentAccountType_Bonds":         "Bonds",
    "InvestmentAccountType_Other":         "Other",
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
    """Return all InvestmentAccount instances from the data graph, including
    drawdown eligibility (ADR-011) and tax treatment (ADR-013) fields.
    """
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
            # Existing fields
            "n":               n,
            "iri":             str(iri.value),
            "name":            get_val("accountName"),
            "balance":         get_val("accountBalance"),
            "balanceDate":     get_val("balanceDate"),
            "currency":        get_local("accountCurrency"),
            "currencyCode":    _currency_code(get_local("accountCurrency")),
            "currencySymbol":  _currency_symbol(get_local("accountCurrency")),
            "growthRate":      get_val("annualGrowthRate"),
            "dividendRate":    get_val("annualDividendRate"),
            "reinvestDividends": reinvest,
            "jurisdiction":    get_local("accountJurisdiction"),
            "accountType":      account_type,
            "accountTypeLabel": INVESTMENT_ACCOUNT_TYPES.get(account_type, account_type),
            "accountTypeShort": INVESTMENT_ACCOUNT_TYPES_SHORT.get(account_type, account_type.replace("InvestmentAccountType_", "")),
            "exchangeRate":    get_val("exchangeRateToBase"),
            "exchangeRateDate": get_val("exchangeRateDate"),
            "notes":           get_val("accountNotes"),
            # ADR-011: drawdown eligibility and ordering
            "drawdownPriority":     get_val("drawdownPriority"),
            "drawdownRatio":        get_val("drawdownRatio"),
            "drawdownMinAge":       get_val("drawdownMinAge"),
            "drawdownMaxAge":       get_val("drawdownMaxAge"),
            "drawdownEarliestDate": get_val("drawdownEarliestDate"),
            "drawdownLatestDate":   get_val("drawdownLatestDate"),
            # ADR-013: tax treatment
            "taxTreatment":               get_local("taxTreatment"),
            "effectiveWithdrawalTaxRate": get_val("effectiveWithdrawalTaxRate"),
            "annualTaxFreeWithdrawal":    get_val("annualTaxFreeWithdrawal"),
            # ADR-015: contribution
            "contribution": get_contribution(str(iri.value)),
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


def save_investment_account(
    n: int,
    name: str,
    balance: float,
    balance_date: str,
    currency_local: str,
    growth_rate: float,
    dividend_rate: float,
    reinvest_dividends: bool,
    jurisdiction_local: str,
    account_type: str,
    exchange_rate: float,
    exchange_rate_date: str,
    notes: str,
    # ADR-011: drawdown eligibility and ordering (all optional)
    drawdown_priority: str       = "",
    drawdown_ratio: str          = "",
    drawdown_min_age: str        = "",
    drawdown_max_age: str        = "",
    drawdown_earliest_date: str  = "",
    drawdown_latest_date: str    = "",
    # ADR-013: tax treatment (all optional)
    tax_treatment: str                  = "",
    effective_withdrawal_tax_rate: str  = "",
    annual_tax_free_withdrawal: str     = "",
) -> None:
    """Write or overwrite an InvestmentAccount_N instance in the data graph.

    All drawdown and tax fields are optional. Absent or blank values are not
    persisted — the projection engine treats absent properties as unrestricted.
    """
    account_iri  = f"{MRL}InvestmentAccount_{n}"
    person_iri   = f"{MRL}Person_1"
    reinvest_str = "true" if reinvest_dividends else "false"

    store.update(f"""
        DELETE WHERE {{
            GRAPH <{DATA_GRAPH.value}> {{
                <{account_iri}> ?p ?o .
            }}
        }}
    """)

    # --- Required fields ---
    triples = f"""
        <{account_iri}> a mrl:InvestmentAccount ;
            mrl:accountName        "{name}" ;
            mrl:accountBalance     "{balance}"^^xsd:decimal ;
            mrl:balanceDate        "{balance_date}"^^xsd:date ;
            mrl:accountCurrency    mrl:{currency_local} ;
            mrl:annualGrowthRate   "{growth_rate}"^^xsd:decimal ;
            mrl:annualDividendRate "{dividend_rate}"^^xsd:decimal ;
            mrl:reinvestDividends  "{reinvest_str}"^^xsd:boolean ;
            mrl:accountJurisdiction mrl:{jurisdiction_local} ;
            mrl:accountType        mrlx:{account_type} ;
            mrl:ownedBy            <{person_iri}> .
    """

    # --- Exchange rate ---
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


def _find_invest_edit(n: int) -> dict | None:
    """Locate an investment-class account by N within the combined list."""
    from src.api.routes.accounts import get_all_accounts_combined
    return next(
        (a for a in get_all_accounts_combined()
         if a["account_class"] == "InvestmentAccount" and a["n"] == str(n)),
        None,
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/investments", response_class=HTMLResponse)
async def investments_redirect():
    """Legacy URL — redirect to the unified /accounts page (backlog #3)."""
    return RedirectResponse(url="/accounts", status_code=301)


# ---------------------------------------------------------------------------
# Live exchange-rate refresh (ADR-016)
#
# Mirrors the cash-accounts refresh: fetches today's rates from open.er-api.com
# for the person's base currency and writes each investment account's
# mrl:exchangeRateToBase + mrl:exchangeRateDate. This is an outbound call that
# transmits only the base currency code — see src/fx.py.
# ---------------------------------------------------------------------------

def _update_investment_rate(account_iri_str: str, rate_to_base: float, rate_date: str) -> None:
    """Overwrite only the two exchange-rate properties on a single investment
    account, leaving every other triple on that account untouched."""
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


@router.post("/investments/refresh-rates")
async def refresh_investment_rates_redirect():
    """Legacy URL — the unified /accounts/refresh-rates updates both classes
    in one pass. 307 preserves the POST method (backlog #3)."""
    return RedirectResponse(url="/accounts/refresh-rates", status_code=307)


@router.post("/investments", response_class=HTMLResponse)
async def add_investment_account(
    request: Request,
    # Existing required fields
    accountName:         str   = Form(...),
    accountBalance:      float = Form(...),
    balanceDate:         str   = Form(...),
    accountCurrency:     str   = Form(...),
    annualGrowthRate:    float = Form(0.0),
    annualDividendRate:  float = Form(0.0),
    reinvestDividends:   Optional[str] = Form(None),
    accountJurisdiction: str   = Form(...),
    accountType:         str   = Form("InvestmentAccountType_StocksShares"),
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
    # ADR-015: optional contribution entered on the add form (all strings —
    # parsed by parse_add_contribution so an empty amount means "no contribution")
    contributionAmount:         str = Form(""),
    contributionFrequency:      str = Form("FrequencyType_Monthly"),
    contributionStartYear:      str = Form(""),
    contributionEndYear:        str = Form(""),
    contributionNote:           str = Form(""),
    contributionGrowthRate:     str = Form("0"),
    employerContributionAmount: str = Form(""),
    contributionFromPayroll:    str = Form(""),
):
    existing = get_all_investment_accounts()
    next_n   = max([int(a["n"]) for a in existing if a["n"].isdigit()], default=0) + 1
    if not exchangeRateDate:
        exchangeRateDate = date.today().isoformat()
    reinvest = reinvestDividends is not None

    save_investment_account(
        next_n, accountName, accountBalance, balanceDate,
        accountCurrency, annualGrowthRate, annualDividendRate,
        reinvest, accountJurisdiction, accountType,
        exchangeRateToBase, exchangeRateDate, accountNotes,
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
    from src.api.routes.accounts import parse_add_contribution
    contrib = parse_add_contribution(
        contributionAmount, contributionFrequency, contributionStartYear,
        contributionEndYear, contributionNote, contributionGrowthRate,
        employerContributionAmount, from_payroll=bool(contributionFromPayroll),
    )
    if contrib:
        save_contribution(f"{MRL}InvestmentAccount_{next_n}", **contrib)
    # Post/redirect/get back to a blank add form on the unified /accounts page
    # (the contribution is captured on the add form itself), so fields reset for
    # the next account and `?added=1` surfaces a clear "saved" confirmation.
    return RedirectResponse(url="/accounts?added=1", status_code=303)


@router.get("/investments/{n}/edit", response_class=HTMLResponse)
async def edit_investment_account_form(request: Request, n: int):
    from src.api.routes.accounts import _render_accounts
    return _render_accounts(request, edit_account=_find_invest_edit(n))


@router.post("/investments/{n}/edit", response_class=HTMLResponse)
async def save_edit_investment_account(
    request: Request,
    n: int,
    # Existing required fields
    accountName:         str   = Form(...),
    accountBalance:      float = Form(...),
    balanceDate:         str   = Form(...),
    accountCurrency:     str   = Form(...),
    annualGrowthRate:    float = Form(0.0),
    annualDividendRate:  float = Form(0.0),
    reinvestDividends:   Optional[str] = Form(None),
    accountJurisdiction: str   = Form(...),
    accountType:         str   = Form("InvestmentAccountType_StocksShares"),
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
    reinvest = reinvestDividends is not None

    save_investment_account(
        n, accountName, accountBalance, balanceDate,
        accountCurrency, annualGrowthRate, annualDividendRate,
        reinvest, accountJurisdiction, accountType,
        exchangeRateToBase, exchangeRateDate, accountNotes,
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
    from src.api.routes.accounts import _render_accounts, get_all_accounts_combined
    # Stay in edit mode after save (see budget.py for rationale).
    combined = get_all_accounts_combined()
    edit_account = next(
        (a for a in combined
         if a.get("n") == str(n) and a.get("account_class") == "InvestmentAccount"),
        None,
    )
    return _render_accounts(request, edit_account=edit_account, saved=True)


@router.get("/investments/{n}/projection", response_class=HTMLResponse)
async def investment_projection_detail(request: Request, n: int):
    """Per-account growth-vs-drawdown detail chart (ADR-012)."""
    from src.api.routes.projection import run_projection, get_projection_settings

    accounts = get_all_investment_accounts()
    account  = next((a for a in accounts if a["n"] == str(n)), None)
    if not account:
        return RedirectResponse("/accounts", status_code=303)

    label = f"InvestmentAccount_{n}"
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

    # Summary stats
    total_return    = round(sum(r for r in returns_data if r > 0), 0)
    total_withdrawn = round(sum(w for w in withdrawals  if w > 0), 0)
    opening_balance = balances[0] if balances else 0
    final_balance   = balances[-1] if balances else 0
    peak_balance    = max(balances) if balances else 0

    # First year where withdrawal exceeds growth (the crossover point)
    crossover_year = next(
        (years[i] for i, (r, w) in enumerate(zip(returns_data, withdrawals)) if w > r and w > 0),
        None
    )
    # First year balance reaches zero
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


@router.post("/investments/{n}/delete", response_class=HTMLResponse)
async def delete_investment_account(request: Request, n: int):
    account_iri = f"{MRL}InvestmentAccount_{n}"
    # Delete the account and any associated contributions
    delete_contribution(account_iri)
    store.update(f"""
        DELETE WHERE {{
            GRAPH <{DATA_GRAPH.value}> {{
                <{account_iri}> ?p ?o .
            }}
        }}
    """)
    from src.api.routes.accounts import _render_accounts
    return _render_accounts(request, deleted=True)


# ---------------------------------------------------------------------------
# Contribution routes (ADR-015)
# ---------------------------------------------------------------------------

@router.post("/investments/{n}/contribution", response_class=HTMLResponse)
async def save_investment_contribution(
    request: Request,
    n: int,
    contributionAmount:    float        = Form(...),
    contributionFrequency: str          = Form("FrequencyType_Monthly"),
    contributionStartYear: Optional[int] = Form(None),
    contributionEndYear:   Optional[int] = Form(None),
    contributionNote:      str          = Form(""),
    contributionGrowthRate: float       = Form(0.0),
    employerContributionAmount: float    = Form(0.0),
    contributionFromPayroll:    str      = Form(""),
):
    """Save (or replace) the contribution for investment account N."""
    account_iri = f"{MRL}InvestmentAccount_{n}"
    save_contribution(
        account_iri,
        contributionAmount,
        contributionFrequency,
        contributionStartYear,
        contributionEndYear,
        contributionNote,
        growth_rate=contributionGrowthRate,
        employer_amount=employerContributionAmount,
        from_payroll=bool(contributionFromPayroll),
    )
    from src.api.routes.accounts import _render_accounts
    return _render_accounts(request, edit_account=_find_invest_edit(n), contribution_saved=True)


@router.post("/investments/{n}/contribution/delete", response_class=HTMLResponse)
async def delete_investment_contribution(request: Request, n: int):
    """Delete the contribution for investment account N."""
    account_iri = f"{MRL}InvestmentAccount_{n}"
    delete_contribution(account_iri)
    from src.api.routes.accounts import _render_accounts
    return _render_accounts(request, edit_account=_find_invest_edit(n), contribution_deleted=True)