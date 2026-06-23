"""Verify src/mfl_import/reader.py against the public MFL demo (ADR-020, Phase 1).

Standalone, assertion-based (this project has no pytest harness — see
CLAUDE_CONTEXT). Reads the committed fixture ``tests/fixtures/mfl_public.mfl``
(the public "Jordan Avery" dataset) and checks the reader reproduces MFL's own
figures — including the bond (×10) and option (×100) price multipliers and the
top-level budget roll-up.

RUN (from the repo root):  python tools/verify_mfl_reader.py
"""
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.mfl_import.reader import read_snapshot

FIXTURE = ROOT / "tests" / "fixtures" / "mfl_public.mfl"

EXPECTED_BALANCES = {            # native account currency, current value
    "Everyday Current":    Decimal("1040.90"),
    "Emergency Fund":      Decimal("19041.85"),
    "Holiday Pot":         Decimal("2100.00"),
    "Aspire Rewards Card": Decimal("-218.26"),
    "Stocks & Shares ISA": Decimal("36796.19"),
    "US Brokerage":        Decimal("17030.54"),   # USD
    "Workplace Pension":   Decimal("87819.33"),
    "Home":                Decimal("315000.00"),
    "Car":                 Decimal("15500.00"),
    "Home Mortgage":       Decimal("-202400.42"),
    "Car Finance":         Decimal("-6001.06"),
}


def main() -> int:
    if not FIXTURE.exists():
        print(f"FAIL: fixture not found at {FIXTURE}")
        return 1

    snap = read_snapshot(str(FIXTURE))
    checks: list[tuple[bool, str]] = []

    def check(cond, label):
        checks.append((bool(cond), label))

    check(snap.person_name == "Jordan Avery", f"person == Jordan Avery (got {snap.person_name!r})")
    check(snap.base_currency == "GBP", f"base currency GBP (got {snap.base_currency!r})")
    check(snap.schema_version == 31, f"schema v31 (got {snap.schema_version})")
    check(not snap.warnings, f"no warnings (got {snap.warnings})")
    check(len(snap.accounts) == 11, f"11 accounts (got {len(snap.accounts)})")

    by_name = {a.name: a for a in snap.accounts}
    for name, expected in EXPECTED_BALANCES.items():
        a = by_name.get(name)
        check(a is not None and a.balance == expected,
              f"{name} balance == {expected} (got {a.balance if a else 'MISSING'})")

    # Family mapping
    check(by_name["Home"].family == "property", "Home is property")
    check(by_name["Car"].family == "vehicle", "Car is vehicle")
    check(by_name["Aspire Rewards Card"].family == "credit", "Aspire card is credit")
    check(by_name["Home Mortgage"].family == "loan" and by_name["Home Mortgage"].loan is not None,
          "Home Mortgage is a loan with loan detail")
    check(by_name["Home Mortgage"].loan.monthly_payment == Decimal("1150.00"),
          f"mortgage payment 1150/mo (got {by_name['Home Mortgage'].loan.monthly_payment})")

    # Provenance keys present (for idempotent re-import)
    check(all(a.source_ref for a in snap.accounts), "every account has a source_ref")

    # Price multipliers (ADR-093): bond ×10, option ×100 on the US Brokerage
    us = by_name["US Brokerage"]
    bond = next((h for h in us.holdings if h.instrument_type == "bond"), None)
    opt = next((h for h in us.holdings if h.instrument_type == "option"), None)
    check(bond is not None and bond.market_value == Decimal("5042.00"),
          f"bond mv = 5 × 100.84 × 10 = 5042.00 (got {bond.market_value if bond else 'MISSING'})")
    check(opt is not None and opt.market_value == Decimal("1048.00"),
          f"option mv = 2 × 5.24 × 100 = 1048.00 (got {opt.market_value if opt else 'MISSING'})")

    # Investment value = cash leg + priced holdings (reconciles to the penny)
    check(us.balance == Decimal("17030.54"), "US Brokerage value reconciles")

    # Budget rolled up to top-level spending categories (not the kind-root)
    bud = {c.name: c for c in (snap.budget.categories if snap.budget else [])}
    check("Housing" in bud and bud["Housing"].monthly == Decimal("989.00"),
          f"budget Housing 989.00/mo (got {bud.get('Housing')})")
    check("Groceries" in bud and bud["Groceries"].monthly == Decimal("360.00"),
          f"budget Groceries 360.00/mo (got {bud.get('Groceries')})")
    check("Expense" not in bud and "Income" not in bud,
          "kind-roots (Expense/Income) are NOT top-level budget lines")
    check(any(c.kind == "income" for c in snap.budget.categories),
          "income categories tagged (Salary)")

    passed = sum(1 for ok, _ in checks if ok)
    for ok, label in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    print(f"\n{passed}/{len(checks)} checks passed")
    return 0 if passed == len(checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
