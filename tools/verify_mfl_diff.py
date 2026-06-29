"""Verify ADR-020 Phase 5 (refresh diff) against an isolated store.
RUN:  python tools/verify_mfl_diff.py
"""
import os, tempfile, sys
from pathlib import Path
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="mrl-diff-")
ROOT = Path(__file__).resolve().parent.parent; sys.path.insert(0, str(ROOT))
from src.store.graph import store
from src.store.ontology_loader import load_ontology
load_ontology(store.store, force=True)
from src.mfl_import.reader import read_snapshot
from src.mfl_import.mapping import build_plan
from src.mfl_import.apply import apply_plan, compute_diff

FIX = str(ROOT / "tests/fixtures/mfl_public.mfl")
checks=[]
def chk(c,l): checks.append((bool(c),l))

# First import: everything is new
plan = build_plan(read_snapshot(FIX), current_year=2026)
d0 = compute_diff(plan)
chk(not d0["is_reimport"], "first import: not a re-import")
chk(d0["counts"]["new"] == 21, f"first import: 21 new (got {d0['counts']['new']})")
chk(d0["counts"]["update"] == 0 and d0["counts"]["keep"] == 0, "first import: nothing to update/keep")
chk(d0["counts"]["orphans"] == 0, "first import: no orphans")

apply_plan(plan, imported_at="2026-06-24")

# Re-import the same file: accounts+assets update, budget kept, no orphans
plan2 = build_plan(read_snapshot(FIX), current_year=2026)
d1 = compute_diff(plan2)
chk(d1["is_reimport"], "re-import: flagged as re-import")
chk(d1["counts"]["new"] == 0, f"re-import: 0 new (got {d1['counts']['new']})")
chk(d1["counts"]["update"] == 9, f"re-import: 9 to update — 6 accounts + 2 assets + 1 income (got {d1['counts']['update']})")
chk(d1["counts"]["keep"] == 12, f"re-import: 12 budget lines kept (got {d1['counts']['keep']})")
chk(d1["counts"]["orphans"] == 0, "re-import same file: no orphans")
# per-ref status spot checks
inv_ref = next(a.source_ref for a in plan2.accounts if a.name == "Workplace Pension")
bud_ref = next(b.source_ref for b in plan2.budget_lines if b.name == "Housing")
chk(d1["status"][inv_ref] == "update", "investment account → update")
chk(d1["status"][bud_ref] == "keep", "budget line → keep")

# An account dropped from the MFL file shows as an orphan (left untouched)
dropped = plan2.accounts[0]
plan2.accounts = plan2.accounts[1:]
d2 = compute_diff(plan2)
chk(d2["counts"]["orphans"] == 1, f"dropped account → 1 orphan (got {d2['counts']['orphans']})")
chk(any(dropped.name == o["name"] for o in d2["orphans"]), f"orphan is the dropped account '{dropped.name}'")

p=sum(1 for ok,_ in checks if ok)
for ok,l in checks: print(f"  [{'PASS' if ok else 'FAIL'}] {l}")
print(f"\n{p}/{len(checks)} checks passed")
sys.exit(0 if p==len(checks) else 1)
