# ADR-012: Discrete Per-Account Balance Tracking and Revised Monte Carlo Scope

**Date:** 2026-05-17
**Status:** Accepted
**Deciders:** Project owner

---

## Context

ADR-009 merged all accounts into a single balance pool for projection. This was a
pragmatic choice for v0.2 that has three limitations now being addressed:

1. **No per-account visibility.** The projection chart shows only a total balance
   line. Users cannot see how individual accounts evolve — which ones are depleting,
   which are growing, or when a restricted account becomes accessible.

2. **Incorrect Monte Carlo scope.** The simulation applies equity-style return
   volatility (σ) to the entire blended balance, including cash accounts. Cash
   savings rates are predictable; modelling them with equity σ overstates uncertainty
   for cash-heavy portfolios and is financially incorrect.

3. **Eligibility-gated drawdown requires per-account balances.** ADR-011 requires
   the engine to track each account independently so it can apply eligibility filters
   and draw from the correct accounts each year.

---

## Decision

### 1. Deterministic engine: per-account balance tracking

The deterministic projection engine is refactored to track each account's balance
as a separate scalar per year. The aggregate total (shown in the aggregate chart
view) is the sum across all accounts.

Per-account processing each year, in order:

1. Apply the account's own growth/dividend rate to its opening balance.
2. Determine eligibility per ADR-011 rules.
3. Draw the account's share of the year's spending shortfall, per the drawdown
   strategy (ADR-011). Tax is applied at point of withdrawal per ADR-013.
4. If a surplus exists (spending < budget), apply the surplus strategy (ADR-011).
5. Apply life event amounts to/from specific accounts where `fundedByAccount` or
   `receivedByAccount` is set.
6. Record the closing balance.

The engine return type changes from a single balance array to a structured result:

```python
{
  "accounts": {
      "mrl:CashAccount_1": [year0_bal, year1_bal, ...],
      "mrl:InvestmentAccount_2": [year0_bal, year1_bal, ...],
      ...
  },
  "total": [year0_total, year1_total, ...],
  "tax_paid": [year0_tax, year1_tax, ...]   # annual net tax figure for display
}
```

### 2. Monte Carlo scope: investment accounts only

Cash accounts have deterministic trajectories and are excluded from the Monte Carlo
simulation. The simulation runs on the **investment account pool only**.

- Cash account balances are computed once, deterministically, per simulation year.
- Monte Carlo generates P10/P50/P90 bands for the investment account pool under
  the selected profile's σ (standard deviation of returns).
- The total displayed on the aggregate chart = deterministic cash balance + investment
  P10/P50/P90 at each year.

This is financially correct: outcome uncertainty in retirement comes predominantly
from investment return volatility, not from cash savings interest rate variation.

A user whose wealth is entirely in cash accounts will show a narrow, deterministic
confidence band — which is accurate. Their risk is drawdown rate vs interest rate,
not market volatility.

### 3. Projection chart modes

The projection chart gains two display modes, toggled by the user:

**Aggregate view** (default, matches current behaviour):
- Total balance as a single area, with P10/P50/P90 Monte Carlo band for the
  investment portion. Cash balance is shown as a deterministic floor layer.

**By Account view** (new):
- Stacked area chart showing each account's closing balance per year (deterministic).
- Monte Carlo bands are shown per investment account rather than total.
- A toggle reveals the secondary drawdown-vs-growth chart (see below).

**Secondary: Drawdown vs Growth chart (per account):**
For each investment account, plots two lines per year:
- Annual drawdown amount taken from this account.
- Annual return earned on this account's opening balance.
Where drawdown > return, the account is depleting. The crossover point is explicitly
marked. This makes the break-even dynamic visible without requiring the user to do
the arithmetic.

### 4. Monte Carlo engine changes

The existing engine pre-computes deterministic arrays for income, budget lines, and
life events before entering the simulation loop (for performance). Cash account
balances join this pre-computed deterministic layer. The simulation loop applies σ
only to the investment pool.

```
pre-computed (deterministic):
  annual_income[y], annual_budget[y], annual_events[y]
  cash_balance[y]   ← new: computed once before loop

simulation loop (500 iterations):
  invest_balance[y] ← perturbed by σ each year
  total[y] = cash_balance[y] + invest_balance[y]
```

P10/P50/P90 are computed on `total[y]` across the 500 simulations.

### 5. Supersession of ADR-009

ADR-009 stated: "Investment accounts [are] merged into total balance pool."
This ADR supersedes that decision for the **deterministic engine**. The Monte Carlo
continues to operate on a pool, now restricted to investment accounts only.

ADR-009's weighted return rate approach is retained for the investment pool: the
blended rate across investment accounts (weighted by opening balance) is used as the
mean return μ for the Monte Carlo, with the profile σ applied around it.

---

## Consequences

- `projection.py` is substantially refactored. The `run_projection()` and
  `run_monte_carlo()` functions change signatures; `projection.html` must be
  updated to handle the new result structure.
- The confidence score (Green/Amber/Red) continues to be computed on the aggregate
  total balance, unchanged in meaning.
- The ADR README must update ADR-009's consequence note to reference this ADR.

### Future considerations

- **Per-jurisdiction Monte Carlo profiles.** NZ, UK, and US equity markets have
  materially different historical return distributions (μ and σ). The current named
  profiles (Conservative/Moderate/Aggressive) are jurisdiction-agnostic global
  approximations. A future `mrl:MarketProfile` class linked from `mrl:Jurisdiction`
  could carry per-jurisdiction μ and σ, replacing or extending the current
  `mrlx:MonteCarloProfileScheme`. This is particularly relevant for a user with
  investments in multiple markets.
- **Per-investment-mix Monte Carlo.** A 70/30 equity/bond portfolio has different
  σ than 100% equity. `mrl:InvestmentAccount` already stores `annualGrowthRate`
  per account; a future enhancement could derive a weighted σ from the actual account
  mix rather than relying on a single user-selected profile.
- **Multiple Monte Carlo runs.** A user with accounts in different jurisdictions
  (e.g. UK ISA and US brokerage) may eventually want separate simulation runs per
  market, combined into a joint distribution. Deferred; requires the per-jurisdiction
  profile model above.
