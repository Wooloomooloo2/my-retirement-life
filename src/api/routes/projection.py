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


def load_income() -> dict:
    income = og.NamedNode(f"{MRL}IncomeSource_1")
    type_check = list(store.store.quads_for_pattern(
        income, og.NamedNode(RDF_TYPE), None, DATA_GRAPH))
    if not type_check:
        return {"amount": 0, "growth_rate": 0}
    return {
        "amount": _float(income, "incomeAnnualAmount"),
        "growth_rate": _float(income, "incomeGrowthRate"),
    }


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
        lines.append({
            "annual_amount": amount * multiplier,
            "change_rate": _float(iri, "annualChangeRate"),
            "line_type": line_type,
            "loan_end_year": loan_end,
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
        return {"inflation_rate": 2.5}
    return {"inflation_rate": _float(ps, "inflationRate", 2.5)}


def save_projection_settings(inflation_rate: float) -> None:
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
        PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
        INSERT DATA {{
            GRAPH <{DATA_GRAPH.value}> {{
                <{ps_iri}> a mrl:ProjectionSettings ;
                    mrl:inflationRate "{inflation_rate}"^^xsd:decimal ;
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

    income_data = load_income()
    accounts = load_accounts()
    budget_lines = load_budget_lines()
    life_events = load_life_events()

    # Weighted average interest rate across all accounts
    total_balance = sum(a["balance"] for a in accounts)
    if total_balance > 0:
        weighted_rate = (
            sum(a["balance"] * a["interest_rate"] for a in accounts)
            / total_balance / 100
        )
    else:
        weighted_rate = 0.0

    # Adjust each account balance from its balance_date to current_year
    # using compound interest
    opening_balance = 0.0
    for a in accounts:
        years_elapsed = max(0, current_year - a["balance_date"].year)
        adjusted = a["balance"] * ((1 + a["interest_rate"] / 100) ** years_elapsed)
        opening_balance += adjusted

    # Year-by-year projection
    projection_years = []
    balance = opening_balance

    for year in range(current_year, end_year + 1):
        years_from_start = year - current_year

        # Income — grows each year, stops at retirement
        if year < retirement_year:
            income_amount = income_data["amount"] * (
                (1 + income_data["growth_rate"] / 100) ** years_from_start
            )
        else:
            income_amount = 0.0

        # Spending — each line grows at its own rate, loans expire
        mandatory = 0.0
        discretionary = 0.0
        loans = 0.0

        for line in budget_lines:
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
        "final_balance": round(final_balance, 0),
        "confidence": confidence,
        "confidence_label": confidence_label,
        "confidence_message": confidence_message,
        "weighted_rate": round(weighted_rate * 100, 2),
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/projection", response_class=HTMLResponse)
async def projection_page(request: Request):
    proj_settings = get_projection_settings()
    projection = run_projection(proj_settings["inflation_rate"])
    return templates.TemplateResponse(
        request=request,
        name="projection.html",
        context={
            "app_name": settings.app_name,
            "active": "projection",
            "projection": projection,
            "inflation_rate": proj_settings["inflation_rate"],
        }
    )


@router.post("/projection/settings", response_class=HTMLResponse)
async def update_projection_settings(
    request: Request,
    inflationRate: float = Form(2.5),
):
    save_projection_settings(inflationRate)
    proj_settings = get_projection_settings()
    projection = run_projection(proj_settings["inflation_rate"])
    return templates.TemplateResponse(
        request=request,
        name="projection.html",
        context={
            "app_name": settings.app_name,
            "active": "projection",
            "projection": projection,
            "inflation_rate": proj_settings["inflation_rate"],
            "settings_saved": True,
        }
    )
