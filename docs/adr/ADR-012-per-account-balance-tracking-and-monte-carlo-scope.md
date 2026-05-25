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

σ (return volatility) applies only to investment account growth. Cash accounts grow
at their fixed interest rate in every simulation — cash savings rates are predictable
and modelling them with equity σ would overstate uncertainty for cash-heavy
portfolios.

A user whose wealth is entirely in cash accounts has no stochastic component, so
Monte Carlo is suppressed for that case (the deterministic projection is the answer).
A user with mixed cash and investments sees a Monte Carlo band that reflects
investment uncertainty layered on top of the deterministic cash trajectory.

**[Updated 2026-05-25, see §4 below]** Monte Carlo and deterministic engines now
share a single year-loop helper (`_simulate_run`). MC is N runs of that helper with
random per-year shocks on investment growth and inflation; the deterministic engine
is one run with zero shocks. This means MC inherits drawdown eligibility (ADR-011),
two-layer tax (ADR-013), contributions (ADR-015), and life-event account routing —
all consistent with the deterministic engine, year by year, account by account.

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

### 4. Monte Carlo engine — shared with deterministic engine (revised 2026-05-25)

Both engines call one helper, `_simulate_run`, which runs a single year-loop with
per-account balance tracking. The helper takes optional per-year shock arrays:

- `return_shocks[y]` — additive perturbation (in %) on each investment account's
  effective growth rate for year `y`. The same shock is applied across all
  investment accounts in a given year (single market-wide move).
- `inflation_shocks[y]` — additive perturbation (in %) on the year's inflation
  rate, which feeds into budget growth via the `change_rate + inflation` rule.

```
deterministic:
  _simulate_run(..., return_shocks=zeros, inflation_shocks=zeros)

Monte Carlo (N runs):
  shocks ~ Normal(0, σ_profile)
  for sim in range(N):
      result = _simulate_run(..., return_shocks=shocks[sim], inflation_shocks=...)
      record result["years"][y]["balance"]
  compute P10/P50/P90 percentiles across sims, per year
  success_rate = % of sims where total balance > 0 in every year
```

Earlier (pre-2026-05-25) the MC engine was a separate aggregate-pool model — cash
grew deterministically as a "floor" while *all* spending hit a single investment
pool. That model was structurally inconsistent with the deterministic engine: it
ignored drawdown eligibility, tax, contributions, and life-event routing, and it
allowed the investment pool to go arbitrarily negative because cash was never
drained. This produced misleading success rates (often near 100% even when the
deterministic engine showed depletion). The current shared-helper approach removes
that discrepancy by construction.

**Performance note.** With the per-account loop in pure Python, N=250 simulations
over a 35-year horizon with ~10 accounts completes in under a second. This is the
new default `n_sims`. The legacy implementation used N=500 with a vectorised numpy
inner loop; trading some MC granularity for model coherence is a deliberate choice.
Should higher N be needed for tighter percentile estimates, the inner year-loop is
the obvious vectorisation target.

### 5. Per-account history surfaces in results

The simulation result includes per-account history arrays for balance, withdrawal,
return, and contribution. The deterministic projection's result keys (e.g.
`account_balances`, `account_withdrawals`) are unchanged from earlier versions of
this ADR.

### 6. Supersession of ADR-009

ADR-009 stated: "Investment accounts [are] merged into total balance pool."
This ADR supersedes that decision for **both** engines. The Monte Carlo no longer
operates on a separate pool — it runs the same per-account simulation as the
deterministic engine, with stochastic shocks layered on investment growth.

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
