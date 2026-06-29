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
from fastapi.responses import HTMLResponse, RedirectResponse
from src.api.templates import templates
from typing import Optional
import pyoxigraph as og

from src.config import settings
from src.store.graph import store, MRL, DATA_GRAPH
from src.fx import fetch_rates, FxError
from src.api.routes.profile import (
    get_base_currency, get_currencies, _currency_code, _currency_symbol,
)

router = APIRouter()

RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
MRL_EXT = "https://myretirementlife.app/ontology/ext#"
ONTOLOGY_GRAPH = og.NamedNode("https://myretirementlife.app/ontology/graph")

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

        income_type   = get_local("incomeSourceType")
        currency_local = get_local("incomeCurrency")
        credited_to    = get_val("creditedToAccount")
        # creditedToAccount is an object property — the value is a full IRI;
        # the template uses the local name for the <option value> match.
        credited_local = credited_to.split("#")[-1].split("/")[-1] if credited_to else ""
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
            "currency":         currency_local,
            "currencyCode":     _currency_code(currency_local),
            "currencySymbol":   _currency_symbol(currency_local),
            "exchangeRate":     get_val("incomeExchangeRateToBase"),
            "exchangeRateDate": get_val("incomeExchangeRateDate"),
            "creditedToAccount": credited_local,
            # ADR-021: rental income linked to a property + net yield %.
            "rentalProperty":   get_local("rentalProperty"),
            "rentalYieldRate":  get_val("rentalYieldRate"),
        })
    sources.sort(key=lambda s: int(s["n"]) if s["n"].isdigit() else 0)
    return sources


def save_income_source(n: int, name: str, income_type: str,
                       annual_amount: float, growth_rate: float,
                       is_net_of_tax: bool,
                       start_year: Optional[int],
                       end_year: Optional[int],
                       currency_local: str = "",
                       exchange_rate: float = 1.0,
                       exchange_rate_date: str = "",
                       credited_to_account: str = "",
                       rental_property: str = "",
                       rental_yield: float = 0.0) -> None:
    """Write or overwrite an IncomeSource_N instance in the data graph.

    currency_local is the Currency individual local name (e.g. "GBP", "USD").
    Falls back to the person's base currency when blank.

    exchange_rate is mrl:incomeExchangeRateToBase — defined as
    "1 unit of income currency = N units of base currency". Only persisted when
    it differs from 1.0 (i.e. income currency != base currency). Mirrors the
    account FX-rate pattern from ADR-016.

    credited_to_account is the local name (e.g. "CashAccount_2") of the
    deposit account; only persisted when set. When absent, the engine falls
    back to surplus routing.
    """
    source_iri = f"{MRL}IncomeSource_{n}"
    person_iri = f"{MRL}Person_1"

    if not currency_local:
        currency_local = get_base_currency()["local"]

    if not exchange_rate_date:
        exchange_rate_date = date.today().isoformat()

    store.update(f"""
        DELETE WHERE {{
            GRAPH <{DATA_GRAPH.value}> {{
                <{source_iri}> ?p ?o .
            }}
        }}
    """)

    triples = f"""
        <{source_iri}> a mrl:IncomeSource ;
            mrl:incomeSourceName "{name}" ;
            mrl:incomeSourceType mrlx:{income_type} ;
            mrl:incomeAnnualAmount "{annual_amount}"^^xsd:decimal ;
            mrl:incomeGrowthRate "{growth_rate}"^^xsd:decimal ;
            mrl:incomeIsNetOfTax "{str(is_net_of_tax).lower()}"^^xsd:boolean ;
            mrl:incomeCurrency mrl:{currency_local} ;
            mrl:incomeOwner <{person_iri}> .
    """

    # Persist FX rate only when it actually differs from 1.0, mirroring the
    # accounts.py pattern. Same-currency rows stay clean in the store.
    if exchange_rate and float(exchange_rate) != 1.0:
        triples += f"""
        <{source_iri}> mrl:incomeExchangeRateToBase "{exchange_rate}"^^xsd:decimal ;
                       mrl:incomeExchangeRateDate   "{exchange_rate_date}"^^xsd:date .
        """

    # Deposit account link — only persist when the user actually chose one.
    if credited_to_account:
        triples += f"""
        <{source_iri}> mrl:creditedToAccount mrl:{credited_to_account} .
        """

    # ADR-021: rental property link + net yield. Only persisted when a property
    # is actually chosen; the yield is written alongside so the engine can
    # derive income from the property's value. A blank property leaves the
    # source on its static amount (parity).
    if rental_property:
        triples += f"""
        <{source_iri}> mrl:rentalProperty  mrl:{rental_property} ;
                       mrl:rentalYieldRate "{rental_yield or 0.0}"^^xsd:decimal .
        """

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


# ---------------------------------------------------------------------------
# Live exchange-rate refresh (ADR-016)
#
# Mirrors the accounts.py / investments.py pattern: fetches today's rates from
# open.er-api.com for the person's base currency and writes each income
# source's mrl:incomeExchangeRateToBase + mrl:incomeExchangeRateDate.
# ---------------------------------------------------------------------------

def _update_income_rate(source_iri_str: str, rate_to_base: float, rate_date: str) -> None:
    """Overwrite only the two FX-rate properties on a single income source,
    leaving every other triple untouched."""
    store.update(f"""
        PREFIX mrl: <{MRL}>
        DELETE WHERE {{
            GRAPH <{DATA_GRAPH.value}> {{
                <{source_iri_str}> mrl:incomeExchangeRateToBase ?r .
            }}
        }}
    """)
    store.update(f"""
        PREFIX mrl: <{MRL}>
        DELETE WHERE {{
            GRAPH <{DATA_GRAPH.value}> {{
                <{source_iri_str}> mrl:incomeExchangeRateDate ?d .
            }}
        }}
    """)
    store.update(f"""
        PREFIX mrl: <{MRL}>
        PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
        INSERT DATA {{
            GRAPH <{DATA_GRAPH.value}> {{
                <{source_iri_str}> mrl:incomeExchangeRateToBase "{rate_to_base}"^^xsd:decimal ;
                                   mrl:incomeExchangeRateDate   "{rate_date}"^^xsd:date .
            }}
        }}
    """)


def _get_retirement_year() -> Optional[int]:
    """Birth year + targetRetirementAge from Person_1, or None if either is missing."""
    person = og.NamedNode(f"{MRL}Person_1")
    dob_qs = list(store.store.quads_for_pattern(
        person, og.NamedNode(f"{MRL}dateOfBirth"), None, DATA_GRAPH))
    age_qs = list(store.store.quads_for_pattern(
        person, og.NamedNode(f"{MRL}targetRetirementAge"), None, DATA_GRAPH))
    if not dob_qs or not age_qs:
        return None
    try:
        return date.fromisoformat(str(dob_qs[0].object.value)).year + int(str(age_qs[0].object.value))
    except (ValueError, TypeError):
        return None


def _page_context(request, sources, edit_source=None, **kwargs):
    from src.api.routes.accounts import get_all_accounts_combined
    from src.api.routes.projection import (
        load_all_assets, load_all_accounts, get_projection_settings,
    )
    current_year = date.today().year
    # ADR-021: properties the user can link a rental income source to. The
    # picker is scoped to PropertyAsset to keep the concept clear, though the
    # engine treats any linked PhysicalAsset uniformly.
    properties = [
        {"label": a["label"], "name": a["name"], "value": round(a.get("balance") or 0.0)}
        for a in load_all_assets() if a.get("asset_subclass") == "PropertyAsset"
    ]
    # Item 54 routing-vs-drawdown guard. Per-account effective drawdown priority
    # (engine truth — unset defaults to 999 = drawn last) plus the EFFECTIVE
    # spending account (configured, else the engine's fallback). The form warns
    # only when income is routed to an account drawn LATER than spending AND at
    # the drawn-last default — relative, not absolute 999, so an undifferentiated
    # all-default setup (every account 999) doesn't trigger a useless warning.
    _accts = load_all_accounts()
    account_priorities = {a["label"]: a["drawdown_priority"] for a in _accts}
    _configured = get_projection_settings().get("spending_account_label") or ""
    if _configured and _configured in account_priorities:
        effective_spending_label = _configured
    else:
        effective_spending_label = (
            next((a["label"] for a in _accts
                  if a["account_class"] == "CashAccount"
                  and a.get("account_type_local") == "CashAccountType_Current"), None)
            or next((a["label"] for a in _accts if a["account_class"] == "CashAccount"), None)
            or (_accts[0]["label"] if _accts else "")
        )
    spending_priority = account_priorities.get(effective_spending_label, 999)
    return {
        "app_name": settings.app_name,
        "active": "income",
        "sources": sources,
        "income_type_options": INCOME_TYPE_LABELS,
        "edit_source": edit_source,
        "current_year": current_year,
        "retirement_year": _get_retirement_year(),
        "currencies":      get_currencies(),
        "base_currency":   get_base_currency(),
        "today":           date.today().isoformat(),
        "all_accounts":    get_all_accounts_combined(),
        "properties":      properties,
        "account_priorities":       account_priorities,
        "effective_spending_label": effective_spending_label,
        "spending_priority":        spending_priority,
        **kwargs,
    }


@router.get("/income", response_class=HTMLResponse)
async def income_page(request: Request, added: int = 0, saved: int = 0):
    # `added=1` / `saved=1` arrive via post/redirect/get after adding or editing
    # an income source, so the form is freshly blank and the banner confirms it.
    sources = get_all_income_sources()
    return templates.TemplateResponse(
        request=request,
        name="income.html",
        context=_page_context(request, sources, added=bool(added), saved=bool(saved)),
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
    incomeCurrency: str = Form(""),
    incomeExchangeRateToBase: float = Form(1.0),
    incomeExchangeRateDate: str = Form(""),
    creditedToAccount: str = Form(""),
    rentalProperty: str = Form(""),
    rentalYieldRate: float = Form(0.0),
):
    existing = get_all_income_sources()
    next_n = max([int(s["n"]) for s in existing if s["n"].isdigit()], default=0) + 1
    save_income_source(next_n, incomeSourceName, incomeSourceType,
                       incomeAnnualAmount, incomeGrowthRate,
                       incomeIsNetOfTax, incomeStartYear, incomeEndYear,
                       currency_local=incomeCurrency,
                       exchange_rate=incomeExchangeRateToBase,
                       exchange_rate_date=incomeExchangeRateDate,
                       credited_to_account=creditedToAccount,
                       rental_property=rentalProperty,
                       rental_yield=rentalYieldRate)
    return RedirectResponse(url="/income?added=1", status_code=303)


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
    incomeCurrency: str = Form(""),
    incomeExchangeRateToBase: float = Form(1.0),
    incomeExchangeRateDate: str = Form(""),
    creditedToAccount: str = Form(""),
    rentalProperty: str = Form(""),
    rentalYieldRate: float = Form(0.0),
):
    save_income_source(n, incomeSourceName, incomeSourceType,
                       incomeAnnualAmount, incomeGrowthRate,
                       incomeIsNetOfTax, incomeStartYear, incomeEndYear,
                       currency_local=incomeCurrency,
                       exchange_rate=incomeExchangeRateToBase,
                       exchange_rate_date=incomeExchangeRateDate,
                       credited_to_account=creditedToAccount,
                       rental_property=rentalProperty,
                       rental_yield=rentalYieldRate)
    # Post/redirect/get back to the list with a blank add form + "saved" banner
    # (matches budget.py — supersedes the earlier stay-in-edit-mode behaviour).
    return RedirectResponse(url="/income?saved=1", status_code=303)


@router.post("/income/refresh-rates", response_class=HTMLResponse)
async def refresh_income_exchange_rates(request: Request):
    """Fetch today's live rates and update every income source's FX rate.

    Mirrors POST /accounts/refresh-rates: the rate stored is
    mrl:incomeExchangeRateToBase, defined as "1 unit of income currency = N
    units of base currency". The provider returns the inverse orientation, so
    the stored value is 1 / rate[income_code]. Sources already in the base
    currency get 1.0. See ADR-016.
    """
    base = get_base_currency()
    base_code = base.get("code", "")

    if not base_code:
        return templates.TemplateResponse(
            request=request, name="income.html",
            context=_page_context(
                request, get_all_income_sources(),
                rate_refresh_error="Set your base currency on the Profile page "
                                   "before refreshing exchange rates.",
            ),
        )

    try:
        data  = fetch_rates(base_code)
        rates = data["rates"]
    except FxError as exc:
        return templates.TemplateResponse(
            request=request, name="income.html",
            context=_page_context(
                request, get_all_income_sources(),
                rate_refresh_error=f"Live rates unavailable — {exc}. "
                                   "Existing rates were left unchanged.",
            ),
        )

    today   = date.today().isoformat()
    updated = 0
    skipped = []
    for src in get_all_income_sources():
        code = src.get("currencyCode", "")
        if not code:
            continue
        if code == base_code:
            _update_income_rate(src["iri"], 1.0, today)
            updated += 1
        elif code in rates and rates[code]:
            rate_to_base = round(1.0 / float(rates[code]), 6)
            _update_income_rate(src["iri"], rate_to_base, today)
            updated += 1
        else:
            skipped.append(code)

    return templates.TemplateResponse(
        request=request, name="income.html",
        context=_page_context(
            request, get_all_income_sources(),
            rate_refresh_count=updated,
            rate_refresh_base=base_code,
            rate_refresh_as_of=data.get("as_of", ""),
            rate_refresh_provider=data.get("provider", ""),
            rate_refresh_skipped=sorted(set(skipped)),
        ),
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
