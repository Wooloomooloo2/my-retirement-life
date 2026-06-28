"""Verify src/mfl_import/mapping.py against the public MFL demo (ADR-020, Phase 2).

Standalone, assertion-based. Reads the committed fixture, builds the import plan,
and checks the MFL→MRL mapping decisions: families routed correctly, investments
flagged for a rate, USD account flagged for FX, loans turned into budget lines
with the right window, budget categories typed, and credit/income skipped.

RUN:  python tools/verify_mfl_mapping.py
"""
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.mfl_import.reader import read_snapshot
from src.mfl_import.mapping import build_plan

FIXTURE = ROOT / "tests" / "fixtures" / "mfl_public.mfl"


def main() -> int:
    if not FIXTURE.exists():
        print(f"FAIL: fixture not found at {FIXTURE}")
        return 1

    plan = build_plan(read_snapshot(str(FIXTURE)), current_year=2026)
    checks: list[tuple[bool, str]] = []

    def check(cond, label):
        checks.append((bool(cond), label))

    s = plan.summary()
    check(plan.person_name == "Jordan Avery", "person Jordan Avery")
    check(plan.base_currency == "GBP", "base GBP")
    check(s["accounts"] == 6, f"6 accounts (3 cash + 3 investment) (got {s['accounts']})")
    check(s["assets"] == 2, f"2 physical assets (got {s['assets']})")
    check(s["budget_lines"] == 12, f"12 budget lines (2 loans + 10 expense) (got {s['budget_lines']})")
    check(s["skipped"] == 2, f"2 skipped (credit card + income) (got {s['skipped']})")
    check(s["needs_rate"] == 3, f"3 investments need a growth rate (got {s['needs_rate']})")
    check(s["needs_fx"] == 1, f"1 account needs FX confirmation (got {s['needs_fx']})")

    acc = {a.name: a for a in plan.accounts}
    # Cash typing
    check(acc["Everyday Current"].account_type == "CashAccountType_Current", "Everyday Current → Current")
    check(acc["Emergency Fund"].account_type == "CashAccountType_Savings", "Emergency Fund → Savings")
    # Investment typing + tax suggestion + rate flag
    check(acc["Stocks & Shares ISA"].account_type == "InvestmentAccountType_TaxAdvantaged"
          and acc["Stocks & Shares ISA"].tax_treatment == "TaxTreatment_TaxFree",
          "S&S ISA → TaxAdvantaged / TaxFree")
    check(acc["Workplace Pension"].account_type == "InvestmentAccountType_WorkPension"
          and acc["Workplace Pension"].tax_treatment == "TaxTreatment_PostTaxTaxFreeWithdrawal",
          "Workplace Pension → WorkPension / PCLS")
    check(acc["US Brokerage"].account_type == "InvestmentAccountType_StocksShares"
          and acc["US Brokerage"].tax_treatment == "TaxTreatment_PostTaxGainsOnly",
          "US Brokerage → StocksShares / GainsOnly")
    check(acc["US Brokerage"].needs_fx and acc["US Brokerage"].currency == "USD",
          "US Brokerage (USD) flagged needs_fx")
    check(all(a.needs_rate for a in plan.accounts if a.kind == "investment"),
          "all investments flagged needs_rate")
    check(all(a.growth_rate is None for a in plan.accounts if a.kind == "investment"),
          "no investment growth rate guessed")
    check(all(a.source_ref for a in plan.accounts), "every account has provenance source_ref")

    # Physical assets
    assets = {a.name: a for a in plan.assets}
    check(assets["Home"].subclass == "PropertyAsset", "Home → PropertyAsset")
    check(assets["Car"].subclass == "VehicleAsset", "Car → VehicleAsset")

    # Loans → budget lines
    bl = {b.name: b for b in plan.budget_lines}
    mort = bl.get("Home Mortgage")
    check(mort is not None and mort.line_type == "BudgetLineType_Loan", "Home Mortgage → Loan line")
    check(mort and mort.monthly_amount == Decimal("1150.00"), f"mortgage £1150/mo (got {mort.monthly_amount if mort else '—'})")
    check(mort and mort.from_year == 2025 and mort.to_year == 2049,
          f"mortgage window 2025–2049 (got {mort.from_year}–{mort.to_year})")
    check(mort and not mort.needs_amount, "mortgage amount known")
    car = bl.get("Car Finance")
    check(car is not None and car.needs_amount, "Car Finance flagged needs_amount (no payment in MFL)")

    # Budget categories typed + amount carried through
    house = bl.get("Housing")
    check(house and house.line_type == "BudgetLineType_Mandatory" and house.monthly_amount == Decimal("989.00"),
          f"Housing → Mandatory £989/mo (got {house.line_type if house else '—'}, {house.monthly_amount if house else '—'})")
    dining = bl.get("Dining out")
    check(dining and dining.line_type == "BudgetLineType_Discretionary", "Dining out → Discretionary")
    check(all(b.from_year == 2026 for b in plan.budget_lines if b.source_kind == "budget"),
          "budget lines default from current year (2026)")

    # Skips
    skip_names = {x.name for x in plan.skipped}
    check("Aspire Rewards Card" in skip_names, "credit card skipped")
    check(any("Salary" in n for n in skip_names), "budget income (Salary) skipped")

    passed = sum(1 for ok, _ in checks if ok)
    for ok, label in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    print(f"\n{passed}/{len(checks)} checks passed")
    return 0 if passed == len(checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
