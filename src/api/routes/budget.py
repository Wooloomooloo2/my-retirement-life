"""
Budget routes — manage the user's budget lines, segments, and categories.

GET  /budget                       — list all budget lines + add form
POST /budget                       — create a new budget line
GET  /budget/{n}/edit              — load edit form for budget line N
POST /budget/{n}/edit              — save edits to budget line N
POST /budget/{n}/delete            — delete budget line N (+ its segments)

POST /budget/categories            — create a new BudgetCategory          (ADR-017)
POST /budget/categories/{n}/rename — rename BudgetCategory_N              (ADR-017)
POST /budget/categories/{n}/delete — delete BudgetCategory_N              (ADR-017)

ADR-017 notes:
- Each BudgetLine has one or more BudgetLineSegment instances linked via
  mrl:segmentOwner; the segment is the source of truth for amount,
  frequency, time window, and real-growth rate.
- Phase 1b shape: single segment per save (Phase 3 will extend the editor
  to multiple segments). get_all_budget_lines() exposes a flattened
  first-segment view at the top level for backwards-compatible templates.
- Categories are user-created on demand. "Account contributions" is
  reserved for the synthetic chart group derived from AccountContribution
  instances (ADR-015).
- migrate_legacy_budget_lines_to_segments() runs idempotently on the first
  /budget render after the 1.0.2 ontology bump; deprecated line-level
  properties are left in place per ADR-017 §3.
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

RDF_TYPE       = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
MRL_EXT        = "https://myretirementlife.app/ontology/ext#"
ONTOLOGY_GRAPH = og.NamedNode("https://myretirementlife.app/ontology/graph")

# Reserved category names — case-insensitive. "Account contributions" is the
# synthetic system group derived from AccountContribution instances (ADR-015).
RESERVED_CATEGORY_NAMES = {"account contributions"}

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

# Starter chip suggestions surfaced in the line form (ADR-017). These are NOT
# pre-created — they only materialise as BudgetCategory_N instances when the
# user actually adopts one.
CATEGORY_SUGGESTIONS = [
    "Housing", "Food", "Transport", "Travel", "Health",
    "Subscriptions", "Personal", "Bills", "Taxes",
]

ACCOUNT_CONTRIBUTIONS_LABEL = "Account contributions"  # synthetic system group
UNCATEGORISED_LABEL         = "Uncategorised"           # fallback group


def _category_palette(name: str) -> tuple[str, str]:
    """Return (fill_rgba, border_color) for a category name.

    System groups have pinned colours:
      - Account contributions → teal (matches the existing 4th-band convention)
      - Uncategorised         → neutral gray

    User categories get a deterministic HSL palette keyed off the lowercased
    name, so the same category always renders in the same colour across
    sessions even though categories are user-created.
    """
    if name == ACCOUNT_CONTRIBUTIONS_LABEL:
        return "rgba(20,184,166,0.45)", "#14b8a6"
    if name == UNCATEGORISED_LABEL:
        return "rgba(156,163,175,0.45)", "#9ca3af"
    import hashlib
    h   = int(hashlib.md5(name.lower().encode("utf-8")).hexdigest()[:6], 16)
    hue = h % 360
    return f"hsla({hue}, 65%, 55%, 0.45)", f"hsl({hue}, 55%, 45%)"


def _escape(s: str) -> str:
    """Minimal SPARQL literal escaping — backslash + double-quote."""
    return (s or "").replace("\\", "\\\\").replace('"', '\\"')


def to_annual(amount: float, frequency_local: str) -> float:
    """Convert an amount at a given frequency to its annual equivalent."""
    multiplier = FREQUENCY_MULTIPLIERS.get(frequency_local, 12)
    return round(amount * multiplier, 2)


# ===========================================================================
# BUDGET CATEGORY (ADR-017)
# ===========================================================================

def get_all_categories() -> list[dict]:
    """Return all BudgetCategory instances, sorted by displayOrder then name."""
    type_node = og.NamedNode(f"{MRL}BudgetCategory")
    quads = store.store.quads_for_pattern(
        None, og.NamedNode(RDF_TYPE), type_node, DATA_GRAPH)
    cats = []
    for q in quads:
        iri = q.subject
        suffix = str(iri.value).split("BudgetCategory_")[-1]
        if not suffix.isdigit():
            continue

        def gv(prop):
            qs = list(store.store.quads_for_pattern(
                iri, og.NamedNode(f"{MRL}{prop}"), None, DATA_GRAPH))
            return str(qs[0].object.value) if qs else ""

        cats.append({
            "n":            suffix,
            "iri":          str(iri.value),
            "name":         gv("categoryName"),
            "displayOrder": gv("categoryDisplayOrder"),
            "source":       gv("categorySource") or "user",
        })
    cats.sort(key=lambda c: (
        int(c["displayOrder"]) if c["displayOrder"].isdigit() else 999_999,
        c["name"].lower(),
    ))
    return cats


def get_category_by_name(name: str) -> Optional[dict]:
    """Case-insensitive lookup by display name."""
    target = (name or "").strip().lower()
    if not target:
        return None
    for c in get_all_categories():
        if c["name"].strip().lower() == target:
            return c
    return None


def _next_category_n() -> int:
    cats = get_all_categories()
    nums = [int(c["n"]) for c in cats if c["n"].isdigit()]
    return max(nums, default=0) + 1


def create_category(name: str) -> dict:
    """Create a BudgetCategory with the given display name. If a category
    with the same name (case-insensitive) already exists, return it
    unchanged. Raises ValueError if the name is empty or reserved.
    """
    name = (name or "").strip()
    if not name:
        raise ValueError("Category name cannot be empty.")
    if name.lower() in RESERVED_CATEGORY_NAMES:
        raise ValueError(f"'{name}' is reserved for the system group.")
    existing = get_category_by_name(name)
    if existing:
        return existing
    n = _next_category_n()
    cat_iri = f"{MRL}BudgetCategory_{n}"
    store.update(f"""
        PREFIX mrl: <{MRL}>
        PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
        INSERT DATA {{
            GRAPH <{DATA_GRAPH.value}> {{
                <{cat_iri}> a mrl:BudgetCategory ;
                    mrl:categoryName "{_escape(name)}" ;
                    mrl:categorySource "user" .
            }}
        }}
    """)
    return {
        "n": str(n), "iri": cat_iri, "name": name,
        "displayOrder": "", "source": "user",
    }


def rename_category(n: int, new_name: str) -> None:
    new_name = (new_name or "").strip()
    if not new_name:
        raise ValueError("Category name cannot be empty.")
    if new_name.lower() in RESERVED_CATEGORY_NAMES:
        raise ValueError(f"'{new_name}' is reserved.")
    cat_iri = f"{MRL}BudgetCategory_{n}"
    store.update(f"""
        PREFIX mrl: <{MRL}>
        DELETE WHERE {{
            GRAPH <{DATA_GRAPH.value}> {{
                <{cat_iri}> mrl:categoryName ?o .
            }}
        }}
    """)
    store.update(f"""
        PREFIX mrl: <{MRL}>
        INSERT DATA {{
            GRAPH <{DATA_GRAPH.value}> {{
                <{cat_iri}> mrl:categoryName "{_escape(new_name)}" .
            }}
        }}
    """)


def get_lines_using_category(cat_n: int) -> list[str]:
    """Return the BudgetLine N values that reference this category."""
    cat_iri = og.NamedNode(f"{MRL}BudgetCategory_{cat_n}")
    pred    = og.NamedNode(f"{MRL}budgetCategory")
    quads   = store.store.quads_for_pattern(None, pred, cat_iri, DATA_GRAPH)
    return [str(q.subject.value).split("BudgetLine_")[-1] for q in quads]


def delete_category(n: int) -> None:
    """Delete a BudgetCategory by N. Errors if any line still references it."""
    using = get_lines_using_category(n)
    if using:
        raise ValueError(
            f"Category is still used by {len(using)} line(s); "
            "reassign them before deleting."
        )
    cat_iri = f"{MRL}BudgetCategory_{n}"
    store.update(f"""
        DELETE WHERE {{
            GRAPH <{DATA_GRAPH.value}> {{
                <{cat_iri}> ?p ?o .
            }}
        }}
    """)


# ===========================================================================
# BUDGET LINE SEGMENT (ADR-017)
# ===========================================================================

def get_segments_for_line(line_n: int) -> list[dict]:
    """All segments owned by BudgetLine_N, sorted by startYear ascending."""
    line_iri = og.NamedNode(f"{MRL}BudgetLine_{line_n}")
    pred     = og.NamedNode(f"{MRL}segmentOwner")
    quads    = store.store.quads_for_pattern(None, pred, line_iri, DATA_GRAPH)
    segs = []
    for q in quads:
        seg_iri = q.subject
        suffix = str(seg_iri.value).split("BudgetLineSegment_")[-1]
        if not suffix.isdigit():
            continue

        def gv(prop):
            qs = list(store.store.quads_for_pattern(
                seg_iri, og.NamedNode(f"{MRL}{prop}"), None, DATA_GRAPH))
            return str(qs[0].object.value) if qs else ""

        def gl(prop):
            v = gv(prop)
            return v.split("#")[-1] if "#" in v else v

        freq   = gl("segmentFrequency")
        amount = gv("segmentAmount")
        try:
            annual = to_annual(float(amount), freq) if amount else 0.0
        except (ValueError, TypeError):
            annual = 0.0
        segs.append({
            "n":              suffix,
            "iri":            str(seg_iri.value),
            "startYear":      gv("segmentStartYear"),
            "endYear":        gv("segmentEndYear"),
            "amount":         amount,
            "frequency":      freq,
            "frequencyLabel": FREQUENCY_LABELS.get(freq, freq),
            "annualAmount":   annual,
            "changeRate":     gv("segmentChangeRate"),
        })
    segs.sort(key=lambda s: int(s["startYear"]) if s["startYear"].isdigit() else 0)
    return segs


def _next_segment_n() -> int:
    type_node = og.NamedNode(f"{MRL}BudgetLineSegment")
    quads = store.store.quads_for_pattern(
        None, og.NamedNode(RDF_TYPE), type_node, DATA_GRAPH)
    nums = []
    for q in quads:
        suffix = str(q.subject.value).split("BudgetLineSegment_")[-1]
        if suffix.isdigit():
            nums.append(int(suffix))
    return max(nums, default=0) + 1


def delete_segments_for_line(line_n: int) -> None:
    """Wipe every segment whose mrl:segmentOwner is BudgetLine_N."""
    line_iri = f"{MRL}BudgetLine_{line_n}"
    store.update(f"""
        PREFIX mrl: <{MRL}>
        DELETE {{
            GRAPH <{DATA_GRAPH.value}> {{ ?seg ?p ?o . }}
        }}
        WHERE {{
            GRAPH <{DATA_GRAPH.value}> {{
                ?seg mrl:segmentOwner <{line_iri}> ;
                     ?p ?o .
            }}
        }}
    """)


def save_segment(n: int, line_n: int, start_year: int,
                 end_year: Optional[int], amount: float,
                 frequency: str, change_rate: float) -> None:
    """Write or overwrite BudgetLineSegment_N owned by BudgetLine_N."""
    seg_iri  = f"{MRL}BudgetLineSegment_{n}"
    line_iri = f"{MRL}BudgetLine_{line_n}"

    store.update(f"""
        DELETE WHERE {{
            GRAPH <{DATA_GRAPH.value}> {{
                <{seg_iri}> ?p ?o .
            }}
        }}
    """)

    end_line = (
        f' ;\n                    mrl:segmentEndYear "{int(end_year)}"^^xsd:integer'
        if end_year else ""
    )
    store.update(f"""
        PREFIX mrl:  <{MRL}>
        PREFIX mrlx: <{MRL_EXT}>
        PREFIX xsd:  <http://www.w3.org/2001/XMLSchema#>
        INSERT DATA {{
            GRAPH <{DATA_GRAPH.value}> {{
                <{seg_iri}> a mrl:BudgetLineSegment ;
                    mrl:segmentOwner <{line_iri}> ;
                    mrl:segmentStartYear "{int(start_year)}"^^xsd:integer ;
                    mrl:segmentAmount "{amount}"^^xsd:decimal ;
                    mrl:segmentFrequency mrlx:{frequency} ;
                    mrl:segmentChangeRate "{change_rate}"^^xsd:decimal{end_line} .
            }}
        }}
    """)


# ===========================================================================
# MIGRATION — legacy line-level fields → BudgetLineSegment (ADR-017 §3)
# ===========================================================================

def migrate_legacy_budget_lines_to_segments() -> int:
    """Idempotent migration. Returns the number of lines migrated this call.

    Guard 1 — any BudgetLineSegment already exists → return 0 (already done).
    Guard 2 — no BudgetLine has budgetLineAmount    → return 0 (nothing to do).

    For each legacy line with budgetLineAmount, create ONE BudgetLineSegment_N
    copying amount / frequency / change_rate / startYear (or current year) /
    endYear (or loanEndYear). The deprecated line-level properties are LEFT
    IN PLACE on the original line per ADR-017 §3. Called on every GET /budget;
    both guards are cheap quad-pattern queries so the steady-state cost is
    two store reads per page render.
    """
    seg_type = og.NamedNode(f"{MRL}BudgetLineSegment")
    if list(store.store.quads_for_pattern(
            None, og.NamedNode(RDF_TYPE), seg_type, DATA_GRAPH)):
        return 0

    amount_pred = og.NamedNode(f"{MRL}budgetLineAmount")
    legacy = list(store.store.quads_for_pattern(
        None, amount_pred, None, DATA_GRAPH))
    if not legacy:
        return 0

    from datetime import date
    current_year = date.today().year
    next_n = _next_segment_n()
    count  = 0

    for q in legacy:
        line_iri = q.subject
        line_n_s = str(line_iri.value).split("BudgetLine_")[-1]
        if not line_n_s.isdigit():
            continue
        line_n = int(line_n_s)

        def gv(prop):
            qs = list(store.store.quads_for_pattern(
                line_iri, og.NamedNode(f"{MRL}{prop}"), None, DATA_GRAPH))
            return str(qs[0].object.value) if qs else ""
        def gl(prop):
            v = gv(prop)
            return v.split("#")[-1] if "#" in v else v

        amount = gv("budgetLineAmount")
        if not amount:
            continue
        freq        = gl("budgetLineFrequency") or "FrequencyType_Monthly"
        change_rate = gv("annualChangeRate") or "0"
        start_year  = gv("budgetStartYear")
        end_year    = gv("budgetEndYear") or gv("loanEndYear")

        try:
            save_segment(
                n=next_n,
                line_n=line_n,
                start_year=int(start_year) if start_year else current_year,
                end_year=int(end_year) if end_year else None,
                amount=float(amount),
                frequency=freq,
                change_rate=float(change_rate),
            )
            next_n += 1
            count  += 1
        except (ValueError, TypeError):
            continue

    return count


# ===========================================================================
# BUDGET LINE — reads
# ===========================================================================

def get_all_budget_lines() -> list:
    """Return all BudgetLine instances with their segments + category.

    Each line also exposes a flattened first-segment view at the top level
    (amount, frequency, annualAmount, changeRate, startYear, endYear,
    loanEndYear) for backwards-compatible template rendering. Phase 3's
    multi-segment editor will consume the `segments` list directly. For
    lines that have not yet been migrated (no segments), the flattened
    view falls back to the deprecated line-level fields.
    """
    type_node = og.NamedNode(f"{MRL}BudgetLine")
    quads = store.store.quads_for_pattern(
        None, og.NamedNode(RDF_TYPE), type_node, DATA_GRAPH)

    cats_by_iri = {c["iri"]: c for c in get_all_categories()}
    lines = []

    for q in quads:
        iri = q.subject
        n_s = str(iri.value).split("BudgetLine_")[-1]
        if not n_s.isdigit():
            continue
        n = int(n_s)

        def gv(prop):
            qs = list(store.store.quads_for_pattern(
                iri, og.NamedNode(f"{MRL}{prop}"), None, DATA_GRAPH))
            return str(qs[0].object.value) if qs else ""
        def gl(prop):
            v = gv(prop)
            return v.split("#")[-1] if "#" in v else v

        cat_qs = list(store.store.quads_for_pattern(
            iri, og.NamedNode(f"{MRL}budgetCategory"), None, DATA_GRAPH))
        category = None
        if cat_qs:
            category = cats_by_iri.get(str(cat_qs[0].object.value))

        # Per-line currency + FX (1.0.5 — ADR-016 follow-on). When unset the
        # line is interpreted in the base currency and exchangeRate defaults
        # to 1.0 downstream (matches the accounts pattern).
        currency_local   = gl("budgetLineCurrency")
        exchange_rate    = gv("budgetLineExchangeRateToBase")
        exchange_rate_dt = gv("budgetLineExchangeRateDate")

        segments  = get_segments_for_line(n)
        line_type = gl("budgetLineType")

        if segments:
            first = segments[0]
            amount       = first["amount"]
            frequency    = first["frequency"]
            annual       = first["annualAmount"]
            change_rate  = first["changeRate"]
            start_year   = first["startYear"]
            end_year_val = first["endYear"]
        else:
            amount       = gv("budgetLineAmount")
            frequency    = gl("budgetLineFrequency")
            try:
                annual = to_annual(float(amount), frequency) if amount else 0.0
            except (ValueError, TypeError):
                annual = 0.0
            change_rate  = gv("annualChangeRate")
            start_year   = gv("budgetStartYear")
            end_year_val = gv("budgetEndYear")

        # Loan lines: surface the end year under both `loanEndYear` (legacy
        # template key) and the new segment-end model. Non-loan lines keep
        # endYear and a separate loanEndYear (legacy, typically empty).
        if line_type == "BudgetLineType_Loan":
            loan_end         = end_year_val
            end_year_display = ""
        else:
            loan_end         = gv("loanEndYear")
            end_year_display = end_year_val

        lines.append({
            "n":             str(n),
            "iri":           str(iri.value),
            "name":          gv("budgetLineName"),
            "lineType":      line_type,
            # ADR-017 category
            "categoryN":     category["n"]    if category else "",
            "categoryName":  category["name"] if category else "",
            # ADR-017 segments list (for Phase 3 multi-segment UI)
            "segments":      segments,
            # Per-line currency + FX (1.0.5 — ADR-016 follow-on)
            "currency":         currency_local,
            "currencyCode":     _currency_code(currency_local)   if currency_local else "",
            "currencySymbol":   _currency_symbol(currency_local) if currency_local else "",
            "exchangeRate":     exchange_rate,
            "exchangeRateDate": exchange_rate_dt,
            # Backwards-compat flattened first-segment view
            "amount":         amount,
            "frequency":      frequency,
            "frequencyLabel": FREQUENCY_LABELS.get(frequency, frequency),
            "annualAmount":   annual,
            "changeRate":     change_rate,
            "startYear":      start_year,
            "endYear":        end_year_display,
            "loanEndYear":    loan_end,
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

        owner_qs = list(store.store.quads_for_pattern(
            c_iri, og.NamedNode(f"{MRL}contributionOwner"), None, DATA_GRAPH))
        owner_label  = ""
        account_name = ""
        if owner_qs:
            owner_iri    = owner_qs[0].object
            owner_label  = str(owner_iri.value).split("#")[-1]
            name_qs      = list(store.store.quads_for_pattern(
                owner_iri, og.NamedNode(f"{MRL}accountName"), None, DATA_GRAPH))
            account_name = str(name_qs[0].object.value) if name_qs else owner_label

        freq       = gl("contributionFrequency")
        multiplier = FREQUENCY_MULTIPLIERS.get(freq, 12)
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
        annual          = round(amount * multiplier, 2)
        employer_annual = round(employer_amount * multiplier, 2)

        results.append({
            "accountLabel":   owner_label,
            "accountName":    account_name,
            "amount":         amount_str,
            "employerAmount": employer_str,
            "frequency":      freq,
            "frequencyLabel": FREQUENCY_LABELS.get(freq, freq),
            "annualAmount":   annual,
            "employerAnnual": employer_annual,
            "fromPayroll":    gv("contributionFromPayroll") == "true",
            "startYear":      gv("contributionStartYear"),
            "endYear":        gv("contributionEndYear"),
            "growthRate":     gv("contributionGrowthRate"),
            "note":           gv("contributionNote"),
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


def _find_active_segment_dict(segments: list, year: int) -> dict | None:
    """Return the segment dict (as exposed by get_segments_for_line()) whose
    [startYear, endYear] window contains `year`, or None if no segment is
    active (line contributes zero — gap, or before/after the line's life).
    Mirrors `find_active_segment()` in projection.py but reads the dict
    shape produced by budget.py's segment loader.
    """
    for seg in segments:
        start = _int_or_none(seg.get("startYear"))
        end   = _int_or_none(seg.get("endYear"))
        if start is not None and year < start: continue
        if end   is not None and year > end:   continue
        return seg
    return None


def compute_annual_spending_series(lines: list, current_year: int, end_year: int) -> dict:
    """Per-year spending arrays in today's pounds, broken out by line type.

    ADR-017: walks each line's `segments` list. The active segment for the
    year provides the amount and change_rate; lines with no active segment
    in a given year contribute zero (gaps render naturally as £0 bands on
    the stacked chart). Growth exponent is the projection year offset `i`
    — matching the deterministic engine in projection.py, so the chart and
    the projection page agree on the same numbers.

    Real-terms only — base inflation is NOT applied here (the budget page
    is conceptually a real-terms plan; the projection layers inflation on
    top).
    """
    years         = list(range(current_year, end_year + 1))
    n             = len(years)
    mandatory     = [0.0] * n
    discretionary = [0.0] * n
    loans         = [0.0] * n

    for line in lines:
        line_type = line.get("lineType", "")
        segments  = line.get("segments") or []
        fx        = _line_fx(line)
        for i, year in enumerate(years):
            seg = _find_active_segment_dict(segments, year)
            if seg is None:
                continue
            annual      = _float_or_zero(seg.get("annualAmount")) * fx
            change_rate = _float_or_zero(seg.get("changeRate"))
            amount      = annual * ((1 + change_rate / 100) ** i)
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
    inflation_rate: float = 0.0,
) -> list:
    """Per-year contributions array.

    Mirrors the engine's logic in `projection.py`:
      - Default active window: current_year … retirement_year (inclusive)
      - Per-contribution growth: base × (1 + g/100) ** years_active, where
        years_active is zero in the first active year

    `inflation_rate` defaults to 0 (real-terms view — today's £). Passing a
    positive value adds an additional `(1 + inflation/100)^(year -
    current_year)` lift on top of the per-contribution growth, yielding
    the nominal view. (Contributions inflate — they are future cash
    commitments the user intends to scale with inflation unless they
    explicitly set a different growth rate.)
    """
    years = list(range(current_year, end_year + 1))
    series = [0.0] * len(years)
    default_end = retirement_year if retirement_year is not None else end_year

    for c in contributions:
        # Payroll/salary-sacrifice contributions (ADR-015 v1.2) credit the
        # account but never reduce net cashflow, so they are excluded from this
        # cashflow-impacting series — mirroring the engine's year_contribution_spending.
        if c.get("fromPayroll"):
            continue
        annual = _float_or_zero(c.get("annualAmount"))
        g_rate = _float_or_zero(c.get("growthRate"))
        start  = _int_or_none(c.get("startYear")) or current_year
        end    = _int_or_none(c.get("endYear"))   or default_end

        for i, year in enumerate(years):
            if year < start or year > end:
                continue
            years_active = year - start
            value        = annual * ((1 + g_rate / 100) ** years_active)
            if inflation_rate:
                value *= (1 + inflation_rate / 100) ** i
            series[i] += value

    return [round(x, 0) for x in series]


def _line_fx(line: dict) -> float:
    """Return the line's exchangeRateToBase, defaulting to 1.0 when absent
    or invalid. Per-line currency + FX is the 1.0.5 addition (ADR-016
    follow-on). Same-currency lines (currencyCode == base) carry no FX
    triple and read as 1.0; cross-currency lines persist the rate."""
    raw = line.get("exchangeRate") or ""
    try:
        return float(raw) if raw else 1.0
    except (TypeError, ValueError):
        return 1.0


def _sum_lines_per_year(lines: list, years: list, inflation_rate: float = 0.0) -> list:
    """Sum the active segment's amount across all `lines` for each year.

    `inflation_rate` defaults to 0 (real-terms view — today's £). Passing a
    positive value adds that inflation lift to non-loan lines per year,
    yielding the nominal view. **Loans are kept fixed-nominal** (no
    inflation lift) so the chart agrees with the projection engine, which
    treats loan repayments as fixed nominal commitments.

    Lines in a non-base currency are pre-multiplied by their stored
    mrl:budgetLineExchangeRateToBase so the chart rolls up in base
    currency — mirrors the accounts and income FX-conversion at load time.
    """
    result = [0.0] * len(years)
    for line in lines:
        segments = line.get("segments") or []
        is_loan  = line.get("lineType") == "BudgetLineType_Loan"
        fx       = _line_fx(line)
        for i, year in enumerate(years):
            seg = _find_active_segment_dict(segments, year)
            if seg is None:
                continue
            annual      = _float_or_zero(seg.get("annualAmount")) * fx
            change_rate = _float_or_zero(seg.get("changeRate"))
            rate = change_rate if is_loan else (inflation_rate + change_rate)
            result[i] += annual * ((1 + rate / 100) ** i)
    return [round(x, 0) for x in result]


def compute_annual_spending_by_category(
    lines: list,
    contributions: list,
    current_year: int,
    end_year: int,
    retirement_year: int | None,
    inflation_rate: float = 0.0,
) -> dict:
    """Per-category per-year spending series for the by-category chart (ADR-017).

    Groups:
      - one per user-defined `mrl:BudgetCategory` actually referenced by a
        line, sorted alphabetically;
      - "Uncategorised" (if any line lacks a category), rendered in neutral
        gray and sorted to the end of user groups;
      - "Account contributions" (always last when any contribution exists),
        the synthetic system group derived from mrl:AccountContribution
        instances and pinned to teal.

    Each group entry is {name, values, fill, border, is_system}.
    """
    years = list(range(current_year, end_year + 1))

    by_cat: dict[str, list] = {}
    for line in lines:
        cat_name = (line.get("categoryName") or "").strip() or UNCATEGORISED_LABEL
        by_cat.setdefault(cat_name, []).append(line)

    groups = []
    user_cats = sorted(k for k in by_cat if k != UNCATEGORISED_LABEL)
    for name in user_cats:
        fill, border = _category_palette(name)
        groups.append({
            "name":      name,
            "values":    _sum_lines_per_year(by_cat[name], years, inflation_rate),
            "fill":      fill,
            "border":    border,
            "is_system": False,
        })
    if UNCATEGORISED_LABEL in by_cat:
        fill, border = _category_palette(UNCATEGORISED_LABEL)
        groups.append({
            "name":      UNCATEGORISED_LABEL,
            "values":    _sum_lines_per_year(by_cat[UNCATEGORISED_LABEL], years, inflation_rate),
            "fill":      fill,
            "border":    border,
            "is_system": False,
        })

    contrib_series = compute_annual_contributions_series(
        contributions, current_year, end_year, retirement_year, inflation_rate)
    if any(v > 0 for v in contrib_series):
        fill, border = _category_palette(ACCOUNT_CONTRIBUTIONS_LABEL)
        groups.append({
            "name":      ACCOUNT_CONTRIBUTIONS_LABEL,
            "values":    contrib_series,
            "fill":      fill,
            "border":    border,
            "is_system": True,
        })

    total = [sum(g["values"][i] for g in groups) for i in range(len(years))]
    return {"years": years, "groups": groups, "total": total}


def compute_annual_spending_by_line(
    lines: list,
    contributions: list,
    current_year: int,
    end_year: int,
    retirement_year: int | None,
    inflation_rate: float = 0.0,
) -> dict:
    """Per-line per-year series for the by-line chart toggle.

    Each budget line becomes its own group; multi-segment lines still
    collapse to a single continuous series (gaps render as £0). Account
    contributions stay aggregated into one synthetic group, matching the
    by-category view.
    """
    years = list(range(current_year, end_year + 1))

    groups = []
    for line in sorted(lines, key=lambda l: (l.get("name") or "").lower()):
        nm = line.get("name") or f"Line {line.get('n','?')}"
        fill, border = _category_palette(nm)
        groups.append({
            "name":      nm,
            "values":    _sum_lines_per_year([line], years, inflation_rate),
            "fill":      fill,
            "border":    border,
            "is_system": False,
        })

    contrib_series = compute_annual_contributions_series(
        contributions, current_year, end_year, retirement_year, inflation_rate)
    if any(v > 0 for v in contrib_series):
        fill, border = _category_palette(ACCOUNT_CONTRIBUTIONS_LABEL)
        groups.append({
            "name":      ACCOUNT_CONTRIBUTIONS_LABEL,
            "values":    contrib_series,
            "fill":      fill,
            "border":    border,
            "is_system": True,
        })

    total = [sum(g["values"][i] for g in groups) for i in range(len(years))]
    return {"years": years, "groups": groups, "total": total}


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


# ===========================================================================
# BUDGET LINE — writes
# ===========================================================================

def save_budget_line_segments(
    n: int,
    name: str,
    line_type: str,
    category_name: str,
    segments: list,
    currency_local: str = "",
    exchange_rate: float = 1.0,
    exchange_rate_date: str = "",
) -> None:
    """Write or overwrite BudgetLine_N together with all its segments.

    `segments` is a list of dicts: {start_year, end_year, amount, frequency,
    change_rate}. Empty `end_year` (None) means open-ended. Empty
    `category_name` leaves the line uncategorised; a non-empty name resolves
    to an existing BudgetCategory by case-insensitive match, creating one on
    the fly if necessary.

    `currency_local` is the Currency individual local name (e.g. "GBP", "USD").
    Falls back to the person's base currency when blank. `exchange_rate` is
    mrl:budgetLineExchangeRateToBase ("1 unit of line currency = N units of
    base currency") — only persisted when it differs from 1.0 (line currency
    != base). Mirrors the accounts.py / income.py FX pattern (ADR-016).
    """
    if not segments:
        raise ValueError("A budget line needs at least one segment.")

    line_iri   = f"{MRL}BudgetLine_{n}"
    person_iri = f"{MRL}Person_1"

    if not currency_local:
        currency_local = (get_base_currency() or {}).get("local", "")
    if not exchange_rate_date:
        exchange_rate_date = date.today().isoformat()

    category_iri = None
    if category_name and category_name.strip():
        try:
            cat = get_category_by_name(category_name) or create_category(category_name)
            category_iri = cat["iri"]
        except ValueError:
            # Reserved name — silently drop category rather than fail the save
            category_iri = None

    # Wipe existing line-level triples + segments
    store.update(f"""
        DELETE WHERE {{
            GRAPH <{DATA_GRAPH.value}> {{
                <{line_iri}> ?p ?o .
            }}
        }}
    """)
    delete_segments_for_line(n)

    cat_clause = (
        f' ;\n                    mrl:budgetCategory <{category_iri}>'
        if category_iri else ""
    )
    currency_clause = (
        f' ;\n                    mrl:budgetLineCurrency mrl:{currency_local}'
        if currency_local else ""
    )
    store.update(f"""
        PREFIX mrl:  <{MRL}>
        PREFIX mrlx: <{MRL_EXT}>
        PREFIX xsd:  <http://www.w3.org/2001/XMLSchema#>
        INSERT DATA {{
            GRAPH <{DATA_GRAPH.value}> {{
                <{line_iri}> a mrl:BudgetLine ;
                    mrl:budgetLineName "{_escape(name)}" ;
                    mrl:budgetLineType mrlx:{line_type} ;
                    mrl:budgetOwner <{person_iri}>{cat_clause}{currency_clause} .
            }}
        }}
    """)

    # Persist FX rate only when it actually differs from 1.0 — matches the
    # accounts/income convention so same-currency rows stay clean in the store.
    if exchange_rate and float(exchange_rate) != 1.0:
        store.update(f"""
            PREFIX mrl: <{MRL}>
            PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
            INSERT DATA {{
                GRAPH <{DATA_GRAPH.value}> {{
                    <{line_iri}> mrl:budgetLineExchangeRateToBase "{exchange_rate}"^^xsd:decimal ;
                                 mrl:budgetLineExchangeRateDate   "{exchange_rate_date}"^^xsd:date .
                }}
            }}
        """)

    next_n = _next_segment_n()
    for seg in segments:
        save_segment(
            n=next_n,
            line_n=n,
            start_year=int(seg["start_year"]),
            end_year=int(seg["end_year"]) if seg.get("end_year") else None,
            amount=float(seg["amount"]),
            frequency=seg["frequency"] or "FrequencyType_Monthly",
            change_rate=float(seg.get("change_rate") or 0),
        )
        next_n += 1


def _segments_from_form(
    start_years: list,
    end_years: list,
    amounts: list,
    frequencies: list,
    change_rates: list,
) -> list:
    """Zip together five parallel form-field lists into a list of segment
    dicts ready for save_budget_line_segments(). Empty end_year strings
    become None (open-ended). Raises ValueError if the lists differ in
    length.
    """
    n = len(start_years)
    if not (len(end_years) == n == len(amounts) == len(frequencies) == len(change_rates)):
        raise ValueError("Segment form field arrays are different lengths.")
    out = []
    for i in range(n):
        end_raw = end_years[i]
        if isinstance(end_raw, str):
            end_raw = end_raw.strip() or None
        out.append({
            "start_year":  start_years[i],
            "end_year":    end_raw,
            "amount":      amounts[i],
            "frequency":   frequencies[i],
            "change_rate": change_rates[i],
        })
    return out


def _update_budget_line_rate(line_iri_str: str, rate_to_base: float, rate_date: str) -> None:
    """Overwrite only the two FX-rate properties on a single budget line,
    leaving every other triple untouched. Mirrors _update_account_rate /
    _update_income_rate (ADR-016)."""
    store.update(f"""
        PREFIX mrl: <{MRL}>
        DELETE WHERE {{
            GRAPH <{DATA_GRAPH.value}> {{
                <{line_iri_str}> mrl:budgetLineExchangeRateToBase ?r .
            }}
        }}
    """)
    store.update(f"""
        PREFIX mrl: <{MRL}>
        DELETE WHERE {{
            GRAPH <{DATA_GRAPH.value}> {{
                <{line_iri_str}> mrl:budgetLineExchangeRateDate ?d .
            }}
        }}
    """)
    store.update(f"""
        PREFIX mrl: <{MRL}>
        PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
        INSERT DATA {{
            GRAPH <{DATA_GRAPH.value}> {{
                <{line_iri_str}> mrl:budgetLineExchangeRateToBase "{rate_to_base}"^^xsd:decimal ;
                                 mrl:budgetLineExchangeRateDate   "{rate_date}"^^xsd:date .
            }}
        }}
    """)


def _page_context(request, lines, edit_line=None, **kwargs):
    contributions = get_all_contributions_for_budget()
    categories    = get_all_categories()
    current_year, end_year, retirement_year = _horizon()

    # Inflation rate from projection settings — used to precompute the
    # "with inflation" (nominal) variants of the chart series. Default is
    # the same fallback the projection engine uses (2.5%) when no settings
    # row exists yet.
    try:
        from src.api.routes.projection import get_projection_settings
        inflation_rate = float(get_projection_settings().get("inflation_rate", 2.5) or 2.5)
    except Exception:
        inflation_rate = 2.5

    spending_series      = compute_annual_spending_series(lines, current_year, end_year)
    contributions_series = compute_annual_contributions_series(
        contributions, current_year, end_year, retirement_year)

    # ADR-017: precompute four chart shapes — {Category, Line} × {Real, Nominal}.
    # Real-terms = today's £, no inflation lift; matches the deterministic
    # engine's interpretation of the user's segment amounts. Nominal applies
    # the projection inflation rate to non-loan lines and to contributions;
    # loan-type lines stay fixed-nominal (matching projection.py loan
    # treatment) so the chart agrees with the projection page.
    chart_series = {
        "by_category": {
            "real":    compute_annual_spending_by_category(
                lines, contributions, current_year, end_year, retirement_year, 0.0),
            "nominal": compute_annual_spending_by_category(
                lines, contributions, current_year, end_year, retirement_year, inflation_rate),
        },
        "by_line": {
            "real":    compute_annual_spending_by_line(
                lines, contributions, current_year, end_year, retirement_year, 0.0),
            "nominal": compute_annual_spending_by_line(
                lines, contributions, current_year, end_year, retirement_year, inflation_rate),
        },
    }

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
        "app_name":             settings.app_name,
        "active":               "budget",
        "lines":                lines,
        "series":               series,
        "chart_series":         chart_series,
        "inflation_rate":       inflation_rate,
        "metrics":              metrics,
        "retirement_year":      retirement_year,
        "current_year":         current_year,
        "end_year":             end_year,
        "frequency_options":    FREQUENCY_LABELS,
        "edit_line":            edit_line,
        "contributions":        contributions,
        "categories":           categories,
        "category_suggestions": CATEGORY_SUGGESTIONS,
        # Per-line currency + FX (1.0.5 — ADR-016 follow-on)
        "currencies":           get_currencies(),
        "base_currency":        get_base_currency(),
        "today":                date.today().isoformat(),
        **kwargs,
    }


# ===========================================================================
# ROUTES — budget lines
# ===========================================================================

@router.get("/budget", response_class=HTMLResponse)
async def budget_page(request: Request, added: int = 0, saved: int = 0):
    migrate_legacy_budget_lines_to_segments()
    lines = get_all_budget_lines()
    # `added=1` / `saved=1` arrive via post/redirect/get after adding or editing
    # a budget line, so the form is freshly blank and the banner confirms the
    # save; the persisted line (incl. any new stages) is visible in the list.
    return templates.TemplateResponse(
        request=request,
        name="budget.html",
        context=_page_context(request, lines, added=bool(added), saved=bool(saved)),
    )


@router.post("/budget/refresh-rates", response_class=HTMLResponse)
async def refresh_budget_exchange_rates(request: Request):
    """Fetch today's live rates and update every cross-currency budget line's
    FX rate. Mirrors POST /accounts/refresh-rates and POST /income/refresh-rates
    (ADR-016). Lines already in the base currency get 1.0; lines whose currency
    has no live rate are listed under `rate_refresh_skipped`."""
    migrate_legacy_budget_lines_to_segments()

    base       = get_base_currency()
    base_code  = (base or {}).get("code", "")
    if not base_code:
        return templates.TemplateResponse(
            request=request, name="budget.html",
            context=_page_context(
                request, get_all_budget_lines(),
                rate_refresh_error="Set your base currency on the Profile page "
                                   "before refreshing exchange rates.",
            ),
        )

    try:
        data  = fetch_rates(base_code)
        rates = data["rates"]
    except FxError as exc:
        return templates.TemplateResponse(
            request=request, name="budget.html",
            context=_page_context(
                request, get_all_budget_lines(),
                rate_refresh_error=f"Live rates unavailable — {exc}. "
                                   "Existing rates were left unchanged.",
            ),
        )

    today   = date.today().isoformat()
    updated = 0
    skipped = []
    for line in get_all_budget_lines():
        code = line.get("currencyCode") or base_code
        if code == base_code:
            # Base-currency lines don't need a rate; leave any stray triple alone.
            continue
        if code in rates and rates[code]:
            rate_to_base = round(1.0 / float(rates[code]), 6)
            _update_budget_line_rate(line["iri"], rate_to_base, today)
            updated += 1
        else:
            skipped.append(code)

    return templates.TemplateResponse(
        request=request, name="budget.html",
        context=_page_context(
            request, get_all_budget_lines(),
            rate_refresh_count=updated,
            rate_refresh_base=base_code,
            rate_refresh_as_of=data.get("as_of", ""),
            rate_refresh_provider=data.get("provider", ""),
            rate_refresh_skipped=sorted(set(skipped)),
        ),
    )


@router.post("/budget", response_class=HTMLResponse)
async def add_budget_line(
    request: Request,
    budgetLineName: str = Form(...),
    budgetLineType: str = Form(...),
    budgetCategoryName: str = Form(""),
    segmentStartYear: list[int]   = Form(...),
    segmentEndYear:   list[str]   = Form(...),
    segmentAmount:    list[float] = Form(...),
    segmentFrequency: list[str]   = Form(...),
    segmentChangeRate: list[float] = Form(...),
    budgetLineCurrency:           str   = Form(""),
    budgetLineExchangeRateToBase: float = Form(1.0),
    budgetLineExchangeRateDate:   str   = Form(""),
):
    existing = get_all_budget_lines()
    next_n   = max([int(l["n"]) for l in existing if l["n"].isdigit()], default=0) + 1
    segments = _segments_from_form(
        segmentStartYear, segmentEndYear, segmentAmount,
        segmentFrequency, segmentChangeRate,
    )
    save_budget_line_segments(
        next_n, budgetLineName, budgetLineType,
        budgetCategoryName, segments,
        currency_local=budgetLineCurrency,
        exchange_rate=budgetLineExchangeRateToBase,
        exchange_rate_date=budgetLineExchangeRateDate,
    )
    # Post/redirect/get back to a blank add form so the fields (including any
    # extra stages added before saving) reset for the next line and `?added=1`
    # surfaces a clear "saved" confirmation. Editing keeps its in-place,
    # stay-populated behaviour (see save_edit_budget_line).
    return RedirectResponse(url="/budget?added=1", status_code=303)


@router.get("/budget/{n}/edit", response_class=HTMLResponse)
async def edit_budget_line_form(request: Request, n: int):
    lines     = get_all_budget_lines()
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
    budgetLineType: str = Form(...),
    budgetCategoryName: str = Form(""),
    segmentStartYear: list[int]   = Form(...),
    segmentEndYear:   list[str]   = Form(...),
    segmentAmount:    list[float] = Form(...),
    segmentFrequency: list[str]   = Form(...),
    segmentChangeRate: list[float] = Form(...),
    budgetLineCurrency:           str   = Form(""),
    budgetLineExchangeRateToBase: float = Form(1.0),
    budgetLineExchangeRateDate:   str   = Form(""),
):
    segments = _segments_from_form(
        segmentStartYear, segmentEndYear, segmentAmount,
        segmentFrequency, segmentChangeRate,
    )
    save_budget_line_segments(
        n, budgetLineName, budgetLineType,
        budgetCategoryName, segments,
        currency_local=budgetLineCurrency,
        exchange_rate=budgetLineExchangeRateToBase,
        exchange_rate_date=budgetLineExchangeRateDate,
    )
    # Post/redirect/get back to the list with a blank add form + "saved" banner.
    # The persisted line — including any stage just added — is visible in the
    # list above, so the save is confirmed without leaving a populated form that
    # looks un-reset. (Supersedes the earlier stay-in-edit-mode behaviour.)
    return RedirectResponse(url="/budget?saved=1", status_code=303)


@router.post("/budget/{n}/delete", response_class=HTMLResponse)
async def delete_budget_line(request: Request, n: int):
    line_iri = f"{MRL}BudgetLine_{n}"
    delete_segments_for_line(n)
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


# ===========================================================================
# ROUTES — categories (ADR-017)
# ===========================================================================

@router.post("/budget/categories", response_class=HTMLResponse)
async def add_category(request: Request, categoryName: str = Form(...)):
    """Create a new BudgetCategory and redirect back to /budget."""
    try:
        create_category(categoryName)
        return RedirectResponse(url="/budget", status_code=303)
    except ValueError as e:
        lines = get_all_budget_lines()
        return templates.TemplateResponse(
            request=request,
            name="budget.html",
            context=_page_context(request, lines, category_error=str(e)),
        )


@router.post("/budget/categories/{n}/rename", response_class=HTMLResponse)
async def rename_category_route(request: Request, n: int, categoryName: str = Form(...)):
    try:
        rename_category(n, categoryName)
        return RedirectResponse(url="/budget", status_code=303)
    except ValueError as e:
        lines = get_all_budget_lines()
        return templates.TemplateResponse(
            request=request,
            name="budget.html",
            context=_page_context(request, lines, category_error=str(e)),
        )


@router.post("/budget/categories/{n}/delete", response_class=HTMLResponse)
async def delete_category_route(request: Request, n: int):
    try:
        delete_category(n)
        return RedirectResponse(url="/budget", status_code=303)
    except ValueError as e:
        lines = get_all_budget_lines()
        return templates.TemplateResponse(
            request=request,
            name="budget.html",
            context=_page_context(request, lines, category_error=str(e)),
        )
