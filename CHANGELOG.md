# Changelog

All notable changes to **My Retirement Life** are recorded here.
This project is pre-1.0; format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [Unreleased — per-line FX + inline live rates] — 2026-05-30

### Feature — Per-line currency on the budget

Budget lines now carry their own currency, alongside the existing per-account
and per-income-source currency support. A USD mortgage, a EUR subscription,
or a JPY rental cost can each live on the budget at their native amount and
get rolled up to your base currency for charts and projections.

The add/edit form has a new **Currency** dropdown (defaults to your base
currency); when it differs from base, an **Exchange rate to base** field
appears next to it with an inline **"Use live rate"** button. The budget
lines table shows the line's own currency symbol with a small
`USD @ 0.79 → £…` sub-line so the conversion is visible inline.

The chart computations and projection engine pre-multiply each segment's
amount by the line's FX rate at load — same pattern accounts and income
have used since ADR-016 — so all stacked-area bands, M/D/L totals, and
projection numbers roll up correctly in base currency.

**Backwards-compatible:** lines that existed before this change have no
FX triple and read as `1.0`, so existing plans produce bit-identical
numbers.

### Feature — Inline "Use live rate" on every FX field

The bulk "Refresh rates" buttons that already existed on the Accounts
and Income pages now have a companion: a per-row **"Use live rate"**
button next to the FX rate input on every edit form (accounts, income,
budget). Click it and the rate + date are populated in-place from
[open.er-api.com](https://www.exchangerate-api.com/) — no page reload,
no need to use the bulk action just to refresh one row.

A shared `GET /api/fx/rate?code=XYZ` JSON endpoint backs all three
inline buttons. The bulk action is still available on every page,
and the budget page now has its own
`POST /budget/refresh-rates` matching the accounts + income pattern.

### Ontology — version bumped to 1.0.5

Three new properties on `mrl:BudgetLine` —
`mrl:budgetLineCurrency` (object property → `mrl:Currency`),
`mrl:budgetLineExchangeRateToBase` (decimal), and
`mrl:budgetLineExchangeRateDate` (date). Same shape as the equivalent
properties on cash + investment accounts and on income sources.

**Run `python tools/reload_ontology.py` once (app closed)** to install
the 1.0.5 schema before exercising the budget change.

### Fixed

- **Income backup/restore round-trip.** Per-income-source currency, FX
  rate, FX-rate-date, and deposit account were silently dropped from
  every backup since those fields were introduced (ADR-016 2026-05-23,
  deposit account 2026-05-25). Affected plans with foreign-currency
  income or routed income would have all four fields wiped back to the
  engine defaults (base currency, unrouted income) on restore. The
  export now carries them, and restore writes them back. Pre-fix
  backups still restore cleanly — missing fields fall back to the same
  defaults as before.

---

## [Unreleased — budget restructure] — 2026-05-27

### Feature — Life-stage spending changes ("stages") in one line

A single budget line can now have **multiple time-bounded stages**, each with
its own amount, frequency, time window, and real-growth rate. Use it to model
spending that changes over your lifetime without splitting one logical line
into many — for example a single Groceries line covering £500/mo as a single
person, £1500/mo with kids for ~18 years, and £600/mo in empty-nest. The chart
shows it as one continuous band that steps up and down as the stages change.

**Gaps between stages are intentional** — they contribute £0 to the chart in
those years. Useful for "pause this category to free up cash" patterns: a
Travel line that drops to zero for two years while paying down a mortgage
faster shows up exactly as a Travel band that hits zero and resumes.

### Feature — User-defined budget categories

Budget lines can now be tagged with a **category** you create (Housing, Food,
Transport, etc.). There's no fixed list — type a name and the category is
created on save. The form offers nine starter chip suggestions (Housing,
Food, Transport, Travel, Health, Subscriptions, Personal, Bills, Taxes) but
these only materialise when you adopt one.

A new **"Manage categories"** card lets you rename or delete categories
inline — delete is refused while any line still references the category.

### Feature — Budget chart: by Category (default) / by Line

The budget chart now groups by **category** instead of by Mandatory /
Discretionary / Loans procedural type. Toggle to **Line** view to see one
band per budget line. Categories get deterministic colours (the same
category always renders in the same colour across sessions); the synthetic
"Account contributions" group stays pinned to teal; uncategorised lines
fall into a neutral gray "Uncategorised" group.

The line type (Mandatory / Discretionary / Loan) still drives engine
behaviour — loans skip inflation lift, Mandatory/Discretionary inflate —
but it's no longer a chart dimension. A mortgage now lives in **Housing**
alongside utilities and insurance, which is what most people mean.

### Feature — Budget chart: "With inflation" toggle

A new checkbox switches the chart between **today's £** (real terms,
default — preserves the long-standing planning-in-real-terms semantic) and
**nominal £ including inflation**. Nominal mode applies the projection's
inflation rate per year to non-loan bands and to contributions; loan bands
stay fixed-nominal because that's how the projection engine treats them.
The result: the budget chart and the projection page now agree on the same
numbers when you flip the toggle on.

### Engine — Budget engine reads segments

The projection engine (`run_projection` and `run_monte_carlo` via the
shared `_simulate_run` helper) now walks each line's stages instead of a
single line-level amount/window. **Single-stage lines are bit-identical to
the pre-1.0.2 engine** — growth exponent stays `years_from_start` and loan
inflation skip is preserved. Multi-stage lines compose cleanly: each
stage's amount is interpreted as "in today's £ at the projection start,
switched in at the stage's start year", inflated to the active year by
the engine.

### Ontology — version bumped to 1.0.2

ADR-017. Adds `mrl:BudgetCategory` (user-created class) and rebuilds the
post-MVP `mrl:BudgetLineSegment` stub into the real thing
(`segmentAmount`, `segmentFrequency`, `segmentChangeRate`,
`segmentStartYear`, `segmentEndYear`, `segmentOwner`). New
`mrl:budgetCategory` predicate on `BudgetLine`. Six legacy line-level
properties marked **deprecated** in their TTL comments but kept on the
class for migration safety.

**Run `python tools\reload_ontology.py` once (app closed)** to install
the 1.0.2 schema. On the first `/budget` render after that, an idempotent
migration creates one `BudgetLineSegment_N` per existing budget line
covering the legacy amount/window/rate — no manual intervention needed.

Backup/restore (`/settings`) round-trips categories and segments; old v0.3
backups still restore cleanly (legacy line fields written, migration
creates segments on next `/budget`).

See `docs/adr/ADR-017-budget-line-segments-and-user-defined-categories.md`
for the full design.

---

## [Unreleased — asset model + net-worth dashboard] — 2026-05-25

### Feature — Physical assets as a third account class

A new **Asset** tab on the Accounts page lets you track physical assets
(property, vehicles, collectibles) alongside cash and investment accounts.
Each asset carries an annual appreciation rate (negative for depreciating
items like vehicles) and an optional planned sale year + proceeds account.

When you set a sale year, the engine **automatically creates a managed Life
Event** ("Sale: {asset name}") and credits the proceeds to the chosen
account in that year. Editing the asset updates the event; deleting the
asset removes it. The Life Events page surfaces these auto-events with a
"Auto · {asset name}" badge and disables direct edit/delete on them — the
asset itself is the single source of truth.

Assets contribute to **net worth** but do NOT participate in retirement
drawdown — illiquid by design.

### Feature — Redesigned dashboard

The dashboard's data-present view now leads with a **net-worth-by-account
stacked area chart** spanning cash → invest → assets, with three snapshot
cards (Today, At retirement, At life expectancy). The chart's legend uses
the same adaptive chip-or-dropdown filter as the projection page, and a
"Setup at a glance" row of five count cards replaces the old vertical
Quick-access sidebar.

The first-run welcome screen and the setup-checklist card (shown while
your plan is still being built) are unchanged — onboarding survives.

### Engine — Asset projection

`run_projection` now appreciates each asset year-by-year and disposes it
at its sale year. Monte Carlo deliberately omits assets from its
investment-pool model — asset sales reach MC via the Life Event path —
saving N × n_years stochastic calculations per simulation.

---

## [Unreleased — beta engine updates] — 2026-05-25

### Engine — Monte Carlo now uses the per-account model

The previous Monte Carlo engine was a simplified aggregate-pool model that
ignored per-account drawdown eligibility, two-layer tax (ADR-013), account
contributions (ADR-015), and life-event account routing. It could let the
simulated investment pool go arbitrarily negative because cash was never
drained, which inflated MC success rates above what a coherent per-account
model would report.

MC now shares the same year-loop helper (`_simulate_run`) as the deterministic
projection, so both engines apply identical drawdown, tax, contribution, and
routing rules every year. Per-year volatility is layered on top via shocks
drawn from the selected MC profile (Conservative / Moderate / Aggressive) and
applied to all investment accounts simultaneously. Cash interest remains
deterministic.

The deterministic projection itself is **unchanged** — bit-for-bit identical
pre- and post-refactor on test scenarios. Only the MC numbers move.

**How to read a green deterministic projection alongside a low MC success
rate:** the plan survives on average returns but is fragile to a poor sequence
of returns early in retirement. That's the kind of risk a pooled-aggregate MC
can't see.

See ADR-012 §4 for the engineering rationale.

### Feature — Per-income-source deposit account

Each income source can now nominate the account it's deposited into each year
(salary → current account; pension → ISA; rental income → savings). The
setting is optional — when unset, income behaves as before and is credited to
the projection's spending account.

> **Behavioural caveat — read before routing income to an investment
> account.** Routing income to an account with a high drawdown priority number
> (one the engine draws last, e.g. priority 999) makes that income compound
> there while the engine continues to drain higher-priority accounts for
> spending. On long horizons the divergence vs leaving income unrouted can run
> into the millions on representative plans. This is the intended behaviour of
> the per-account drawdown waterfall, but it surprises people the first time
> they see it.

For the simplest behaviour (income offsets that year's spending), either leave
the deposit account unset, or route to a current account that already sits
high in your drawdown waterfall.

### Fixed

- **Personal allowance over-shielding (ADR-013).** Tax-free withdrawals from
  ISA / PCLS-style accounts were erroneously consuming the residence personal
  allowance, leaving more allowance available for taxable withdrawals than
  reality. The engine now excludes `PostTaxTaxFreeWithdrawal` and `TaxFree`
  treatments from the residence-taxable accumulator. The Accounts edit page
  also clarifies that the per-account "annual tax-free withdrawal" is an
  instrument-level shield (e.g. UK pension 25% PCLS), not your personal
  allowance — entering the same figure in both was the most common cause of
  under-taxed projections. A new **Tax shield summary** panel on the
  Projection page now surfaces both layers side-by-side so over-shielding is
  visible at a glance.

- **Accounts page header totals (display only).** The "Cash / Investments"
  totals in the Accounts page header were summing raw account balances without
  applying each account's exchange rate, so multi-currency setups overstated
  the totals by the FX delta. Engine projections were unaffected — only the
  header strip on `/accounts` misreported. Affected setups with USD/EUR
  accounts and a GBP base currency saw the header overstate investments by
  roughly 40%.

### Added in earlier sessions (2026-05-23) — see commit log

- Offline packaging — first working Windows `.exe` (ADR-002, unsigned).
- Live exchange rates on cash, investment, and income (ADR-016).
- Account contributions surfaced in the Budget chart and snapshot cards.
- Unified Accounts ↔ Investments UI (single `/accounts` table).
- Jurisdiction list expanded to match the 17-currency set.
- INR, CNY, AED currencies added.
- `£` swept from all templates in favour of the user's configured base
  currency symbol.
