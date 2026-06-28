"""Persist an ImportPlan into the MRL store (ADR-020, Phase 3).

Writes the proposed entities from :mod:`src.mfl_import.mapping` into the data
graph, reusing MRL's own ``save_*`` functions so imported entities are
indistinguishable from hand-entered ones, then stamps each with provenance
(``mrl:importSourceApp`` / ``importSourceRef`` / ``importedAt`` — ontology 1.0.8).

Two paths, keyed on the provenance match:

* **Create** (first import / a source not seen before): allocate the next N,
  call the relevant ``save_*``, write provenance.
* **Refresh** (a source already imported): surgically update only the *imported
  fact* — the balance (and its date) — leaving every user-entered field
  (growth/dividend rate, tax treatment, drawdown order, …) untouched. Budget
  lines are create-only on refresh, so a user's evolved budget plan is never
  clobbered.

Requires the 1.0.8 ontology to be loaded (``tools/reload_ontology.py``) for the
provenance property declarations, though the writes don't depend on them.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional

import pyoxigraph as og

from src.store.graph import store, MRL, DATA_GRAPH
from src.mfl_import.mapping import ImportPlan, ProposedAccount, ProposedAsset, ProposedBudgetLine

RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"

# Base currency → tax-residence jurisdiction (MFL has no jurisdiction; the user
# can correct it afterwards — jurisdiction is part of the retirement layer).
_CCY_JURISDICTION = {
    "GBP": "Jurisdiction_GB", "USD": "Jurisdiction_US", "EUR": "Jurisdiction_EU",
    "CAD": "Jurisdiction_CA", "AUD": "Jurisdiction_AU", "CHF": "Jurisdiction_CH",
    "JPY": "Jurisdiction_JP", "CNY": "Jurisdiction_CN", "INR": "Jurisdiction_IN",
    "AED": "Jurisdiction_AE", "HKD": "Jurisdiction_HK", "SGD": "Jurisdiction_SG",
    "NZD": "Jurisdiction_NZ", "ZAR": "Jurisdiction_ZA", "SEK": "Jurisdiction_SE",
    "NOK": "Jurisdiction_NO", "DKK": "Jurisdiction_DK",
}


@dataclass
class ApplyResult:
    created: int = 0
    refreshed: int = 0
    budget_skipped_existing: int = 0
    details: list[str] = field(default_factory=list)


def _esc(s: str) -> str:
    return (s or "").replace("\\", "\\\\").replace('"', '\\"')


def _find_imported() -> dict[str, str]:
    """Map importSourceRef -> entity local name (e.g. 'CashAccount_3') already in
    the store, so a re-import matches and refreshes rather than duplicating."""
    out: dict[str, str] = {}
    for q in store.store.quads_for_pattern(
            None, og.NamedNode(f"{MRL}importSourceRef"), None, DATA_GRAPH):
        local = str(q.subject.value).split("#")[-1].split("/")[-1]
        if local.startswith(MRL):
            local = local[len(MRL):]
        out[q.object.value] = local
    return out


def _write_provenance(local: str, source_app: str, source_ref: str, when: str) -> None:
    iri = f"{MRL}{local}"
    store.update(f"""
        PREFIX mrl: <{MRL}>
        DELETE WHERE {{ GRAPH <{DATA_GRAPH.value}> {{
            <{iri}> mrl:importSourceApp ?a . <{iri}> mrl:importSourceRef ?r .
            <{iri}> mrl:importedAt ?d . }} }}
    """)
    store.update(f"""
        PREFIX mrl: <{MRL}>
        PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
        INSERT DATA {{ GRAPH <{DATA_GRAPH.value}> {{
            <{iri}> mrl:importSourceApp "{_esc(source_app)}" ;
                    mrl:importSourceRef "{_esc(source_ref)}" ;
                    mrl:importedAt "{when}"^^xsd:date . }} }}
    """)


def _entity_name(local: str) -> str:
    iri = og.NamedNode(f"{MRL}{local}")
    for prop in ("accountName", "budgetLineName"):
        for q in store.store.quads_for_pattern(
                iri, og.NamedNode(f"{MRL}{prop}"), None, DATA_GRAPH):
            return q.object.value
    return local


def compute_diff(plan: ImportPlan) -> dict:
    """Compare an ImportPlan against what's already been imported (ADR-020 Phase 5).

    Returns per-source_ref status ('new' | 'update' | 'keep') plus the
    'orphans' — entities a previous import created that are no longer in this
    MFL file (left untouched, never auto-deleted). Drives the wizard's
    create-vs-update preview diff. On a first import everything is 'new'.
    """
    existing = _find_imported()
    status: dict[str, str] = {}
    refs: set[str] = set()
    for a in plan.accounts:
        refs.add(a.source_ref)
        status[a.source_ref] = "update" if a.source_ref in existing else "new"
    for a in plan.assets:
        refs.add(a.source_ref)
        status[a.source_ref] = "update" if a.source_ref in existing else "new"
    for b in plan.budget_lines:
        refs.add(b.source_ref)
        status[b.source_ref] = "keep" if b.source_ref in existing else "new"
    orphans = [{"name": _entity_name(local), "local": local}
               for ref, local in sorted(existing.items()) if ref not in refs]
    counts = {"new": 0, "update": 0, "keep": 0}
    for s in status.values():
        counts[s] += 1
    counts["orphans"] = len(orphans)
    return {"status": status, "orphans": orphans, "counts": counts,
            "is_reimport": bool(existing)}


def _refresh_balance(local: str, balance: float, balance_date: str) -> None:
    """Surgically update only the balance/date triples — preserves user edits."""
    iri = f"{MRL}{local}"
    store.update(f"""
        PREFIX mrl: <{MRL}>
        DELETE WHERE {{ GRAPH <{DATA_GRAPH.value}> {{
            <{iri}> mrl:accountBalance ?b . <{iri}> mrl:balanceDate ?d . }} }}
    """)
    store.update(f"""
        PREFIX mrl: <{MRL}>
        PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
        INSERT DATA {{ GRAPH <{DATA_GRAPH.value}> {{
            <{iri}> mrl:accountBalance "{balance}"^^xsd:decimal ;
                    mrl:balanceDate "{balance_date}"^^xsd:date . }} }}
    """)


def apply_plan(plan: ImportPlan, imported_at: Optional[str] = None) -> ApplyResult:
    """Create or refresh MRL entities from the plan. Returns counts + details."""
    # Lazy imports — the routes modules form an import cycle; apply.py is a leaf.
    from src.api.routes.accounts import (
        save_account, save_asset, get_all_accounts, get_all_asset_accounts,
        _next_asset_n,
    )
    from src.api.routes.investments import save_investment_account, get_all_investment_accounts
    from src.api.routes.budget import save_budget_line_segments, get_all_budget_lines

    when = imported_at or date.today().isoformat()
    jurisdiction = _CCY_JURISDICTION.get(plan.base_currency, "Jurisdiction_GB")
    existing = _find_imported()
    res = ApplyResult()

    def next_n(rows):
        return max([int(r["n"]) for r in rows if str(r["n"]).isdigit()], default=0) + 1

    # --- Accounts (cash + investment) ---
    for a in plan.accounts:
        if a.source_ref in existing:
            _refresh_balance(existing[a.source_ref], float(a.balance), when)
            _write_provenance(existing[a.source_ref], a.source_app, a.source_ref, when)
            res.refreshed += 1
            res.details.append(f"refreshed {a.kind} '{a.name}' → balance {a.balance}")
            continue
        if a.kind == "cash":
            n = next_n(get_all_accounts())
            save_account(
                n=n, name=a.name, balance=float(a.balance), balance_date=when,
                currency_local=a.currency, interest_rate=0.0,
                jurisdiction_local=jurisdiction, account_type=a.account_type,
                exchange_rate=float(a.exchange_rate), exchange_rate_date=when,
                notes="Imported from My Financial Life",
                tax_treatment=a.tax_treatment or "")
            local = f"CashAccount_{n}"
        else:
            n = next_n(get_all_investment_accounts())
            save_investment_account(
                n=n, name=a.name, balance=float(a.balance), balance_date=when,
                currency_local=a.currency,
                growth_rate=float(a.growth_rate) if a.growth_rate is not None else 0.0,
                dividend_rate=float(a.dividend_rate) if a.dividend_rate is not None else 0.0,
                reinvest_dividends=True, jurisdiction_local=jurisdiction,
                account_type=a.account_type, exchange_rate=float(a.exchange_rate),
                exchange_rate_date=when, notes="Imported from My Financial Life",
                tax_treatment=a.tax_treatment or "")
            local = f"InvestmentAccount_{n}"
        _write_provenance(local, a.source_app, a.source_ref, when)
        res.created += 1
        res.details.append(f"created {a.kind} '{a.name}' as {local}")

    # --- Physical assets ---
    for asset in plan.assets:
        if asset.source_ref in existing:
            _refresh_balance(existing[asset.source_ref], float(asset.balance), when)
            _write_provenance(existing[asset.source_ref], asset.source_app, asset.source_ref, when)
            res.refreshed += 1
            res.details.append(f"refreshed asset '{asset.name}' → {asset.balance}")
            continue
        n = _next_asset_n(asset.subclass)
        save_asset(
            subclass=asset.subclass, n=n, name=asset.name,
            current_value=float(asset.balance), balance_date=when,
            currency_local=asset.currency, exchange_rate=1.0, exchange_rate_date=when,
            notes="Imported from My Financial Life",
            appreciation_rate=("" if asset.appreciation_rate is None else str(asset.appreciation_rate)))
        local = f"{asset.subclass}_{n}"
        _write_provenance(local, asset.source_app, asset.source_ref, when)
        res.created += 1
        res.details.append(f"created asset '{asset.name}' as {local}")

    # --- Budget lines (loans + spending) — create-only on refresh ---
    for b in plan.budget_lines:
        if b.source_ref in existing:
            res.budget_skipped_existing += 1
            res.details.append(f"kept existing budget line '{b.name}' (user-owned)")
            continue
        n = next_n(get_all_budget_lines())
        segment = {
            "start_year": b.from_year,
            "end_year": b.to_year,
            "amount": float(b.monthly_amount),
            "frequency": "FrequencyType_Monthly",
            "change_rate": 0,
        }
        save_budget_line_segments(
            n=n, name=b.name, line_type=b.line_type,
            category_name=(b.category_name or ""), segments=[segment])
        local = f"BudgetLine_{n}"
        _write_provenance(local, b.source_app, b.source_ref, when)
        res.created += 1
        res.details.append(f"created budget line '{b.name}' as {local}")

    return res
