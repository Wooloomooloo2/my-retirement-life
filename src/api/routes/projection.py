"""
Projection routes — retirement burndown calculation and visualisation.

GET  /projection             — run projection and render chart
POST /projection/mc-profile  — save Monte Carlo profile
POST /projection/settings    — save full projection settings (new)

Engine changes (ADR-011, ADR-012, ADR-013):
  ADR-012: Per-account balance tracking replaces single merged pool.
           Monte Carlo σ applied to investment accounts only; cash is deterministic.
  ADR-011: Drawdown eligibility filters, Waterfall/Proportional strategies,
           surplus handling, life-event account routing.
  ADR-013: Two-layer tax model — source-country tax per account,
           residence-level adjustment above personal allowance.
"""
from datetime import date
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse
from src.api.templates import templates
import pyoxigraph as og

from src.config import settings
from src.store.graph import store, MRL, DATA_GRAPH

router = APIRouter()

RDF_TYPE  = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
MRL_EXT   = "https://myretirementlife.app/ontology/ext#"
ONTOLOGY_GRAPH = og.NamedNode("https://myretirementlife.app/ontology/graph")

FREQUENCY_MULTIPLIERS = {
    "FrequencyType_Weekly":       52,
    "FrequencyType_Fortnightly":  26,
    "FrequencyType_TwiceMonthly": 24,
    "FrequencyType_Monthly":      12,
    "FrequencyType_Quarterly":     4,
    "FrequencyType_Annually":      1,
}


# ---------------------------------------------------------------------------
# Low-level data helpers (unchanged from v0.2)
# ---------------------------------------------------------------------------

def _quads(subject_iri, prop: str):
    return list(store.store.quads_for_pattern(
        subject_iri, og.NamedNode(f"{MRL}{prop}"), None, DATA_GRAPH))

def _val(subject_iri, prop: str, default: str = "") -> str:
    qs = _quads(subject_iri, prop)
    return str(qs[0].object.value) if qs else default

def _local(subject_iri, prop: str) -> str:
    v = _val(subject_iri, prop)
    return v.split("#")[-1] if "#" in v else v

def _float(subject_iri, prop: str, default: float = 0.0) -> float:
    try:
        return float(_val(subject_iri, prop, str(default)))
    except ValueError:
        return default

def _int(subject_iri, prop: str, default: int = 0) -> int:
    try:
        return int(_val(subject_iri, prop, str(default)))
    except ValueError:
        return default

def _iri_local(full_iri: str) -> str:
    """Extract the local name from a full IRI string."""
    if "#" in full_iri:
        return full_iri.split("#")[-1]
    if "/" in full_iri:
        return full_iri.split("/")[-1]
    return full_iri


# ---------------------------------------------------------------------------
# Profile and cost-of-living (unchanged from v0.2)
# ---------------------------------------------------------------------------

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
    except ValueError:
        return None
    return {
        "birth_year":      dob.year,
        "retirement_age":  _int(person, "targetRetirementAge", 67),
        "life_expectancy": _int(person, "lifeExpectancy", 85),
    }


def _col_index(jurisdiction_iri: og.NamedNode) -> float:
    qs = list(store.store.quads_for_pattern(
        jurisdiction_iri, og.NamedNode(f"{MRL}costOfLivingIndex"), None, ONTOLOGY_GRAPH))
    try:
        return float(qs[0].object.value) if qs else 1.0
    except (ValueError, IndexError):
        return 1.0


def load_col_ratio() -> float:
    person = og.NamedNode(f"{MRL}Person_1")
    resides_qs = list(store.store.quads_for_pattern(
        person, og.NamedNode(f"{MRL}residesIn"), None, DATA_GRAPH))
    retire_qs  = list(store.store.quads_for_pattern(
        person, og.NamedNode(f"{MRL}plansToRetireIn"), None, DATA_GRAPH))
    if not resides_qs or not retire_qs:
        return 1.0
    current_iri = resides_qs[0].object
    retire_iri  = retire_qs[0].object
    if str(current_iri.value) == str(retire_iri.value):
        return 1.0
    current_col = _col_index(current_iri)
    retire_col  = _col_index(retire_iri)
    return round(retire_col / current_col, 6) if current_col != 0 else 1.0


# ---------------------------------------------------------------------------
# Income sources (unchanged from v0.2)
# ---------------------------------------------------------------------------

def load_all_income_sources() -> list:
    """Load income sources, pre-converting amounts to the base currency.

    Each source carries mrl:incomeCurrency + (when not base) mrl:incomeExchangeRateToBase.
    Converting once at load time lets the downstream engine treat every amount
    as base-currency, mirroring how account balances are pre-multiplied by
    exchangeRateToBase in load_all_accounts().
    """
    type_node = og.NamedNode(f"{MRL}IncomeSource")
    quads = store.store.quads_for_pattern(None, og.NamedNode(RDF_TYPE), type_node, DATA_GRAPH)
    sources = []
    for q in quads:
        iri = q.subject
        start_raw = _val(iri, "incomeStartYear", "")
        end_raw   = _val(iri, "incomeEndYear",   "")
        try:
            start_year = int(start_raw) if start_raw else None
        except ValueError:
            start_year = None
        try:
            end_year = int(end_raw) if end_raw else None
        except ValueError:
            end_year = None
        raw_amount = _float(iri, "incomeAnnualAmount")
        fx_rate    = _float(iri, "incomeExchangeRateToBase", 1.0)
        sources.append({
            "name":        _val(iri, "incomeSourceName", "Income"),
            "amount":      raw_amount * fx_rate,
            "growth_rate": _float(iri, "incomeGrowthRate"),
            "start_year":  start_year,
            "end_year":    end_year,
        })
    return sources


# ---------------------------------------------------------------------------
# Accounts — unified loader (ADR-011, ADR-012, ADR-013)
#
# Replaces the separate load_accounts() + load_investment_accounts() functions.
# Loads CashAccount and InvestmentAccount instances in one pass, enriched with:
#   - drawdown eligibility and ordering properties (ADR-011)
#   - tax treatment properties (ADR-013)
# Sorted by drawdown_priority (lower = drawn first).
# ---------------------------------------------------------------------------

def load_all_accounts() -> list:
    """Return all CashAccount and InvestmentAccount instances with full metadata."""
    all_accounts = []

    for account_class in ("CashAccount", "InvestmentAccount"):
        type_node = og.NamedNode(f"{MRL}{account_class}")
        quads = store.store.quads_for_pattern(
            None, og.NamedNode(RDF_TYPE), type_node, DATA_GRAPH)

        for q in quads:
            iri     = q.subject
            iri_str = str(iri.value)
            label   = _iri_local(iri_str)

            balance_date_str = _val(iri, "balanceDate", date.today().isoformat())
            try:
                balance_date = date.fromisoformat(balance_date_str)
            except ValueError:
                balance_date = date.today()

            raw_balance = _float(iri, "accountBalance")
            fx_rate     = _float(iri, "exchangeRateToBase", 1.0)
            base_balance = raw_balance * fx_rate

            # --- Drawdown priority and ratio (ADR-011) ---
            priority_raw = _val(iri, "drawdownPriority", "")
            try:
                drawdown_priority = int(priority_raw) if priority_raw else 999
            except ValueError:
                drawdown_priority = 999

            ratio_raw = _val(iri, "drawdownRatio", "")
            try:
                drawdown_ratio = float(ratio_raw) if ratio_raw else 1.0
            except ValueError:
                drawdown_ratio = 1.0

            # --- Drawdown eligibility (ADR-011) ---
            def _opt_float(prop: str) -> float | None:
                v = _val(iri, prop, "")
                if not v:
                    return None
                try:
                    return float(v)
                except ValueError:
                    return None

            def _opt_year(prop: str) -> int | None:
                """Read a drawdown date property and return the year, or None."""
                v = _val(iri, prop, "")
                if not v:
                    return None
                try:
                    return date.fromisoformat(v).year
                except ValueError:
                    try:
                        return int(v)
                    except ValueError:
                        return None

            # --- Tax treatment (ADR-013) ---
            tax_treat_raw = _val(iri, "taxTreatment", "")
            tax_treatment = _iri_local(tax_treat_raw) if tax_treat_raw else ""

            eff_rate_raw = _val(iri, "effectiveWithdrawalTaxRate", "")
            try:
                effective_tax_rate = float(eff_rate_raw) if eff_rate_raw else 0.0
            except ValueError:
                effective_tax_rate = 0.0

            tax_free_raw = _val(iri, "annualTaxFreeWithdrawal", "")
            try:
                annual_tax_free = float(tax_free_raw) if tax_free_raw else 0.0
            except ValueError:
                annual_tax_free = 0.0

            acc = {
                "iri":           iri_str,
                "label":         label,
                "name":          _val(iri, "accountName", label),
                "account_class": account_class,
                "account_type_local": _local(iri, "accountType"),
                "balance":       base_balance,
                "balance_date":  balance_date,
                # Rate fields — zero for inapplicable class
                "interest_rate":    _float(iri, "annualInterestRate") if account_class == "CashAccount" else 0.0,
                "growth_rate":      _float(iri, "annualGrowthRate")   if account_class == "InvestmentAccount" else 0.0,
                "dividend_rate":    _float(iri, "annualDividendRate")  if account_class == "InvestmentAccount" else 0.0,
                "reinvest_dividends": True,
                # Drawdown (ADR-011)
                "drawdown_priority":    drawdown_priority,
                "drawdown_ratio":       drawdown_ratio,
                "drawdown_min_age":     _opt_float("drawdownMinAge"),
                "drawdown_max_age":     _opt_float("drawdownMaxAge"),
                "drawdown_earliest_year": _opt_year("drawdownEarliestDate"),
                "drawdown_latest_year":   _opt_year("drawdownLatestDate"),
                # Tax (ADR-013)
                "tax_treatment":               tax_treatment,
                "effective_withdrawal_tax_rate": effective_tax_rate,
                "annual_tax_free_withdrawal":   annual_tax_free,
            }

            if account_class == "InvestmentAccount":
                reinvest_raw = _val(iri, "reinvestDividends", "true")
                acc["reinvest_dividends"] = reinvest_raw.lower() not in ("false", "0")

            all_accounts.append(acc)

    # Lower priority number = drawn first
    all_accounts.sort(key=lambda a: a["drawdown_priority"])
    return all_accounts


# ---------------------------------------------------------------------------
# Backward-compatibility shims
#
# app.py (dashboard) imports load_accounts() and load_investment_accounts()
# by name. These thin wrappers preserve that interface without duplicating logic.
# ---------------------------------------------------------------------------

def load_accounts() -> list:
    """Backward-compat shim: returns only CashAccount instances.

    The returned dicts have the same keys as the old function (balance,
    raw_balance, fx_rate, interest_rate, balance_date) plus the new ADR-011/013
    fields, so any existing dashboard code that reads the old keys still works.
    """
    return [a for a in load_all_accounts() if a["account_class"] == "CashAccount"]


def load_investment_accounts() -> list:
    """Backward-compat shim: returns only InvestmentAccount instances.

    Preserves the old keys (balance, balance_date, growth_rate, dividend_rate,
    reinvest_dividends) alongside the new ADR-011/013 fields.
    """
    return [a for a in load_all_accounts() if a["account_class"] == "InvestmentAccount"]


# ---------------------------------------------------------------------------
# Budget lines (unchanged from v0.2)
# ---------------------------------------------------------------------------

def load_budget_lines() -> list:
    type_node = og.NamedNode(f"{MRL}BudgetLine")
    quads = store.store.quads_for_pattern(None, og.NamedNode(RDF_TYPE), type_node, DATA_GRAPH)
    lines = []
    for q in quads:
        iri = q.subject
        freq       = _local(iri, "budgetLineFrequency")
        multiplier = FREQUENCY_MULTIPLIERS.get(freq, 12)
        amount     = _float(iri, "budgetLineAmount")
        line_type  = _local(iri, "budgetLineType")

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
            "change_rate":   _float(iri, "annualChangeRate"),
            "line_type":     line_type,
            "loan_end_year": loan_end,
            "start_year":    start_year,
            "end_year":      end_year,
        })
    return lines


# ---------------------------------------------------------------------------
# Life events — extended with account routing (ADR-011)
# ---------------------------------------------------------------------------

def load_life_events() -> list:
    """Load life events. Each event now carries optional funded_by / received_by
    account labels for direct account routing (ADR-011 §5).
    """
    type_node = og.NamedNode(f"{MRL}LifeEvent")
    quads = store.store.quads_for_pattern(None, og.NamedNode(RDF_TYPE), type_node, DATA_GRAPH)
    events = []
    for q in quads:
        iri = q.subject
        try:
            year = int(_val(iri, "lifeEventYear", "0"))
        except ValueError:
            year = 0

        funded_qs   = list(store.store.quads_for_pattern(
            iri, og.NamedNode(f"{MRL}fundedByAccount"),   None, DATA_GRAPH))
        received_qs = list(store.store.quads_for_pattern(
            iri, og.NamedNode(f"{MRL}receivedByAccount"), None, DATA_GRAPH))

        funded_by   = _iri_local(str(funded_qs[0].object.value))   if funded_qs   else None
        received_by = _iri_local(str(received_qs[0].object.value)) if received_qs else None

        events.append({
            "year":                year,
            "amount":              _float(iri, "lifeEventAmount"),
            "funded_by_account":   funded_by,   # e.g. "CashAccount_2", or None
            "received_by_account": received_by,
        })
    return events


# ---------------------------------------------------------------------------
# Account contributions (ADR-015)
# ---------------------------------------------------------------------------

def load_all_contributions() -> dict:
    """Return all AccountContribution instances keyed by account label.

    Each value is a dict with:
        annual_amount — contribution amount × frequency multiplier
        start_year    — int or None (defaults to current_year in engine)
        end_year      — int or None (defaults to retirement_year in engine)

    Only accounts that have a contribution are included.
    """
    type_node = og.NamedNode(f"{MRL}AccountContribution")
    quads     = store.store.quads_for_pattern(None, og.NamedNode(RDF_TYPE), type_node, DATA_GRAPH)
    contributions: dict = {}

    for q in quads:
        c_iri = q.subject

        # Find the account this contribution belongs to
        owner_qs = list(store.store.quads_for_pattern(
            c_iri, og.NamedNode(f"{MRL}contributionOwner"), None, DATA_GRAPH))
        if not owner_qs:
            continue
        account_label = _iri_local(str(owner_qs[0].object.value))

        freq       = _local(c_iri, "contributionFrequency")
        multiplier = FREQUENCY_MULTIPLIERS.get(freq, 12)
        amount     = _float(c_iri, "contributionAmount")

        start_raw = _val(c_iri, "contributionStartYear", "")
        end_raw   = _val(c_iri, "contributionEndYear",   "")
        try:
            start_year = int(start_raw) if start_raw else None
        except ValueError:
            start_year = None
        try:
            end_year = int(end_raw) if end_raw else None
        except ValueError:
            end_year = None

        contributions[account_label] = {
            "annual_amount": amount * multiplier,
            "start_year":    start_year,
            "end_year":      end_year,
            "growth_rate":   _float(c_iri, "contributionGrowthRate"),   # ADR-015 v1.1
        }

    return contributions


# ---------------------------------------------------------------------------
# Projection settings — extended (ADR-011, ADR-013)
# ---------------------------------------------------------------------------

def get_projection_settings() -> dict:
    """Load all projection settings including drawdown and tax configuration."""
    ps = og.NamedNode(f"{MRL}ProjectionSettings_1")
    type_check = list(store.store.quads_for_pattern(
        ps, og.NamedNode(RDF_TYPE), None, DATA_GRAPH))

    defaults = {
        "inflation_rate":             2.5,
        "mc_profile":                 "MonteCarloProfile_Moderate",
        "drawdown_strategy":          "DrawdownStrategy_Proportional",
        "surplus_strategy":           "SurplusStrategy_ReduceDrawdown",
        "spending_account_label":     None,
        "surplus_account_label":      None,
        "annual_personal_allowance":  0.0,
        "residence_income_tax_rate":  0.0,
    }

    if not type_check:
        return defaults

    def _ps_local(prop: str) -> str | None:
        qs = list(store.store.quads_for_pattern(
            ps, og.NamedNode(f"{MRL}{prop}"), None, DATA_GRAPH))
        if not qs:
            return None
        return _iri_local(str(qs[0].object.value))

    return {
        "inflation_rate":             _float(ps, "inflationRate", 2.5),
        "mc_profile":                 _ps_local("monteCarloProfile")   or "MonteCarloProfile_Moderate",
        "drawdown_strategy":          _ps_local("drawdownStrategy")    or "DrawdownStrategy_Proportional",
        "surplus_strategy":           _ps_local("surplusStrategy")     or "SurplusStrategy_ReduceDrawdown",
        "spending_account_label":     _ps_local("spendingAccount"),
        "surplus_account_label":      _ps_local("surplusAccount"),
        "annual_personal_allowance":  _float(ps, "annualPersonalAllowance",  0.0),
        "residence_income_tax_rate":  _float(ps, "residenceIncomeTaxRate",   0.0),
    }


def save_projection_settings(
    inflation_rate: float,
    mc_profile: str                  = "MonteCarloProfile_Moderate",
    drawdown_strategy: str           = "DrawdownStrategy_Proportional",
    surplus_strategy: str            = "SurplusStrategy_ReduceDrawdown",
    spending_account_label: str | None = None,
    surplus_account_label: str  | None = None,
    annual_personal_allowance: float = 0.0,
    residence_income_tax_rate: float = 0.0,
) -> None:
    ps_iri     = f"{MRL}ProjectionSettings_1"
    person_iri = f"{MRL}Person_1"

    store.update(f"""
        DELETE WHERE {{
            GRAPH <{DATA_GRAPH.value}> {{
                <{ps_iri}> ?p ?o .
            }}
        }}
    """)

    # Build the triple block — object properties use mrlx: individuals
    triples = f"""
        <{ps_iri}> a mrl:ProjectionSettings ;
            mrl:inflationRate             "{inflation_rate}"^^xsd:decimal ;
            mrl:monteCarloProfile         mrlx:{mc_profile} ;
            mrl:drawdownStrategy          mrlx:{drawdown_strategy} ;
            mrl:surplusStrategy           mrlx:{surplus_strategy} ;
            mrl:annualPersonalAllowance   "{annual_personal_allowance}"^^xsd:decimal ;
            mrl:residenceIncomeTaxRate    "{residence_income_tax_rate}"^^xsd:decimal ;
            mrl:projectionOwner           <{person_iri}> .
    """

    if spending_account_label:
        triples += f'\n        <{ps_iri}> mrl:spendingAccount mrl:{spending_account_label} .'
    if surplus_account_label:
        triples += f'\n        <{ps_iri}> mrl:surplusAccount  mrl:{surplus_account_label} .'

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
# Drawdown helpers (ADR-011)
# ---------------------------------------------------------------------------

def _is_eligible(account: dict, year: int, birth_year: int) -> bool:
    """Return True if this account is eligible for drawdown in the given year.

    Checks all four eligibility constraints from ADR-011 §1:
      drawdownMinAge, drawdownMaxAge, drawdownEarliestDate, drawdownLatestDate.
    Absent constraints are not restrictive.
    drawdownEarliestDate takes precedence over drawdownMinAge when set.
    """
    person_age = year - birth_year

    if account["drawdown_min_age"] is not None and person_age < account["drawdown_min_age"]:
        return False
    if account["drawdown_max_age"] is not None and person_age > account["drawdown_max_age"]:
        return False
    if account["drawdown_earliest_year"] is not None and year < account["drawdown_earliest_year"]:
        return False
    if account["drawdown_latest_year"] is not None and year > account["drawdown_latest_year"]:
        return False
    return True


def _apply_drawdown(
    eligible: list[dict],
    shortfall: float,
    strategy: str,
    balances: dict[str, float],
) -> dict[str, float]:
    """Compute gross withdrawal amounts per eligible account to meet the shortfall.

    Waterfall: drains the lowest-priority-numbered account first, then the next.
    Proportional: draws from each account in proportion to its drawdown_ratio,
                  with overflow distributed waterfall-style if any account is
                  exhausted before covering its share.

    Returns {account_label: gross_withdrawal_amount}.
    Only draws from accounts with a positive balance.
    """
    if shortfall <= 0:
        return {}

    drawable = [a for a in eligible if balances.get(a["label"], 0) > 0]
    if not drawable:
        return {}

    withdrawals: dict[str, float] = {}

    if strategy == "DrawdownStrategy_Waterfall":
        remaining = shortfall
        for acc in sorted(drawable, key=lambda a: a["drawdown_priority"]):
            if remaining <= 0:
                break
            draw = min(balances[acc["label"]], remaining)
            if draw > 0:
                withdrawals[acc["label"]] = draw
                remaining -= draw

    else:  # DrawdownStrategy_Proportional (default)
        total_ratio = sum(a["drawdown_ratio"] for a in drawable if a["drawdown_ratio"] > 0)
        if total_ratio <= 0:
            total_ratio = float(len(drawable))
            for a in drawable:
                a["drawdown_ratio"] = 1.0

        # First pass: proportional allocation, capped at each account's available balance
        overflow = 0.0
        for acc in drawable:
            share = (acc["drawdown_ratio"] / total_ratio) * shortfall
            draw  = min(balances[acc["label"]], share)
            withdrawals[acc["label"]] = draw
            overflow += share - draw  # deficit if this account couldn't cover its share

        # Second pass: redistribute any overflow waterfall-style among accounts with headroom
        if overflow > 0.01:
            for acc in sorted(drawable, key=lambda a: a["drawdown_priority"]):
                if overflow <= 0.01:
                    break
                headroom = balances[acc["label"]] - withdrawals.get(acc["label"], 0)
                extra = min(headroom, overflow)
                if extra > 0:
                    withdrawals[acc["label"]] = withdrawals.get(acc["label"], 0) + extra
                    overflow -= extra

    return withdrawals


# ---------------------------------------------------------------------------
# Tax helpers (ADR-013)
# ---------------------------------------------------------------------------

def _compute_source_tax(
    account: dict,
    gross_withdrawal: float,
    tax_free_used_so_far: float,
) -> tuple[float, float]:
    """Compute source-country withholding tax on a single account withdrawal.

    Returns (tax_free_used_this_draw, source_tax).
    tax_free_used_this_draw should be added to the running per-year counter.

    Per ADR-013 §3:
      tax_free_used     = min(annualTaxFreeWithdrawal - used_so_far, gross_withdrawal)
      taxable_at_source = gross_withdrawal - tax_free_used
      source_tax        = taxable_at_source × effectiveWithdrawalTaxRate
    """
    annual_limit   = account["annual_tax_free_withdrawal"]
    remaining_free = max(0.0, annual_limit - tax_free_used_so_far)
    free_this_draw = min(remaining_free, gross_withdrawal)
    taxable        = max(0.0, gross_withdrawal - free_this_draw)
    source_tax     = taxable * account["effective_withdrawal_tax_rate"]
    return free_this_draw, source_tax


def _compute_residence_tax(
    total_taxable: float,
    total_source_tax: float,
    personal_allowance: float,
    residence_rate: float,
) -> float:
    """Compute residence-level tax above the personal allowance, net of source tax.

    Per ADR-013 §3 (residence-level adjustment):
      income_above_allowance = total_taxable - personal_allowance
      residence_tax = max(0, income_above_allowance × rate - total_source_tax)
    """
    if total_taxable <= personal_allowance or residence_rate <= 0:
        return 0.0
    income_above = total_taxable - personal_allowance
    return max(0.0, income_above * residence_rate - total_source_tax)


# ---------------------------------------------------------------------------
# Projection engine (ADR-011, ADR-012, ADR-013)
# ---------------------------------------------------------------------------

def run_projection(
    inflation_rate: float = 2.5,
    proj_settings: dict | None = None,
) -> dict | None:
    """Per-account burndown projection.

    Tracks each account's balance independently each year. Applies drawdown
    eligibility rules, the chosen drawdown strategy (Waterfall/Proportional),
    surplus handling, and the two-layer tax model.

    Return value is backward-compatible with projection.html plus new keys:
      account_balances  — {label: [closing_balance_y0, y1, ...]}
      account_names     — {label: human-readable name}
      account_classes   — {label: "CashAccount" | "InvestmentAccount"}
      total_tax_paid    — cumulative tax paid over the full projection
    Each year dict includes "tax_paid" (new) alongside existing keys.
    """
    profile = load_profile()
    if not profile:
        return None

    if proj_settings is None:
        proj_settings = get_projection_settings()

    today        = date.today()
    current_year = today.year
    birth_year   = profile["birth_year"]
    retirement_year = birth_year + profile["retirement_age"]
    end_year        = birth_year + profile["life_expectancy"]

    income_sources = load_all_income_sources()
    all_accounts   = load_all_accounts()
    budget_lines   = load_budget_lines()
    life_events    = load_life_events()
    contributions  = load_all_contributions()   # ADR-015
    col_ratio      = load_col_ratio()

    if not all_accounts:
        return None

    drawdown_strategy = proj_settings.get("drawdown_strategy", "DrawdownStrategy_Proportional")
    surplus_strategy  = proj_settings.get("surplus_strategy",  "SurplusStrategy_ReduceDrawdown")
    spending_acc      = proj_settings.get("spending_account_label")
    surplus_acc       = proj_settings.get("surplus_account_label")
    personal_allowance = proj_settings.get("annual_personal_allowance", 0.0)
    residence_rate     = proj_settings.get("residence_income_tax_rate",  0.0)

    # --- Opening balances grown from balance_date to current_year ---
    balances: dict[str, float] = {}
    for acc in all_accounts:
        ye = max(0, current_year - acc["balance_date"].year)
        if acc["account_class"] == "CashAccount":
            rate = acc["interest_rate"] / 100
        else:
            eff  = acc["growth_rate"] + (acc["dividend_rate"] if acc["reinvest_dividends"] else 0)
            rate = eff / 100
        balances[acc["label"]] = acc["balance"] * ((1 + rate) ** ye)

    # --- Non-reinvested dividend income sources ---
    div_sources = []
    for acc in all_accounts:
        if acc["account_class"] == "InvestmentAccount" \
                and not acc["reinvest_dividends"] \
                and acc["dividend_rate"] > 0:
            ye = max(0, current_year - acc["balance_date"].year)
            div_sources.append({
                "opening_value": acc["balance"] * ((1 + acc["growth_rate"] / 100) ** ye),
                "growth_rate":   acc["growth_rate"],
                "dividend_rate": acc["dividend_rate"],
            })

    # --- Weighted rate display figure ---
    total_opening = sum(balances.values())
    if total_opening > 0:
        rate_num = sum(
            balances[acc["label"]] * (
                acc["interest_rate"] if acc["account_class"] == "CashAccount"
                else acc["growth_rate"] + (acc["dividend_rate"] if acc["reinvest_dividends"] else 0)
            )
            for acc in all_accounts
        )
        weighted_rate_pct = rate_num / total_opening
    else:
        weighted_rate_pct = 0.0

    inv_opening = sum(
        balances[acc["label"]] for acc in all_accounts
        if acc["account_class"] == "InvestmentAccount"
    )

    # --- Year-by-year loop ---
    # Per-account balance, withdrawal, return and contribution history
    account_history: dict[str, list[float]]             = {acc["label"]: [] for acc in all_accounts}
    account_withdrawal_history: dict[str, list[float]]  = {acc["label"]: [] for acc in all_accounts}
    account_return_history: dict[str, list[float]]      = {acc["label"]: [] for acc in all_accounts}
    account_contribution_history: dict[str, list[float]] = {acc["label"]: [] for acc in all_accounts}  # ADR-015
    projection_years    = []
    cumulative_tax      = 0.0
    cumulative_contributions = 0.0   # ADR-015

    for year in range(current_year, end_year + 1):
        years_from_start = year - current_year

        # 1. Capture opening balances before growth (for returns calculation)
        opening_this_year = dict(balances)

        # 2. Apply growth to each account (CashAccount: interest; InvestmentAccount: capital + optional reinvested dividend)
        for acc in all_accounts:
            if balances[acc["label"]] <= 0:
                continue
            if acc["account_class"] == "CashAccount":
                balances[acc["label"]] *= (1 + acc["interest_rate"] / 100)
            else:
                eff = acc["growth_rate"] + (acc["dividend_rate"] if acc["reinvest_dividends"] else 0)
                balances[acc["label"]] *= (1 + eff / 100)

        # Returns earned this year — total for display, and per-account for detail chart
        returns_this_year = sum(
            balances[acc["label"]] - opening_this_year[acc["label"]]
            for acc in all_accounts
        )
        for acc in all_accounts:
            account_return_history[acc["label"]].append(
                round(balances[acc["label"]] - opening_this_year[acc["label"]], 0)
            )

        # 2b. Apply contributions (ADR-015)
        # Credits each account's balance; the matching cashflow cost is deducted
        # from pre_net below so that drawdown covers any funding shortfall.
        # Default active window: current_year … retirement_year (inclusive).
        year_contribution_spending = 0.0
        for acc in all_accounts:
            contrib = contributions.get(acc["label"])
            contrib_this_year = 0.0
            if contrib:
                c_start = contrib["start_year"] if contrib["start_year"] else current_year
                c_end   = contrib["end_year"]   if contrib["end_year"]   else retirement_year
                if c_start <= year <= c_end:
                    base   = contrib["annual_amount"]
                    g_rate = contrib.get("growth_rate", 0.0)
                    years_active = year - c_start   # 0 in first active year
                    contrib_this_year = (
                        base * ((1 + g_rate / 100) ** years_active)
                        if g_rate != 0.0 else base
                    )
                    balances[acc["label"]] += contrib_this_year
                    year_contribution_spending += contrib_this_year
            account_contribution_history[acc["label"]].append(round(contrib_this_year, 0))
        cumulative_contributions += year_contribution_spending

        # 3. Income: active income sources + non-reinvested dividends
        income_amount = 0.0
        for src in income_sources:
            src_start = src["start_year"] or current_year
            src_end   = src["end_year"]
            if year >= src_start and (src_end is None or year <= src_end):
                income_amount += src["amount"] * ((1 + src["growth_rate"] / 100) ** years_from_start)
        for ds in div_sources:
            pv = ds["opening_value"] * ((1 + ds["growth_rate"] / 100) ** years_from_start)
            income_amount += pv * (ds["dividend_rate"] / 100)

        # 4. Spending
        mandatory = discretionary = loans = 0.0
        for line in budget_lines:
            if line["start_year"]    and year < line["start_year"]:
                continue
            if line["end_year"]      and year > line["end_year"]:
                continue
            if line["loan_end_year"] and year > line["loan_end_year"]:
                continue
            if line["line_type"] == "BudgetLineType_Loan":
                rate = line["change_rate"]
            else:
                rate = inflation_rate + line["change_rate"]
            annual = line["annual_amount"] * ((1 + rate / 100) ** years_from_start)
            if   line["line_type"] == "BudgetLineType_Mandatory":     mandatory     += annual
            elif line["line_type"] == "BudgetLineType_Discretionary": discretionary += annual
            elif line["line_type"] == "BudgetLineType_Loan":          loans         += annual

        if col_ratio != 1.0 and year >= retirement_year:
            mandatory     *= col_ratio
            discretionary *= col_ratio
            loans         *= col_ratio

        # 5. Life events — route to specific accounts where designated (ADR-011 §5)
        life_event_costs    = 0.0
        life_event_receipts = 0.0
        general_costs       = 0.0
        general_receipts    = 0.0

        for evt in life_events:
            if evt["year"] != year:
                continue
            amt = evt["amount"]
            if amt >= 0:  # expenditure
                life_event_costs += amt
                if evt["funded_by_account"] and evt["funded_by_account"] in balances:
                    balances[evt["funded_by_account"]] = \
                        max(0.0, balances[evt["funded_by_account"]] - amt)
                else:
                    general_costs += amt
            else:  # receipt / windfall
                life_event_receipts += abs(amt)
                if evt["received_by_account"] and evt["received_by_account"] in balances:
                    balances[evt["received_by_account"]] += abs(amt)
                else:
                    general_receipts += abs(amt)

        # 6. Net cashflow before drawdown
        # Contributions are funded from cashflow (same as mandatory spending).
        total_spending = mandatory + discretionary + loans + general_costs
        pre_net        = income_amount + general_receipts - total_spending - year_contribution_spending

        # 7. Drawdown or surplus
        tax_free_used: dict[str, float] = {acc["label"]: 0.0 for acc in all_accounts}
        total_source_tax       = 0.0
        total_taxable_at_source = 0.0
        net_annual_tax          = 0.0
        year_withdrawals: dict[str, float] = {}   # gross withdrawal per account this year

        if pre_net < 0:
            # Shortfall — draw from eligible accounts
            shortfall = -pre_net
            eligible  = [
                acc for acc in all_accounts
                if _is_eligible(acc, year, birth_year) and balances.get(acc["label"], 0) > 0
            ]
            withdrawals = _apply_drawdown(eligible, shortfall, drawdown_strategy, balances)

            for acc_label, gross_draw in withdrawals.items():
                acc = next(a for a in all_accounts if a["label"] == acc_label)
                free_used, src_tax = _compute_source_tax(
                    acc, gross_draw, tax_free_used[acc_label])
                tax_free_used[acc_label]  += free_used
                total_source_tax           += src_tax
                total_taxable_at_source    += (gross_draw - free_used)
                # Debit account: gross withdrawal + source tax withheld
                balances[acc_label] = max(0.0, balances[acc_label] - gross_draw - src_tax)
                year_withdrawals[acc_label] = gross_draw   # record for history

            # Residence-level tax (ADR-013 §3)
            res_tax = _compute_residence_tax(
                total_taxable_at_source, total_source_tax,
                personal_allowance, residence_rate)

            if res_tax > 0:
                # Apply residence tax to the spending account, or spread proportionally
                if spending_acc and spending_acc in balances:
                    balances[spending_acc] = max(0.0, balances[spending_acc] - res_tax)
                elif eligible:
                    total_el_bal = sum(balances.get(a["label"], 0) for a in eligible)
                    if total_el_bal > 0:
                        for a in eligible:
                            share = (balances.get(a["label"], 0) / total_el_bal) * res_tax
                            balances[a["label"]] = max(0.0, balances[a["label"]] - share)

            net_annual_tax = total_source_tax + res_tax

        else:
            # Surplus — income exceeded spending + contributions this year.
            # Always credit to the spending account (or first cash account as fallback)
            # so that unspent income accumulates correctly rather than disappearing.
            surplus = pre_net
            if surplus_strategy == "SurplusStrategy_SweepToAccount":
                target = surplus_acc or spending_acc
            else:
                # ReduceDrawdown: no drawdown was needed; surplus stays in the
                # income/spending account rather than being redistributed elsewhere.
                target = spending_acc

            if target and target in balances:
                balances[target] += surplus
            else:
                # No spending account configured.
                # Priority: Current account → any cash account → any account.
                # This avoids silently routing surplus into an ISA or investment account
                # just because it was the first one created.
                first_current = next(
                    (a["label"] for a in all_accounts
                     if a["account_class"] == "CashAccount"
                     and a.get("account_type_local") == "CashAccountType_Current"),
                    None
                )
                first_cash = next(
                    (a["label"] for a in all_accounts
                     if a["account_class"] == "CashAccount"),
                    None
                )
                fallback = (
                    first_current
                    or first_cash
                    or (all_accounts[0]["label"] if all_accounts else None)
                )
                if fallback:
                    balances[fallback] += surplus

        cumulative_tax += net_annual_tax

        # 8. Record closing balances and withdrawal amounts per account
        for acc in all_accounts:
            account_history[acc["label"]].append(round(balances[acc["label"]], 0))
            account_withdrawal_history[acc["label"]].append(
                round(year_withdrawals.get(acc["label"], 0.0), 0)
            )

        total_balance = sum(balances.values())

        projection_years.append({
            "year":                year,
            "balance":             round(total_balance, 0),
            "income":              round(income_amount, 0),
            "mandatory":           round(mandatory, 0),
            "discretionary":       round(discretionary, 0),
            "loans":               round(loans, 0),
            "life_event_costs":    round(life_event_costs, 0),
            "life_event_receipts": round(life_event_receipts, 0),
            "interest":            round(returns_this_year, 0),
            "tax_paid":            round(net_annual_tax, 0),
            "is_retirement_year":  year == retirement_year,
        })

    # --- Confidence scoring (unchanged logic) ---
    runs_out_year = next(
        (y["year"] for y in projection_years if y["balance"] <= 0), None)
    final_balance = projection_years[-1]["balance"] if projection_years else 0

    if runs_out_year is None:
        confidence       = "green"
        confidence_label = "On track"
        confidence_message = (
            f"Your savings last beyond your life expectancy "
            f"with £{final_balance:,.0f} remaining."
        )
    elif runs_out_year >= end_year - 5:
        confidence       = "amber"
        confidence_label = "Borderline"
        confidence_message = (
            f"Your savings run out in {runs_out_year}, "
            f"within 5 years of your life expectancy."
        )
    else:
        confidence       = "red"
        confidence_label = "At risk"
        confidence_message = (
            f"Your savings run out in {runs_out_year}, "
            f"{end_year - runs_out_year} years before your life expectancy."
        )

    return {
        # Existing keys (unchanged for backward compat)
        "years":                     projection_years,
        "runs_out_year":             runs_out_year,
        "retirement_year":           retirement_year,
        "end_year":                  end_year,
        "current_year":              current_year,
        "opening_balance":           round(total_opening, 0),
        "opening_investment_balance": round(inv_opening, 0),
        "final_balance":             round(final_balance, 0),
        "confidence":                confidence,
        "confidence_label":          confidence_label,
        "confidence_message":        confidence_message,
        "weighted_rate":             round(weighted_rate_pct, 2),
        "col_ratio":                 col_ratio,
        # ADR-012: per-account balance, withdrawal and return history
        "account_balances":    account_history,
        "account_withdrawals": account_withdrawal_history,
        "account_returns":     account_return_history,
        "account_contributions": account_contribution_history,    # ADR-015
        "account_names":       {acc["label"]: acc["name"]          for acc in all_accounts},
        "account_classes":     {acc["label"]: acc["account_class"] for acc in all_accounts},
        # ADR-013: tax summary
        "total_tax_paid":         round(cumulative_tax, 0),
        # ADR-015: contribution summary
        "total_contributions": round(cumulative_contributions, 0),
    }


# ---------------------------------------------------------------------------
# Monte Carlo engine — investment-only σ (ADR-012)
# ---------------------------------------------------------------------------

def _get_mc_params(profile_local: str) -> tuple[float, float]:
    profile_iri = og.NamedNode(f"{MRL_EXT}{profile_local}")
    qs_ret = list(store.store.quads_for_pattern(
        profile_iri, og.NamedNode(f"{MRL_EXT}returnVolatility"),    None, ONTOLOGY_GRAPH))
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
    inflation_rate: float    = 2.5,
    mc_profile_local: str    = "MonteCarloProfile_Moderate",
    n_sims: int              = 500,
) -> dict | None:
    """Monte Carlo simulation with investment-only volatility (ADR-012).

    Cash accounts grow deterministically at their weighted average rate.
    σ (return volatility) is applied only to the investment account pool.
    All annual income / spending cashflow passes through the investment pool
    in the simulation; cash simply compounds at its fixed rate.

    Total balance per simulation year:
        total[y] = cash_floor[y]  +  investment_sim[y]

    Where cash_floor is the same deterministic series across all simulations.

    Returns P10/P50/P90 for the aggregate total, plus:
      cash_floor — deterministic cash balance series for chart rendering.
    """
    import numpy as np

    profile = load_profile()
    if not profile:
        return None

    return_vol, inflation_vol = _get_mc_params(mc_profile_local)

    today        = date.today()
    current_year = today.year
    birth_year   = profile["birth_year"]
    retirement_year = birth_year + profile["retirement_age"]
    end_year        = birth_year + profile["life_expectancy"]

    all_accounts   = load_all_accounts()
    # No investments → nothing stochastic to model; suppress so the template
    # doesn't show a misleading cash-floor confidence band.
    if not any(a["account_class"] == "InvestmentAccount" for a in all_accounts):
        return None

    income_sources = load_all_income_sources()
    budget_lines   = load_budget_lines()
    life_events    = load_life_events()
    col_ratio      = load_col_ratio()

    year_range = list(range(current_year, end_year + 1))
    n_years    = len(year_range)

    # --- Split accounts by class ---
    cash_accounts   = [a for a in all_accounts if a["account_class"] == "CashAccount"]
    invest_accounts = [a for a in all_accounts if a["account_class"] == "InvestmentAccount"]

    def _opening(acc: dict) -> float:
        ye   = max(0, current_year - acc["balance_date"].year)
        rate = (
            acc["interest_rate"] / 100 if acc["account_class"] == "CashAccount"
            else (acc["growth_rate"] + (acc["dividend_rate"] if acc["reinvest_dividends"] else 0)) / 100
        )
        return acc["balance"] * ((1 + rate) ** ye)

    cash_opening   = sum(_opening(a) for a in cash_accounts)
    invest_opening = sum(_opening(a) for a in invest_accounts)

    # Weighted average rates for each pool
    cash_total = sum(a["balance"] for a in cash_accounts)
    cash_avg_rate = (
        sum(a["balance"] * a["interest_rate"] for a in cash_accounts) / cash_total / 100
        if cash_total > 0 else 0.0
    )

    invest_total = sum(a["balance"] for a in invest_accounts)
    inv_avg_rate = (
        sum(
            a["balance"] * (a["growth_rate"] + (a["dividend_rate"] if a["reinvest_dividends"] else 0))
            for a in invest_accounts
        ) / invest_total / 100
        if invest_total > 0 else 0.0
    )

    # Non-reinvested dividend income (deterministic)
    div_sources = []
    for acc in invest_accounts:
        if not acc["reinvest_dividends"] and acc["dividend_rate"] > 0:
            ye = max(0, current_year - acc["balance_date"].year)
            div_sources.append({
                "opening_value": acc["balance"] * ((1 + acc["growth_rate"] / 100) ** ye),
                "growth_rate":   acc["growth_rate"],
                "dividend_rate": acc["dividend_rate"],
            })

    # --- Pre-compute deterministic per-year values (income, budget, life events) ---
    income_per_year = []
    for yi, year in enumerate(year_range):
        total = 0.0
        for src in income_sources:
            src_start = src["start_year"] or current_year
            src_end   = src["end_year"]
            if year >= src_start and (src_end is None or year <= src_end):
                total += src["amount"] * ((1 + src["growth_rate"] / 100) ** yi)
        for ds in div_sources:
            pv = ds["opening_value"] * ((1 + ds["growth_rate"] / 100) ** yi)
            total += pv * (ds["dividend_rate"] / 100)
        income_per_year.append(total)

    # Budget: (base_annual, own_rate, line_type) tuples + post-retirement flag
    budget_per_year = []
    for yi, year in enumerate(year_range):
        active = []
        for line in budget_lines:
            if line["start_year"]    and year < line["start_year"]:  continue
            if line["end_year"]      and year > line["end_year"]:     continue
            if line["loan_end_year"] and year > line["loan_end_year"]: continue
            active.append((line["annual_amount"], line["change_rate"], line["line_type"]))
        budget_per_year.append((active, year >= retirement_year))

    life_costs = [
        sum(e["amount"]       for e in life_events if e["year"] == y and e["amount"] >= 0)
        for y in year_range
    ]
    life_receipts = [
        sum(abs(e["amount"])  for e in life_events if e["year"] == y and e["amount"] < 0)
        for y in year_range
    ]

    # --- Deterministic cash floor (no σ, no drawdown in this series) ---
    # Cash simply grows at its average rate. All cashflow uncertainty is modelled
    # in the investment pool; if investment is exhausted the simulation shows
    # a negative investment balance, which offsets against the positive cash floor
    # to give the correct aggregate.
    cash_floor = []
    cb = cash_opening
    for yi in range(n_years):
        cb = cb * (1 + cash_avg_rate) if cb > 0 else cb
        cash_floor.append(round(cb, 0))

    # --- Monte Carlo: simulate investment pool ---
    rng = np.random.default_rng()
    return_shocks   = rng.normal(0.0, return_vol / 100.0, (n_sims, n_years))
    inflation_shocks = rng.normal(0.0, inflation_vol,      (n_sims, n_years))

    all_balances = np.empty((n_sims, n_years), dtype=np.float64)

    for sim in range(n_sims):
        invest_bal = invest_opening

        for yi in range(n_years):
            sim_rate      = max(0.0, inv_avg_rate + return_shocks[sim, yi])
            sim_inflation = max(0.1, inflation_rate + inflation_shocks[sim, yi])

            # Apply investment growth (σ perturbed)
            if invest_bal > 0:
                invest_bal *= (1 + sim_rate)

            # Spending
            mandatory = discretionary = loans = 0.0
            active_lines, is_post_retirement = budget_per_year[yi]
            for base, own_rate, lt in active_lines:
                if lt == "BudgetLineType_Loan":
                    rate = own_rate
                else:
                    rate = sim_inflation + own_rate
                annual = base * ((1 + rate / 100) ** yi)
                if   lt == "BudgetLineType_Mandatory":     mandatory     += annual
                elif lt == "BudgetLineType_Discretionary": discretionary += annual
                elif lt == "BudgetLineType_Loan":          loans         += annual

            if col_ratio != 1.0 and is_post_retirement:
                mandatory     *= col_ratio
                discretionary *= col_ratio
                loans         *= col_ratio

            total_spending = mandatory + discretionary + loans + life_costs[yi]
            # All cashflow routes through the investment pool in the MC
            invest_bal += income_per_year[yi] + life_receipts[yi] - total_spending

            # Aggregate = deterministic cash floor + stochastic investment pool
            all_balances[sim, yi] = cash_floor[yi] + invest_bal

    p10 = np.percentile(all_balances, 10, axis=0).round(0).tolist()
    p50 = np.percentile(all_balances, 50, axis=0).round(0).tolist()
    p90 = np.percentile(all_balances, 90, axis=0).round(0).tolist()

    success_rate = round(
        float(np.mean(np.all(all_balances >= 0, axis=1))) * 100, 1)

    return {
        "years":        year_range,
        "p10":          p10,
        "p50":          p50,
        "p90":          p90,
        "success_rate": success_rate,
        "n_sims":       n_sims,
        "profile":      mc_profile_local,
        "cash_floor":   cash_floor,  # ADR-012: deterministic cash layer for chart
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/projection", response_class=HTMLResponse)
async def projection_page(request: Request):
    proj_settings = get_projection_settings()
    projection    = run_projection(proj_settings["inflation_rate"], proj_settings)
    mc            = run_monte_carlo(proj_settings["inflation_rate"], proj_settings["mc_profile"])
    all_accounts  = load_all_accounts()

    # Determine where surplus income accumulates — mirrors the engine fallback logic —
    # so the UI can tell the user clearly rather than leaving it implicit.
    spending_label = proj_settings.get("spending_account_label")
    if spending_label:
        surplus_dest_name = next(
            (a["name"] for a in all_accounts if a["label"] == spending_label),
            spending_label
        )
        surplus_dest_configured = True
    else:
        first_current = next(
            (a for a in all_accounts
             if a["account_class"] == "CashAccount"
             and a.get("account_type_local") == "CashAccountType_Current"),
            None
        )
        first_cash = next(
            (a for a in all_accounts if a["account_class"] == "CashAccount"),
            None
        )
        fallback = first_current or first_cash or (all_accounts[0] if all_accounts else None)
        surplus_dest_name = fallback["name"] if fallback else "not configured"
        surplus_dest_configured = False

    return templates.TemplateResponse(
        request=request,
        name="projection.html",
        context={
            "app_name":               settings.app_name,
            "active":                 "projection",
            "projection":             projection,
            "mc":                     mc,
            "mc_profile":             proj_settings["mc_profile"],
            "inflation_rate":         proj_settings["inflation_rate"],
            "proj_settings":          proj_settings,
            "all_accounts":           all_accounts,
            "surplus_dest_name":      surplus_dest_name,
            "surplus_dest_configured": surplus_dest_configured,
        }
    )


@router.post("/projection/settings", response_class=HTMLResponse)
async def save_settings(
    request: Request,
    inflation_rate:            float = Form(2.5),
    mc_profile:                str   = Form("MonteCarloProfile_Moderate"),
    drawdown_strategy:         str   = Form("DrawdownStrategy_Proportional"),
    surplus_strategy:          str   = Form("SurplusStrategy_ReduceDrawdown"),
    spending_account_label:    str   = Form(""),
    surplus_account_label:     str   = Form(""),
    annual_personal_allowance: float = Form(0.0),
    residence_income_tax_rate: float = Form(0.0),
):
    """Save all projection settings and redirect to the projection page."""
    from fastapi.responses import RedirectResponse
    save_projection_settings(
        inflation_rate            = inflation_rate,
        mc_profile                = mc_profile,
        drawdown_strategy         = drawdown_strategy,
        surplus_strategy          = surplus_strategy,
        spending_account_label    = spending_account_label or None,
        surplus_account_label     = surplus_account_label  or None,
        annual_personal_allowance = annual_personal_allowance,
        residence_income_tax_rate = residence_income_tax_rate / 100.0,  # form sends %
    )
    return RedirectResponse(url="/projection", status_code=303)


@router.post("/projection/mc-profile", response_class=HTMLResponse)
async def save_mc_profile(
    request: Request,
    mc_profile: str = Form("MonteCarloProfile_Moderate"),
):
    """Save the Monte Carlo profile only. Backward-compatible endpoint."""
    from fastapi.responses import RedirectResponse
    ps = get_projection_settings()
    save_projection_settings(
        inflation_rate            = ps["inflation_rate"],
        mc_profile                = mc_profile,
        drawdown_strategy         = ps["drawdown_strategy"],
        surplus_strategy          = ps["surplus_strategy"],
        spending_account_label    = ps["spending_account_label"],
        surplus_account_label     = ps["surplus_account_label"],
        annual_personal_allowance = ps["annual_personal_allowance"],
        residence_income_tax_rate = ps["residence_income_tax_rate"],
    )
    return RedirectResponse(url="/projection", status_code=303)