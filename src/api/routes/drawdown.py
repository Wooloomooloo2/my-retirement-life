"""Drawdown Strategy page.

A single view of every account's drawdown ordering and tax treatment, with a
non-persisting "sandbox" preview: the user can drag accounts to reorder the
waterfall, edit tax treatments/rates inline, and click **Recompute** to see the
combined effect on a withdrawals-over-time chart — all without writing to the
store. **Save strategy** commits the changes back to the accounts + projection
settings.

The engine does all the maths; this module just:
  - GET  /drawdown-strategy        renders the page
  - POST /api/drawdown/preview     runs run_projection() with in-memory overrides (NO write)
  - POST /api/drawdown/save        persists ordering + tax + strategy, then signals a redirect

Every drawdown/tax property already exists in the ontology and is read by
load_all_accounts() / written here via a targeted update that touches only the
five relevant predicates (modelled on accounts._update_account_rate).
"""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

from src.config import settings
from src.api.templates import templates
from src.store.graph import store, MRL, DATA_GRAPH
from src.api.routes.projection import (
    run_projection,
    get_projection_settings,
    save_projection_settings,
    load_all_accounts,
    migrate_drawdown_max_age_to_mandatory,
)

router = APIRouter()

# mrlx: individuals (tax-treatment concepts) live in the ext namespace.
MRL_EXT = "https://myretirementlife.app/ontology/ext#"

# The four tax-treatment options — values match the <option> values on the
# Accounts form (accounts.html) and the local names stored by load_all_accounts
# (which keep the "TaxTreatment_" prefix). Kept here as the single source for
# this page's dropdowns.
TAX_TREATMENT_OPTIONS = [
    {"value": "",
     "label": "— not set —"},
    {"value": "TaxTreatment_PreTaxWholeWithdrawal",
     "label": "Pre-tax — whole withdrawal taxable (SIPP, 401(k), pension pot)"},
    {"value": "TaxTreatment_PostTaxGainsOnly",
     "label": "Post-tax — gains only taxable (GIA, general brokerage)"},
    {"value": "TaxTreatment_PostTaxTaxFreeWithdrawal",
     "label": "Post-tax — withdrawals tax-free (Cash/S&S ISA, Roth IRA)"},
    {"value": "TaxTreatment_TaxFree",
     "label": "Tax-free — no tax at any stage (Premium Bonds, NS&I)"},
]


# ---------------------------------------------------------------------------
# Persistence — targeted per-account update (mirrors _update_account_rate)
# ---------------------------------------------------------------------------

def update_account_drawdown(
    label: str,
    priority: int,
    ratio: float,
    tax_treatment: str,
    effective_rate: float,   # decimal, e.g. 0.20
    annual_tax_free: float,
) -> None:
    """Overwrite ONLY the five drawdown/tax predicates on one account, leaving
    balance, name, eligibility and every other triple untouched.

    Works for both CashAccount_N and InvestmentAccount_N — these predicates are
    declared on the mrl:Account superclass.
    """
    iri = f"{MRL}{label}"

    for pred in ("drawdownPriority", "drawdownRatio", "taxTreatment",
                 "effectiveWithdrawalTaxRate", "annualTaxFreeWithdrawal"):
        store.update(f"""
            PREFIX mrl: <{MRL}>
            DELETE WHERE {{
                GRAPH <{DATA_GRAPH.value}> {{ <{iri}> mrl:{pred} ?o . }}
            }}
        """)

    triples = (
        f'<{iri}> mrl:drawdownPriority "{int(priority)}"^^xsd:integer ;\n'
        f'        mrl:drawdownRatio     "{float(ratio)}"^^xsd:decimal'
    )
    if tax_treatment:
        triples += f' ;\n        mrl:taxTreatment mrlx:{tax_treatment}'
    if effective_rate and effective_rate > 0:
        triples += f' ;\n        mrl:effectiveWithdrawalTaxRate "{effective_rate}"^^xsd:decimal'
    if annual_tax_free and annual_tax_free > 0:
        triples += f' ;\n        mrl:annualTaxFreeWithdrawal "{annual_tax_free}"^^xsd:decimal'
    triples += " ."

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
# Shared payload parsing — the preview and save bodies have the same shape
# ---------------------------------------------------------------------------

def _parse_overrides(body: dict) -> tuple[str | None, dict, list]:
    """Turn the JSON body into (strategy, account_overrides, rows).

    `account_overrides` is keyed by account label for run_projection().
    `rows` is the cleaned per-account list (with decimal effective rate) used by
    the save path. The UI sends `effective_rate` as a PERCENT; we convert to the
    decimal the engine and store expect (÷100), matching accounts.py.
    Priority is taken verbatim from the payload — the UI sets it from the drag
    order so preview and save agree exactly.
    """
    strategy = body.get("strategy") or None
    overrides: dict = {}
    rows: list = []

    for a in body.get("accounts", []):
        label = a.get("label")
        if not label:
            continue
        priority   = int(a.get("priority", 999))
        ratio      = float(a.get("ratio", 1.0) or 0.0)
        treatment  = (a.get("tax_treatment") or "").strip()
        eff_rate   = float(a.get("effective_rate", 0.0) or 0.0) / 100.0
        tax_free   = float(a.get("annual_tax_free", 0.0) or 0.0)

        overrides[label] = {
            "drawdown_priority":             priority,
            "drawdown_ratio":                ratio,
            "tax_treatment":                 treatment,
            "effective_withdrawal_tax_rate": eff_rate,
            "annual_tax_free_withdrawal":    tax_free,
        }
        rows.append({
            "label": label, "priority": priority, "ratio": ratio,
            "tax_treatment": treatment, "effective_rate": eff_rate,
            "annual_tax_free": tax_free,
        })

    return strategy, overrides, rows


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/drawdown-strategy", response_class=HTMLResponse)
async def drawdown_strategy_page(request: Request, saved: int = 0):
    migrate_drawdown_max_age_to_mandatory()  # ADR-018: legacy cutoff → mandatory age
    all_accounts  = load_all_accounts()
    proj_settings = get_projection_settings()

    return templates.TemplateResponse(
        request=request,
        name="drawdown_strategy.html",
        context={
            "app_name":              settings.app_name,
            "active":                "drawdown_strategy",
            "accounts":              all_accounts,
            "current_strategy":      proj_settings["drawdown_strategy"],
            "tax_treatment_options": TAX_TREATMENT_OPTIONS,
            "saved":                 bool(saved),
        },
    )


@router.post("/api/drawdown/preview")
async def drawdown_preview(request: Request):
    """Run the projection with in-memory overrides and return chart data. No write."""
    body = await request.json()
    strategy, overrides, _rows = _parse_overrides(body)

    proj_settings = dict(get_projection_settings())
    if strategy:
        proj_settings["drawdown_strategy"] = strategy

    projection = run_projection(
        proj_settings["inflation_rate"],
        proj_settings,
        account_overrides=overrides,
    )
    if projection is None:
        return JSONResponse(
            {"ok": False, "error": "Add a profile and at least one account to model a drawdown strategy."},
            status_code=400,
        )

    years = [y["year"] for y in projection["years"]]
    return {
        "ok":                  True,
        "years":               years,
        "account_withdrawals": projection["account_withdrawals"],
        "account_names":       projection["account_names"],
        "account_classes":     projection["account_classes"],
        "tax_per_year":        [y["tax_paid"] for y in projection["years"]],
        "retirement_year":     projection["retirement_year"],
        "runs_out_year":       projection["runs_out_year"],
        "total_tax_paid":      projection["total_tax_paid"],
        "final_balance":       projection["final_balance"],
        "confidence":          projection["confidence"],
        "confidence_label":    projection["confidence_label"],
        "confidence_message":  projection["confidence_message"],
        "total_unfunded":      projection["total_unfunded"],
        "first_unfunded_year": projection["first_unfunded_year"],
    }


@router.post("/api/drawdown/save")
async def drawdown_save(request: Request):
    """Persist ordering + tax treatments + strategy, then tell the client where
    to redirect (PRG: GET /drawdown-strategy?saved=1 shows the saved banner)."""
    body = await request.json()
    strategy, _overrides, rows = _parse_overrides(body)

    # Strategy → projection settings, preserving every other setting.
    ps = get_projection_settings()
    save_projection_settings(
        inflation_rate            = ps["inflation_rate"],
        mc_profile                = ps["mc_profile"],
        drawdown_strategy         = strategy or ps["drawdown_strategy"],
        surplus_strategy          = ps["surplus_strategy"],
        spending_account_label    = ps["spending_account_label"],
        surplus_account_label     = ps["surplus_account_label"],
        annual_personal_allowance = ps["annual_personal_allowance"],
        residence_income_tax_rate = ps["residence_income_tax_rate"],
        emergency_fund_account_label = ps["emergency_fund_account_label"],
        emergency_fund_months        = ps["emergency_fund_months"],
    )

    # Per-account ordering + tax (effective_rate already decimal from _parse).
    for row in rows:
        update_account_drawdown(
            label           = row["label"],
            priority        = row["priority"],
            ratio           = row["ratio"],
            tax_treatment   = row["tax_treatment"],
            effective_rate  = row["effective_rate"],
            annual_tax_free = row["annual_tax_free"],
        )

    return {"ok": True, "redirect": "/drawdown-strategy?saved=1"}
