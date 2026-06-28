"""Verify ADR-020 Phase 3 (persistence) against an isolated store.

Create path, idempotent re-import (no duplicates), and the key guarantee:
a user-entered field survives a refresh while the imported balance updates.
RUN:  python tools/verify_mfl_apply.py   (uses an isolated temp DATA_DIR)
"""
import os, tempfile, sys
from pathlib import Path
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="mrl-applytest-")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pyoxigraph as og
from src.store.graph import store, MRL, DATA_GRAPH
from src.store.ontology_loader import load_ontology
load_ontology(store.store, force=True)

from src.mfl_import.reader import read_snapshot
from src.mfl_import.mapping import build_plan
from src.mfl_import.apply import apply_plan, _find_imported
from src.api.routes.accounts import get_all_accounts, get_all_asset_accounts
from src.api.routes.investments import get_all_investment_accounts
from src.api.routes.budget import get_all_budget_lines

FIX = str(ROOT / "tests" / "fixtures" / "mfl_public.mfl")
checks = []
def check(c, label): checks.append((bool(c), label))

def read_one(iri_local, prop):
    for q in store.store.quads_for_pattern(
        og.NamedNode(f"{MRL}{iri_local}"), og.NamedNode(f"{MRL}{prop}"), None, DATA_GRAPH):
        return q.object.value
    return None

# --- First import (empty store) ---
plan = build_plan(read_snapshot(FIX), current_year=2026)
r1 = apply_plan(plan, imported_at="2026-06-23")
check(r1.created == 20, f"first import creates 20 entities (got {r1.created})")
check(len(get_all_accounts()) == 3, f"3 cash accounts (got {len(get_all_accounts())})")
check(len(get_all_investment_accounts()) == 3, f"3 investment accounts (got {len(get_all_investment_accounts())})")
check(len(get_all_asset_accounts()) == 2, f"2 physical assets (got {len(get_all_asset_accounts())})")
check(len(get_all_budget_lines()) == 12, f"12 budget lines (got {len(get_all_budget_lines())})")
check(len(_find_imported()) == 20, f"20 provenance refs recorded (got {len(_find_imported())})")

# Find the Workplace Pension investment account's local name
inv = {a["name"]: a for a in get_all_investment_accounts()}
wp_n = inv["Workplace Pension"]["n"]
wp_local = f"InvestmentAccount_{wp_n}"
check(read_one(wp_local, "importSourceApp") == "MFL", "imported account stamped importSourceApp=MFL")
check(read_one(wp_local, "importedAt") == "2026-06-23", "imported account stamped importedAt")
orig_balance = read_one(wp_local, "accountBalance")

# --- Simulate a USER EDIT after import: set a growth rate the wizard left blank ---
store.update(f"""PREFIX mrl: <{MRL}> PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
  DELETE WHERE {{ GRAPH <{DATA_GRAPH.value}> {{ <{MRL}{wp_local}> mrl:annualGrowthRate ?g . }} }}""")
store.update(f"""PREFIX mrl: <{MRL}> PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
  INSERT DATA {{ GRAPH <{DATA_GRAPH.value}> {{ <{MRL}{wp_local}> mrl:annualGrowthRate "5.0"^^xsd:decimal . }} }}""")

# --- Re-import with a CHANGED balance for the same account ---
for a in plan.accounts:
    if a.name == "Workplace Pension":
        from decimal import Decimal
        a.balance = Decimal("99999.99")
r2 = apply_plan(plan, imported_at="2026-06-24")
check(r2.created == 0, f"re-import creates nothing (got {r2.created})")
check(r2.refreshed == 8, f"re-import refreshes 8 accounts+assets (got {r2.refreshed})")
check(r2.budget_skipped_existing == 12, f"re-import keeps 12 user-owned budget lines (got {r2.budget_skipped_existing})")
# No duplicates
check(len(get_all_investment_accounts()) == 3, f"still 3 investment accounts after re-import (got {len(get_all_investment_accounts())})")
check(len(get_all_budget_lines()) == 12, f"still 12 budget lines after re-import (got {len(get_all_budget_lines())})")
check(len(_find_imported()) == 20, f"still 20 provenance refs (got {len(_find_imported())})")
# The key guarantee: balance refreshed, user growth rate preserved
new_balance = read_one(wp_local, "accountBalance")
check(str(new_balance) == "99999.99", f"balance refreshed to 99999.99 (got {new_balance}, was {orig_balance})")
_gr = read_one(wp_local, "annualGrowthRate")
check(_gr is not None and float(_gr) == 5.0, f"user-set growth rate preserved (got {_gr})")
check(read_one(wp_local, "importedAt") == "2026-06-24", "importedAt advanced to re-import date")

passed = sum(1 for ok,_ in checks if ok)
for ok,l in checks: print(f"  [{'PASS' if ok else 'FAIL'}] {l}")
print(f"\n{passed}/{len(checks)} checks passed")
sys.exit(0 if passed==len(checks) else 1)
