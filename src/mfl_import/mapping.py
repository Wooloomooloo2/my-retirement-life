"""Map an MFL snapshot onto proposed MRL entities (ADR-020, Phase 2).

Pure transform — no store writes, no Date.now/randomness. Takes the
:class:`~src.mfl_import.reader.MflSnapshot` from Phase 1 and produces an
:class:`ImportPlan`: the MRL accounts, physical assets, loan→budget lines and
budget lines the wizard will review before anything is written. Every proposed
entity carries an `mrl:importSourceRef` so a later re-import can match and
update it instead of duplicating (ADR-020 idempotent refresh).

Decisions encoded (per ADR-020):
- cash/investment → MRL accounts; property/vehicle → physical assets;
  loan → a `BudgetLineType_Loan` budget line; credit cards → skipped.
- investment growth/dividend rates are **left unset and flagged** — MFL holds no
  forward assumptions, so the wizard must collect them.
- budget categories arrive already rolled up to top level (reader); expense
  categories → spending lines, budget INCOME categories → MRL IncomeSource
  entities (income is first-class in MRL, so it is imported, not dropped).
- FX for non-base currencies is flagged for confirmation rather than guessed.
The wizard owns the from/to range and any stage (segment) edits for budget
lines; this layer proposes a sensible default (from the current year, ongoing).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Optional

from src.mfl_import.reader import MflSnapshot, MflAccount


# --- MRL vocab (local names; see docs/ontology/mrl-ontology.ttl) ------------
_CASH_TYPE = {"cash_std": "CashAccountType_Current",
              "savings_std": "CashAccountType_Savings"}
_ASSET_SUBCLASS = {"property": "PropertyAsset", "vehicle": "VehicleAsset"}

# Light heuristics so the wizard starts from a sensible guess the user can edit.
_MANDATORY_HINTS = {"housing", "utilities", "groceries", "healthcare", "health",
                    "insurance", "transport", "childcare", "education",
                    "council tax", "rent", "mortgage", "bills"}


def _investment_type(name: str) -> str:
    n = name.lower()
    if "sipp" in n:
        return "InvestmentAccountType_Pension"
    if "pension" in n:
        return "InvestmentAccountType_WorkPension"
    if "isa" in n:
        return "InvestmentAccountType_TaxAdvantaged"
    return "InvestmentAccountType_StocksShares"


def _suggested_tax_treatment(inv_type: str) -> str:
    return {
        "InvestmentAccountType_TaxAdvantaged": "TaxTreatment_TaxFree",
        "InvestmentAccountType_WorkPension":   "TaxTreatment_PostTaxTaxFreeWithdrawal",
        "InvestmentAccountType_Pension":       "TaxTreatment_PostTaxTaxFreeWithdrawal",
    }.get(inv_type, "TaxTreatment_PostTaxGainsOnly")


def _budget_line_type(category_name: str) -> str:
    n = category_name.lower()
    if any(h in n for h in _MANDATORY_HINTS):
        return "BudgetLineType_Mandatory"
    return "BudgetLineType_Discretionary"


# MFL income category name → MRL IncomeSource type (best-guess; wizard-editable).
_INCOME_TYPE_HINTS = [
    (("salary", "wage", "payroll", "employment", "pay"), "IncomeSourceType_Employment"),
    (("rent", "rental", "letting", "tenant"),            "IncomeSourceType_Property"),
    (("pension", "annuity", "retirement", "state pension"), "IncomeSourceType_Retirement"),
    (("dividend",),                                       "IncomeSourceType_Investment"),
    (("interest",),                                       "IncomeSourceType_InterestIncome"),
    (("business", "self-employ", "self employ", "freelance", "consult"),
                                                          "IncomeSourceType_BusinessIncome"),
]


def _income_type(name: str) -> str:
    n = (name or "").lower()
    for keys, t in _INCOME_TYPE_HINTS:
        if any(k in n for k in keys):
            return t
    return "IncomeSourceType_Other"


# --- Proposed-entity dataclasses --------------------------------------------
@dataclass
class ProposedAccount:
    kind: str                     # 'cash' | 'investment'
    name: str
    balance: Decimal
    currency: str
    account_type: str             # MRL accountType local name
    exchange_rate: Decimal        # to base; 1.0 when same currency
    needs_fx: bool                # True when currency != base and rate unconfirmed
    tax_treatment: Optional[str]
    growth_rate: Optional[float]  # investment only; None ⇒ wizard must collect
    dividend_rate: Optional[float]
    needs_rate: bool              # investment only — growth/dividend unset
    source_ref: str
    interest_rate: Optional[float] = None  # cash only; None ⇒ wizard collects (default 0)
    source_app: str = "MFL"


@dataclass
class ProposedAsset:
    subclass: str                 # PropertyAsset | VehicleAsset
    name: str
    balance: Decimal
    currency: str
    appreciation_rate: Optional[float]   # None ⇒ wizard may collect (default 0)
    source_ref: str
    source_app: str = "MFL"


@dataclass
class ProposedBudgetLine:
    name: str
    line_type: str                # BudgetLineType_*
    category_name: Optional[str]
    monthly_amount: Decimal
    from_year: int
    to_year: Optional[int]        # None ⇒ ongoing
    source_ref: str
    source_kind: str              # 'budget' | 'loan'
    needs_amount: bool = False    # loan with no recorded payment
    source_app: str = "MFL"


@dataclass
class ProposedIncome:
    name: str
    income_type: str              # IncomeSourceType_* (best-guess from the name)
    annual_amount: Decimal
    currency: str                 # base currency — MFL budget income is in base
    source_ref: str
    source_app: str = "MFL"


@dataclass
class SkippedItem:
    name: str
    reason: str


@dataclass
class ImportPlan:
    person_name: str
    base_currency: str
    accounts: list[ProposedAccount] = field(default_factory=list)
    assets: list[ProposedAsset] = field(default_factory=list)
    income: list[ProposedIncome] = field(default_factory=list)
    budget_lines: list[ProposedBudgetLine] = field(default_factory=list)
    skipped: list[SkippedItem] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def summary(self) -> dict:
        return {
            "accounts": len(self.accounts),
            "assets": len(self.assets),
            "income": len(self.income),
            "budget_lines": len(self.budget_lines),
            "skipped": len(self.skipped),
            "needs_rate": sum(1 for a in self.accounts if a.needs_rate),
            "needs_fx": sum(1 for a in self.accounts if a.needs_fx),
        }


# --- FX -----------------------------------------------------------------
def _exchange_rate(currency: str, base: str, fx_rates: dict) -> tuple[Decimal, bool]:
    """Best-effort MRL exchangeRateToBase (base per 1 unit of `currency`).

    MFL's fx_rate direction isn't relied upon — when the currency differs from
    base we surface a suggestion if derivable but flag it for confirmation, since
    getting the direction wrong silently distorts every balance (ADR-020).
    """
    if currency == base:
        return Decimal("1.0"), False
    # Try both orientations; treat whichever is present as a *suggestion only*.
    rate = fx_rates.get((base, currency)) or fx_rates.get((currency, base))
    if rate:
        return Decimal(str(rate)), True   # suggested, still needs confirmation
    return Decimal("1.0"), True


# --- Build the plan ---------------------------------------------------------
def build_plan(snapshot: MflSnapshot, current_year: Optional[int] = None) -> ImportPlan:
    if current_year is None:
        current_year = date.today().year
    base = snapshot.base_currency
    plan = ImportPlan(person_name=snapshot.person_name, base_currency=base,
                      warnings=list(snapshot.warnings))

    for a in snapshot.accounts:
        if a.family == "cash":
            rate, needs_fx = _exchange_rate(a.currency, base, snapshot.fx_rates)
            plan.accounts.append(ProposedAccount(
                kind="cash", name=a.name, balance=a.balance, currency=a.currency,
                account_type=_CASH_TYPE.get(a.type, "CashAccountType_Current"),
                exchange_rate=rate, needs_fx=needs_fx,
                tax_treatment="TaxTreatment_TaxFree",
                growth_rate=None, dividend_rate=None, needs_rate=False,
                source_ref=a.source_ref))

        elif a.family == "investment":
            inv_type = _investment_type(a.name)
            rate, needs_fx = _exchange_rate(a.currency, base, snapshot.fx_rates)
            plan.accounts.append(ProposedAccount(
                kind="investment", name=a.name, balance=a.balance, currency=a.currency,
                account_type=inv_type, exchange_rate=rate, needs_fx=needs_fx,
                tax_treatment=_suggested_tax_treatment(inv_type),
                growth_rate=None, dividend_rate=None, needs_rate=True,
                source_ref=a.source_ref))

        elif a.family in _ASSET_SUBCLASS:
            plan.assets.append(ProposedAsset(
                subclass=_ASSET_SUBCLASS[a.family], name=a.name, balance=a.balance,
                currency=a.currency, appreciation_rate=None, source_ref=a.source_ref))

        elif a.family == "loan":
            plan.budget_lines.append(_loan_to_budget_line(a, current_year))

        elif a.family == "credit":
            plan.skipped.append(SkippedItem(
                a.name, "Credit-card balance — revolving debt isn't modelled in a "
                        "retirement projection."))
        else:
            plan.skipped.append(SkippedItem(a.name, f"Unsupported account family '{a.family}'."))

    # Budget: expense categories → spending lines; income categories → MRL
    # IncomeSource entities (MRL models income as a first-class concept, so they
    # are imported, not dropped). The wizard can edit type/amount before applying.
    if snapshot.budget:
        for c in snapshot.budget.categories:
            if c.kind == "income":
                if c.annual and c.annual > 0:
                    plan.income.append(ProposedIncome(
                        name=c.name, income_type=_income_type(c.name),
                        annual_amount=c.annual, currency=base,
                        source_ref=f"income:{c.name}"))
                continue
            if c.kind not in ("expense", ""):
                continue   # transfers / interest-only buckets aren't spending lines
            plan.budget_lines.append(ProposedBudgetLine(
                name=c.name, line_type=_budget_line_type(c.name),
                category_name=c.name, monthly_amount=c.monthly,
                from_year=current_year, to_year=None,
                source_ref=f"budget:{c.name}", source_kind="budget"))

    if plan.income:
        plan.warnings.append(
            "Imported income is treated as net (take-home) and ongoing with no end "
            "year — review each source under Income (set an end year for employment "
            "that stops at retirement, and confirm net vs gross).")

    return plan


def _loan_to_budget_line(a: MflAccount, current_year: int) -> ProposedBudgetLine:
    loan = a.loan
    from_year = current_year
    to_year: Optional[int] = None
    monthly = Decimal("0.00")
    needs_amount = True
    if loan is not None:
        if loan.start_date and len(loan.start_date) >= 4 and loan.start_date[:4].isdigit():
            from_year = int(loan.start_date[:4])
        if loan.term_months:
            # inclusive final year of the repayment window
            to_year = from_year + (int(loan.term_months) - 1) // 12
        if loan.monthly_payment and loan.monthly_payment > 0:
            monthly = loan.monthly_payment
            needs_amount = False
    return ProposedBudgetLine(
        name=a.name, line_type="BudgetLineType_Loan", category_name=None,
        monthly_amount=monthly, from_year=from_year, to_year=to_year,
        source_ref=a.source_ref, source_kind="loan", needs_amount=needs_amount)
