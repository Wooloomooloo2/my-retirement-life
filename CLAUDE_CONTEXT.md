# CLAUDE_CONTEXT — My Retirement Life (MRL)

> Drop this file into a new conversation to restore full project context.
> Keep it updated at the end of each session.
> Last updated: 2026-05-23

---

## Project overview

**My Retirement Life (MRL)** is a local-first personal retirement planning application.
The user is a business architect and data modeller — Claude does all coding.

- **GitHub:** `Wooloomooloo2/my-retirement-life`
- **Stack:** Python 3.13 + FastAPI, pyoxigraph (Oxigraph triple store), HTMX + Tailwind + DaisyUI, Chart.js, NumPy
- **Platform:** Windows (VS Code), repo at `C:\Projects\my-retirement-life`, `.venv` present. May migrate to Linux.
- **Data storage:** Oxigraph RDF triple store at `AppData/Local/MyRetirementLife/store` (via `platformdirs`)
- **Ontology:** `mrl-ontology.ttl`, version 1.0.1 + ADR-015 additions + 3 new currencies (INR, CNY, AED). 17 `Currency` individuals total.

---

## Working agreement (how the user wants Claude to work)

- Deliver **full files**, never snippets, and always state the **full repo path** for each file.
- **Don't guess** folder structure or unseen file contents — ask for the file and wait.
- The user assembles files manually one at a time, on Windows. Minimise re-touching already-installed files.

---

## Changes this session (2026-05-23)

All delivered and confirmed working unless noted.

1. **Offline packaging (ADR-002) — Windows build working.**
   - `tools/vendor_assets.py` (new): downloads all CDN front-end assets (DaisyUI, Tailwind Play, HTMX, Chart.js, Tabler icons + fonts) into `src/static/vendor/`. Stdlib-only; rewrites Tabler font URLs to local paths.
   - `src/templates/base.html`: repointed the 5 CDN references to `/static/vendor/...`. (The `/static` mount already existed in `app.py` via `settings.static_dir`.)
   - `src/config.py`: added `_frozen_base()` + `ontology_ttl` property; `templates_dir`/`static_dir`/`ontology_ttl` now resolve from `sys._MEIPASS` when frozen, normal paths in dev. No-op for `python main.py`.
   - `src/store/ontology_loader.py`: `ONTOLOGY_TTL` now comes from `settings.ontology_ttl` (frozen-aware) instead of a `__file__`-relative path.
   - `main.spec` (new, repo root): one-folder PyInstaller build. Bundles `src/templates`, `src/static`, `docs/ontology/mrl-ontology.ttl`; `collect_all` for pyoxigraph + rdflib; uvicorn hidden imports. `console=True` for first release. Build: `pyinstaller main.spec` → `dist/MyRetirementLife/`.
   - Unsigned exe → SmartScreen warning expected (ADR-002).

2. **Backlog fix — `drawdown_configured` fires too early.** FIXED in `app.py` `get_dashboard_data()`: flag now derives from `proj_settings.get("spending_account_label")` (a spending account is actually chosen) instead of mere existence of `ProjectionSettings_1`.

3. **New currencies INR, CNY, AED** added as `mrl:Currency` individuals in `docs/ontology/mrl-ontology.ttl` (symbols ₹, CN¥, د.إ). The other requested ones (HKD/AUD/CAD/CHF/SGD/NZD/ZAR) already existed.

4. **Live exchange rates (ADR-016) — COMPLETE on both account types.**
   - `src/fx.py` (new): the app's ONLY outbound network call. `fetch_rates(base_code)` hits `https://open.er-api.com/v6/latest/<BASE>` (free, no key, 160+ currencies incl. AED). Stdlib `urllib`, no new dependency. Only the base currency code is transmitted.
   - `accounts.py`: `POST /accounts/refresh-rates` + `_update_account_rate()` + `_render_accounts()`. Writes `exchangeRateToBase = 1 / rate[code]` (base→1.0) and `exchangeRateDate` per cash account.
   - `investments.py`: `POST /investments/refresh-rates` + `_update_investment_rate()` (same model, self-contained — each page refreshes its own account type; not unified, to keep modules decoupled).
   - `accounts.html` / `investments.html`: "Refresh rates" button + "Live rates from open.er-api.com" attribution in the card header + result banner wired to `rate_refresh_*` context (count, base, as_of, provider, skipped; amber warning on offline/failure).
   - `docs/adr/ADR-016-live-exchange-rates.md` (new) + indexed in `docs/adr/README.md`.

5. **`docs/adr/README.md`**: added index rows + summaries for ADR-014, 015, 016.

6. **`tools/reload_ontology.py`** (new): force-reloads the ontology named graph (`load_ontology(force=True)`) after TTL edits. Run with the app CLOSED: `python tools\reload_ontology.py`.

7. **Backlog #8 — budget-line growth is now real (above inflation).** Engine: `projection.py` (deterministic + Monte Carlo branches) now computes `rate = inflation_rate + line["change_rate"]` instead of substituting one for the other. UI: `budget.html` field relabelled to "Real growth rate % (above inflation)"; placeholder and hint updated; table column renamed "Real growth". Verified by running the app and confirming mandatory-line growth of ~6.6%/yr at inflation=3.5% — mathematically impossible under the old "substitute" formula (max would have been 4%). **Silent reinterpretation accepted** (pre-beta): existing budget lines with non-zero `change_rate` now grow faster than before.

8. **Loan-line inflation (follow-on from #7) — DONE.** `projection.py` (both branches): for `BudgetLineType_Loan`, effective rate is now `change_rate` only — no inflation added. Default 0% gives flat nominal repayments (correct for fixed-rate mortgages etc.). Field label on `budget.html` left as-is per user call; the global "0 = grows with inflation only" hint is technically misleading for loans but in practice users leave 0% and get correct behavior.

9. **Backlog #10 — Monte Carlo gated on investment accounts.** `projection.py` `run_monte_carlo()` returns `None` early when no `InvestmentAccount` exists in `all_accounts` (ADR-012 — there's nothing stochastic to model without investments). Template's existing `{% if mc %}` guards auto-hide the MC card, JS, and confidence-card line. `projection.html` adds an info notice in the `else` branch explaining why MC isn't shown and linking to `/investments`. Note: the deeper "MC model discrepancy" (aggregate-pool MC vs per-account deterministic depletion) is a SEPARATE issue and remains open.

10. **Backlog #1 + #2 — employment end default and workplace pension type.** Commit `627db7f`. `income.py`/`income.html`: new income source defaults End year to the person's retirement year, with JS that auto-clears it when Type isn't Employment. `mrl-ontology.ttl` + `investments.py`/`investments.html`: new `InvestmentAccountType_WorkPension` for employer-sponsored pensions (UK auto-enrolment, US 401(k)/403(b), Australian super, German bAV); existing Pension type rescoped to self-directed plans (SIPP / IRA / RRSP). Requires `python tools\reload_ontology.py` to appear in the live store.

11. **Backlog #5 — Income currency exposed with per-source FX rate.** Commit `81023f3`. Ontology adds `mrl:incomeExchangeRateToBase` + `mrl:incomeExchangeRateDate` on `IncomeSource` (mirrors ADR-016 account pattern; `mrl:incomeCurrency` already existed). `income.py`: new form fields persisted via `save_income_source()`; new `POST /income/refresh-rates` route; helpers `_currency_code` / `_currency_symbol` / `get_currencies` / `get_base_currency` imported from `profile.py` to avoid duplication. `income.html`: currency dropdown defaulting to base currency (and defaulting to base for legacy rows so editing pre-existing income doesn't silently flip currency to whatever sorts first); FX rate field shown only when income currency ≠ base; "Refresh rates" button + result banner. Engine: `projection.py` `load_all_income_sources()` pre-multiplies `amount` by `incomeExchangeRateToBase` (default 1.0), so `run_projection` and `run_monte_carlo` see base-currency figures without further changes.

12. **Backlog #6 — Default base-currency symbol everywhere.** Same commit `81023f3`. `app.py`: new Jinja globals `base_currency_symbol()` + `base_currency_code()`, resolved via `profile.get_base_currency()` (returns `{local, code, symbol}`, falls back to GBP/£ when no profile exists). `budget.html`, `life_events.html`, `income.html`: every hardcoded `£` in templates and inline JS now uses the Jinja global. Per-budget-line and per-life-event currency overrides remain unmodelled — those screens continue to treat all amounts as being in the base currency; per-item override stays on the Post-1.0 ADR-016 follow-on list.

### Documentation tidy-ups still pending (small, user to action)
- **ADR-016** is `Proposed` and its scope says "cash accounts only." Now that investments are implemented too: flip to `Accepted` when agreed, change scope to "cash **and investment** accounts," and move investment accounts out of the deferred list (genuine remaining follow-ons: per-budget-line currency, separate retirement-base currency).

---

## Repository structure

```
my-retirement-life/
├── main.py                          ← entry point: loads ontology, starts uvicorn, opens browser
├── main.spec                        ← PyInstaller build spec (one-folder)
├── requirements.txt
├── .env.example
├── README.md
├── src/
│   ├── config.py                    ← Settings; frozen-aware resource paths + ontology_ttl
│   ├── fx.py                        ← Live exchange-rate client (ONLY outbound network call)
│   ├── api/
│   │   ├── app.py                   ← FastAPI app, middleware, dashboard route, Jinja globals
│   │   ├── templates.py             ← Jinja2 templates instance
│   │   └── routes/
│   │       ├── profile.py
│   │       ├── accounts.py          ← Cash CRUD + contribution CRUD + /accounts/refresh-rates
│   │       ├── investments.py       ← Investment CRUD + contribution CRUD + /investments/refresh-rates
│   │       ├── income.py            ← NOT YET SEEN
│   │       ├── budget.py            ← Budget-line CRUD + get_all_contributions_for_budget()
│   │       ├── life_events.py       ← NOT YET SEEN
│   │       ├── projection.py        ← Engine + projection settings
│   │       ├── settings_route.py    ← Backup/restore/export (NOT YET SEEN)
│   │       └── scenarios.py         ← Scenario management (NOT YET SEEN)
│   ├── store/
│   │   ├── graph.py                 ← Store singleton; MRL/DATA_GRAPH constants (seen in part)
│   │   ├── ontology_loader.py       ← Loads docs/ontology TTL into named graph
│   │   ├── scenario_manager.py      ← NOT YET SEEN
│   │   └── mrl-ontology.ttl         ← NOT loaded at runtime (see note below) — likely unused/dead
│   ├── static/
│   │   ├── css/
│   │   ├── js/
│   │   └── vendor/                  ← vendored offline assets (vendor_assets.py output)
│   │       ├── tabler/ (css + fonts/)
│   │       ├── chart.umd.min.js
│   │       ├── daisyui.full.min.css
│   │       ├── htmx.min.js
│   │       └── tailwind.play.min.js
│   └── templates/
│       ├── base.html                ← assets now local; trailing scenario-indicator snippet NOT yet integrated
│       ├── dashboard.html           ← NOT YET SEEN
│       ├── profile.html             ← NOT YET SEEN
│       ├── accounts.html
│       ├── investments.html
│       ├── investment_projection.html ← NOT YET SEEN
│       ├── income.html              ← NOT YET SEEN
│       ├── budget.html              ← Budget-line CRUD form + read-only contributions table
│       ├── life_events.html         ← NOT YET SEEN
│       ├── projection.html          ← NOT YET SEEN
│       ├── settings.html            ← NOT YET SEEN
│       ├── scenarios.html           ← NOT YET SEEN
│       └── error.html               ← NOT YET SEEN
├── tools/
│   ├── vendor_assets.py
│   └── reload_ontology.py
└── docs/
    ├── ontology/
    │   └── mrl-ontology.ttl         ← THE runtime ontology (loaded by ontology_loader)
    └── adr/
        ├── README.md
        └── ADR-001 through ADR-016
```

---

## CRITICAL ontology facts (corrected this session)

- **Only `docs/ontology/mrl-ontology.ttl` is loaded at runtime.** `ontology_loader.py` resolves it via `settings.ontology_ttl`. The `src/store/mrl-ontology.ttl` copy is **not** read at runtime and appears to be dead — confirm/remove in a future cleanup. Edit currencies/classes in the `docs/ontology` copy.
- **To apply ontology edits**, do NOT delete the store folder (that destroys user data). Close the app, then run `python tools\reload_ontology.py` (force-reloads only the ontology named graph; data graph untouched). On a fresh install the ontology loads automatically, so distributed packages need no action.
- The loader is **idempotent** (ADR-005): it skips loading if the ontology graph already has triples — which is why edits don't appear until a force reload.

---

## ADR summary

| # | Decision | Status |
|---|---------|--------|
| 001 | Python + FastAPI + Oxigraph backend | Implemented |
| 002 | PyInstaller/AppImage packaging | Accepted (Windows build working) |
| 003 | HTMX + Tailwind + DaisyUI frontend | Implemented |
| 004 | Cross-platform portability practices | Implemented |
| 005 | Ontology loaded from TTL into named graph on startup | Implemented |
| 006 | Instance IRIs follow mrl:ClassName_N pattern | Implemented |
| 007 | Quad patterns for reads, SPARQL UPDATE for writes | Implemented |
| 008 | Multiple income sources with start/end dates | Implemented |
| 009 | Investment accounts; Monte Carlo with named profiles | Implemented |
| 010 | Sister app (MFL) loads and extends MRL ontology | Accepted |
| 011 | Per-account drawdown eligibility, ordering, surplus | Implemented |
| 012 | Per-account balance tracking; MC restricted to investments | Implemented |
| 013 | Two-layer tax model (source tax + residence allowance) | Implemented |
| 014 | Scenario management | Implemented |
| 015 | Account contributions | Implemented |
| 016 | Live exchange rates (open.er-api.com) | Proposed — code complete (see tidy-up above) |

---

## Multi-currency model — current state vs. intended (relevant to backlog)

**Modelled & working today:**
- `mrl:Currency` individuals (code/symbol/name); 17 total.
- `mrl:baseCurrency` on `mrl:Person` (single base).
- `mrl:accountCurrency` + `mrl:exchangeRateToBase` + `mrl:exchangeRateDate` on cash AND investment accounts; the deterministic engine applies the per-account rate (`base_balance = raw_balance * fx_rate`, default 1.0).
- `mrl:incomeCurrency` + `mrl:incomeExchangeRateToBase` + `mrl:incomeExchangeRateDate` on `IncomeSource`; income form exposes currency selector defaulting to base; engine pre-multiplies amount × rate in `load_all_income_sources()`.
- Live refresh of `exchangeRateToBase` on both account pages **and** `incomeExchangeRateToBase` on the income page (ADR-016).
- All template displays of monetary amounts on `budget.html`, `life_events.html`, and `income.html` use the Jinja global `base_currency_symbol()` (resolves from `Person.baseCurrency`).

**NOT modelled yet (gaps behind several backlog items):**
- No per-budget-line currency property.
- No per-life-event currency property (events follow base currency).
- No separate "expected retirement base" currency (only one `baseCurrency`).
- Account / investment / projection / dashboard / settings templates still contain hardcoded `£` in places — sweep is a quick follow-on once the income/budget/life-events pattern is approved.

---

## Projection engine (`projection.py`) key structure

```python
load_all_accounts()           → list (cash + investment, all ADR-011/012/013 fields
                                + account_type_local e.g. "CashAccountType_Current")
load_all_income_sources()
load_budget_lines()
load_life_events()
load_all_contributions()      → {account_label: {annual_amount, start_year, end_year, growth_rate}}
get_projection_settings() / save_projection_settings()
    # get_projection_settings() returns inflation_rate, spending_account_label, etc.

run_projection(inflation_rate, proj_settings=None)
    → {
        "years":                 [{year, income, mandatory, discretionary, balance, tax_paid, ...}],
        "retirement_year":       int,
        "total_tax_paid":        float,
        "total_contributions":   float,          # ADR-015
        "account_balances":      {label: [y0, y1, ...]},
        "account_withdrawals":   {label: [w0, w1, ...]},
        "account_returns":       {label: [r0, r1, ...]},
        "account_contributions": {label: [c0, c1, ...]},  # ADR-015
        "account_names":         {label: name},
        "account_classes":       {label: "CashAccount"|"InvestmentAccount"},
      }

run_monte_carlo(inflation_rate, proj_settings=None)
    → {years, p10, p50, p90, cash_floor, retirement_year, success_rate, ...}
```

### Year loop order (run_projection)

1. Capture `opening_this_year` balances
2. Apply growth to each account (interest for cash, growth+dividends for investments)
3. Record per-account returns = closing_after_growth − opening
4. **Apply contributions** (ADR-015): credit account balance + accumulate `year_contribution_spending`
5. Sum active income sources + non-reinvested dividends
6. Sum active budget lines (inflation-adjusted, COL ratio in retirement)
7. Process life events (cost/receipt; account-specific if fundedBy/receivedBy set)
8. `pre_net = income + receipts − spending − year_contribution_spending`
9. If `pre_net < 0`: drawdown via `_apply_drawdown()` + `_compute_source_tax()`; residence tax
10. If `pre_net >= 0`: **always credit surplus to spending account** (or first current account,
    or first cash account, or first account — in that priority order)
11. Record closing balances, withdrawals, contributions per account

### Surplus routing fallback priority
1. Configured `spending_account` (explicit — always wins)
2. First `CashAccountType_Current` account
3. First cash account of any type
4. First account of any class (last resort)

### Contribution growth rate (ADR-015)
```python
years_active = year - c_start            # 0 in the first active year
contrib_this_year = base_annual * ((1 + growth_rate / 100) ** years_active)
```

### Confidence scoring
- **Runs out year:** first year where `balance <= 0`
- Green: never runs out · Amber: within 5 years of life expectancy · Red: before life expectancy

---

## Account contributions (ADR-015) — COMPLETE

- `mrl:AccountContribution` class linked via `mrl:contributionOwner`; IRI `AccountContribution_N`
- Properties: `contributionAmount`, `contributionFrequency`, `contributionStartYear`,
  `contributionEndYear`, `contributionNote`, `contributionGrowthRate`, `contributionOwner`
- One contribution per account in v1.0 UI (data model supports multiples)
- Routes: `POST /accounts/{n}/contribution(/delete)`, `POST /investments/{n}/contribution(/delete)`
- Engine dual effect: credits account balance AND deducts from cashflow. Default active window: current year → retirement year if start/end not set.
- UI: collapsible section in a SEPARATE `<form>` AFTER the main account `</form>` (avoids nested-form invalidity); shown only when editing. Budget page shows a read-only contributions table.
- Export/restore handled in `settings_route.py`.

---

## Live exchange rates (ADR-016) — COMPLETE

- `src/fx.py` — `fetch_rates(base)` → `{base, as_of, provider, rates}`; raises `FxError`. Provider: `open.er-api.com`. Only base code transmitted; no caching; offline = clean failure.
- `_update_account_rate()` / `_update_investment_rate()` overwrite only `exchangeRateToBase` + `exchangeRateDate` for one account IRI.
- Routes `POST /accounts/refresh-rates` and `POST /investments/refresh-rates` render their own page with `rate_refresh_*` context.
- Rate convention: `exchangeRateToBase` = "1 unit of account ccy = N units of base"; provider gives the inverse, so stored value = `1 / rate[code]`; base-currency account = 1.0.

---

## Life events — amount sign convention

- **Stored:** positive = cost (reduces balance), negative = receipt/windfall (increases balance)
- **UI input:** always positive; sign badge + hint update by event type; JS negates for `LifeEventType_Windfall` on submit
- `RECEIPT_TYPES` set in `life_events.html` JS: currently `{'LifeEventType_Windfall'}`

---

## Store / ontology patterns

```python
MRL        = "https://myretirementlife.app/ontology#"
MRL_EXT    = "https://myretirementlife.app/ontology/ext#"
DATA_GRAPH = NamedNode("https://myretirementlife.app/data/graph")
ONTOLOGY_GRAPH = NamedNode("https://myretirementlife.app/ontology/graph")
```
- IRI naming: `mrl:ClassName_N` where N = MAX(existing) + 1
- Reads of known instances → `quads_for_pattern`; queries → SPARQL SELECT; writes → SPARQL UPDATE with explicit XSD datatypes
- Tax rates: stored as decimals (0.20), entered as percentages (20) — divide by 100 on save
- `_currency_code(local)` / `_currency_symbol(local)` resolve against `ONTOLOGY_GRAPH` (present in both accounts.py and investments.py)

---

## app.py Jinja2 globals
- `user_initials` — initials from Person_1
- `active_scenario` — scenario state dict (`name`, `saved`, `display_name`, `is_named`, `is_clean`)
- `setup_state` — setup checklist completion dict

## Projection route context keys
```python
{ "projection": dict, "mc": dict, "proj_settings": dict, "all_accounts": list,
  "surplus_dest_name": str, "surplus_dest_configured": bool }
```

---

## Key UX conventions
- Chart wrappers: `position:relative; height:Npx` + `maintainAspectRatio:false`
- Form sections: DaisyUI `collapse`/`collapse-arrow`
- Contribution sections: separate `<form>` AFTER the main `</form>`, inside the same `card-body`
- New account flow: `POST /accounts` and `POST /investments` redirect to `/{n}/edit` after creation
- Alerts: DaisyUI `alert alert-{success|info|warning}` + Tabler `ti` icons
- Scenario dirty state: set by HTTP middleware in `app.py`, NOT by route handlers

---

## Current backlog

### PRE-BETA — new items from end-to-end walkthrough (2026-05-23)
All to be addressed before public beta. File(s) each will need are noted.

1. _(RESOLVED — commit `627db7f`; see "Changes this session" item 10.)_
2. _(RESOLVED — commit `627db7f`; see "Changes this session" item 10.)_
3. **Accounts vs Investments are awkwardly separated with overlapping options.** Information-architecture review — the two screens duplicate currency/FX/contribution/tax options. Decide on unification or clearer separation. _Needs: design review across `accounts.*` + `investments.*`._
4. **"Plan to retire in" doesn't match available currencies.** The retirement-jurisdiction options and the currency set are inconsistent. Align jurisdictions ↔ currencies (clarify intended relationship first). _Needs: `profile.py`/`profile.html` + jurisdiction/currency individuals in `mrl-ontology.ttl`._
5. _(RESOLVED — commit `81023f3`; see "Changes this session" item 11.)_
6. _(RESOLVED — commit `81023f3`; see "Changes this session" item 12 — for the income/budget/life-events templates. Hardcoded `£` still present on `projection.html`, `dashboard.html`, `accounts.html`, `investments.html`, `settings.html` — quick sweep to follow.)_
7. **Contributions not explicit in the budget.** Savings/investment contributions (ADR-015) need to be clearly called out in the budget. A read-only section exists but isn't prominent/explicit enough. _Needs: `budget.py`/`budget.html`._
8. _(RESOLVED earlier this session — see "Changes this session" item 8.)_
9. **Personal-allowance aggregation.** Personal allowance appears both on the projection screen (residence level, ADR-013) and per account in the drawdown/tax fields. Need a clear way to aggregate accounts against the single personal allowance so it isn't double-applied. _Needs: `projection.py` (tax pass), `projection.html`, account tax fields._
10. _(RESOLVED earlier this session — see "Changes this session" item 9.)_

### PRE-BETA — carried over (still open)
- **Income deposit account UI** — income sources should specify which account receives the income (engine surplus routing already delivers most of the value). _Needs: `income.py`, `income.html`._
- **Load/Save quick-action buttons in top banner** — `base.html` has a scenario-indicator snippet sitting AFTER `</html>` that was never integrated into the header. Integrate it near the user avatar. _Needs: design decision; `base.html` now seen._
- **Accounts table overflow on narrower screens.**
- **MC model discrepancy** — Monte Carlo shows high success rates even when the deterministic engine runs out; MC uses an aggregate pool that doesn't model per-account depletion (ADR-012 limitation). The cash-only gating (#10) was a separate, narrower fix — this deeper model issue remains.

### RESOLVED this session
- ~~`drawdown_configured` dashboard flag fires too early~~ — FIXED.
- ~~Offline packaging / first Windows .exe~~ — DONE.
- ~~Add currencies INR/CNY/AED~~ — DONE.
- ~~Auto-populate exchange rates from today's rate~~ — DONE (ADR-016, both account types).
- ~~Spending growth rate must be REAL, not nominal (#8)~~ — DONE. Engine now composes `inflation + change_rate`; UI relabelled.
- ~~Loan-line inflation (follow-on)~~ — DONE. Loans now use `change_rate` only; no inflation lift.
- ~~Monte Carlo runs with cash-only input (#10)~~ — DONE. `run_monte_carlo()` returns `None` when no investment accounts; template shows an info notice instead.
- ~~Employment income default end (#1)~~ — DONE (commit `627db7f`). Defaults to retirement year for Employment type with JS sync.
- ~~Workplace pension investment type (#2)~~ — DONE (commit `627db7f`). `InvestmentAccountType_WorkPension` added; existing Pension type now scoped to self-directed plans.
- ~~Income currency selector + per-source FX rate (#5)~~ — DONE (commit `81023f3`). Engine FX-converts income via `incomeExchangeRateToBase` at load time.
- ~~Default base-currency symbol on income/budget/life-events (#6 partial)~~ — DONE (commit `81023f3`). `base_currency_symbol()` Jinja global. Remaining templates (`projection`, `dashboard`, `accounts`, `investments`, `settings`) still hardcode `£` — quick sweep follow-on.

### Post-1.0
- Tax-optimal drawdown ordering (ADR-011 future)
- PCLS dedicated model
- Multiple marginal tax bands (ADR-013 future)
- Per-jurisdiction Monte Carlo profiles (ADR-012 future)
- Employer contributions (`isEmployerContribution`, ADR-015 v1.1)
- Multiple contributions per account surfaced in UI (ADR-015 v1.1)
- Per-budget-line currency; separate expected-retirement base currency (ADR-016 follow-ons)
- Unify rate refresh into one "refresh everything" action across account types (ADR-016 follow-on)
- GIA cost basis from MFL data portability
- `mrl-core` namespace extraction when MFL is stable
- Remove dead `src/store/mrl-ontology.ttl` if confirmed unused
- MFL sister app

---

## Files Claude has SEEN (current/uploaded this project)
`main.py`, `main.spec`, `requirements.txt`, `src/config.py`, `src/fx.py`,
`src/api/app.py`, `src/api/routes/accounts.py`, `src/api/routes/profile.py`,
`src/api/routes/investments.py`, `src/api/routes/projection.py` (full),
`src/api/routes/budget.py`, `src/api/routes/income.py`, `src/api/routes/life_events.py`,
`src/store/ontology_loader.py`,
`src/templates/base.html`, `src/templates/accounts.html`,
`src/templates/investments.html`, `src/templates/budget.html`,
`src/templates/income.html`, `src/templates/life_events.html`,
`docs/ontology/mrl-ontology.ttl`, `docs/adr/README.md`, ADR-014/015/016.

## Files Claude has NOT seen (upload when relevant)
- `src/templates/profile.html` — item 4 (and to confirm currency dropdowns now show INR/CNY/AED)
- `src/templates/projection.html` — items 9, remaining `£` sweep (template only — route file now fully seen)
- `src/api/routes/settings_route.py`, `src/api/routes/scenarios.py`, `src/store/scenario_manager.py`, `src/store/graph.py` (full)
- `dashboard.html`, `settings.html`, `scenarios.html`, `investment_projection.html`, `error.html` — all candidates for the remaining `£`-symbol sweep