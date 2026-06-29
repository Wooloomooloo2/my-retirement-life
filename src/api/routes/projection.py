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

# ADR-013: Tax treatments whose withdrawals are wholly exempt from residence
# income tax (e.g. ISA, Roth IRA, premium bonds). Excluded from aggregate
# taxable income so they don't erroneously consume the personal allowance.
RESIDENCE_EXEMPT_TREATMENTS = frozenset({
    "TaxTreatment_PostTaxTaxFreeWithdrawal",
    "TaxTreatment_TaxFree",
})

# ADR-018 follow-on (item 61) — minimum annual shortfall, in base currency, that
# counts as genuinely "unfunded". `year_unfunded = shortfall - sum(drawdown)` is a
# difference of floats, so a fully-covered year can leave a sub-penny residual that
# is `> 0` in float arithmetic. Without a tolerance that residue sets
# first_unfunded_year and paints the whole projection red while total_unfunded still
# rounds to £0 — the contradictory "spending unfunded — £0 unfunded" false positive.
# £1/year is comfortably below anything material and kills the noise.
UNFUNDED_EPSILON = 1.0


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

    deposit_account is the local name (e.g. "CashAccount_2") of the account
    that should receive this income each year, or None to follow surplus
    routing (mrl:creditedToAccount, ADR-011-aligned).
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
        credited_qs = list(store.store.quads_for_pattern(
            iri, og.NamedNode(f"{MRL}creditedToAccount"), None, DATA_GRAPH))
        deposit_account = _iri_local(str(credited_qs[0].object.value)) if credited_qs else None

        # ADR-021: a rental source linked to a property derives its income from
        # the property's projected value × yield, not the static amount.
        rental_qs = list(store.store.quads_for_pattern(
            iri, og.NamedNode(f"{MRL}rentalProperty"), None, DATA_GRAPH))
        rental_property = _iri_local(str(rental_qs[0].object.value)) if rental_qs else None
        rental_yield    = _float(iri, "rentalYieldRate")

        sources.append({
            "name":            _val(iri, "incomeSourceName", "Income"),
            "amount":          raw_amount * fx_rate,
            "growth_rate":     _float(iri, "incomeGrowthRate"),
            "start_year":      start_year,
            "end_year":        end_year,
            "deposit_account": deposit_account,
            "rental_property": rental_property,
            "rental_yield":    rental_yield,
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
                "drawdown_max_age":     _opt_float("drawdownMaxAge"),  # deprecated (ADR-018) — kept for round-trip, no longer gates eligibility
                "drawdown_earliest_year": _opt_year("drawdownEarliestDate"),
                "drawdown_latest_year":   _opt_year("drawdownLatestDate"),
                # Mandatory (RMD-style) withdrawal — ADR-018
                "mandatory_withdrawal_age":  _opt_float("mandatoryWithdrawalAge"),
                "mandatory_withdrawal_rate": _opt_float("mandatoryWithdrawalRate"),
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
# Physical assets (Phase 3 — see CLAUDE_CONTEXT items 27-28)
#
# Tangible (non-financial) holdings that contribute to net worth but do NOT
# participate in retirement drawdown, don't earn interest/dividend, and have
# no contributions. They appreciate per year at assetAppreciationRate and zero
# at assetSaleYear. The sale proceeds are handled separately via the auto-
# managed LifeEventType_AssetSale event (Phase 2) which the existing engine
# Life Event path credits to assetProceedsAccount.
#
# Kept in a structure parallel to all_accounts so the engine's spendable
# `balances` dict (used for drawdown and the "runs out" calculation) is not
# polluted by illiquid assets.
# ---------------------------------------------------------------------------

def load_all_assets() -> list:
    """Return all PhysicalAsset subclass instances (PropertyAsset / VehicleAsset
    / CollectibleAsset) with base-currency-converted opening balance and the
    fields the engine needs to project them year-by-year.
    """
    assets = []
    for subclass in ("PropertyAsset", "VehicleAsset", "CollectibleAsset"):
        type_node = og.NamedNode(f"{MRL}{subclass}")
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

            raw_balance  = _float(iri, "accountBalance")
            fx_rate      = _float(iri, "exchangeRateToBase", 1.0)
            base_balance = raw_balance * fx_rate

            sale_year_raw = _val(iri, "assetSaleYear", "")
            try:
                sale_year = int(sale_year_raw) if sale_year_raw else None
            except ValueError:
                sale_year = None

            proceeds_qs = list(store.store.quads_for_pattern(
                iri, og.NamedNode(f"{MRL}assetProceedsAccount"), None, DATA_GRAPH))
            proceeds_account = (
                _iri_local(str(proceeds_qs[0].object.value)) if proceeds_qs else None
            )

            assets.append({
                "iri":               iri_str,
                "label":             label,
                "name":              _val(iri, "accountName", label),
                "asset_subclass":    subclass,
                "account_class":     "PhysicalAsset",
                "balance":           base_balance,
                "balance_date":      balance_date,
                "appreciation_rate": _float(iri, "assetAppreciationRate"),
                "sale_year":         sale_year,
                "proceeds_account":  proceeds_account,
            })
    return assets


# ---------------------------------------------------------------------------
# Budget lines (unchanged from v0.2)
# ---------------------------------------------------------------------------

def _int_or_none(raw: str) -> int | None:
    try:
        return int(raw) if raw else None
    except (ValueError, TypeError):
        return None


def find_active_segment(line: dict, year: int) -> dict | None:
    """Return the segment of `line` whose [start_year, end_year] window
    contains `year`, or None if no segment is active (line contributes
    zero — typical in a gap between segments or before/after the line's
    lifetime). Segments are pre-sorted by start_year in load_budget_lines().
    Per ADR-017 the UI rejects overlapping segments, so at most one is
    active for any given year.
    """
    for seg in line["segments"]:
        if seg["start_year"] is not None and year < seg["start_year"]:
            continue
        if seg["end_year"] is not None and year > seg["end_year"]:
            continue
        return seg
    return None


def load_budget_lines() -> list:
    """Load all BudgetLine instances with their segments (ADR-017).

    Each returned line has:
      - line_type: "BudgetLineType_Mandatory" | "_Discretionary" | "_Loan"
      - segments:  list of {annual_amount, change_rate, start_year, end_year},
                   sorted ascending by start_year

    Backwards compatible with pre-1.0.2 data: if a line has no segment
    instances yet, the legacy line-level amount / frequency / window /
    annualChangeRate / loanEndYear are synthesised into a single in-memory
    segment so the engine produces correct numbers even before
    migrate_legacy_budget_lines_to_segments() has had a chance to persist
    them (which happens on the next GET /budget render).
    """
    type_node = og.NamedNode(f"{MRL}BudgetLine")
    quads = store.store.quads_for_pattern(
        None, og.NamedNode(RDF_TYPE), type_node, DATA_GRAPH)
    lines = []

    seg_owner_pred = og.NamedNode(f"{MRL}segmentOwner")

    for q in quads:
        line_iri  = q.subject
        line_type = _local(line_iri, "budgetLineType")

        # Per-line FX conversion (1.0.5 — ADR-016 follow-on). Pre-multiplied
        # into each segment's annual_amount so the rest of the engine sees
        # base-currency figures only, mirroring how accounts + income are
        # FX-converted at load. Same-currency lines have no triple → 1.0.
        fx_rate = _float(line_iri, "budgetLineExchangeRateToBase", 1.0)

        segments = []
        for sq in store.store.quads_for_pattern(
                None, seg_owner_pred, line_iri, DATA_GRAPH):
            seg_iri    = sq.subject
            freq       = _local(seg_iri, "segmentFrequency") or "FrequencyType_Monthly"
            multiplier = FREQUENCY_MULTIPLIERS.get(freq, 12)
            amount     = _float(seg_iri, "segmentAmount")
            segments.append({
                "annual_amount": amount * multiplier * fx_rate,
                "change_rate":   _float(seg_iri, "segmentChangeRate"),
                "start_year":    _int_or_none(_val(seg_iri, "segmentStartYear", "")),
                "end_year":      _int_or_none(_val(seg_iri, "segmentEndYear",   "")),
            })
        segments.sort(key=lambda s: s["start_year"] if s["start_year"] is not None else 0)

        # Fallback: synthesise a single in-memory segment from the legacy
        # line-level fields when no BudgetLineSegment instance exists yet.
        # Folds loanEndYear into segment end_year (ADR-017 unified model).
        if not segments:
            freq       = _local(line_iri, "budgetLineFrequency") or "FrequencyType_Monthly"
            multiplier = FREQUENCY_MULTIPLIERS.get(freq, 12)
            amount     = _float(line_iri, "budgetLineAmount")
            start_year = _int_or_none(_val(line_iri, "budgetStartYear", ""))
            end_year   = _int_or_none(_val(line_iri, "budgetEndYear",   ""))
            loan_end   = _int_or_none(_val(line_iri, "loanEndYear",     ""))
            segments.append({
                "annual_amount": amount * multiplier * fx_rate,
                "change_rate":   _float(line_iri, "annualChangeRate"),
                "start_year":    start_year,
                "end_year":      end_year if end_year is not None else loan_end,
            })

        lines.append({
            "line_type": line_type,
            "segments":  segments,
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
        annual_amount          — employee contribution × frequency multiplier
        employer_annual_amount — employer portion × frequency multiplier (ADR-015 v1.1)
        from_payroll           — bool; employee portion deducted at source (ADR-015 v1.2)
        start_year             — int or None (defaults to current_year in engine)
        end_year               — int or None (defaults to retirement_year in engine)

    The employer portion credits the account balance like the employee portion
    but does NOT reduce personal cashflow (the employer pays it). When
    from_payroll is true the employee portion behaves the same way — it credits
    the balance but is excluded from cashflow, because the entered (net) income
    already excludes a salary-sacrifice / at-source deduction.

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
        employer   = _float(c_iri, "employerContributionAmount")
        from_payroll = _val(c_iri, "contributionFromPayroll", "") == "true"

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
            "annual_amount":          amount * multiplier,
            "employer_annual_amount": employer * multiplier,
            "from_payroll":           from_payroll,   # ADR-015 v1.2
            "start_year":             start_year,
            "end_year":                end_year,
            "growth_rate":            _float(c_iri, "contributionGrowthRate"),   # ADR-015 v1.1
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
        "emergency_fund_account_label": None,
        "emergency_fund_months":        0.0,
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
        "emergency_fund_account_label": _ps_local("emergencyFundAccount"),
        "emergency_fund_months":        _float(ps, "emergencyFundMonths",     0.0),
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
    emergency_fund_account_label: str | None = None,
    emergency_fund_months: float = 0.0,
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
            mrl:emergencyFundMonths       "{emergency_fund_months}"^^xsd:decimal ;
            mrl:projectionOwner           <{person_iri}> .
    """

    if spending_account_label:
        triples += f'\n        <{ps_iri}> mrl:spendingAccount mrl:{spending_account_label} .'
    if surplus_account_label:
        triples += f'\n        <{ps_iri}> mrl:surplusAccount  mrl:{surplus_account_label} .'
    if emergency_fund_account_label:
        triples += f'\n        <{ps_iri}> mrl:emergencyFundAccount mrl:{emergency_fund_account_label} .'

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

    Checks the eligibility constraints from ADR-011 §1:
      drawdownMinAge, drawdownEarliestDate, drawdownLatestDate.
    Absent constraints are not restrictive.
    drawdownEarliestDate takes precedence over drawdownMinAge when set.

    NB: drawdownMaxAge (a hard upper-age cutoff) was REMOVED in 1.0.6 (ADR-018) —
    it silently stranded balances. An upper age now means "withdrawals must start"
    (mandatoryWithdrawalAge + mandatoryWithdrawalRate), handled in the year loop,
    not an access cutoff. No account is ever blocked by an upper age.
    """
    person_age = year - birth_year

    if account["drawdown_min_age"] is not None and person_age < account["drawdown_min_age"]:
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
# Simulation helper — shared between deterministic and Monte Carlo engines
# (ADR-011, ADR-012, ADR-013, ADR-015)
#
# A single year-by-year simulation. The deterministic engine calls this with
# zero shocks; Monte Carlo calls it N times with random per-year shocks on
# investment growth and inflation. Both paths share the same drawdown
# eligibility, drawdown strategy, surplus routing, tax (source + residence),
# contributions, and life-event account routing — so MC reflects exactly the
# same model as the deterministic projection, just stochastic.
# ---------------------------------------------------------------------------

def _simulate_run(
    profile: dict,
    all_accounts: list,
    income_sources: list,
    budget_lines: list,
    life_events: list,
    contributions: dict,
    col_ratio: float,
    inflation_rate: float,
    proj_settings: dict,
    return_shocks: list[float] | None = None,
    inflation_shocks: list[float] | None = None,
    all_assets: list | None = None,
) -> dict:
    """Run one year-by-year simulation and return the year-level history.

    Shocks are per-year additive perturbations in PERCENT units (matching the
    growth_rate / inflation_rate convention), e.g. a shock of 6.0 is +6
    percentage points on that year's effective investment growth rate. Cash
    interest is never shocked (ADR-012 — σ applies to investments only).
    Negative simulated investment rates are clipped at -100% (cannot lose
    more than the balance).

    all_assets is a parallel list of mrl:PhysicalAsset instances (Phase 3).
    Assets appreciate at their own rate, do not participate in drawdown, and
    are zeroed at their sale_year. Sale proceeds flow through the existing
    Life Event engine path via the auto-managed LifeEventType_AssetSale
    created by accounts.py (Phase 2). Asset balances are tracked in a parallel
    structure so the spendable `balances` total used for drawdown and
    "runs-out-year" detection is not polluted by illiquid holdings.
    """
    today           = date.today()
    current_year    = today.year
    birth_year      = profile["birth_year"]
    retirement_year = birth_year + profile["retirement_age"]
    end_year        = birth_year + profile["life_expectancy"]
    n_years         = end_year - current_year + 1

    if return_shocks is None:
        return_shocks = [0.0] * n_years
    if inflation_shocks is None:
        inflation_shocks = [0.0] * n_years
    if all_assets is None:
        all_assets = []

    drawdown_strategy  = proj_settings.get("drawdown_strategy",  "DrawdownStrategy_Proportional")
    surplus_strategy   = proj_settings.get("surplus_strategy",   "SurplusStrategy_ReduceDrawdown")
    spending_acc       = proj_settings.get("spending_account_label")
    surplus_acc        = proj_settings.get("surplus_account_label")
    personal_allowance = proj_settings.get("annual_personal_allowance", 0.0)
    residence_rate     = proj_settings.get("residence_income_tax_rate",  0.0)
    ef_label           = proj_settings.get("emergency_fund_account_label")  # ADR-019
    ef_months          = proj_settings.get("emergency_fund_months", 0.0) or 0.0

    # Effective spending target — the account that surplus would actually land
    # in this scenario, even when the user hasn't explicitly configured one
    # on the Projection settings page. Falls back to first Current account,
    # then first Cash account, then first account (mirrors the surplus
    # routing fallback chain below at the surplus branch). Used by the
    # income-routing comparison further down so that "income to my main
    # current account" is treated as cashflow even on a freshly-set-up
    # scenario where the projection settings haven't been saved yet.
    def _resolve_effective_spending() -> str | None:
        if spending_acc:
            return spending_acc
        first_current = next(
            (a["label"] for a in all_accounts
             if a["account_class"] == "CashAccount"
             and a.get("account_type_local") == "CashAccountType_Current"),
            None,
        )
        if first_current:
            return first_current
        first_cash = next(
            (a["label"] for a in all_accounts
             if a["account_class"] == "CashAccount"),
            None,
        )
        if first_cash:
            return first_cash
        return all_accounts[0]["label"] if all_accounts else None

    effective_spending = _resolve_effective_spending()

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

    # --- Non-reinvested dividend income sources (deterministic) ---
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

    # --- Weighted display rate (informational, no σ applied) ---
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

    # --- Asset opening balances (Phase 3) ---
    # Forward-grow each asset's current value from its balance_date to
    # current_year using its appreciation_rate (same pattern as accounts).
    # Assets already sold before current_year are zeroed up-front so they
    # never appear in any year's history.
    asset_balances: dict[str, float] = {}
    for asset in all_assets:
        ye = max(0, current_year - asset["balance_date"].year)
        rate = asset["appreciation_rate"] / 100
        opening_val = asset["balance"] * ((1 + rate) ** ye)
        if asset["sale_year"] is not None and asset["sale_year"] <= current_year:
            opening_val = 0.0
        asset_balances[asset["label"]] = opening_val

    # Per-account history arrays
    account_history:              dict[str, list[float]] = {acc["label"]: [] for acc in all_accounts}
    account_withdrawal_history:   dict[str, list[float]] = {acc["label"]: [] for acc in all_accounts}
    account_return_history:       dict[str, list[float]] = {acc["label"]: [] for acc in all_accounts}
    account_contribution_history: dict[str, list[float]] = {acc["label"]: [] for acc in all_accounts}
    asset_history:                dict[str, list[float]] = {asset["label"]: [] for asset in all_assets}
    projection_years         = []
    cumulative_tax           = 0.0
    cumulative_contributions = 0.0
    cumulative_unfunded      = 0.0    # ADR-018 follow-on: spending that could not be drawn
    first_unfunded_year      = None

    for yi, year in enumerate(range(current_year, end_year + 1)):
        years_from_start = year - current_year

        # Per-year shocks (zero for deterministic runs)
        ret_shock_pct   = return_shocks[yi]    if yi < len(return_shocks)    else 0.0
        infl_shock_pct  = inflation_shocks[yi] if yi < len(inflation_shocks) else 0.0
        sim_inflation   = max(0.1, inflation_rate + infl_shock_pct)

        # 1. Capture opening balances
        opening_this_year = dict(balances)

        # 2. Apply growth — investments get σ, cash stays deterministic
        for acc in all_accounts:
            if balances[acc["label"]] <= 0:
                continue
            if acc["account_class"] == "CashAccount":
                balances[acc["label"]] *= (1 + acc["interest_rate"] / 100)
            else:
                eff_pct     = acc["growth_rate"] + (acc["dividend_rate"] if acc["reinvest_dividends"] else 0)
                sim_eff_pct = max(-100.0, eff_pct + ret_shock_pct)
                balances[acc["label"]] *= (1 + sim_eff_pct / 100)

        # Returns earned this year — per-account for detail chart and total for display
        returns_this_year = sum(
            balances[acc["label"]] - opening_this_year[acc["label"]]
            for acc in all_accounts
        )
        for acc in all_accounts:
            account_return_history[acc["label"]].append(
                round(balances[acc["label"]] - opening_this_year[acc["label"]], 0)
            )

        # 2b. Contributions (ADR-015) — credit balance + accumulate cashflow cost.
        # Employer portion (ADR-015 v1.1) credits balance but does NOT reduce
        # personal cashflow — the employer pays it. A payroll/salary-sacrifice
        # employee portion (ADR-015 v1.2, from_payroll) is treated the same way:
        # it credits the balance but is excluded from cashflow, because the
        # entered (net) income already excludes an at-source deduction. Both
        # portions share one growth_rate and time window.
        year_contribution_spending = 0.0
        for acc in all_accounts:
            contrib = contributions.get(acc["label"])
            contrib_this_year = 0.0
            if contrib:
                c_start = contrib["start_year"] if contrib["start_year"] else current_year
                c_end   = contrib["end_year"]   if contrib["end_year"]   else retirement_year
                if c_start <= year <= c_end:
                    employee_base = contrib["annual_amount"]
                    employer_base = contrib.get("employer_annual_amount", 0.0)
                    g_rate        = contrib.get("growth_rate", 0.0)
                    years_active  = year - c_start
                    growth_factor = (
                        (1 + g_rate / 100) ** years_active
                        if g_rate != 0.0 else 1.0
                    )
                    employee_this_year = employee_base * growth_factor
                    employer_this_year = employer_base * growth_factor
                    contrib_this_year  = employee_this_year + employer_this_year
                    balances[acc["label"]] += contrib_this_year
                    if not contrib.get("from_payroll", False):
                        year_contribution_spending += employee_this_year
            account_contribution_history[acc["label"]].append(round(contrib_this_year, 0))
        cumulative_contributions += year_contribution_spending

        # 3. Income (active sources + non-reinvested dividends).
        # Income earned this year is always tracked in income_amount for display.
        # Sources with a deposit_account land directly in that account's balance
        # and are excluded from unrouted_income (which feeds pre_net); sources
        # without one accumulate in unrouted_income and follow the projection's
        # surplus routing as before. Non-reinvested dividends remain unrouted.
        #
        # Exception: when deposit_account == spending_account, the income is
        # treated as unrouted. Otherwise the engine credits the income to the
        # balance but doesn't recognise it as covering this year's spending,
        # so pre_net goes negative and drawdown is triggered against every
        # eligible account at the same priority — including the very account
        # that just received the deposit. That produces "contribute + draw
        # down the same account in the same year" behaviour that doesn't
        # match anyone's mental model when the user has already nominated the
        # spending account as the income destination.
        income_amount   = 0.0
        unrouted_income = 0.0
        for src in income_sources:
            src_start = src["start_year"] or current_year
            src_end   = src["end_year"]
            if year < src_start or (src_end is not None and year > src_end):
                continue
            # ADR-021: a property-linked rental source derives its income from
            # the linked asset's value at the START of this year (asset_balances
            # before step 7b's appreciation/disposal) × the net yield, ignoring
            # the static amount and growth rate. Once the asset is sold, step 7b
            # has already zeroed its balance, so the rent becomes 0 with no
            # end-date needed. A dangling/deleted link falls back to the static
            # amount so it degrades safely.
            rental_prop = src.get("rental_property")
            if rental_prop and rental_prop in asset_balances and src.get("rental_yield"):
                amt = asset_balances[rental_prop] * (src["rental_yield"] / 100)
            else:
                amt = src["amount"] * ((1 + src["growth_rate"] / 100) ** years_from_start)
            income_amount += amt
            deposit = src.get("deposit_account")
            if deposit and deposit in balances and deposit != effective_spending:
                balances[deposit] += amt
            else:
                unrouted_income += amt
        for ds in div_sources:
            pv = ds["opening_value"] * ((1 + ds["growth_rate"] / 100) ** years_from_start)
            div_income = pv * (ds["dividend_rate"] / 100)
            income_amount   += div_income
            unrouted_income += div_income

        # 4. Spending (sim_inflation for non-loan lines)
        # ADR-017: each line has 1+ segments; find_active_segment() returns
        # the one whose [start_year, end_year] window contains `year`, or
        # None if no segment is active (gap or before/after the line's life).
        # The growth exponent stays `years_from_start` (the projection's own
        # year offset) so single-segment migrated lines produce bit-identical
        # numbers to the pre-ADR-017 engine.
        mandatory = discretionary = loans = 0.0
        for line in budget_lines:
            seg = find_active_segment(line, year)
            if seg is None:
                continue
            if line["line_type"] == "BudgetLineType_Loan":
                rate = seg["change_rate"]
            else:
                rate = sim_inflation + seg["change_rate"]
            annual = seg["annual_amount"] * ((1 + rate / 100) ** years_from_start)
            if   line["line_type"] == "BudgetLineType_Mandatory":     mandatory     += annual
            elif line["line_type"] == "BudgetLineType_Discretionary": discretionary += annual
            elif line["line_type"] == "BudgetLineType_Loan":          loans         += annual

        if col_ratio != 1.0 and year >= retirement_year:
            mandatory     *= col_ratio
            discretionary *= col_ratio
            loans         *= col_ratio

        # 5. Life events (with account routing per ADR-011 §5)
        life_event_costs    = 0.0
        life_event_receipts = 0.0
        general_costs       = 0.0
        general_receipts    = 0.0
        for evt in life_events:
            if evt["year"] != year:
                continue
            amt = evt["amount"]
            if amt >= 0:
                life_event_costs += amt
                if evt["funded_by_account"] and evt["funded_by_account"] in balances:
                    balances[evt["funded_by_account"]] = \
                        max(0.0, balances[evt["funded_by_account"]] - amt)
                else:
                    general_costs += amt
            else:
                life_event_receipts += abs(amt)
                if evt["received_by_account"] and evt["received_by_account"] in balances:
                    balances[evt["received_by_account"]] += abs(amt)
                else:
                    general_receipts += abs(amt)

        # 6. Net cashflow before drawdown.
        # Routed income has already been credited directly to deposit accounts;
        # only unrouted_income flows through here. The drawdown logic will then
        # cover any shortfall from eligible accounts (including those that just
        # received deposits, naturally).
        total_spending = mandatory + discretionary + loans + general_costs
        pre_net        = unrouted_income + general_receipts - total_spending - year_contribution_spending

        # 7. Drawdown, mandatory (RMD) withdrawals, surplus — ADR-011 + ADR-018.
        # Phases: A cover spending shortfall, B force mandatory minimums,
        # C tax all withdrawals once, D sweep unspent forced proceeds. With no
        # mandatoryWithdrawalRate set anywhere, B/D are no-ops and the result is
        # byte-identical to the pre-1.0.6 single-branch engine.
        tax_free_used: dict[str, float] = {acc["label"]: 0.0 for acc in all_accounts}
        total_source_tax        = 0.0
        total_taxable_at_source = 0.0
        net_annual_tax          = 0.0
        year_unfunded           = 0.0    # spending this year that no eligible account could cover
        year_withdrawals: dict[str, float] = {}
        person_age              = year - birth_year

        # Where surplus / unspent forced proceeds land (the long-standing
        # surplus-routing fallback, resolved once up front so Phase D can reuse it).
        if surplus_strategy == "SurplusStrategy_SweepToAccount":
            sweep_target = surplus_acc or spending_acc
        else:
            sweep_target = spending_acc
        if not (sweep_target and sweep_target in balances):
            first_current = next(
                (a["label"] for a in all_accounts
                 if a["account_class"] == "CashAccount"
                 and a.get("account_type_local") == "CashAccountType_Current"),
                None)
            first_cash = next(
                (a["label"] for a in all_accounts if a["account_class"] == "CashAccount"),
                None)
            sweep_target = first_current or first_cash or (all_accounts[0]["label"] if all_accounts else None)

        eligible = [
            acc for acc in all_accounts
            if _is_eligible(acc, year, birth_year) and balances.get(acc["label"], 0) > 0
        ]

        # Emergency fund (ADR-019). Target = months/12 of this year's RECURRING
        # spend (mandatory + discretionary + loans; one-off life events excluded).
        # sweep() tops the fund up to target before overflowing to sweep_target;
        # the fund is also drawn first in Phase A. With no ef account set,
        # ef_acct is None → sweep() is the plain old surplus sweep (parity).
        ef_acct   = next((a for a in all_accounts if a["label"] == ef_label), None) if ef_label else None
        ef_target = (ef_months / 12.0) * (mandatory + discretionary + loans) if (ef_acct and ef_months > 0) else 0.0

        def sweep(amount):
            if amount <= 0:
                return
            if ef_acct and ef_target > 0:
                ef_bal = balances.get(ef_label, 0.0)
                if ef_bal < ef_target:
                    fill = min(amount, ef_target - ef_bal)
                    balances[ef_label] = ef_bal + fill
                    amount -= fill
            if amount > 0 and sweep_target and sweep_target in balances:
                balances[sweep_target] += amount

        # Phase A — cover this year's spending shortfall (or bank a surplus).
        if pre_net < 0:
            shortfall = -pre_net
            # Emergency fund drawn first (ADR-019) — the buffer absorbs the shock
            # before the chosen strategy liquidates anything else.
            if ef_acct and shortfall > 0 and _is_eligible(ef_acct, year, birth_year):
                ef_draw = min(balances.get(ef_label, 0.0), shortfall)
                if ef_draw > 0:
                    balances[ef_label] -= ef_draw
                    year_withdrawals[ef_label] = year_withdrawals.get(ef_label, 0.0) + ef_draw
                    shortfall -= ef_draw
            remaining_eligible = [a for a in eligible if a["label"] != ef_label]
            drawdown = _apply_drawdown(
                remaining_eligible, shortfall, drawdown_strategy, balances)
            for acc_label, gross_draw in drawdown.items():
                balances[acc_label] -= gross_draw  # tax applied once in Phase C
                year_withdrawals[acc_label] = year_withdrawals.get(acc_label, 0.0) + gross_draw
            # ADR-018 follow-on — record any shortfall that NO eligible account could
            # cover. `shortfall` is already net of the emergency-fund draw; whatever
            # the drawdown strategy couldn't supply (every eligible balance exhausted)
            # is unfunded spending. This is a GROSS measure — it flags "you couldn't
            # draw enough to meet spending", separate from the source/residence tax
            # that Phase C then levies on what *was* drawn. It is distinct from
            # runs_out_year: money locked in not-yet-eligible accounts (e.g. a pension
            # below its access age) can leave spending unfunded while total balance > 0.
            year_unfunded = max(0.0, shortfall - sum(drawdown.values()))
        elif pre_net > 0:
            sweep(pre_net)

        # Phase B — mandatory (RMD-style) minimum withdrawals (ADR-018). An
        # account past its mandatoryWithdrawalAge must draw at least
        # balance × rate% this year; a shortfall draw already taken counts toward
        # it, so only the top-up is forced. The forced top-up is surplus (spending
        # was covered) — its after-tax value is swept in Phase D.
        forced_gross = 0.0
        for acc in all_accounts:
            mwa = acc.get("mandatory_withdrawal_age")
            mwr = acc.get("mandatory_withdrawal_rate")
            if mwa is None or not mwr or mwr <= 0 or person_age < mwa:
                continue
            label = acc["label"]
            bal   = balances.get(label, 0.0)
            if bal <= 0:
                continue
            required = bal * (mwr / 100.0)
            already  = year_withdrawals.get(label, 0.0)
            extra    = min(bal, max(0.0, required - already))
            if extra > 0:
                balances[label] -= extra
                year_withdrawals[label] = already + extra
                forced_gross += extra

        # Phase C — tax over ALL withdrawals this year (shortfall + forced), ADR-013.
        for acc_label, gross_draw in year_withdrawals.items():
            acc = next(a for a in all_accounts if a["label"] == acc_label)
            free_used, src_tax = _compute_source_tax(
                acc, gross_draw, tax_free_used[acc_label])
            tax_free_used[acc_label] += free_used
            total_source_tax         += src_tax
            if acc["tax_treatment"] not in RESIDENCE_EXEMPT_TREATMENTS:
                total_taxable_at_source += (gross_draw - free_used)
            balances[acc_label] = max(0.0, balances[acc_label] - src_tax)

        res_tax = _compute_residence_tax(
            total_taxable_at_source, total_source_tax,
            personal_allowance, residence_rate)
        if res_tax > 0:
            if spending_acc and spending_acc in balances:
                balances[spending_acc] = max(0.0, balances[spending_acc] - res_tax)
            elif eligible:
                total_el_bal = sum(balances.get(a["label"], 0) for a in eligible)
                if total_el_bal > 0:
                    for a in eligible:
                        share = (balances.get(a["label"], 0) / total_el_bal) * res_tax
                        balances[a["label"]] = max(0.0, balances[a["label"]] - share)
        net_annual_tax = total_source_tax + res_tax

        # Phase D — sweep the AFTER-TAX forced proceeds to the spending account.
        # They weren't needed for spending; an RMD forces a taxable distribution
        # that you then bank. Tax is attributed to the forced portion pro-rata.
        if forced_gross > 0:
            total_gross = sum(year_withdrawals.values())
            forced_tax  = net_annual_tax * (forced_gross / total_gross) if total_gross > 0 else 0.0
            forced_net  = max(0.0, forced_gross - forced_tax)
            sweep(forced_net)  # ADR-019: tops up the emergency fund first, then overflows

        cumulative_tax += net_annual_tax
        if year_unfunded > UNFUNDED_EPSILON:
            cumulative_unfunded += year_unfunded
            if first_unfunded_year is None:
                first_unfunded_year = year

        # 7b. Asset appreciation / disposal (Phase 3).
        # Assets appreciate at their own rate each year up to (but not
        # including) their sale_year. From sale_year onwards they are zero —
        # the proceeds were already injected into proceeds_account this year
        # via the auto-managed LifeEventType_AssetSale processed in step 5.
        for asset in all_assets:
            label = asset["label"]
            if asset["sale_year"] is not None and year >= asset["sale_year"]:
                asset_balances[label] = 0.0
            elif asset_balances[label] > 0:
                asset_balances[label] *= (1 + asset["appreciation_rate"] / 100)
            asset_history[label].append(round(asset_balances[label], 0))

        # 8. Record closing balances per account and per-year totals
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
            "unfunded":            round(year_unfunded, 0),
            "is_retirement_year":  year == retirement_year,
        })

    return {
        "years":                       projection_years,
        "account_balances":            account_history,
        "account_withdrawals":         account_withdrawal_history,
        "account_returns":             account_return_history,
        "account_contributions":       account_contribution_history,
        "asset_balances":              asset_history,
        "total_tax_paid":              round(cumulative_tax, 0),
        "total_contributions":         round(cumulative_contributions, 0),
        "total_unfunded":              round(cumulative_unfunded, 0),
        "first_unfunded_year":         first_unfunded_year,
        "opening_balance":             round(total_opening, 0),
        "opening_investment_balance":  round(inv_opening, 0),
        "weighted_rate":               round(weighted_rate_pct, 2),
        "retirement_year":             retirement_year,
        "end_year":                    end_year,
        "current_year":                current_year,
    }


# ---------------------------------------------------------------------------
# ADR-018 migration — drawdownMaxAge (cutoff) → mandatoryWithdrawalAge
# ---------------------------------------------------------------------------

def migrate_drawdown_max_age_to_mandatory() -> int:
    """Idempotently copy any legacy mrl:drawdownMaxAge to mrl:mandatoryWithdrawalAge.

    ADR-018 retired the hard upper-age cutoff. This preserves the user's intended
    age under the new meaning ("withdrawals must start") while leaving the rate
    unset — so a migrated account simply becomes drawable again (no stranding)
    and forces nothing until the user sets a rate. drawdownMaxAge is left in place
    (deprecate-in-place). Safe to call on every relevant request; returns the
    number of accounts migrated this call.
    """
    max_pred  = og.NamedNode(f"{MRL}drawdownMaxAge")
    mand_pred = og.NamedNode(f"{MRL}mandatoryWithdrawalAge")
    legacy = list(store.store.quads_for_pattern(None, max_pred, None, DATA_GRAPH))
    if not legacy:
        return 0
    migrated = 0
    for q in legacy:
        subj = q.subject
        if list(store.store.quads_for_pattern(subj, mand_pred, None, DATA_GRAPH)):
            continue  # already migrated
        store.update(f"""
            PREFIX mrl: <{MRL}>
            PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
            INSERT DATA {{
                GRAPH <{DATA_GRAPH.value}> {{
                    <{subj.value}> mrl:mandatoryWithdrawalAge "{q.object.value}"^^xsd:decimal .
                }}
            }}
        """)
        migrated += 1
    return migrated


# ---------------------------------------------------------------------------
# Deterministic projection — thin wrapper over _simulate_run
# ---------------------------------------------------------------------------

def run_projection(
    inflation_rate: float = 2.5,
    proj_settings: dict | None = None,
    account_overrides: dict | None = None,
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

    migrate_drawdown_max_age_to_mandatory()  # ADR-018: legacy cutoff → mandatory age

    if proj_settings is None:
        proj_settings = get_projection_settings()

    income_sources = load_all_income_sources()
    all_accounts   = load_all_accounts()
    all_assets     = load_all_assets()           # Phase 3
    budget_lines   = load_budget_lines()
    life_events    = load_life_events()
    contributions  = load_all_contributions()   # ADR-015
    col_ratio      = load_col_ratio()

    if not all_accounts:
        return None

    # Non-persisting what-if overrides (Drawdown Strategy page). Patches only the
    # drawdown/tax fields of matching account dicts in memory before simulating;
    # nothing is written to the store. account_overrides=None → byte-identical to
    # a normal run, preserving engine parity for every existing caller.
    if account_overrides:
        for acc in all_accounts:
            ov = account_overrides.get(acc["label"])
            if not ov:
                continue
            for k in ("drawdown_priority", "drawdown_ratio", "tax_treatment",
                      "effective_withdrawal_tax_rate", "annual_tax_free_withdrawal"):
                if k in ov:
                    acc[k] = ov[k]
        all_accounts.sort(key=lambda a: a["drawdown_priority"])  # mirror load_all_accounts

    sim = _simulate_run(
        profile         = profile,
        all_accounts    = all_accounts,
        income_sources  = income_sources,
        budget_lines    = budget_lines,
        life_events     = life_events,
        contributions   = contributions,
        col_ratio       = col_ratio,
        inflation_rate  = inflation_rate,
        proj_settings   = proj_settings,
        all_assets      = all_assets,
    )

    # --- Confidence scoring ---
    runs_out_year = next(
        (y["year"] for y in sim["years"] if y["balance"] <= 0), None)
    final_balance = sim["years"][-1]["balance"] if sim["years"] else 0
    end_year      = sim["end_year"]
    total_unfunded      = sim["total_unfunded"]
    first_unfunded_year = sim["first_unfunded_year"]

    # ADR-018 follow-on: an unfunded shortfall is the most serious outcome and
    # takes precedence over runs_out_year. It catches the silent case runs_out
    # misses — spending the plan can't cover while money sits locked in accounts
    # not yet eligible for drawdown, so total balance never reaches zero.
    if first_unfunded_year is not None:
        confidence       = "red"
        confidence_label = "Spending unfunded"
        locked = " (some balances remain locked in accounts not yet available to draw)" \
                 if runs_out_year is None else ""
        confidence_message = (
            f"From {first_unfunded_year} your eligible accounts can't cover planned "
            f"spending — £{total_unfunded:,.0f} of spending goes unfunded over the plan{locked}."
        )
    elif runs_out_year is None:
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
        "years":                      sim["years"],
        "runs_out_year":              runs_out_year,
        "retirement_year":            sim["retirement_year"],
        "end_year":                   end_year,
        "current_year":               sim["current_year"],
        "opening_balance":            sim["opening_balance"],
        "opening_investment_balance": sim["opening_investment_balance"],
        "final_balance":              round(final_balance, 0),
        "confidence":                 confidence,
        "confidence_label":           confidence_label,
        "confidence_message":         confidence_message,
        "total_unfunded":             total_unfunded,
        "first_unfunded_year":        first_unfunded_year,
        "weighted_rate":              sim["weighted_rate"],
        "col_ratio":                  col_ratio,
        "account_balances":           sim["account_balances"],
        "account_withdrawals":        sim["account_withdrawals"],
        "account_returns":            sim["account_returns"],
        "account_contributions":      sim["account_contributions"],
        "account_names":              {acc["label"]: acc["name"]          for acc in all_accounts},
        "account_classes":            {acc["label"]: acc["account_class"] for acc in all_accounts},
        # Phase 3: physical assets — parallel structure, doesn't pollute total_balance
        "asset_balances":             sim["asset_balances"],
        "asset_names":                {a["label"]: a["name"]           for a in all_assets},
        "asset_subclasses":           {a["label"]: a["asset_subclass"] for a in all_assets},
        "total_tax_paid":             sim["total_tax_paid"],
        "total_contributions":        sim["total_contributions"],
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
    inflation_rate: float       = 2.5,
    mc_profile_local: str       = "MonteCarloProfile_Moderate",
    n_sims: int                 = 250,
    proj_settings: dict | None  = None,
) -> dict | None:
    """Monte Carlo simulation built on the shared per-account simulation helper.

    Each simulation is one full run of _simulate_run with random per-year shocks
    on investment growth and inflation. σ (return volatility) is applied only
    to investment growth; cash interest stays deterministic per ADR-012.

    Because both engines share _simulate_run, MC reflects the same drawdown
    eligibility, drawdown strategy, contributions (ADR-015), life-event account
    routing, and two-layer tax model (ADR-013) as the deterministic projection.

    Returns P10 / P50 / P90 percentiles of the total balance per year, plus
    success_rate (% of simulations that funded all spending every year — i.e.
    total balance never hit zero AND no year's spending went unfunded, item 61).
    """
    import numpy as np

    profile = load_profile()
    if not profile:
        return None
    if proj_settings is None:
        proj_settings = get_projection_settings()

    all_accounts = load_all_accounts()
    if not any(a["account_class"] == "InvestmentAccount" for a in all_accounts):
        # No investments → nothing stochastic to model.
        return None

    return_vol, inflation_vol = _get_mc_params(mc_profile_local)

    income_sources = load_all_income_sources()
    budget_lines   = load_budget_lines()
    life_events    = load_life_events()
    contributions  = load_all_contributions()
    col_ratio      = load_col_ratio()

    today           = date.today()
    current_year    = today.year
    end_year        = profile["birth_year"] + profile["life_expectancy"]
    year_range      = list(range(current_year, end_year + 1))
    n_years         = len(year_range)

    # Shocks in PERCENT units (matching the rate convention used by _simulate_run)
    rng              = np.random.default_rng()
    return_shocks    = rng.normal(0.0, return_vol,    (n_sims, n_years))
    inflation_shocks = rng.normal(0.0, inflation_vol, (n_sims, n_years))

    all_balances = np.empty((n_sims, n_years), dtype=np.float64)
    sim_unfunded = np.zeros(n_sims, dtype=bool)   # ADR-018 follow-on (item 61)

    for sim in range(n_sims):
        result = _simulate_run(
            profile          = profile,
            all_accounts     = all_accounts,
            income_sources   = income_sources,
            budget_lines     = budget_lines,
            life_events      = life_events,
            contributions    = contributions,
            col_ratio        = col_ratio,
            inflation_rate   = inflation_rate,
            proj_settings    = proj_settings,
            return_shocks    = return_shocks[sim].tolist(),
            inflation_shocks = inflation_shocks[sim].tolist(),
        )
        all_balances[sim] = [y["balance"] for y in result["years"]]
        sim_unfunded[sim] = result.get("first_unfunded_year") is not None

    p10 = np.percentile(all_balances, 10, axis=0).round(0).tolist()
    p50 = np.percentile(all_balances, 50, axis=0).round(0).tolist()
    p90 = np.percentile(all_balances, 90, axis=0).round(0).tolist()
    # Success = the plan funded all spending every year. Two failure modes,
    # mirroring the deterministic confidence logic exactly:
    #   1. total balance reached zero (runs_out) — balance <= 0 in any year;
    #   2. spending went UNFUNDED (item 61) — eligible accounts couldn't cover
    #      a year's spend even though total balance stayed > 0 (the locked-money
    #      case: money compounding in an account below its access age). Without
    #      this, MC reported a confident "success" on a run the deterministic
    #      engine would paint red "Spending unfunded".
    # Per-account balances are floored at 0 inside _simulate_run, so the total
    # can hit 0 but never go negative; "> 0" is the correct balance test.
    balance_ok   = np.all(all_balances > 0, axis=1)
    success_rate = round(float(np.mean(balance_ok & ~sim_unfunded)) * 100, 1)

    has_cash = any(a["account_class"] == "CashAccount" for a in all_accounts)

    return {
        "years":            year_range,
        "p10":              p10,
        "p50":              p50,
        "p90":              p90,
        "success_rate":     success_rate,
        "n_sims":           n_sims,
        "profile":          mc_profile_local,
        # Legacy key — was the old aggregate-pool cash layer; new model integrates
        # cash and investments coherently, so this is always empty. Kept for
        # template backward-compat (existing checks fall through cleanly).
        "cash_floor":       [],
        "has_cash":         has_cash,
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/projection", response_class=HTMLResponse)
async def projection_page(request: Request):
    proj_settings = get_projection_settings()
    projection    = run_projection(proj_settings["inflation_rate"], proj_settings)
    mc            = run_monte_carlo(proj_settings["inflation_rate"], proj_settings["mc_profile"], proj_settings=proj_settings)
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

    # Tax shield summary — surface the two-layer ADR-013 model so the user can
    # see personal allowance and per-account allowances side-by-side. They
    # intentionally stack; this panel helps catch double-counting (e.g. same
    # figure entered in both places).
    shield_accounts = [
        {
            "name":           a["name"],
            "amount":         a["annual_tax_free_withdrawal"],
            "tax_treatment":  a["tax_treatment"],
            "account_class":  a["account_class"],
        }
        for a in all_accounts
        if a["annual_tax_free_withdrawal"] > 0
    ]
    shield_accounts_total = sum(a["amount"] for a in shield_accounts)
    personal_allowance    = proj_settings.get("annual_personal_allowance", 0.0)
    tax_shield_summary = {
        "personal_allowance": personal_allowance,
        "accounts":           shield_accounts,
        "accounts_total":     shield_accounts_total,
        "combined":           personal_allowance + shield_accounts_total,
        "show":               personal_allowance > 0 or shield_accounts_total > 0,
    }

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
            "tax_shield_summary":     tax_shield_summary,
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
    emergency_fund_account_label: str = Form(""),
    emergency_fund_months:        float = Form(0.0),
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
        emergency_fund_account_label = emergency_fund_account_label or None,
        emergency_fund_months        = emergency_fund_months,
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
        emergency_fund_account_label = ps["emergency_fund_account_label"],
        emergency_fund_months        = ps["emergency_fund_months"],
    )
    return RedirectResponse(url="/projection", status_code=303)