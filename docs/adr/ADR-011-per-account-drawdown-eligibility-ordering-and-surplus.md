# ADR-011: Per-Account Drawdown Eligibility, Ordering, and Surplus Handling

**Date:** 2026-05-17
**Status:** Accepted
**Deciders:** Project owner

---

## Context

The v0.2 projection engine treats all accounts as a merged balance pool drawn down
as a single unit. This is adequate for estimating overall retirement viability but
does not model:

- Account-specific access restrictions — a pension that cannot be accessed before
  age 57, or a fixed-term savings bond with a maturity date, must not appear in the
  drawdown pool until eligible.
- The order or proportion in which accounts should be drawn — e.g. draw from a GIA
  before an ISA for tax efficiency, or draw proportionally across all accounts to
  maintain a target allocation.
- Where the drawn cash lands — a designated spending account receives the drawdown;
  the user should not have to think about which account covers daily spending.
- Surplus handling — when projected spending is below budget in a given year, the
  underspend should either be swept to a savings account or cause drawdown to be
  reduced so more money stays invested.

These are among the defining decisions in real retirement income planning. The
application cannot give meaningful drawdown guidance without modelling them.

---

## Decision

### 1. Drawdown eligibility per account

The following properties are added to `mrl:Account` and inherited by all subtypes:

| Property | Type | Purpose |
|---|---|---|
| `mrl:drawdownMinAge` | `xsd:decimal` | Minimum age at which this account may be drawn. Decimal to support fractional ages (e.g. 59.5 for US 401(k), 57.0 for UK pension post-2028). |
| `mrl:drawdownMaxAge` | `xsd:decimal` | Optional maximum age. |
| `mrl:drawdownEarliestDate` | `xsd:date` | Fixed-term start date; account cannot be accessed before this date. Takes precedence over `drawdownMinAge` when set. |
| `mrl:drawdownLatestDate` | `xsd:date` | Maturity or expiry date after which the account should be drawn down or closed. |

The projection engine filters the eligible account set each year before computing
drawdown. An account is eligible in year Y if:

- `drawdownMinAge` is absent, OR `person_age_in_year_Y ≥ drawdownMinAge`
- `drawdownMaxAge` is absent, OR `person_age_in_year_Y ≤ drawdownMaxAge`
- `drawdownEarliestDate` is absent, OR `Y ≥ year(drawdownEarliestDate)`
- `drawdownLatestDate` is absent, OR `Y ≤ year(drawdownLatestDate)`

### 2. Drawdown ordering and ratio

The existing `mrl:drawdownPriority` (xsd:integer, lower number = drawn first) is
retained. A new `mrl:drawdownRatio` (xsd:decimal, 0.0–1.0) supports proportional
strategies.

`mrl:drawdownStrategy` on `mrl:ProjectionSettings` selects the strategy from
`mrlx:DrawdownStrategyScheme`:

| Concept | Behaviour |
|---|---|
| `mrlx:DrawdownStrategy_Waterfall` | Drain the lowest-priority-numbered eligible account until exhausted, then move to the next. Suitable for tax-sequencing strategies (e.g. GIA before ISA before pension). |
| `mrlx:DrawdownStrategy_Proportional` | Draw from all eligible accounts simultaneously. Each account's `drawdownRatio` values are normalised across eligible accounts each year so ratios always sum to 1.0. Suitable for maintaining a target allocation. |

### 3. Spending account

`mrl:spendingAccount` on `mrl:ProjectionSettings` designates the account into which
all drawdown cash is deposited before being spent against the budget. This is
typically a current/checking account. The engine models the drawdown as a transfer
into this account; the budget lines then draw against it.

The user nominates the spending account during initial setup (accounts step of the
setup wizard). If not set, the engine falls back to drawing directly against budget
with no intermediate account, preserving v0.2 behaviour.

### 4. Surplus handling

When projected spending for a year is below the year's budget total, two strategies
are available via `mrl:surplusStrategy` on `mrl:ProjectionSettings`:

| Concept | Behaviour |
|---|---|
| `mrlx:SurplusStrategy_SweepToAccount` | Unspent drawdown is swept into `mrl:surplusAccount`. Builds a liquid cash buffer. If `surplusAccount` is not set, the surplus stays in the spending account. |
| `mrlx:SurplusStrategy_ReduceDrawdown` | Each eligible account's drawdown is reduced proportionally. Undrawn amounts remain invested, continuing to earn returns in their source accounts. Financially preferable when investment accounts are earning above cash rates. |

### 5. Life event account association

Two new properties are added to `mrl:LifeEvent`:

| Property | Purpose |
|---|---|
| `mrl:fundedByAccount` | For expenditure events: the account from which the cost is drawn. |
| `mrl:receivedByAccount` | For receipt/windfall events: the account that receives the funds. |

Both are optional. If absent, the engine applies the event amount to the general
pool using normal drawdown or surplus logic as appropriate.

---

## Consequences

- The setup wizard must prompt the user to designate a spending account and surplus
  strategy at the accounts step. These are added as optional fields rather than
  blocking the wizard so as not to overwhelm new users.
- The projection engine must resolve eligible accounts per year before computing
  drawdown (engine changes are covered in ADR-012).
- Drawdown ordering interacts with tax treatment (ADR-013) — the most tax-efficient
  order may differ from the user's stated priority. The engine does not reorder
  automatically; the user sets priorities with knowledge of their own situation.
- The life-events UI must present an account picker, populated from the user's
  account list, for both funded-by and received-by fields.
- The backup/restore (settings_route.py) must export and restore all new properties.

### Future considerations

- **Manual strategy** (`mrlx:DrawdownStrategy_Manual`) allowing explicit per-year
  drawdown amounts per account. Deferred; too complex for v0.3.
- **Tax-optimal automatic ordering** — compute the optimal drawdown sequence from
  tax treatment types (e.g. GIA before ISA before pension). Deferred to v0.4+;
  requires ADR-013 engine to be mature first.
- **Pension commencement lump sum modelling** — the 25% PCLS on UK pensions is a
  one-time event rather than an annual drawdown; currently approximated via
  `mrl:annualTaxFreeWithdrawal` and a life event. A dedicated PCLS model could be
  added in a future version.
