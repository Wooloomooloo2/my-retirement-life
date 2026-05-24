"""
Budget routes — manage the user's budget lines.

GET  /budget              — list all budget lines + add form
POST /budget              — create a new budget line
GET  /budget/{n}/edit     — load edit form for budget line N
POST /budget/{n}/edit     — save edits to budget line N
POST /budget/{n}/delete   — delete budget line N
"""
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

# Frequency multipliers for normalising to annual amounts
FREQUENCY_MULTIPLIERS = {
    "FrequencyType_Weekly": 52,
    "FrequencyType_Fortnightly": 26,
    "FrequencyType_TwiceMonthly": 24,
    "FrequencyType_Monthly": 12,
    "FrequencyType_Quarterly": 4,
    "FrequencyType_Annually": 1,
}

FREQUENCY_LABELS = {
    "FrequencyType_Weekly": "Weekly",
    "FrequencyType_Fortnightly": "Fortnightly (every 2 weeks)",
    "FrequencyType_TwiceMonthly": "Twice monthly",
    "FrequencyType_Monthly": "Monthly",
    "FrequencyType_Quarterly": "Quarterly",
    "FrequencyType_Annually": "Annually",
}


def to_annual(amount: float, frequency_local: str) -> float:
    """Convert an amount at a given frequency to its annual equivalent."""
    multiplier = FREQUENCY_MULTIPLIERS.get(frequency_local, 12)
    return round(amount * multiplier, 2)


def get_all_budget_lines() -> list:
    """Return all BudgetLine instances from the data graph."""
    type_node = og.NamedNode(f"{MRL}BudgetLine")
    quads = store.store.quads_for_pattern(
        None, og.NamedNode(RDF_TYPE), type_node, DATA_GRAPH)
    lines = []
    for q in quads:
        iri = q.subject
        n = str(iri.value).split("BudgetLine_")[-1]

        def get_val(prop):
            qs = list(store.store.quads_for_pattern(
                iri, og.NamedNode(f"{MRL}{prop}"), None, DATA_GRAPH))
            return str(qs[0].object.value) if qs else ""

        def get_local(prop):
            v = get_val(prop)
            return v.split("#")[-1] if "#" in v else v

        freq = get_local("budgetLineFrequency")
        amount = get_val("budgetLineAmount")
        annual = to_annual(float(amount), freq) if amount else 0

        lines.append({
            "n": n,
            "iri": str(iri.value),
            "name": get_val("budgetLineName"),
            "amount": amount,
            "frequency": freq,
            "frequencyLabel": FREQUENCY_LABELS.get(freq, freq),
            "annualAmount": annual,
            "lineType": get_local("budgetLineType"),
            "changeRate": get_val("annualChangeRate"),
            "loanEndYear": get_val("loanEndYear"),
            "startYear": get_val("budgetStartYear"),
            "endYear": get_val("budgetEndYear"),
        })
    lines.sort(key=lambda l: int(l["n"]) if l["n"].isdigit() else 0)
    return lines


def get_all_contributions_for_budget() -> list:
    """Return all AccountContribution instances with their owning account name.

    Used for the read-only 'Account contributions' section on the budget page.
    """
    type_node = og.NamedNode(f"{MRL}AccountContribution")
    quads     = store.store.quads_for_pattern(None, og.NamedNode(RDF_TYPE), type_node, DATA_GRAPH)
    results   = []

    for q in quads:
        c_iri = q.subject

        def gv(prop):
            r = list(store.store.quads_for_pattern(
                c_iri, og.NamedNode(f"{MRL}{prop}"), None, DATA_GRAPH))
            return str(r[0].object.value) if r else ""

        def gl(prop):
            v = gv(prop)
            return v.split("#")[-1] if "#" in v else v

        # Resolve account name via contributionOwner
        owner_qs = list(store.store.quads_for_pattern(
            c_iri, og.NamedNode(f"{MRL}contributionOwner"), None, DATA_GRAPH))
        owner_label = ""
        account_name = ""
        if owner_qs:
            owner_iri = owner_qs[0].object
            owner_label = str(owner_iri.value).split("#")[-1]
            name_qs = list(store.store.quads_for_pattern(
                owner_iri, og.NamedNode(f"{MRL}accountName"), None, DATA_GRAPH))
            account_name = str(name_qs[0].object.value) if name_qs else owner_label

        freq       = gl("contributionFrequency")
        multiplier = FREQUENCY_MULTIPLIERS.get(freq, 12)
        amount_str = gv("contributionAmount")
        try:
            amount = float(amount_str)
        except (ValueError, TypeError):
            amount = 0.0
        annual = round(amount * multiplier, 2)

        results.append({
            "accountLabel": owner_label,
            "accountName":  account_name,
            "amount":       amount_str,
            "frequency":    freq,
            "frequencyLabel": FREQUENCY_LABELS.get(freq, freq),
            "annualAmount": annual,
            "startYear":    gv("contributionStartYear"),
            "endYear":      gv("contributionEndYear"),
            "growthRate":   gv("contributionGrowthRate"),
            "note":         gv("contributionNote"),
        })

    results.sort(key=lambda x: x["accountName"])
    return results


def _int_or_none(v):
    try:
        return int(v) if v else None
    except (ValueError, TypeError):
        return None


def _float_or_zero(v):
    try:
        return float(v) if v else 0.0
    except (ValueError, TypeError):
        return 0.0


def _horizon() -> tuple[int, int, int | None]:
    """Return (current_year, end_year, retirement_year) for the annual-spending
    chart. Uses the profile's life expectancy when available; otherwise falls
    back to a 40-year window. retirement_year is None when no profile is set.
    """
    from datetime import date
    current_year = date.today().year
    try:
        from src.api.routes.projection import load_profile
        prof = load_profile()
    except Exception:
        prof = None
    if prof:
        retirement_year = prof["birth_year"] + prof["retirement_age"]
        end_year        = prof["birth_year"] + prof["life_expectancy"]
        return current_year, end_year, retirement_year
    return current_year, current_year + 40, None


def compute_annual_spending_series(lines: list, current_year: int, end_year: int) -> dict:
    """Per-year spending arrays in today's pounds, broken out by line type.

    For each line, applies its `change_rate` (real growth above inflation) but
    NOT the base inflation rate — the budget page is conceptually a real-terms
    plan. The projection engine layers inflation on top of this when computing
    actual nominal cash outflows.

    Respects each line's start_year / end_year / loan_end_year so non-
    overlapping lines no longer double-count in any single year.
    """
    years         = list(range(current_year, end_year + 1))
    n             = len(years)
    mandatory     = [0.0] * n
    discretionary = [0.0] * n
    loans         = [0.0] * n

    for line in lines:
        annual      = _float_or_zero(line.get("annualAmount"))
        change_rate = _float_or_zero(line.get("changeRate"))
        start       = _int_or_none(line.get("startYear"))
        end         = _int_or_none(line.get("endYear"))
        loan_end    = _int_or_none(line.get("loanEndYear"))
        line_type   = line.get("lineType", "")

        for i, year in enumerate(years):
            if start    is not None and year < start:    continue
            if end      is not None and year > end:      continue
            if loan_end is not None and year > loan_end: continue
            amount = annual * ((1 + change_rate / 100) ** i)
            if   line_type == "BudgetLineType_Mandatory":     mandatory[i]     += amount
            elif line_type == "BudgetLineType_Discretionary": discretionary[i] += amount
            elif line_type == "BudgetLineType_Loan":          loans[i]         += amount

    total = [m + d + l for m, d, l in zip(mandatory, discretionary, loans)]
    return {
        "years":         years,
        "mandatory":     [round(x, 0) for x in mandatory],
        "discretionary": [round(x, 0) for x in discretionary],
        "loans":         [round(x, 0) for x in loans],
        "total":         [round(x, 0) for x in total],
    }


def compute_annual_contributions_series(
    contributions: list,
    current_year: int,
    end_year: int,
    retirement_year: int | None,
) -> list:
    """Per-year contributions array in today's pounds.

    Mirrors the engine's logic in `projection.py`:
      - Default active window: current_year … retirement_year (inclusive)
      - Growth: base × (1 + g/100) ** years_active, where years_active is
        zero in the first active year

    Returned in real terms (no inflation lift), matching the budget-spending
    series convention. Contributions are a cashflow commitment alongside
    spending — the chart stacks them on top of the spending categories.
    """
    years = list(range(current_year, end_year + 1))
    series = [0.0] * len(years)
    default_end = retirement_year if retirement_year is not None else end_year

    for c in contributions:
        annual = _float_or_zero(c.get("annualAmount"))
        g_rate = _float_or_zero(c.get("growthRate"))
        start  = _int_or_none(c.get("startYear")) or current_year
        end    = _int_or_none(c.get("endYear"))   or default_end

        for i, year in enumerate(years):
            if year < start or year > end:
                continue
            years_active = year - start
            series[i] += annual * ((1 + g_rate / 100) ** years_active)

    return [round(x, 0) for x in series]


def get_budget_metrics(series: dict, retirement_year: int | None) -> dict:
    """Pick out the three headline numbers shown above the chart: today,
    at retirement, and the peak year. Each entry is
    {year, total, spending, contributions} (or None when no data, or when no
    retirement year is set for the at-retirement slot).

    `total` is spending + contributions — the full cashflow commitment.
    Snapshot cards show that total with a breakdown line beneath.
    """
    if not series["years"] or not series["total"]:
        return {"today": None, "retirement": None, "peak": None}

    years         = series["years"]
    total         = series["total"]
    spending      = series["spending_total"]
    contributions = series["contributions"]

    def snapshot(idx):
        return {
            "year":          years[idx],
            "total":         total[idx],
            "spending":      spending[idx],
            "contributions": contributions[idx],
        }

    today = snapshot(0)

    retirement = None
    if retirement_year is not None and years[0] <= retirement_year <= years[-1]:
        retirement = snapshot(retirement_year - years[0])

    peak_idx = max(range(len(total)), key=lambda i: total[i])
    peak     = snapshot(peak_idx)

    return {"today": today, "retirement": retirement, "peak": peak}


def save_budget_line(n: int, name: str, amount: float, frequency: str,
                     line_type: str, change_rate: float,
                     loan_end_year: Optional[int],
                     start_year: Optional[int] = None,
                     end_year: Optional[int] = None) -> None:
    """Write or overwrite a BudgetLine_N instance in the data graph."""
    line_iri = f"{MRL}BudgetLine_{n}"
    person_iri = f"{MRL}Person_1"

    store.update(f"""
        DELETE WHERE {{
            GRAPH <{DATA_GRAPH.value}> {{
                <{line_iri}> ?p ?o .
            }}
        }}
    """)

    store.update(f"""
        PREFIX mrl:  <{MRL}>
        PREFIX mrlx: <{MRL_EXT}>
        PREFIX xsd:  <http://www.w3.org/2001/XMLSchema#>

        INSERT DATA {{
            GRAPH <{DATA_GRAPH.value}> {{
                <{line_iri}> a mrl:BudgetLine ;
                    mrl:budgetLineName "{name}" ;
                    mrl:budgetLineAmount "{amount}"^^xsd:decimal ;
                    mrl:budgetLineFrequency mrlx:{frequency} ;
                    mrl:budgetLineType mrlx:{line_type} ;
                    mrl:annualChangeRate "{change_rate}"^^xsd:decimal ;
                    mrl:budgetOwner <{person_iri}> .
            }}
        }}
    """)

    if loan_end_year:
        store.update(f"""
            PREFIX mrl: <{MRL}>
            PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
            INSERT DATA {{
                GRAPH <{DATA_GRAPH.value}> {{
                    <{line_iri}> mrl:loanEndYear "{loan_end_year}"^^xsd:integer .
                }}
            }}
        """)

    if start_year:
        store.update(f"""
            PREFIX mrl: <{MRL}>
            PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
            INSERT DATA {{
                GRAPH <{DATA_GRAPH.value}> {{
                    <{line_iri}> mrl:budgetStartYear "{start_year}"^^xsd:integer .
                }}
            }}
        """)

    if end_year:
        store.update(f"""
            PREFIX mrl: <{MRL}>
            PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
            INSERT DATA {{
                GRAPH <{DATA_GRAPH.value}> {{
                    <{line_iri}> mrl:budgetEndYear "{end_year}"^^xsd:integer .
                }}
            }}
        """)


def _page_context(request, lines, edit_line=None, **kwargs):
    contributions = get_all_contributions_for_budget()
    current_year, end_year, retirement_year = _horizon()

    spending_series      = compute_annual_spending_series(lines, current_year, end_year)
    contributions_series = compute_annual_contributions_series(
        contributions, current_year, end_year, retirement_year)

    # Combined series: spending categories + contributions, plus a single
    # spending-only total and a combined grand-total for the snapshot cards.
    spending_total = spending_series["total"]
    grand_total    = [s + c for s, c in zip(spending_total, contributions_series)]

    series = {
        "years":          spending_series["years"],
        "mandatory":      spending_series["mandatory"],
        "discretionary":  spending_series["discretionary"],
        "loans":          spending_series["loans"],
        "contributions":  contributions_series,
        "spending_total": spending_total,
        "total":          grand_total,
    }
    metrics = get_budget_metrics(series, retirement_year)

    return {
        "app_name":          settings.app_name,
        "active":            "budget",
        "lines":             lines,
        "series":            series,
        "metrics":           metrics,
        "retirement_year":   retirement_year,
        "current_year":      current_year,
        "end_year":          end_year,
        "frequency_options": FREQUENCY_LABELS,
        "edit_line":         edit_line,
        "contributions":     contributions,
        **kwargs,
    }


@router.get("/budget", response_class=HTMLResponse)
async def budget_page(request: Request):
    lines = get_all_budget_lines()
    return templates.TemplateResponse(
        request=request,
        name="budget.html",
        context=_page_context(request, lines),
    )


@router.post("/budget", response_class=HTMLResponse)
async def add_budget_line(
    request: Request,
    budgetLineName: str = Form(...),
    budgetLineAmount: float = Form(...),
    budgetLineFrequency: str = Form("FrequencyType_Monthly"),
    budgetLineType: str = Form(...),
    annualChangeRate: float = Form(0.0),
    loanEndYear: Optional[int] = Form(None),
    budgetStartYear: Optional[int] = Form(None),
    budgetEndYear: Optional[int] = Form(None),
):
    existing = get_all_budget_lines()
    next_n = max([int(l["n"]) for l in existing if l["n"].isdigit()], default=0) + 1
    save_budget_line(next_n, budgetLineName, budgetLineAmount,
                     budgetLineFrequency, budgetLineType,
                     annualChangeRate, loanEndYear,
                     budgetStartYear, budgetEndYear)
    lines = get_all_budget_lines()
    return templates.TemplateResponse(
        request=request,
        name="budget.html",
        context=_page_context(request, lines, saved=True),
    )


@router.get("/budget/{n}/edit", response_class=HTMLResponse)
async def edit_budget_line_form(request: Request, n: int):
    lines = get_all_budget_lines()
    edit_line = next((l for l in lines if l["n"] == str(n)), None)
    return templates.TemplateResponse(
        request=request,
        name="budget.html",
        context=_page_context(request, lines, edit_line=edit_line),
    )


@router.post("/budget/{n}/edit", response_class=HTMLResponse)
async def save_edit_budget_line(
    request: Request,
    n: int,
    budgetLineName: str = Form(...),
    budgetLineAmount: float = Form(...),
    budgetLineFrequency: str = Form("FrequencyType_Monthly"),
    budgetLineType: str = Form(...),
    annualChangeRate: float = Form(0.0),
    loanEndYear: Optional[int] = Form(None),
    budgetStartYear: Optional[int] = Form(None),
    budgetEndYear: Optional[int] = Form(None),
):
    save_budget_line(n, budgetLineName, budgetLineAmount,
                     budgetLineFrequency, budgetLineType,
                     annualChangeRate, loanEndYear,
                     budgetStartYear, budgetEndYear)
    lines = get_all_budget_lines()
    return templates.TemplateResponse(
        request=request,
        name="budget.html",
        context=_page_context(request, lines, saved=True),
    )


@router.post("/budget/{n}/delete", response_class=HTMLResponse)
async def delete_budget_line(request: Request, n: int):
    line_iri = f"{MRL}BudgetLine_{n}"
    store.update(f"""
        DELETE WHERE {{
            GRAPH <{DATA_GRAPH.value}> {{
                <{line_iri}> ?p ?o .
            }}
        }}
    """)
    lines = get_all_budget_lines()
    return templates.TemplateResponse(
        request=request,
        name="budget.html",
        context=_page_context(request, lines, deleted=True),
    )
