# Changelog

All notable changes to **My Retirement Life** are recorded here.
This project is pre-1.0; format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

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
