"""
Projection routes — retirement burndown calculation and visualisation.

GET  /projection          — run projection and render chart
POST /projection/settings — save projection settings (inflation rate)
"""
from datetime import date
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse
from src.api.templates import templates
import pyoxigraph as og

from src.config import settings
from src.store.graph import store, MRL, DATA_GRAPH

router = APIRouter()

RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
MRL_EXT = "https://myretirementlife.app/ontology/ext#"
ONTOLOGY_GRAPH = og.NamedNode("https://myretirementlife.app/ontology/graph")

FREQUENCY_MULTIPLIERS = {
    "FrequencyType_Weekly": 52,
    "FrequencyType_Fortnightly": 26,
    "FrequencyType_TwiceMonthly": 24,
    "FrequencyType_Monthly": 12,
    "FrequencyType_Quarterly": 4,
    "FrequencyType_Annually": 1,
}


# ---------------------------------------------------------------------------
# Data loading helpers
# ---------------------------------------------------------------------------

def _quads(subject_iri, prop: str):
    return list(store.store.quads_for_pattern(
        subject_iri, og.NamedNode(f"{MRL}{prop}"), None, DATA_GRAPH))

def _val(subject_iri, prop: str, default="") -> str:
    qs = _quads(subject_iri, prop)
    return str(qs[0].object.value) if qs else default

def _local(subject_iri, prop: str) -> str:
    v = _val(subject_iri, prop)
    return v.split("#")[-1] if "#" in v else v

def _float(subject_iri, prop: str, default=0.0) -> float:
    try:
        return float(_val(subject_iri, prop, str(default)))
    except ValueError:
        return default

def _int(subject_iri, prop: str, default=0) -> int:
    try:
        return int(_val(subject_iri, prop, str(default)))
    except ValueError:
        return default


def load_profile() -> dict | None:
    person = og.NamedNode(f"{MRL}Person_1")
    type_check = list(store.store.quads_for_pattern(
        person, og.NamedNode(RDF_TYPE), None, DATA_GRAPH))
    if not type_check:
        return None
    dob_str = _val(person, "dateOfBirth")
    if not dob_str:
        return None
    try:
        dob = date.fromisoformat(dob_str)
        birth_year = dob.year
    except ValueError:
        return None
    return {
        "birth_year": birth_year,
        "retirement_age": _int(person, "targetRetirementAge", 67),
        "life_expectancy": _int(person, "lifeExpectancy", 85),
    }


def _col_index(jurisdiction_iri: og.NamedNode) -> float:
    """Read costOfLivingIndex from a Jurisdiction individual in the ontology graph."""
    qs = list(store.store.quads_for_pattern(
        jurisdiction_iri, og.NamedNode(f"{MRL}costOfLivingIndex"), None, ONTOLOGY_GRAPH))
    try:
        return float(qs[0].object.value) if qs else 1.0
    except (ValueError, IndexError):
        return 1.0


def load_col_ratio() -> float:
    """Return the spending multiplier to apply from retirement year onward.

    Reads mrl:residesIn and mrl:plansToRetireIn from Person_1.
    Returns retirement_col / current_col, or 1.0 if not set / same jurisdiction.
    """
    person = og.NamedNode(f"{MRL}Person_1")

    resides_qs = list(store.store.quads_for_pattern(
        person, og.NamedNode(f"{MRL}residesIn"), None, DATA_GRAPH))
    retire_qs = list(store.store.quads_for_pattern(
        person, og.NamedNode(f"{MRL}plansToRetireIn"), None, DATA_GRAPH))

    if not resides_qs or not retire_qs:
        return 1.0

    current_iri = resides_qs[0].object
    retire_iri = retire_qs[0].object

    if str(current_iri.value) == str(retire_iri.value):
        return 1.0

    current_col = _col_index(current_iri)
    retire_col = _col_index(retire_iri)

    if current_col == 0:
        return 1.0
    return round(retire_col / current_col, 6)


def load_all_income_sources() -> list:
    """Load all IncomeSource instances with their start/end years."""
    type_node = og.NamedNode(f"{MRL}IncomeSource")
    quads = store.store.quads_for_pattern(
        None, og.NamedNode(RDF_TYPE), type_node, DATA_GRAPH)
    sources = []
    for q in quads:
        iri = q.subject
        start_raw = _val(iri, "incomeStartYear", "")
        end_raw = _val(iri, "incomeEndYear", "")
        try:
            start_year = int(start_raw) if start_raw else None
        except ValueError:
            start_year = None
        try:
            end_year = int(end_raw) if end_raw else None
        except ValueError:
            end_year = None
        sources.append({
            "name": _val(iri, "incomeSourceName", "Income"),
            "amount": _float(iri, "incomeAnnualAmount"),
            "growth_rate": _float(iri, "incomeGrowthRate"),
            "start_year": start_year,
            "end_year": end_year,
        })
    return sources


def load_accounts() -> list:
    type_node = og.NamedNode(f"{MRL}CashAccount")
    quads = store.store.quads_for_pattern(
        None, og.NamedNode(RDF_TYPE), type_node, DATA_GRAPH)
    accounts = []
    for q in quads:
        iri = q.subject
        balance_date_str = _val(iri, "balanceDate",
                                 date.today().isoformat())
        try:
            balance_date = date.fromisoformat(balance_date_str)
        except ValueError:
            balance_date = date.today()
        raw_balance = _float(iri, "accountBalance")
        fx_rate = _float(iri, "exchangeRateToBase", 1.0)
        # Convert to base currency using stored exchange rate
        base_balance = raw_balance * fx_rate
        accounts.append({
            "balance": base_balance,
            "raw_balance": raw_balance,
            "fx_rate": fx_rate,
            "interest_rate": _float(iri, "annualInterestRate"),
            "balance_date": balance_date,
        })
    return accounts


def load_investment_accounts() -> list:
    """Load all InvestmentAccount instances with growth and dividend rates."""
    type_node = og.NamedNode(f"{MRL}InvestmentAccount")
    quads = store.store.quads_for_pattern(
        None, og.NamedNode(RDF_TYPE), type_node, DATA_GRAPH)
    investments = []
    for q in quads:
        iri = q.subject
        balance_date_str = _val(iri, "balanceDate", date.today().isoformat())
        try:
            balance_date = date.fromisoformat(balance_date_str)
        except ValueError:
            balance_date = date.today()
        raw_balance = _float(iri, "accountBalance")
        fx_rate = _float(iri, "exchangeRateToBase", 1.0)
        base_balance = raw_balance * fx_rate
        reinvest_raw = _val(iri, "reinvestDividends", "true")
        reinvest = reinvest_raw.lower() not in ("false", "0")
        investments.append({
            "balance": base_balance,
            "balance_date": balance_date,
            "growth_rate": _float(iri, "annualGrowthRate"),
            "dividend_rate": _float(iri, "annualDividendRate"),
            "reinvest_dividends": reinvest,
        })
    return investments


def load_budget_lines() -> list:
    type_node = og.NamedNode(f"{MRL}BudgetLine")
    quads = store.store.quads_for_pattern(
        None, og.NamedNode(RDF_TYPE), type_node, DATA_GRAPH)
    lines = []
    for q in quads:
        iri = q.subject
        freq = _local(iri, "budgetLineFrequency")
        multiplier = FREQUENCY_MULTIPLIERS.get(freq, 12)
        amount = _float(iri, "budgetLineAmount")
        line_type = _local(iri, "budgetLineType")
        loan_end_raw = _val(iri, "loanEndYear", "")
        try:
            loan_end = int(loan_end_raw) if loan_end_raw else None
        except ValueError:
            loan_end = None
        start_raw = _val(iri, "budgetStartYear", "")
        try:
            start_year = int(start_raw) if start_raw else None
        except ValueError:
            start_year = None
        end_raw = _val(iri, "budgetEndYear", "")
        try:
            end_year = int(end_raw) if end_raw else None
        except ValueError:
            end_year = None
        lines.append({
            "annual_amount": amount * multiplier,
            "change_rate": _float(iri, "annualChangeRate"),
            "line_type": line_type,
            "loan_end_year": loan_end,
            "start_year": start_year,
            "end_year": end_year,
        })
    return lines


def load_life_events() -> list:
    type_node = og.NamedNode(f"{MRL}LifeEvent")
    quads = store.store.quads_for_pattern(
        None, og.NamedNode(RDF_TYPE), type_node, DATA_GRAPH)
    events = []
    for q in quads:
        iri = q.subject
        try:
            year = int(_val(iri, "lifeEventYear", "0"))
        except ValueError:
            year = 0
        events.append({
            "year": year,
            "amount": _float(iri, "lifeEventAmount"),
        })
    return events


def get_projection_settings() -> dict:
    ps = og.NamedNode(f"{MRL}ProjectionSettings_1")
    type_check = list(store.store.quads_for_pattern(
        ps, og.NamedNode(RDF_TYPE), None, DATA_GRAPH))
    if not type_check:
        return {"inflation_rate": 2.5, "mc_profile": "MonteCarloProfile_Moderate"}
    mc_qs = list(store.store.quads_for_pattern(
        ps, og.NamedNode(f"{MRL}monteCarloProfile"), None, DATA_GRAPH))
    mc_local = "MonteCarloProfile_Moderate"
    if mc_qs:
        raw = str(mc_qs[0].object.value)
        mc_local = raw.split("#")[-1] if "#" in raw else raw
    return {
        "inflation_rate": _float(ps, "inflationRate", 2.5),
        "mc_profile": mc_local,
    }


def save_projection_settings(
    inflation_rate: float,
    mc_profile: str = "MonteCarloProfile_Moderate",
) -> None:
    ps_iri = f"{MRL}ProjectionSettings_1"
    person_iri = f"{MRL}Person_1"
    store.update(f"""
        DELETE WHERE {{
            GRAPH <{DATA_GRAPH.value}> {{
                <{ps_iri}> ?p ?o .
            }}
        }}
    """)
    store.update(f"""
        PREFIX mrl: <{MRL}>
        PREFIX mrlx: <{MRL_EXT}>
        PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
        INSERT DATA {{
            GRAPH <{DATA_GRAPH.value}> {{
                <{ps_iri}> a mrl:ProjectionSettings ;
                    mrl:inflationRate "{inflation_rate}"^^xsd:decimal ;
                    mrl:monteCarloProfile mrlx:{mc_profile} ;
                    mrl:projectionOwner <{person_iri}> .
            }}
        }}
    """)


# ---------------------------------------------------------------------------
# Projection engine
# ---------------------------------------------------------------------------

def run_projection(inflation_rate: float = 2.5) -> dict | None:
    profile = load_profile()
    if not profile:
        return None

    today = date.today()
    current_year = today.year
    birth_year = profile["birth_year"]
    retirement_year = birth_year + profile["retirement_age"]
    end_year = birth_year + profile["life_expectancy"]

    income_sources = load_all_income_sources()
    accounts = load_accounts()
    investment_accounts = load_investment_accounts()
    budget_lines = load_budget_lines()
    life_events = load_life_events()
    col_ratio = load_col_ratio()

    # --- Weighted return rate across cash + investment accounts ---
    # Uses initial (pre-growth) balances as weights, same approximation as existing cash logic.
    # Investment effective rate = growth_rate + dividend_rate (if reinvested).
    cash_rate_num = sum(a["balance"] * a["interest_rate"] for a in accounts)
    cash_balance_total = sum(a["balance"] for a in accounts)

    inv_effective_rates = [
        (inv["balance"],
         inv["growth_rate"] + (inv["dividend_rate"] if inv["reinvest_dividends"] else 0))
        for inv in investment_accounts
    ]
    inv_rate_num = sum(b * r for b, r in inv_effective_rates)
    inv_balance_total = sum(b for b, r in inv_effective_rates)

    all_balance_total = cash_balance_total + inv_balance_total
    if all_balance_total > 0:
        weighted_rate = (cash_rate_num + inv_rate_num) / all_balance_total / 100
    else:
        weighted_rate = 0.0

    # --- Opening balance: cash accounts grown to current year ---
    opening_balance = 0.0
    for a in accounts:
        years_elapsed = max(0, current_year - a["balance_date"].year)
        adjusted = a["balance"] * ((1 + a["interest_rate"] / 100) ** years_elapsed)
        opening_balance += adjusted

    # --- Opening balance: investment accounts grown to current year ---
    inv_opening = 0.0
    for inv in investment_accounts:
        years_elapsed = max(0, current_year - inv["balance_date"].year)
        effective_rate = inv["growth_rate"] + (inv["dividend_rate"] if inv["reinvest_dividends"] else 0)
        inv_opening += inv["balance"] * ((1 + effective_rate / 100) ** years_elapsed)
    opening_balance += inv_opening

    # --- Non-reinvested dividend income sources ---
    # Modelled as: portfolio_value_at_year * dividend_rate / 100
    # Portfolio value approximated by growing the opening investment value at growth_rate.
    dividend_income_sources = []
    for inv in investment_accounts:
        if not inv["reinvest_dividends"] and inv["dividend_rate"] > 0:
            years_elapsed = max(0, current_year - inv["balance_date"].year)
            opening_inv_value = inv["balance"] * ((1 + inv["growth_rate"] / 100) ** years_elapsed)
            dividend_income_sources.append({
                "opening_value": opening_inv_value,
                "growth_rate": inv["growth_rate"],
                "dividend_rate": inv["dividend_rate"],
            })

    # Year-by-year projection
    projection_years = []
    balance = opening_balance

    for year in range(current_year, end_year + 1):
        years_from_start = year - current_year

        # Income — sum all active sources for this year
        # Each source is active if: start_year <= year <= end_year (or null)
        income_amount = 0.0
        for src in income_sources:
            src_start = src["start_year"] or current_year
            src_end = src["end_year"]  # None = indefinite
            if year >= src_start and (src_end is None or year <= src_end):
                income_amount += src["amount"] * (
                    (1 + src["growth_rate"] / 100) ** years_from_start
                )

        # Non-reinvested dividend income: portfolio value grows at growth_rate,
        # dividend yield applied to that value each year
        for ds in dividend_income_sources:
            portfolio_value = ds["opening_value"] * ((1 + ds["growth_rate"] / 100) ** years_from_start)
            income_amount += portfolio_value * (ds["dividend_rate"] / 100)

        # Spending — each line grows at its own rate, loans expire
        mandatory = 0.0
        discretionary = 0.0
        loans = 0.0

        for line in budget_lines:
            if line["start_year"] and year < line["start_year"]:
                continue
            if line["end_year"] and year > line["end_year"]:
                continue
            if line["loan_end_year"] and year > line["loan_end_year"]:
                continue
            rate = line["change_rate"] if line["change_rate"] != 0 else inflation_rate
            annual = line["annual_amount"] * ((1 + rate / 100) ** years_from_start)
            lt = line["line_type"]
            if lt == "BudgetLineType_Mandatory":
                mandatory += annual
            elif lt == "BudgetLineType_Discretionary":
                discretionary += annual
            elif lt == "BudgetLineType_Loan":
                loans += annual

        # Life events this year
        life_event_costs = sum(
            e["amount"] for e in life_events
            if e["year"] == year and e["amount"] >= 0
        )
        life_event_receipts = sum(
            abs(e["amount"]) for e in life_events
            if e["year"] == year and e["amount"] < 0
        )

        # Cost-of-living adjustment: apply from retirement year if retiring abroad
        if col_ratio != 1.0 and year >= retirement_year:
            mandatory = mandatory * col_ratio
            discretionary = discretionary * col_ratio
            loans = loans * col_ratio

        # Interest earned on positive balance only
        interest = balance * weighted_rate if balance > 0 else 0.0

        # Net cashflow
        total_spending = mandatory + discretionary + loans + life_event_costs
        net = income_amount + interest + life_event_receipts - total_spending
        balance = balance + net

        projection_years.append({
            "year": year,
            "balance": round(balance, 0),
            "income": round(income_amount, 0),
            "mandatory": round(mandatory, 0),
            "discretionary": round(discretionary, 0),
            "loans": round(loans, 0),
            "life_event_costs": round(life_event_costs, 0),
            "life_event_receipts": round(life_event_receipts, 0),
            "interest": round(interest, 0),
            "is_retirement_year": year == retirement_year,
        })

    # Confidence scoring
    runs_out_year = next(
        (y["year"] for y in projection_years if y["balance"] < 0), None)
    final_balance = projection_years[-1]["balance"] if projection_years else 0

    if runs_out_year is None:
        confidence = "green"
        confidence_label = "On track"
        confidence_message = (
            f"Your savings last beyond your life expectancy "
            f"with £{final_balance:,.0f} remaining."
        )
    elif runs_out_year >= end_year - 5:
        confidence = "amber"
        confidence_label = "Borderline"
        confidence_message = (
            f"Your savings run out in {runs_out_year}, "
            f"within 5 years of your life expectancy."
        )
    else:
        confidence = "red"
        confidence_label = "At risk"
        confidence_message = (
            f"Your savings run out in {runs_out_year}, "
            f"{end_year - runs_out_year} years before your life expectancy."
        )

    return {
        "years": projection_years,
        "runs_out_year": runs_out_year,
        "retirement_year": retirement_year,
        "end_year": end_year,
        "current_year": current_year,
        "opening_balance": round(opening_balance, 0),
        "opening_investment_balance": round(inv_opening, 0),
        "final_balance": round(final_balance, 0),
        "confidence": confidence,
        "confidence_label": confidence_label,
        "confidence_message": confidence_message,
        "weighted_rate": round(weighted_rate * 100, 2),
        "col_ratio": col_ratio,
    }


# ---------------------------------------------------------------------------
# Monte Carlo engine
# ---------------------------------------------------------------------------

def _get_mc_params(profile_local: str) -> tuple[float, float]:
    """Read returnVolatility and inflationVolatility from a MonteCarloProfile individual."""
    profile_iri = og.NamedNode(f"{MRL_EXT}{profile_local}")
    qs_ret = list(store.store.quads_for_pattern(
        profile_iri, og.NamedNode(f"{MRL_EXT}returnVolatility"), None, ONTOLOGY_GRAPH))
    qs_inf = list(store.store.quads_for_pattern(
        profile_iri, og.NamedNode(f"{MRL_EXT}inflationVolatility"), None, ONTOLOGY_GRAPH))
    try:
        return_vol = float(qs_ret[0].object.value) if qs_ret else 6.0
    except (ValueError, IndexError):
        return_vol = 6.0
    try:
        inflation_vol = float(qs_inf[0].object.value) if qs_inf else 1.5
    except (ValueError, IndexError):
        inflation_vol = 1.5
    return return_vol, inflation_vol


def run_monte_carlo(
    inflation_rate: float = 2.5,
    mc_profile_local: str = "MonteCarloProfile_Moderate",
    n_sims: int = 500,
) -> dict | None:
    """Run N Monte Carlo simulations with randomised returns and inflation.

    Each simulation draws year-by-year shocks from N(0, volatility) and adds
    them to the deterministic weighted_rate and inflation_rate.  Income source
    growth rates are fixed (user-specified); only savings returns and the
    inflation-linked portion of budget lines are perturbed.

    Returns P10 / P50 / P90 balance arrays and a success rate.
    """
    import numpy as np

    profile = load_profile()
    if not profile:
        return None

    return_vol, inflation_vol = _get_mc_params(mc_profile_local)

    today = date.today()
    current_year = today.year
    birth_year = profile["birth_year"]
    retirement_year = birth_year + profile["retirement_age"]
    end_year = birth_year + profile["life_expectancy"]

    income_sources = load_all_income_sources()
    accounts = load_accounts()
    investment_accounts = load_investment_accounts()
    budget_lines = load_budget_lines()
    life_events = load_life_events()
    col_ratio = load_col_ratio()

    year_range = list(range(current_year, end_year + 1))
    n_years = len(year_range)

    # --- Opening balance (same logic as run_projection) ---
    cash_rate_num = sum(a["balance"] * a["interest_rate"] for a in accounts)
    cash_balance_total = sum(a["balance"] for a in accounts)
    inv_effective_rates = [
        (inv["balance"],
         inv["growth_rate"] + (inv["dividend_rate"] if inv["reinvest_dividends"] else 0))
        for inv in investment_accounts
    ]
    inv_rate_num = sum(b * r for b, r in inv_effective_rates)
    inv_balance_total = sum(b for b, _ in inv_effective_rates)
    all_balance_total = cash_balance_total + inv_balance_total
    weighted_rate = (cash_rate_num + inv_rate_num) / all_balance_total / 100 if all_balance_total > 0 else 0.0

    opening_balance = 0.0
    for a in accounts:
        ye = max(0, current_year - a["balance_date"].year)
        opening_balance += a["balance"] * ((1 + a["interest_rate"] / 100) ** ye)
    for inv in investment_accounts:
        ye = max(0, current_year - inv["balance_date"].year)
        eff = inv["growth_rate"] + (inv["dividend_rate"] if inv["reinvest_dividends"] else 0)
        opening_balance += inv["balance"] * ((1 + eff / 100) ** ye)

    # --- Non-reinvested dividend income sources ---
    dividend_income_sources = []
    for inv in investment_accounts:
        if not inv["reinvest_dividends"] and inv["dividend_rate"] > 0:
            ye = max(0, current_year - inv["balance_date"].year)
            opening_inv_value = inv["balance"] * ((1 + inv["growth_rate"] / 100) ** ye)
            dividend_income_sources.append({
                "opening_value": opening_inv_value,
                "growth_rate": inv["growth_rate"],
                "dividend_rate": inv["dividend_rate"],
            })

    # --- Pre-compute deterministic per-year values ---
    # Income from income sources and dividends does not vary with MC shocks.
    income_per_year = []
    for yi, year in enumerate(year_range):
        total = 0.0
        for src in income_sources:
            src_start = src["start_year"] or current_year
            src_end = src["end_year"]
            if year >= src_start and (src_end is None or year <= src_end):
                total += src["amount"] * ((1 + src["growth_rate"] / 100) ** yi)
        for ds in dividend_income_sources:
            pv = ds["opening_value"] * ((1 + ds["growth_rate"] / 100) ** yi)
            total += pv * (ds["dividend_rate"] / 100)
        income_per_year.append(total)

    # Active budget lines per year: (base_annual, own_rate, line_type)
    # own_rate == 0 means "use inflation" → perturbed per sim; otherwise fixed.
    budget_per_year = []
    for yi, year in enumerate(year_range):
        active = []
        for line in budget_lines:
            if line["start_year"] and year < line["start_year"]:
                continue
            if line["end_year"] and year > line["end_year"]:
                continue
            if line["loan_end_year"] and year > line["loan_end_year"]:
                continue
            active.append((line["annual_amount"], line["change_rate"], line["line_type"]))
        budget_per_year.append((active, year >= retirement_year))

    life_costs = [
        sum(e["amount"] for e in life_events if e["year"] == y and e["amount"] >= 0)
        for y in year_range
    ]
    life_receipts = [
        sum(abs(e["amount"]) for e in life_events if e["year"] == y and e["amount"] < 0)
        for y in year_range
    ]

    # --- Draw all shocks at once ---
    rng = np.random.default_rng()
    # return_shocks: fractional (added directly to weighted_rate)
    return_shocks = rng.normal(0.0, return_vol / 100.0, (n_sims, n_years))
    # inflation_shocks: percentage points (added directly to inflation_rate)
    inflation_shocks = rng.normal(0.0, inflation_vol, (n_sims, n_years))

    all_balances = np.empty((n_sims, n_years), dtype=np.float64)

    for sim in range(n_sims):
        balance = opening_balance
        for yi in range(n_years):
            sim_rate = max(0.0, weighted_rate + return_shocks[sim, yi])
            sim_inflation = max(0.1, inflation_rate + inflation_shocks[sim, yi])

            # Spending
            mandatory = discretionary = loans = 0.0
            active_lines, is_post_retirement = budget_per_year[yi]
            for base, own_rate, lt in active_lines:
                rate = own_rate if own_rate != 0.0 else sim_inflation
                annual = base * ((1 + rate / 100) ** yi)
                if lt == "BudgetLineType_Mandatory":
                    mandatory += annual
                elif lt == "BudgetLineType_Discretionary":
                    discretionary += annual
                elif lt == "BudgetLineType_Loan":
                    loans += annual

            if col_ratio != 1.0 and is_post_retirement:
                mandatory *= col_ratio
                discretionary *= col_ratio
                loans *= col_ratio

            interest = balance * sim_rate if balance > 0.0 else 0.0
            total_spending = mandatory + discretionary + loans + life_costs[yi]
            balance += income_per_year[yi] + interest + life_receipts[yi] - total_spending
            all_balances[sim, yi] = balance

    p10 = np.percentile(all_balances, 10, axis=0).round(0).tolist()
    p50 = np.percentile(all_balances, 50, axis=0).round(0).tolist()
    p90 = np.percentile(all_balances, 90, axis=0).round(0).tolist()

    # Success: simulations where the balance never goes below zero
    success_rate = round(float(np.mean(np.all(all_balances >= 0, axis=1))) * 100, 1)

    return {
        "years": year_range,
        "p10": p10,
        "p50": p50,
        "p90": p90,
        "success_rate": success_rate,
        "n_sims": n_sims,
        "profile": mc_profile_local,
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/projection", response_class=HTMLResponse)
async def projection_page(request: Request):
    proj_settings = get_projection_settings()
    projection = run_projection(proj_settings["inflation_rate"])
    mc = run_monte_carlo(proj_settings["inflation_rate"], proj_settings["mc_profile"])
    return templates.TemplateResponse(
        request=request,
        name="projection.html",
        context={
            "app_name": settings.app_name,
            "active": "projection",
            "projection": projection,
            "mc": mc,
            "mc_profile": proj_settings["mc_profile"],
            "inflation_rate": proj_settings["inflation_rate"],
        }
    )


@router.post("/projection/mc-profile", response_class=HTMLResponse)
async def save_mc_profile(
    request: Request,
    mc_profile: str = Form("MonteCarloProfile_Moderate"),
):
    """Save the selected Monte Carlo profile and redirect back to the projection."""
    from fastapi.responses import RedirectResponse
    proj_settings = get_projection_settings()
    save_projection_settings(proj_settings["inflation_rate"], mc_profile)
    return RedirectResponse(url="/projection", status_code=303)
