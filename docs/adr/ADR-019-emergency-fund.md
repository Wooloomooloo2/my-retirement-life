# ADR-019: Emergency fund — fill-first on surplus, draw-first on shortfall

**Date:** 2026-06-03
**Status:** Accepted
**Deciders:** Project owner

---

## Context

Tracing the "Jamie Smith" scenario showed a structural gap in how cash is
modelled. Income routed to the spending account is treated as cashflow (it
offsets the year's spending rather than crediting a balance — ADR-011 §5), and
any annual surplus is swept to the designated surplus account (often an
investment account). The result: the everyday cash accounts never accumulate a
buffer. They sit at their opening balances until the first year spending exceeds
income, then get wiped — and from then on shortfalls are met by liquidating
investments. There was no way to model the everyday-finance staple of an
**emergency fund**: a pot of cash you build up and draw on first.

## Options considered

- **Sweep-fill only.** Surplus tops the fund up to a target, but the fund is
  drawn at its normal priority. Simpler, but it doesn't make the fund behave as
  a buffer — a shortfall could still hit investments while cash sits idle.
- **Fill-first on surplus AND draw-first on shortfall (chosen).** The fund is
  both built up preferentially and spent down preferentially — which is what an
  emergency fund actually is.

For the target size: a **fixed cash amount** is simple but erodes with inflation
over a multi-decade projection; **months of spending** auto-scales with
inflation and budget changes and matches the familiar "3–6 months of expenses"
rule. Months of spending was chosen.

## Decision

Two new properties on `mrl:ProjectionSettings` (ontology **1.0.7**):

- **`mrl:emergencyFundAccount`** (object → `mrl:Account`) — the account used as
  the emergency fund.
- **`mrl:emergencyFundMonths`** (`xsd:decimal`) — the target size in months of
  that year's **recurring** spending (mandatory + discretionary + loan budget;
  one-off life events are excluded). Target = `months / 12 × recurring_spend`.

Engine behaviour each year (`_simulate_run`):

- **Fill-first.** Whenever surplus is swept (the normal below-budget surplus and
  the after-tax proceeds of a forced/RMD withdrawal, ADR-018), it first tops the
  emergency-fund account up toward its target; only the overflow continues to
  the surplus account (via the existing fallback chain).
- **Draw-first.** In a shortfall year the emergency-fund account is drawn down
  before the chosen drawdown strategy (Waterfall/Proportional) runs on the rest,
  provided it is eligible (`_is_eligible`) and has a balance.

## Consequences

- **A real cash buffer is now expressible.** Surplus builds the fund up to N
  months of spend; spikes and shortfalls drain the buffer before any investment
  is liquidated — smoothing exactly the failure seen in Jamie's plan.
- **Target tracks reality.** Because it is months-of-spending, the buffer grows
  with inflation and with life-stage budget changes; no manual re-tuning.
- **Parity preserved.** With no `emergencyFundAccount` set, both paths are
  no-ops and engine output is byte-identical to the post-ADR-018 engine.
- **Requires `tools/reload_ontology.py`** (app closed) for the new properties to
  appear in the live store; backend writes do not depend on the declaration.
- **Interaction with routing/RMD is intentional:** the fund is filled from the
  same sweep that feeds the surplus account, and from RMD proceeds; it is drawn
  ahead of the strategy but still respects account eligibility (a restricted
  account chosen as the fund is simply skipped until eligible).
- **The fund is one account.** Splitting a buffer across several accounts, or a
  fixed-amount alternative target, are possible future refinements.
