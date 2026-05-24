# ADR-016: Live exchange rates

**Status:** Accepted
**Date:** 2026-05-22

> Numbering: this assumes 016 is the next free ADR. If that number is already
> taken, renumber to the next available one — the content is unaffected.

## Context

My Retirement Life is a local-first desktop application. The packaged build
runs entirely offline: the UI assets, the ontology, and the user's data all
live on the local machine, and the app makes no network calls during normal
operation.

The ontology models multi-currency holdings: accounts, income and the person's
base currency all point at `mrl:Currency` individuals, and each account carries
`mrl:exchangeRateToBase` (defined as "1 unit of account currency = N units of
base currency") plus `mrl:exchangeRateDate`. Until now these rates were entered
and maintained by hand. We want to let the user populate them with today's
real rates on demand.

This introduces the application's first and only outbound network dependency,
which for a personal-finance tool deserves an explicit, documented decision.

## Decision

1. **Provider:** `open.er-api.com` — the free, no-API-key "Open" tier of
   ExchangeRate-API. Chosen because it requires no key (suits a packaged app
   with no per-user secrets to manage) and covers 160+ currencies, including
   ones the ECB-based free APIs omit (e.g. AED).

2. **Endpoint:** `GET https://open.er-api.com/v6/latest/<BASE_CURRENCY_CODE>`.
   The provider returns rates as "1 base = N foreign"; the app stores the
   inverse (`1 / rate`) to match `mrl:exchangeRateToBase`. Accounts already in
   the base currency are set to `1.0`.

3. **User-triggered only.** Rates are fetched only when the user explicitly
   presses "Refresh rates" on the Accounts page. There is no background polling
   or fetch-on-startup.

4. **No caching.** Each refresh is a fresh live lookup (per the product
   decision that rates should always reflect today). When the machine is
   offline the refresh fails cleanly and existing rates are left untouched.

5. **Isolation.** All network access is confined to `src/fx.py`. The rest of
   the codebase never makes outbound calls. This keeps the network boundary
   auditable in one small, well-documented module.

6. **Data minimisation / transparency.** The only datum transmitted is the
   base currency code (e.g. `GBP`) in the URL path. No balances, names, dates
   or any other personal or financial data are sent. The provider name is
   shown in the UI next to the refresh control, and the date each rate was
   fetched is stored in `mrl:exchangeRateDate` and displayed per account.

## Consequences

- The packaged app remains fully usable offline; only the optional rate
  refresh needs connectivity. This is consistent with the offline-first
  packaging goal (the static front-end assets are vendored locally).
- A third party (ExchangeRate-API) can observe that *some* client requested
  rates for a given base currency, but learns nothing about the user's
  finances or identity beyond that single code.
- Rates are only as current as the user's last refresh; `mrl:exchangeRateDate`
  makes staleness visible.
- `urllib` (standard library) is used for the request, so no new third-party
  dependency is added to `requirements.txt`.

## Alternatives considered

- **Frankfurter / ECB-based free APIs:** rejected because their currency
  coverage excludes some currencies the app supports (e.g. AED).
- **A keyed provider (higher limits/SLA):** rejected for now — managing an API
  key in a distributed desktop build adds friction with no benefit at this
  scale. Can be revisited if rate limits become a problem.
- **Caching a daily snapshot:** rejected per the "always reflect today"
  product decision; revisit if offline refresh becomes a requirement.

## Scope (this ADR)

Covers refreshing `mrl:exchangeRateToBase` on **cash accounts** and **investment accounts**, and `mrl:incomeExchangeRateToBase` on **income sources** (same provider, same `src/fx.py` boundary). Extending the same refresh to per-budget-line currency and a separate expected-retirement base currency are tracked as separate follow-on items — they require additional ontology properties and projection-engine changes beyond this decision.
