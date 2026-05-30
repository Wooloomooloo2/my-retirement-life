"""
Settings routes — app configuration, data export and import.

GET  /settings         — settings page
GET  /settings/export  — download all user data as JSON
POST /settings/import  — restore data from a JSON backup file
POST /settings/inflation — update the default inflation rate

Changes (ADR-011, ADR-012, ADR-013):
  export_all_data() now includes drawdown eligibility, drawdown ordering,
  tax treatment, life-event account routing, and full projection settings.
  restore_all_data() restores all new fields; old v0.2 backups restore cleanly
  (missing optional fields are silently skipped).
  APP_VERSION bumped to 0.3.0.

Changes (asset model / ADR-015 v1.1+v1.2):
  export_all_data() / restore_all_data() now also cover PhysicalAsset instances
  (Property / Vehicle / Collectible) and the employer-contribution amount and
  payroll/salary-sacrifice flag on contributions. Previously assets were not
  exported, so restoring a scenario/backup (which wipes the data graph first)
  silently deleted them. APP_VERSION bumped to 0.3.1.
"""
import json
from datetime import date, datetime
from fastapi import APIRouter, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse, Response
from src.api.templates import templates
from typing import Optional
import pyoxigraph as og

from src.config import settings as app_settings
from src.store.graph import store, MRL, DATA_GRAPH

router = APIRouter()

RDF_TYPE       = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
MRL_EXT        = "https://myretirementlife.app/ontology/ext#"
ONTOLOGY_GRAPH = og.NamedNode("https://myretirementlife.app/ontology/graph")

APP_VERSION = "0.3.1"


# ---------------------------------------------------------------------------
# Read helpers
# ---------------------------------------------------------------------------

def _quads(subject, prop):
    return list(store.store.quads_for_pattern(
        subject, og.NamedNode(f"{MRL}{prop}"), None, DATA_GRAPH))

def _val(subject, prop, default=""):
    qs = _quads(subject, prop)
    return str(qs[0].object.value) if qs else default

def _local(subject, prop):
    v = _val(subject, prop)
    return v.split("#")[-1] if "#" in v else v

def _float_val(subject, prop, default=0.0):
    try:
        return float(_val(subject, prop, str(default)))
    except ValueError:
        return default

def _int_val(subject, prop):
    """Return int or None if the property is absent."""
    v = _val(subject, prop, "")
    if not v:
        return None
    try:
        return int(v)
    except ValueError:
        return None

def _opt_float(subject, prop):
    """Return float or None if the property is absent."""
    v = _val(subject, prop, "")
    if not v:
        return None
    try:
        return float(v)
    except ValueError:
        return None

def _opt_str(subject, prop):
    """Return non-empty string or None."""
    v = _local(subject, prop)
    return v if v else None


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def export_all_data() -> dict:
    """Serialise all user data from the triple store to a portable dict.

    The dict is designed for round-trip fidelity: every field written by the
    application routes is captured here and restored by restore_all_data().
    Optional fields that were never set are exported as None and silently
    skipped on restore, preserving backward compatibility with older backups.
    """

    # Profile
    person     = og.NamedNode(f"{MRL}Person_1")
    type_check = list(store.store.quads_for_pattern(
        person, og.NamedNode(RDF_TYPE), None, DATA_GRAPH))
    profile = None
    if type_check:
        profile = {
            "firstName":           _val(person, "firstName"),
            "lastName":            _val(person, "lastName"),
            "dateOfBirth":         _val(person, "dateOfBirth"),
            "employmentStatus":    _local(person, "employmentStatus"),
            "targetRetirementAge": _int_val(person, "targetRetirementAge"),
            "lifeExpectancy":      _int_val(person, "lifeExpectancy"),
            "baseCurrency":        _local(person, "baseCurrency"),
            "jurisdiction":        _local(person, "residesIn"),
            "plansToRetireIn":     _opt_str(person, "plansToRetireIn"),
        }

    # Income sources
    income_sources = []
    for q in store.store.quads_for_pattern(
            None, og.NamedNode(RDF_TYPE), og.NamedNode(f"{MRL}IncomeSource"), DATA_GRAPH):
        iri = q.subject
        n   = str(iri.value).split("IncomeSource_")[-1]
        income_sources.append({
            "n":            n,
            "name":         _val(iri, "incomeSourceName"),
            "incomeType":   _local(iri, "incomeSourceType"),
            "annualAmount": _float_val(iri, "incomeAnnualAmount"),
            "growthRate":   _float_val(iri, "incomeGrowthRate"),
            "isNetOfTax":   _val(iri, "incomeIsNetOfTax", "true"),
            "startYear":    _int_val(iri, "incomeStartYear"),
            "endYear":      _int_val(iri, "incomeEndYear"),
            # FX (ADR-016, CLAUDE_CONTEXT item 11) — was missing from export.
            "currency":         _local(iri, "incomeCurrency"),
            "exchangeRate":     _float_val(iri, "incomeExchangeRateToBase", 1.0),
            "exchangeRateDate": _val(iri, "incomeExchangeRateDate"),
            # Deposit account (ADR-024 deposit-routing, CLAUDE_CONTEXT item 24) —
            # was missing from export. Stored as the local label e.g. "CashAccount_2".
            "creditedToAccount": _local(iri, "creditedToAccount"),
        })
    income_sources.sort(key=lambda x: int(x["n"]) if x["n"].isdigit() else 0)

    # Cash accounts
    accounts = []
    for q in store.store.quads_for_pattern(
            None, og.NamedNode(RDF_TYPE), og.NamedNode(f"{MRL}CashAccount"), DATA_GRAPH):
        iri = q.subject
        n   = str(iri.value).split("CashAccount_")[-1]
        accounts.append({
            # Core fields
            "n":               n,
            "name":            _val(iri, "accountName"),
            "balance":         _float_val(iri, "accountBalance"),
            "balanceDate":     _val(iri, "balanceDate"),
            "currency":        _local(iri, "accountCurrency"),
            "interestRate":    _float_val(iri, "annualInterestRate"),
            "jurisdiction":    _local(iri, "accountJurisdiction"),
            "accountType":     _local(iri, "accountType"),
            "exchangeRate":    _float_val(iri, "exchangeRateToBase", 1.0),
            "exchangeRateDate": _val(iri, "exchangeRateDate"),
            "notes":           _val(iri, "accountNotes"),
            # ADR-011: drawdown eligibility and ordering
            "drawdownPriority":     _int_val(iri, "drawdownPriority"),
            "drawdownRatio":        _opt_float(iri, "drawdownRatio"),
            "drawdownMinAge":       _opt_float(iri, "drawdownMinAge"),
            "drawdownMaxAge":       _opt_float(iri, "drawdownMaxAge"),
            "drawdownEarliestDate": _val(iri, "drawdownEarliestDate") or None,
            "drawdownLatestDate":   _val(iri, "drawdownLatestDate")   or None,
            # ADR-013: tax treatment
            "taxTreatment":               _opt_str(iri, "taxTreatment"),
            "effectiveWithdrawalTaxRate": _opt_float(iri, "effectiveWithdrawalTaxRate"),
            "annualTaxFreeWithdrawal":    _opt_float(iri, "annualTaxFreeWithdrawal"),
        })
    accounts.sort(key=lambda x: int(x["n"]) if x["n"].isdigit() else 0)

    # Account contributions (ADR-015)
    account_contributions = []
    for q in store.store.quads_for_pattern(
            None, og.NamedNode(RDF_TYPE), og.NamedNode(f"{MRL}AccountContribution"), DATA_GRAPH):
        iri = q.subject
        owner_qs = list(store.store.quads_for_pattern(
            iri, og.NamedNode(f"{MRL}contributionOwner"), None, DATA_GRAPH))
        owner_label = str(owner_qs[0].object.value).split("#")[-1] if owner_qs else None
        if not owner_label:
            continue
        account_contributions.append({
            "ownerLabel":     owner_label,
            "amount":         _float_val(iri, "contributionAmount"),
            "employerAmount": _opt_float(iri, "employerContributionAmount"),
            "fromPayroll":    _val(iri, "contributionFromPayroll") == "true",
            "frequency":      _local(iri, "contributionFrequency"),
            "startYear":      _int_val(iri, "contributionStartYear"),
            "endYear":        _int_val(iri, "contributionEndYear"),
            "note":           _val(iri, "contributionNote"),
            "growthRate":     _opt_float(iri, "contributionGrowthRate"),
        })

    # Investment accounts
    investment_accounts = []
    for q in store.store.quads_for_pattern(
            None, og.NamedNode(RDF_TYPE), og.NamedNode(f"{MRL}InvestmentAccount"), DATA_GRAPH):
        iri = q.subject
        n   = str(iri.value).split("InvestmentAccount_")[-1]
        investment_accounts.append({
            # Core fields
            "n":               n,
            "name":            _val(iri, "accountName"),
            "balance":         _float_val(iri, "accountBalance"),
            "balanceDate":     _val(iri, "balanceDate"),
            "currency":        _local(iri, "accountCurrency"),
            "growthRate":      _float_val(iri, "annualGrowthRate"),
            "dividendRate":    _float_val(iri, "annualDividendRate"),
            "reinvestDividends": _val(iri, "reinvestDividends", "true"),
            "jurisdiction":    _local(iri, "accountJurisdiction"),
            "accountType":     _local(iri, "accountType"),
            "exchangeRate":    _float_val(iri, "exchangeRateToBase", 1.0),
            "exchangeRateDate": _val(iri, "exchangeRateDate"),
            "notes":           _val(iri, "accountNotes"),
            # ADR-011: drawdown eligibility and ordering
            "drawdownPriority":     _int_val(iri, "drawdownPriority"),
            "drawdownRatio":        _opt_float(iri, "drawdownRatio"),
            "drawdownMinAge":       _opt_float(iri, "drawdownMinAge"),
            "drawdownMaxAge":       _opt_float(iri, "drawdownMaxAge"),
            "drawdownEarliestDate": _val(iri, "drawdownEarliestDate") or None,
            "drawdownLatestDate":   _val(iri, "drawdownLatestDate")   or None,
            # ADR-013: tax treatment
            "taxTreatment":               _opt_str(iri, "taxTreatment"),
            "effectiveWithdrawalTaxRate": _opt_float(iri, "effectiveWithdrawalTaxRate"),
            "annualTaxFreeWithdrawal":    _opt_float(iri, "annualTaxFreeWithdrawal"),
        })
    investment_accounts.sort(key=lambda x: int(x["n"]) if x["n"].isdigit() else 0)

    # Physical assets (Property / Vehicle / Collectible — asset model)
    # Each is a concrete subclass of mrl:PhysicalAsset; the subclass + N live in
    # the IRI (e.g. PropertyAsset_3). Without this, save-scenario/backup silently
    # dropped assets, and restore (which wipes the graph first) deleted them.
    from src.api.routes.accounts import ASSET_SUBCLASSES
    physical_assets = []
    for subclass in ASSET_SUBCLASSES:
        for q in store.store.quads_for_pattern(
                None, og.NamedNode(RDF_TYPE), og.NamedNode(f"{MRL}{subclass}"), DATA_GRAPH):
            iri = q.subject
            n   = str(iri.value).split(f"{subclass}_")[-1]
            physical_assets.append({
                "n":                n,
                "subclass":         subclass,
                "name":             _val(iri, "accountName"),
                "balance":          _float_val(iri, "accountBalance"),
                "balanceDate":      _val(iri, "balanceDate"),
                "currency":         _local(iri, "accountCurrency"),
                "exchangeRate":     _float_val(iri, "exchangeRateToBase", 1.0),
                "exchangeRateDate": _val(iri, "exchangeRateDate"),
                "notes":            _val(iri, "accountNotes"),
                # PhysicalAsset-specific (asset model)
                "appreciationRate": _opt_float(iri, "assetAppreciationRate"),
                "saleYear":         _int_val(iri, "assetSaleYear"),
                "saleValue":        _opt_float(iri, "assetSaleValue"),
                "proceedsAccount":  _opt_str(iri, "assetProceedsAccount"),
            })
    physical_assets.sort(key=lambda x: (x["subclass"], int(x["n"]) if x["n"].isdigit() else 0))

    # Budget categories (ADR-017)
    budget_categories = []
    for q in store.store.quads_for_pattern(
            None, og.NamedNode(RDF_TYPE), og.NamedNode(f"{MRL}BudgetCategory"), DATA_GRAPH):
        iri = q.subject
        n   = str(iri.value).split("BudgetCategory_")[-1]
        budget_categories.append({
            "n":            n,
            "name":         _val(iri, "categoryName"),
            "displayOrder": _int_val(iri, "categoryDisplayOrder"),
            "source":       _val(iri, "categorySource") or "user",
        })
    budget_categories.sort(key=lambda x: int(x["n"]) if x["n"].isdigit() else 0)

    # Budget lines
    # Legacy line-level amount/frequency/window/changeRate kept on the export
    # for backwards compatibility with pre-1.0.2 backups and to support the
    # one-shot migration on restore (ADR-017 §3).
    budget_lines = []
    for q in store.store.quads_for_pattern(
            None, og.NamedNode(RDF_TYPE), og.NamedNode(f"{MRL}BudgetLine"), DATA_GRAPH):
        iri = q.subject
        n   = str(iri.value).split("BudgetLine_")[-1]
        budget_lines.append({
            "n":               n,
            "name":            _val(iri, "budgetLineName"),
            "amount":          _float_val(iri, "budgetLineAmount"),
            "frequency":       _local(iri, "budgetLineFrequency"),
            "lineType":        _local(iri, "budgetLineType"),
            "changeRate":      _float_val(iri, "annualChangeRate"),
            "loanEndYear":     _int_val(iri, "loanEndYear"),
            "budgetStartYear": _int_val(iri, "budgetStartYear"),
            "budgetEndYear":   _int_val(iri, "budgetEndYear"),
            # ADR-017: category link (local name of BudgetCategory_N, or empty)
            "categoryN":       _local(iri, "budgetCategory"),
            # 1.0.5 — ADR-016 follow-on: per-line currency + FX
            "currency":         _local(iri, "budgetLineCurrency"),
            "exchangeRate":     _float_val(iri, "budgetLineExchangeRateToBase", 1.0),
            "exchangeRateDate": _val(iri, "budgetLineExchangeRateDate"),
        })
    budget_lines.sort(key=lambda x: int(x["n"]) if x["n"].isdigit() else 0)

    # Budget line segments (ADR-017)
    budget_line_segments = []
    for q in store.store.quads_for_pattern(
            None, og.NamedNode(RDF_TYPE), og.NamedNode(f"{MRL}BudgetLineSegment"), DATA_GRAPH):
        iri = q.subject
        n   = str(iri.value).split("BudgetLineSegment_")[-1]
        budget_line_segments.append({
            "n":          n,
            "ownerLabel": _local(iri, "segmentOwner"),  # e.g. "BudgetLine_3"
            "startYear":  _int_val(iri, "segmentStartYear"),
            "endYear":    _int_val(iri, "segmentEndYear"),
            "amount":     _float_val(iri, "segmentAmount"),
            "frequency":  _local(iri, "segmentFrequency"),
            "changeRate": _float_val(iri, "segmentChangeRate"),
        })
    budget_line_segments.sort(key=lambda x: int(x["n"]) if x["n"].isdigit() else 0)

    # Life events
    life_events = []
    for q in store.store.quads_for_pattern(
            None, og.NamedNode(RDF_TYPE), og.NamedNode(f"{MRL}LifeEvent"), DATA_GRAPH):
        iri = q.subject
        n   = str(iri.value).split("LifeEvent_")[-1]
        life_events.append({
            "n":          n,
            "name":       _val(iri, "lifeEventName"),
            "year":       _int_val(iri, "lifeEventYear"),
            "amount":     _float_val(iri, "lifeEventAmount"),
            "eventType":  _local(iri, "lifeEventType"),
            "notes":      _val(iri, "lifeEventNotes"),
            # ADR-011: account routing
            "fundedByAccount":   _opt_str(iri, "fundedByAccount"),
            "receivedByAccount": _opt_str(iri, "receivedByAccount"),
        })
    life_events.sort(key=lambda x: x["year"] or 0)

    # Projection settings
    ps       = og.NamedNode(f"{MRL}ProjectionSettings_1")
    ps_check = list(store.store.quads_for_pattern(
        ps, og.NamedNode(RDF_TYPE), None, DATA_GRAPH))
    projection_settings = None
    if ps_check:
        projection_settings = {
            # Existing
            "inflationRate":     _float_val(ps, "inflationRate", 2.5),
            "monteCarloProfile": _opt_str(ps, "monteCarloProfile"),
            # ADR-011: drawdown and surplus strategies
            "drawdownStrategy":      _opt_str(ps, "drawdownStrategy"),
            "surplusStrategy":       _opt_str(ps, "surplusStrategy"),
            "spendingAccount":       _opt_str(ps, "spendingAccount"),
            "surplusAccount":        _opt_str(ps, "surplusAccount"),
            # ADR-013: residence tax
            "annualPersonalAllowance": _float_val(ps, "annualPersonalAllowance", 0.0),
            "residenceIncomeTaxRate":  _float_val(ps, "residenceIncomeTaxRate",  0.0),
        }

    return {
        "version":  APP_VERSION,
        "exported": date.today().isoformat(),
        "app":      "My Retirement Life",
        "data": {
            "profile":               profile,
            "income_sources":        income_sources,
            "accounts":              accounts,
            "account_contributions": account_contributions,   # ADR-015
            "investment_accounts":   investment_accounts,
            "physical_assets":       physical_assets,          # asset model
            "budget_categories":     budget_categories,        # ADR-017
            "budget_lines":          budget_lines,
            "budget_line_segments":  budget_line_segments,     # ADR-017
            "life_events":           life_events,
            "projection_settings":   projection_settings,
        }
    }


# ---------------------------------------------------------------------------
# Restore helpers
# ---------------------------------------------------------------------------

def _triples_drawdown_tax(iri_str: str, item: dict) -> str:
    """Return optional SPARQL triple lines for drawdown and tax fields.

    Shared by both the cash-account and investment-account restore blocks.
    Returns a (possibly empty) string of additional triple lines — each already
    prefixed with a newline, ready to be appended to the main triples block.
    """
    t = ""
    if item.get("drawdownPriority") is not None:
        t += f'\n        <{iri_str}> mrl:drawdownPriority "{int(item["drawdownPriority"])}"^^xsd:integer .'
    if item.get("drawdownRatio") is not None:
        t += f'\n        <{iri_str}> mrl:drawdownRatio "{item["drawdownRatio"]}"^^xsd:decimal .'
    if item.get("drawdownMinAge") is not None:
        t += f'\n        <{iri_str}> mrl:drawdownMinAge "{item["drawdownMinAge"]}"^^xsd:decimal .'
    if item.get("drawdownMaxAge") is not None:
        t += f'\n        <{iri_str}> mrl:drawdownMaxAge "{item["drawdownMaxAge"]}"^^xsd:decimal .'
    if item.get("drawdownEarliestDate"):
        t += f'\n        <{iri_str}> mrl:drawdownEarliestDate "{item["drawdownEarliestDate"]}"^^xsd:date .'
    if item.get("drawdownLatestDate"):
        t += f'\n        <{iri_str}> mrl:drawdownLatestDate "{item["drawdownLatestDate"]}"^^xsd:date .'
    if item.get("taxTreatment"):
        t += f'\n        <{iri_str}> mrl:taxTreatment mrlx:{item["taxTreatment"]} .'
    if item.get("effectiveWithdrawalTaxRate") is not None:
        t += f'\n        <{iri_str}> mrl:effectiveWithdrawalTaxRate "{item["effectiveWithdrawalTaxRate"]}"^^xsd:decimal .'
    if item.get("annualTaxFreeWithdrawal") is not None:
        t += f'\n        <{iri_str}> mrl:annualTaxFreeWithdrawal "{item["annualTaxFreeWithdrawal"]}"^^xsd:decimal .'
    return t


def restore_all_data(backup: dict) -> tuple[bool, str]:
    """Restore data from a backup dict. Clears all existing user data first.

    Backward-compatible with v0.2 backups — optional fields absent from older
    exports are silently skipped.

    Returns (success, message).
    """
    try:
        data = backup.get("data", {})

        # Clear all existing user data
        store.update(f"""
            DELETE WHERE {{
                GRAPH <{DATA_GRAPH.value}> {{
                    ?s ?p ?o .
                }}
            }}
        """)

        person_iri = f"{MRL}Person_1"

        # --- Profile ---
        profile = data.get("profile")
        if profile:
            store.update(f"""
                PREFIX mrl:  <{MRL}>
                PREFIX mrlx: <{MRL_EXT}>
                PREFIX xsd:  <http://www.w3.org/2001/XMLSchema#>
                INSERT DATA {{
                    GRAPH <{DATA_GRAPH.value}> {{
                        <{person_iri}> a mrl:Person ;
                            mrl:firstName  "{profile.get('firstName', '')}" ;
                            mrl:lastName   "{profile.get('lastName', '')}" ;
                            mrl:dateOfBirth "{profile.get('dateOfBirth', '')}"^^xsd:date ;
                            mrl:employmentStatus mrlx:{profile.get('employmentStatus', 'EmploymentStatus_Employed')} ;
                            mrl:targetRetirementAge {profile.get('targetRetirementAge', 67)} ;
                            mrl:lifeExpectancy {profile.get('lifeExpectancy', 85)} ;
                            mrl:baseCurrency mrl:{profile.get('baseCurrency', 'Currency_GBP')} ;
                            mrl:residesIn mrl:{profile.get('jurisdiction', 'Jurisdiction_GB')} .
                    }}
                }}
            """)
            if profile.get("plansToRetireIn"):
                store.update(f"""
                    PREFIX mrl: <{MRL}>
                    INSERT DATA {{ GRAPH <{DATA_GRAPH.value}> {{
                        <{person_iri}> mrl:plansToRetireIn mrl:{profile['plansToRetireIn']} . }} }}
                """)

        # --- Income sources ---
        for src in data.get("income_sources", []):
            n       = src.get("n", "1")
            src_iri = f"{MRL}IncomeSource_{n}"
            store.update(f"""
                PREFIX mrl:  <{MRL}>
                PREFIX mrlx: <{MRL_EXT}>
                PREFIX xsd:  <http://www.w3.org/2001/XMLSchema#>
                INSERT DATA {{
                    GRAPH <{DATA_GRAPH.value}> {{
                        <{src_iri}> a mrl:IncomeSource ;
                            mrl:incomeSourceName "{src.get('name', '')}" ;
                            mrl:incomeSourceType mrlx:{src.get('incomeType', 'IncomeSourceType_Employment')} ;
                            mrl:incomeAnnualAmount "{src.get('annualAmount', 0)}"^^xsd:decimal ;
                            mrl:incomeGrowthRate "{src.get('growthRate', 0)}"^^xsd:decimal ;
                            mrl:incomeIsNetOfTax "{src.get('isNetOfTax', 'true')}"^^xsd:boolean ;
                            mrl:incomeOwner <{person_iri}> .
                    }}
                }}
            """)
            if src.get("startYear"):
                store.update(f"""
                    PREFIX mrl: <{MRL}> PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
                    INSERT DATA {{ GRAPH <{DATA_GRAPH.value}> {{
                        <{src_iri}> mrl:incomeStartYear "{src['startYear']}"^^xsd:integer . }} }}
                """)
            if src.get("endYear"):
                store.update(f"""
                    PREFIX mrl: <{MRL}> PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
                    INSERT DATA {{ GRAPH <{DATA_GRAPH.value}> {{
                        <{src_iri}> mrl:incomeEndYear "{src['endYear']}"^^xsd:integer . }} }}
                """)
            # FX (ADR-016) — pre-session-7 backups didn't carry these; absent
            # fields fall back to the base currency at engine load time.
            if src.get("currency"):
                store.update(f"""
                    PREFIX mrl: <{MRL}>
                    INSERT DATA {{ GRAPH <{DATA_GRAPH.value}> {{
                        <{src_iri}> mrl:incomeCurrency mrl:{src['currency']} . }} }}
                """)
            if src.get("exchangeRate") and float(src.get("exchangeRate", 1.0)) != 1.0:
                _rate_date = src.get("exchangeRateDate") or date.today().isoformat()
                store.update(f"""
                    PREFIX mrl: <{MRL}> PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
                    INSERT DATA {{ GRAPH <{DATA_GRAPH.value}> {{
                        <{src_iri}> mrl:incomeExchangeRateToBase "{src['exchangeRate']}"^^xsd:decimal ;
                                    mrl:incomeExchangeRateDate   "{_rate_date}"^^xsd:date . }} }}
                """)
            # Deposit account routing (CLAUDE_CONTEXT item 24) — also missed by
            # earlier exports. Restored after cash + investment accounts further
            # below means the referenced account may not yet exist when this
            # triple is written, but that's OK: it's a literal IRI link and the
            # target only needs to resolve at engine read time, not at write.
            if src.get("creditedToAccount"):
                store.update(f"""
                    PREFIX mrl: <{MRL}>
                    INSERT DATA {{ GRAPH <{DATA_GRAPH.value}> {{
                        <{src_iri}> mrl:creditedToAccount mrl:{src['creditedToAccount']} . }} }}
                """)

        # --- Cash accounts ---
        for acc in data.get("accounts", []):
            n       = acc.get("n", "1")
            acc_iri = f"{MRL}CashAccount_{n}"

            triples = f"""
        <{acc_iri}> a mrl:CashAccount ;
            mrl:accountName        "{acc.get('name', '')}" ;
            mrl:accountBalance     "{acc.get('balance', 0)}"^^xsd:decimal ;
            mrl:balanceDate        "{acc.get('balanceDate', date.today().isoformat())}"^^xsd:date ;
            mrl:accountCurrency    mrl:{acc.get('currency', 'Currency_GBP')} ;
            mrl:annualInterestRate "{acc.get('interestRate', 0)}"^^xsd:decimal ;
            mrl:accountJurisdiction mrl:{acc.get('jurisdiction', 'Jurisdiction_GB')} ;
            mrl:accountType        mrlx:{acc.get('accountType', 'CashAccountType_Current')} ;
            mrl:ownedBy            <{person_iri}> .
            """

            if acc.get("exchangeRate") and float(acc.get("exchangeRate", 1.0)) != 1.0:
                triples += f'\n        <{acc_iri}> mrl:exchangeRateToBase "{acc["exchangeRate"]}"^^xsd:decimal ;'
                triples += f'\n                    mrl:exchangeRateDate   "{acc.get("exchangeRateDate", date.today().isoformat())}"^^xsd:date .'
            if acc.get("notes"):
                safe = acc["notes"].replace('"', '\\"')
                triples += f'\n        <{acc_iri}> mrl:accountNotes "{safe}" .'

            triples += _triples_drawdown_tax(acc_iri, acc)

            store.update(f"""
                PREFIX mrl:  <{MRL}>
                PREFIX mrlx: <{MRL_EXT}>
                PREFIX xsd:  <http://www.w3.org/2001/XMLSchema#>
                INSERT DATA {{ GRAPH <{DATA_GRAPH.value}> {{ {triples} }} }}
            """)

        # --- Investment accounts ---
        for inv in data.get("investment_accounts", []):
            n       = inv.get("n", "1")
            inv_iri = f"{MRL}InvestmentAccount_{n}"

            triples = f"""
        <{inv_iri}> a mrl:InvestmentAccount ;
            mrl:accountName        "{inv.get('name', '')}" ;
            mrl:accountBalance     "{inv.get('balance', 0)}"^^xsd:decimal ;
            mrl:balanceDate        "{inv.get('balanceDate', date.today().isoformat())}"^^xsd:date ;
            mrl:accountCurrency    mrl:{inv.get('currency', 'Currency_GBP')} ;
            mrl:annualGrowthRate   "{inv.get('growthRate', 0)}"^^xsd:decimal ;
            mrl:annualDividendRate "{inv.get('dividendRate', 0)}"^^xsd:decimal ;
            mrl:reinvestDividends  "{inv.get('reinvestDividends', 'true')}"^^xsd:boolean ;
            mrl:accountJurisdiction mrl:{inv.get('jurisdiction', 'Jurisdiction_GB')} ;
            mrl:accountType        mrlx:{inv.get('accountType', 'InvestmentAccountType_StocksShares')} ;
            mrl:ownedBy            <{person_iri}> .
            """

            if inv.get("exchangeRate") and float(inv.get("exchangeRate", 1.0)) != 1.0:
                triples += f'\n        <{inv_iri}> mrl:exchangeRateToBase "{inv["exchangeRate"]}"^^xsd:decimal ;'
                triples += f'\n                    mrl:exchangeRateDate   "{inv.get("exchangeRateDate", date.today().isoformat())}"^^xsd:date .'
            if inv.get("notes"):
                safe = inv["notes"].replace('"', '\\"')
                triples += f'\n        <{inv_iri}> mrl:accountNotes "{safe}" .'

            triples += _triples_drawdown_tax(inv_iri, inv)

            store.update(f"""
                PREFIX mrl:  <{MRL}>
                PREFIX mrlx: <{MRL_EXT}>
                PREFIX xsd:  <http://www.w3.org/2001/XMLSchema#>
                INSERT DATA {{ GRAPH <{DATA_GRAPH.value}> {{ {triples} }} }}
            """)

        # --- Physical assets (Property / Vehicle / Collectible) ---
        # Recreate mrl:{subclass}_{n}; mirrors save_asset() in accounts.py.
        # Restored after cash + investment accounts so an assetProceedsAccount
        # reference points at an account that already exists. Backups predating
        # the asset model omit "physical_assets" and this loop is a no-op.
        for asset in data.get("physical_assets", []):
            subclass = asset.get("subclass")
            if not subclass:
                continue
            a_n       = asset.get("n", "1")
            asset_iri = f"{MRL}{subclass}_{a_n}"

            triples = f"""
        <{asset_iri}> a mrl:{subclass} ;
            mrl:accountName     "{asset.get('name', '')}" ;
            mrl:accountBalance  "{asset.get('balance', 0)}"^^xsd:decimal ;
            mrl:balanceDate     "{asset.get('balanceDate', date.today().isoformat())}"^^xsd:date ;
            mrl:accountCurrency mrl:{asset.get('currency', 'Currency_GBP')} ;
            mrl:ownedBy         <{person_iri}> .
            """
            if asset.get("exchangeRate") and float(asset.get("exchangeRate", 1.0)) != 1.0:
                triples += f'\n        <{asset_iri}> mrl:exchangeRateToBase "{asset["exchangeRate"]}"^^xsd:decimal ;'
                triples += f'\n                    mrl:exchangeRateDate   "{asset.get("exchangeRateDate", date.today().isoformat())}"^^xsd:date .'
            if asset.get("notes"):
                safe = asset["notes"].replace('"', '\\"')
                triples += f'\n        <{asset_iri}> mrl:accountNotes "{safe}" .'
            if asset.get("appreciationRate") is not None:
                triples += f'\n        <{asset_iri}> mrl:assetAppreciationRate "{asset["appreciationRate"]}"^^xsd:decimal .'
            if asset.get("saleYear") is not None:
                triples += f'\n        <{asset_iri}> mrl:assetSaleYear "{asset["saleYear"]}"^^xsd:integer .'
            if asset.get("saleValue") is not None:
                triples += f'\n        <{asset_iri}> mrl:assetSaleValue "{asset["saleValue"]}"^^xsd:decimal .'
            if asset.get("proceedsAccount"):
                triples += f'\n        <{asset_iri}> mrl:assetProceedsAccount mrl:{asset["proceedsAccount"]} .'

            store.update(f"""
                PREFIX mrl:  <{MRL}>
                PREFIX mrlx: <{MRL_EXT}>
                PREFIX xsd:  <http://www.w3.org/2001/XMLSchema#>
                INSERT DATA {{ GRAPH <{DATA_GRAPH.value}> {{ {triples} }} }}
            """)

        # --- Account contributions (ADR-015) ---
        # Contributions are restored by iterating through the ownerLabel, finding a
        # fresh AccountContribution_N and writing the triples.
        # Uses a local counter so N values don't collide.
        contrib_n = 1
        for contrib in data.get("account_contributions", []):
            owner_label = contrib.get("ownerLabel")
            if not owner_label:
                continue
            c_iri = f"{MRL}AccountContribution_{contrib_n}"
            contrib_n += 1
            freq = contrib.get("frequency", "FrequencyType_Monthly")

            triples = f"""
        <{c_iri}> a mrl:AccountContribution ;
            mrl:contributionAmount    "{contrib.get('amount', 0)}"^^xsd:decimal ;
            mrl:contributionFrequency mrlx:{freq} ;
            mrl:contributionOwner     <{MRL}{owner_label}> .
            """
            if contrib.get("startYear"):
                triples += f'\n        <{c_iri}> mrl:contributionStartYear "{contrib["startYear"]}"^^xsd:integer .'
            if contrib.get("endYear"):
                triples += f'\n        <{c_iri}> mrl:contributionEndYear "{contrib["endYear"]}"^^xsd:integer .'
            if contrib.get("note"):
                safe = contrib["note"].replace('"', '\\"')
                triples += f'\n        <{c_iri}> mrl:contributionNote "{safe}" .'
            if contrib.get("growthRate") is not None and contrib["growthRate"] != 0.0:
                triples += f'\n        <{c_iri}> mrl:contributionGrowthRate "{contrib["growthRate"]}"^^xsd:decimal .'
            if contrib.get("employerAmount") is not None and contrib["employerAmount"] != 0.0:
                triples += f'\n        <{c_iri}> mrl:employerContributionAmount "{contrib["employerAmount"]}"^^xsd:decimal .'
            if contrib.get("fromPayroll"):
                triples += f'\n        <{c_iri}> mrl:contributionFromPayroll "true"^^xsd:boolean .'

            store.update(f"""
                PREFIX mrl:  <{MRL}>
                PREFIX mrlx: <{MRL_EXT}>
                PREFIX xsd:  <http://www.w3.org/2001/XMLSchema#>
                INSERT DATA {{ GRAPH <{DATA_GRAPH.value}> {{ {triples} }} }}
            """)

        # --- Budget categories (ADR-017) ---
        # Restored BEFORE budget lines so the line's budgetCategory IRI is valid.
        for cat in data.get("budget_categories", []):
            cat_n   = cat.get("n", "1")
            cat_iri = f"{MRL}BudgetCategory_{cat_n}"
            safe_name = (cat.get("name") or "").replace("\\", "\\\\").replace('"', '\\"')
            triples = f"""
        <{cat_iri}> a mrl:BudgetCategory ;
            mrl:categoryName "{safe_name}" ;
            mrl:categorySource "{cat.get('source', 'user')}" .
            """
            if cat.get("displayOrder") is not None:
                triples += (f'\n        <{cat_iri}> mrl:categoryDisplayOrder '
                            f'"{cat["displayOrder"]}"^^xsd:integer .')
            store.update(f"""
                PREFIX mrl: <{MRL}>
                PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
                INSERT DATA {{ GRAPH <{DATA_GRAPH.value}> {{ {triples} }} }}
            """)

        # --- Budget lines ---
        # Legacy line-level fields (amount, frequency, changeRate, window) are
        # still restored verbatim for pre-1.0.2 backups; for new backups they
        # may be absent but the segments block below will populate everything.
        # On any restore that lacks segments, migrate_legacy_budget_lines_to_segments()
        # will run on the next /budget render (ADR-017 §3).
        for line in data.get("budget_lines", []):
            n        = line.get("n", "1")
            line_iri = f"{MRL}BudgetLine_{n}"
            safe_line_name = (line.get("name") or "").replace("\\", "\\\\").replace('"', '\\"')
            base_triples = f"""
        <{line_iri}> a mrl:BudgetLine ;
            mrl:budgetLineName "{safe_line_name}" ;
            mrl:budgetLineType mrlx:{line.get('lineType', 'BudgetLineType_Mandatory')} ;
            mrl:budgetOwner <{person_iri}> .
            """
            # Legacy line-level fields — only emitted when actually present
            # in the backup. Newer backups (Phase 1b+) put these on segments.
            if line.get("amount") is not None:
                base_triples += (f'\n        <{line_iri}> mrl:budgetLineAmount '
                                 f'"{line["amount"]}"^^xsd:decimal .')
            if line.get("frequency"):
                base_triples += (f'\n        <{line_iri}> mrl:budgetLineFrequency '
                                 f'mrlx:{line["frequency"]} .')
            if line.get("changeRate") is not None:
                base_triples += (f'\n        <{line_iri}> mrl:annualChangeRate '
                                 f'"{line["changeRate"]}"^^xsd:decimal .')
            if line.get("categoryN"):
                base_triples += (f'\n        <{line_iri}> mrl:budgetCategory '
                                 f'<{MRL}{line["categoryN"]}> .')
            # 1.0.5: per-line currency. Backups predating this field don't
            # carry it — restore as-is and the engine falls back to the base
            # currency at load time (matches the in-app default).
            if line.get("currency"):
                base_triples += (f'\n        <{line_iri}> mrl:budgetLineCurrency '
                                 f'mrl:{line["currency"]} .')
            if line.get("exchangeRate") and float(line.get("exchangeRate", 1.0)) != 1.0:
                base_triples += (f'\n        <{line_iri}> mrl:budgetLineExchangeRateToBase '
                                 f'"{line["exchangeRate"]}"^^xsd:decimal .')
                _rate_date = line.get("exchangeRateDate") or date.today().isoformat()
                base_triples += (f'\n        <{line_iri}> mrl:budgetLineExchangeRateDate '
                                 f'"{_rate_date}"^^xsd:date .')
            store.update(f"""
                PREFIX mrl:  <{MRL}>
                PREFIX mrlx: <{MRL_EXT}>
                PREFIX xsd:  <http://www.w3.org/2001/XMLSchema#>
                INSERT DATA {{ GRAPH <{DATA_GRAPH.value}> {{ {base_triples} }} }}
            """)
            if line.get("loanEndYear"):
                store.update(f"""
                    PREFIX mrl: <{MRL}> PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
                    INSERT DATA {{ GRAPH <{DATA_GRAPH.value}> {{
                        <{line_iri}> mrl:loanEndYear "{line['loanEndYear']}"^^xsd:integer . }} }}
                """)
            if line.get("budgetStartYear"):
                store.update(f"""
                    PREFIX mrl: <{MRL}> PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
                    INSERT DATA {{ GRAPH <{DATA_GRAPH.value}> {{
                        <{line_iri}> mrl:budgetStartYear "{line['budgetStartYear']}"^^xsd:integer . }} }}
                """)
            if line.get("budgetEndYear"):
                store.update(f"""
                    PREFIX mrl: <{MRL}> PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
                    INSERT DATA {{ GRAPH <{DATA_GRAPH.value}> {{
                        <{line_iri}> mrl:budgetEndYear "{line['budgetEndYear']}"^^xsd:integer . }} }}
                """)

        # --- Budget line segments (ADR-017) ---
        # Restored AFTER budget lines so the segmentOwner IRI is valid.
        for seg in data.get("budget_line_segments", []):
            seg_n   = seg.get("n", "1")
            owner   = seg.get("ownerLabel")
            if not owner:
                continue
            seg_iri = f"{MRL}BudgetLineSegment_{seg_n}"
            seg_triples = f"""
        <{seg_iri}> a mrl:BudgetLineSegment ;
            mrl:segmentOwner <{MRL}{owner}> ;
            mrl:segmentStartYear "{seg.get('startYear', 0)}"^^xsd:integer ;
            mrl:segmentAmount "{seg.get('amount', 0)}"^^xsd:decimal ;
            mrl:segmentFrequency mrlx:{seg.get('frequency', 'FrequencyType_Monthly')} ;
            mrl:segmentChangeRate "{seg.get('changeRate', 0)}"^^xsd:decimal .
            """
            if seg.get("endYear") is not None:
                seg_triples += (f'\n        <{seg_iri}> mrl:segmentEndYear '
                                f'"{seg["endYear"]}"^^xsd:integer .')
            store.update(f"""
                PREFIX mrl:  <{MRL}>
                PREFIX mrlx: <{MRL_EXT}>
                PREFIX xsd:  <http://www.w3.org/2001/XMLSchema#>
                INSERT DATA {{ GRAPH <{DATA_GRAPH.value}> {{ {seg_triples} }} }}
            """)

        # --- Life events ---
        for event in data.get("life_events", []):
            n         = event.get("n", "1")
            event_iri = f"{MRL}LifeEvent_{n}"

            triples = f"""
        <{event_iri}> a mrl:LifeEvent ;
            mrl:lifeEventName   "{event.get('name', '')}" ;
            mrl:lifeEventYear   "{event.get('year', 2030)}"^^xsd:integer ;
            mrl:lifeEventAmount "{event.get('amount', 0)}"^^xsd:decimal ;
            mrl:lifeEventType   mrlx:{event.get('eventType', 'LifeEventType_LargeExpenditure')} ;
            mrl:lifeEventOwner  <{person_iri}> .
            """

            if event.get("notes"):
                safe = event["notes"].replace('"', '\\"')
                triples += f'\n        <{event_iri}> mrl:lifeEventNotes "{safe}" .'
            # ADR-011: account routing
            if event.get("fundedByAccount"):
                triples += f'\n        <{event_iri}> mrl:fundedByAccount mrl:{event["fundedByAccount"]} .'
            if event.get("receivedByAccount"):
                triples += f'\n        <{event_iri}> mrl:receivedByAccount mrl:{event["receivedByAccount"]} .'

            store.update(f"""
                PREFIX mrl:  <{MRL}>
                PREFIX mrlx: <{MRL_EXT}>
                PREFIX xsd:  <http://www.w3.org/2001/XMLSchema#>
                INSERT DATA {{ GRAPH <{DATA_GRAPH.value}> {{ {triples} }} }}
            """)

        # --- Projection settings ---
        ps_data = data.get("projection_settings")
        if ps_data:
            ps_iri = f"{MRL}ProjectionSettings_1"

            triples = f"""
        <{ps_iri}> a mrl:ProjectionSettings ;
            mrl:inflationRate           "{ps_data.get('inflationRate', 2.5)}"^^xsd:decimal ;
            mrl:annualPersonalAllowance "{ps_data.get('annualPersonalAllowance', 0.0)}"^^xsd:decimal ;
            mrl:residenceIncomeTaxRate  "{ps_data.get('residenceIncomeTaxRate', 0.0)}"^^xsd:decimal ;
            mrl:projectionOwner         <{person_iri}> .
            """

            # Object properties — only write if present (older backups may lack them)
            if ps_data.get("monteCarloProfile"):
                triples += f'\n        <{ps_iri}> mrl:monteCarloProfile mrlx:{ps_data["monteCarloProfile"]} .'
            if ps_data.get("drawdownStrategy"):
                triples += f'\n        <{ps_iri}> mrl:drawdownStrategy mrlx:{ps_data["drawdownStrategy"]} .'
            if ps_data.get("surplusStrategy"):
                triples += f'\n        <{ps_iri}> mrl:surplusStrategy mrlx:{ps_data["surplusStrategy"]} .'
            if ps_data.get("spendingAccount"):
                triples += f'\n        <{ps_iri}> mrl:spendingAccount mrl:{ps_data["spendingAccount"]} .'
            if ps_data.get("surplusAccount"):
                triples += f'\n        <{ps_iri}> mrl:surplusAccount mrl:{ps_data["surplusAccount"]} .'

            store.update(f"""
                PREFIX mrl:  <{MRL}>
                PREFIX mrlx: <{MRL_EXT}>
                PREFIX xsd:  <http://www.w3.org/2001/XMLSchema#>
                INSERT DATA {{ GRAPH <{DATA_GRAPH.value}> {{ {triples} }} }}
            """)

        return True, "Data restored successfully."

    except Exception as e:
        return False, f"Restore failed: {str(e)}"


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    from src.store.ontology_loader import ontology_triple_count
    data_count     = len(list(store.store.quads_for_pattern(None, None, None, DATA_GRAPH)))
    ontology_count = ontology_triple_count(store.store)
    data_dir       = str(app_settings.data_dir)

    try:
        from src.api.routes.projection import get_projection_settings
        proj_settings = get_projection_settings()
    except Exception:
        proj_settings = None

    return templates.TemplateResponse(
        request=request,
        name="settings.html",
        context={
            "app_name":              app_settings.app_name,
            "active":                "settings",
            "app_version":           APP_VERSION,
            "data_dir":              data_dir,
            "data_triple_count":     data_count,
            "ontology_triple_count": ontology_count,
            "proj_settings":         proj_settings,
            "today":                 date.today().isoformat(),
        }
    )


@router.get("/settings/export")
async def export_data():
    """Download all user data as a JSON backup file."""
    data     = export_all_data()
    filename = f"my-retirement-life-backup-{date.today().isoformat()}.json"
    return Response(
        content=json.dumps(data, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


@router.post("/settings/import", response_class=HTMLResponse)
async def import_data(request: Request, backup_file: UploadFile = File(...)):
    """Restore data from an uploaded JSON backup file."""
    from src.store.ontology_loader import ontology_triple_count

    try:
        content = await backup_file.read()
        backup  = json.loads(content)
        if backup.get("app") != "My Retirement Life":
            raise ValueError("File does not appear to be a My Retirement Life backup.")
        success, message = restore_all_data(backup)
    except json.JSONDecodeError:
        success, message = False, "File is not valid JSON."
    except Exception as e:
        success, message = False, str(e)

    data_count     = len(list(store.store.quads_for_pattern(None, None, None, DATA_GRAPH)))
    ontology_count = ontology_triple_count(store.store)

    try:
        from src.api.routes.projection import get_projection_settings
        proj_settings = get_projection_settings()
    except Exception:
        proj_settings = None

    return templates.TemplateResponse(
        request=request,
        name="settings.html",
        context={
            "app_name":              app_settings.app_name,
            "active":                "settings",
            "app_version":           APP_VERSION,
            "data_dir":              str(app_settings.data_dir),
            "data_triple_count":     data_count,
            "ontology_triple_count": ontology_count,
            "proj_settings":         proj_settings,
            "today":                 date.today().isoformat(),
            "import_success":        success,
            "import_message":        message,
        }
    )


@router.post("/settings/inflation", response_class=HTMLResponse)
async def update_inflation(
    request: Request,
    inflationRate: float = Form(2.5),
):
    """Update the default inflation rate (legacy endpoint — kept for backward compat)."""
    from src.store.ontology_loader import ontology_triple_count
    from src.api.routes.projection import get_projection_settings, save_projection_settings

    # Preserve all existing settings, just update the inflation rate
    ps = get_projection_settings()
    save_projection_settings(
        inflation_rate            = inflationRate,
        mc_profile                = ps["mc_profile"],
        drawdown_strategy         = ps["drawdown_strategy"],
        surplus_strategy          = ps["surplus_strategy"],
        spending_account_label    = ps["spending_account_label"],
        surplus_account_label     = ps["surplus_account_label"],
        annual_personal_allowance = ps["annual_personal_allowance"],
        residence_income_tax_rate = ps["residence_income_tax_rate"],
    )

    data_count = len(list(store.store.quads_for_pattern(None, None, None, DATA_GRAPH)))

    return templates.TemplateResponse(
        request=request,
        name="settings.html",
        context={
            "app_name":              app_settings.app_name,
            "active":                "settings",
            "app_version":           APP_VERSION,
            "data_dir":              str(app_settings.data_dir),
            "data_triple_count":     data_count,
            "ontology_triple_count": ontology_triple_count(store.store),
            "inflation_rate":        inflationRate,
            "today":                 date.today().isoformat(),
            "inflation_saved":       True,
        }
    )