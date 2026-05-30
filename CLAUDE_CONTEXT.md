# CLAUDE_CONTEXT — My Retirement Life (MRL)

> Drop this file into a new conversation to restore full project context.
> Keep it updated at the end of each session.
> Last updated: 2026-05-30 (session 7 — inline live FX rate buttons + per-line budget currency)

---

## Project overview

**My Retirement Life (MRL)** is a local-first personal retirement planning application.
The user is a business architect and data modeller — Claude does all coding.

- **GitHub:** `Wooloomooloo2/my-retirement-life`
- **Stack:** Python 3.13 + FastAPI, pyoxigraph (Oxigraph triple store), HTMX + Tailwind + DaisyUI, Chart.js, NumPy
- **Platform:** Windows (VS Code), repo at `C:\Users\hallm\Documents\GitHub\my-retirement-life`, `.venv` present. Also runs on macOS (Apple Silicon) at `/Users/markhall/Projects/my-retirement-life` — session 6 added macOS packaging + native window support. Linux deferred.
- **Data storage:** Oxigraph RDF triple store at `AppData/Local/MyRetirementLife/store` (via `platformdirs`)
- **Ontology:** `mrl-ontology.ttl`, version **1.0.5** (ADR-016 follow-on — per-line currency + FX on `mrl:BudgetLine`). 17 `Currency` individuals total.

---

## Working agreement (how the user wants Claude to work)

**On Claude Code (current workflow, from 2026-05-24):**
- Edit files directly with the Edit/Write tools — user reviews the diff in the harness.
- Still **state the full repo path** of every file touched so the change is unambiguous.
- Still **don't guess** the contents of files you haven't read — read them first.
- When working on this machine, the repo lives at `C:\Users\hallm\Documents\GitHub\my-retirement-life`, NOT `C:\Projects\my-retirement-life` (that was the previous machine).

**On chat (legacy workflow, kept for reference):**
- Deliver full files, never snippets, with the full repo path; user assembles manually one at a time. Minimise re-touching already-installed files.

---

## Changes this session (2026-05-30 — seventh session)

_Shipped in commit **`585e786`** — "ADR-016 follow-on: per-line budget currency + inline live FX buttons" (items 50–53). End-to-end smoke-tested by Mark across all three pages (inline buttons populate live, bulk refresh works, per-line budget currency rolls up correctly in chart + projection, backup/restore round-trips income FX + deposit account)._

50. **Shared `GET /api/fx/rate?code=XYZ` JSON endpoint.** Single live-rate lookup used by all three inline buttons (accounts, income, budget) so the per-row "Use live rate" UX doesn't need a page reload. Returns `{ok: True, code, rate_to_base, as_of, provider}` on success, `{ok: False, error: "..."}` with a 4xx/5xx status on failure. Lives in `src/api/routes/accounts.py` (the existing FX hub — already had bulk refresh and `_update_account_rate`). Uses the same `1 / rate_provider[code]` convention as the bulk refresh, with a 1.0 short-circuit when the asked-for code equals the base. Same-origin only; no auth needed (app is local-first).
    - **Why one JSON endpoint instead of three per-page POSTs:** the bulk refresh routes are HTML-rendering (they re-render the page with a banner). The inline button just needs to populate two fields. JSON keeps the JS simple and avoids three near-identical handlers.
    - **No new dependency** on httpx in the runtime — the `TestClient` import in `fastapi.testclient` requires it, so I couldn't end-to-end test from the dev shell; the logic mirrors the proven bulk refresh path so the parity argument carries.

51. **Inline "Use live rate" button on accounts + income edit forms.** Adds a small button next to the FX rate input that calls `/api/fx/rate?code=...` and populates the rate + date in-place. Failure modes (offline, no rate for code, base currency not set) surface a one-line warning hint and leave the existing rate untouched. Mark wanted this because the bulk "Refresh rates" button updates everything at once; sometimes you only want one row's rate while editing it. Pattern is identical across both pages so the JS is copy-pasted with the right element IDs.
    - `src/templates/accounts.html`: button + spinner + hint span added next to `name="exchangeRateToBase"`; `pullLiveRate()` JS handler appended to the existing FX-visibility script block. Works for all three account classes (cash + investment + asset) because they share one form and one FX field.
    - `src/templates/income.html`: same pattern; reads `data-code` from the currency `<option>` (the dropdown already carried it for the visibility toggle). Updates the hidden `incomeExchangeRateDate` input as well as the visible rate input, and rewrites the "Last updated …" pill if it's present.

52. **Per-line currency + FX + live refresh on budget (1.0.5 — ADR-016 follow-on).** Until this session, budget lines were assumed to be in the user's base currency — there was no way to model a USD mortgage or a EUR subscription. This change adds the same currency + FX model that accounts and income already had.
    - **Ontology 1.0.4 → 1.0.5** (`docs/ontology/mrl-ontology.ttl`): three new properties on `mrl:BudgetLine` — `budgetLineCurrency` (object property → `mrl:Currency`, optional, defaults to base at read time), `budgetLineExchangeRateToBase` (decimal, "1 unit of line currency = N units of base"), `budgetLineExchangeRateDate` (date). FX-rate convention identical to `mrl:exchangeRateToBase` on accounts and `mrl:incomeExchangeRateToBase` on income sources. Requires `python tools/reload_ontology.py` (app closed) before the property declarations appear in the live store, though backend writes don't depend on them.
    - **Backend** (`src/api/routes/budget.py`):
      - `get_all_budget_lines()` now reads `currency`/`currencyCode`/`currencySymbol`/`exchangeRate`/`exchangeRateDate` and surfaces them on each line dict.
      - `save_budget_line_segments()` takes three new kwargs (`currency_local`, `exchange_rate`, `exchange_rate_date`); writes `mrl:budgetLineCurrency` always (defaults to person's base if blank), and writes the rate pair only when ≠ 1.0 — matches accounts/income persistence convention.
      - New `_update_budget_line_rate()` helper (mirrors `_update_account_rate` / `_update_income_rate`) wipes + rewrites just the two FX-rate triples per line.
      - New `POST /budget/refresh-rates` route — bulk refresh over every cross-currency line in one pass; renders the budget page with the same `rate_refresh_*` context the accounts/income pages use.
      - `_sum_lines_per_year()` and `compute_annual_spending_series()` now pre-multiply each segment's `annualAmount` by `_line_fx(line)` so multi-currency lines roll up correctly on the by-category, by-line, and M/D/L breakdowns. Defaults to 1.0 for absent/invalid rates, so pre-1.0.5 lines are bit-identical.
      - `_page_context` exposes `currencies`, `base_currency`, and `today` for the form template.
      - Both `POST /budget` and `POST /budget/{n}/edit` gain `budgetLineCurrency` / `budgetLineExchangeRateToBase` / `budgetLineExchangeRateDate` Form params and pass them through.
    - **Engine** (`src/api/routes/projection.py` `load_budget_lines()`): pre-multiplies each segment's `annual_amount` by the line's `budgetLineExchangeRateToBase` (default 1.0). Same FX-at-load pattern used for accounts (`load_all_accounts`) and income (`load_all_income_sources`); downstream year-loop sees base-currency figures only. **Parity preserved**: pre-1.0.5 lines have no FX triple → 1.0 → identical numbers.
    - **Template** (`src/templates/budget.html`):
      - New rate-refresh banner block at top (mirrors accounts/income).
      - Budget-lines card header gains a "Refresh rates" button + "Live rates from open.er-api.com" pill.
      - Annual-total cell in the lines table shows the line's own currency symbol, then a small sub-line with `{code} @ {rate} → {base equivalent}` when the line currency differs from base.
      - Add/edit form gains a Currency dropdown (defaults to base) and a conditional Exchange-rate field with the same inline "Use live rate" button + hidden date input pattern used on the other two pages.
    - **Export/restore** (`src/api/routes/settings_route.py`): `budget_lines` export adds `currency` / `exchangeRate` / `exchangeRateDate`; restore writes the currency triple when present and the FX-rate pair only when ≠ 1.0 (matches the save path). Pre-1.0.5 backups round-trip cleanly: no currency triple is written and the engine falls back to base at load.

53. **Income export/restore round-trip — fixed.** Same session, after item 52 surfaced the gap. The income source export had been missing four fields since they were introduced: `incomeCurrency` and `incomeExchangeRate*` (added 2026-05-23, item 11) and `creditedToAccount` (added 2026-05-25, item 24). Backups silently dropped them, so a restore wiped every cross-currency income source back to base + every deposit-account routing back to the default surplus path — material outcome changes for any plan with foreign-currency income or routed income. Now mirrored on the budget pattern from item 52: export adds the four fields, restore emits the FX-rate pair only when ≠ 1.0, the currency triple when present, and the `creditedToAccount` link when set. Pre-fix backups still restore cleanly — missing fields just fall back to the engine defaults (base currency, unrouted income). No ontology change needed; the properties have existed since 2026-05-23.

---

## Changes in session 6 (2026-05-30)

_Session 6 changes (items 48 + 49) — packaging shipped in commit **`18cafb3`**, pywebview integration in commit **`f489261`**._

48. **macOS packaging: PyInstaller `.app` + `.dmg` distributable.** Implements the ADR-002 strategy that had been documented but not built. New `tools/MyRetirementLife.spec` bundles `src/templates`, `src/static`, and `docs/ontology/mrl-ontology.ttl` with explicit hidden imports for the API route modules and uvicorn's dynamic loaders (`uvicorn.loops.auto`, `uvicorn.protocols.http.h11_impl`, etc.). `src/config.py` already handled `sys._MEIPASS` so no source changes were needed. New `tools/build_mac.sh` cleans `build/` + `dist/`, runs PyInstaller, then `hdiutil create -format UDZO` against a stage dir containing the `.app` plus an `Applications` symlink so the DMG has the standard drag-to-install affordance. `VERSION` env var stamps the DMG filename (default `dev`). Build deps moved to a separate `requirements-build.txt` (just `pyinstaller~=6.11`) to keep them out of the runtime install. `.gitignore` keeps the `*.spec` wildcard but adds `!tools/MyRetirementLife.spec` so the committed spec is tracked while PyInstaller's auto-generated ones at the repo root stay ignored. README gains a "Building a macOS distributable" section with the Gatekeeper note pointing at ADR-002.
    - **Build machine note:** PyInstaller cannot cross-compile — current build targets arm64 only (the build machine arch). Universal2 deferred per ADR-002.
    - **Gatekeeper / Sequoia (15.0+) discovery:** the right-click → Open bypass that ADR-002 documents was **removed** in Sequoia. Recipients now get "Move to Bin" only; the workarounds are System Settings → Privacy & Security → "Open Anyway", or `xattr -dr com.apple.quarantine "/Applications/My Retirement Life.app"`. Code-signing + notarisation (Apple Developer ID, $99/yr) remain the proper fix — still deferred to v1.0. ADR-002's "right-click → Open" wording is stale; update if/when the ADR is revised.
    - **Smoke-test caveat to remember:** the packaged build and a running `python main.py` dev server share the same per-user `DATA_DIR` and so contend for the Oxigraph store lock (`~/Library/Application Support/MyRetirementLife/store/LOCK`). If both run at once, whichever loses the race crashes with `OSError: ... lock file ... Resource temporarily unavailable`. Not a packaging bug — same as two dev servers. When smoke-testing the packaged `.app` without killing the dev server, override both: `APP_PORT=8765 DATA_DIR=/tmp/mrl-smoke/data "./dist/My Retirement Life.app/Contents/MacOS/MyRetirementLife"`.
    - **Build artifacts:** 64M `.app`, 31M DMG (well under ADR-002's 80–150M ceiling).

49. **Native desktop window via pywebview — replaces "open in default browser".** Mark wanted the packaged app to feel like a real desktop app, not a Chrome tab. Chose pywebview over Electron/Tauri after architectural discussion: the webview is just a window manager around `localhost:8000`, the FastAPI + HTMX architecture stays unchanged, no Xcode / Node / Rust needed. Tauri also uses each OS's webview so it doesn't escape the three-engine split — only Electron does (by shipping Chromium), and the bundle-size + toolchain tax isn't worth it for this app. Mental model: a future "My Financial Life" sister app's larger datasets and richer interactivity won't be bottlenecked by the webview either — the real architecture decisions for that app would be SQLite-vs-Oxigraph for transaction-heavy data, and pure-HTMX vs HTMX + interactive islands for grid-style UX. Window shell is swappable later (`main.py` is the only file that knows about it).
    - **`main.py`** rewritten: uvicorn now runs in a daemon thread; main thread waits on `/health` (15s timeout via `urlopen`) then calls `webview.create_window(title=settings.app_name, url=..., width=1400, height=900, min_size=(900,600), resizable=True)` + `webview.start()` (blocking). `webview.start()` must be on the main thread on macOS — Cocoa requirement. When the window closes, the process exits and the daemon thread is torn down with it. Eager `from src.api.app import app` before starting the thread surfaces any import-time failure on the main thread instead of silently inside the worker.
    - **`requirements.txt`** gains `pywebview>=5.4` plus platform-conditional deps via `sys_platform` markers: `pyobjc-core`, `pyobjc-framework-Cocoa`, `pyobjc-framework-WebKit` on Darwin; `pythonnet>=3.0` on Win32. Installed pywebview 6.2.1 + pyobjc-core 12.1 in the venv.
    - **`tools/MyRetirementLife.spec`** adds `webview.platforms.cocoa` to `hiddenimports` so the Cocoa backend is always bundled (pyinstaller-hooks-contrib usually picks it up, but explicit is safer against future hook changes).
    - **Verified:** dev run (`python main.py`) and packaged `.app` both open a native WKWebView window with the dashboard rendered inside (logs show `GET /` plus every static asset returning 200 to the window's request context). Bundle 64M → 66M, DMG 31M → 33M. `dist/` was rebuilt after the pywebview changes; no further build needed before distributing.
    - **Windows + Linux next steps:** `main.py` change is platform-agnostic. Windows packaging will need a sibling `tools/build_windows.ps1` plus likely a separate `.spec` with `webview.platforms.winforms` or `edgechromium` as the explicit hidden import (WebView2 runtime is preinstalled on Win10/11). Linux deferred per Mark.

---

## Changes in session 5 (2026-05-30)

_Shipped in commit **`56d2da9`** — "Form-reset UX: PRG remaining edit handlers (accounts/investments/income)" (item 47)._

47. **PRG fix applied to the four remaining edit handlers.** Mark reported that saving an edit on a cash account left the form populated with no clear confirmation — the very same symptom session 4 fixed for budget. CLAUDE_CONTEXT item 45 had explicitly flagged accounts/investments/income edit handlers as still on the old stay-populated pattern. This session closes that gap.
    - `src/api/routes/accounts.py`: `GET /accounts` now also accepts `?saved=1`; `POST /accounts/{n}/edit` and `POST /accounts/asset/{label}/edit` both 303-redirect to `/accounts?saved=1` instead of re-rendering with `edit_account=…, saved=True`.
    - `src/api/routes/investments.py`: `POST /investments/{n}/edit` 303-redirects to `/accounts?saved=1` (investments share the unified accounts template per item 21).
    - `src/api/routes/income.py`: `GET /income` accepts `?added=1`/`?saved=1`. **Income add also fixed while there** — it had been a `TemplateResponse` re-render with `saved=True` (form happened to be blank because no `edit_source` was passed, but F5 would resubmit). Both `POST /income` and `POST /income/{n}/edit` now redirect properly (to `/income?added=1` and `/income?saved=1` respectively). `RedirectResponse` added to the imports line.
    - `src/templates/income.html`: added an `{% if added %}` banner above the existing `{% if saved %}` banner, matching the accounts/budget two-banner pattern.
    - `accounts.html` already had both `added` and `saved` banners from prior work — no template change needed there.
    - **Memory rule already in place** (from session 4): _every save (add + edit) should PRG to a blank form + "saved" banner; never leave a populated form_. This session applied that rule across the remaining handlers; no new memory written.
    - **Also debugged** during the session: a Chrome "Invalid value" balloon on the `drawdownLatestDate` HTML5 date input when typing dates by keyboard (the field has zero validation in our code — confirmed by grep). Root cause was Chrome's segment-by-segment parser rejecting transient partial-year states; picker works fine. No code change made — left as a known browser quirk. If users hit it often, a defensive `min`/`max` on the two `<input type="date">` fields would bound the year segment.

## Changes in session 4 (2026-05-29)

_Shipped in commit **`a281e34`** — "Form-reset UX + scenario/backup PhysicalAsset coverage" (items 45 + 46)._

45. **Add forms reset after save (post/redirect/get); edit too.** Mark reported that after saving an Add (account / budget line) the fields stayed populated and it wasn't clear it had saved. Root cause: `add_account`/`add_investment_account` 303-redirected to `/accounts/{n}/edit` (populated + the `/edit` scroll-to-form JS fired). Fixed: add handlers now PRG to `/accounts?added=1` (and `/budget?added=1`); the index GETs read the flag and show an `{% if added %}` "added and saved — form below is ready for the next one" banner over a blank form. Then Mark flagged that **adding a stage to an existing budget line** (the edit path) still stayed populated — so `save_edit_budget_line` now also PRGs to `/budget?saved=1` (blank form + "saved" banner; the persisted line with its new stage count is visible in the list). **This supersedes item 38's "stay in edit mode after save" for budget.** Memory updated: every save (add + edit) should land on a clean form + clear banner, never a populated form. (accounts/investments/income **edit** handlers still use the old stay-populated pattern — apply the same PRG fix if Mark hits them.)

46. **Scenario/backup save now includes PhysicalAssets — was silently deleting them.** Mark asked whether "save scenario" persists everything recent. Audit found `export_all_data()` only queried `CashAccount` + `InvestmentAccount`, never `PhysicalAsset`. Because `restore_all_data()` wipes the whole data graph (`DELETE WHERE { ?s ?p ?o }`) before re-inserting, loading any scenario/backup **permanently deleted every property/vehicle/collectible** (and its appreciation rate, sale year/value, proceeds-account link). Fixed: `export_all_data()` now emits a `physical_assets` list (iterating `ASSET_SUBCLASSES`, lazily imported from accounts.py) and `restore_all_data()` recreates `mrl:{subclass}_{n}` after the cash/investment accounts (so `assetProceedsAccount` targets exist), mirroring `save_asset()`. Export schema → 0.3.1. Verified with an isolated in-memory-store export→wipe→restore→export round-trip (all asset fields intact, other entities preserved). Confirmed already-covered: employer contributions, payroll flag, budget stages/segments, account types/tax/drawdown.

## Changes in session 3 (2026-05-28)

_Shipped in commit **`5a98682`** — "ADR-015 v1.2: payroll/salary-sacrifice flag + contributions on add form" (items 43 + 44)._

43. **Contributions can now be added on the new-account form (one step).** Previously the contribution panel only rendered when editing an existing account (`{% if edit_account %}` gate in `accounts.html`), so adding a workplace pension was add-then-edit. Extracted the contribution field grid into a Jinja macro `contrib_fields(contrib, required)` and render it inline in the main add form (wrapped `class-field class-field-cash class-field-invest` so it shows for cash + investment, hides + disables for assets → not submitted). Amount is `required` only in edit mode; add mode parses optionally so accounts can still be created with no contribution. `add_account`/`add_investment_account` gained string-typed contribution Form params + a shared `parse_add_contribution()` helper (in accounts.py, imported by investments.py) that returns save_contribution kwargs or None.

44. **ADR-015 v1.2 — payroll / salary-sacrifice flag (ontology 1.0.4).** Mark's insight: a contribution taken from payroll (occupational pension / salary sacrifice) shouldn't debit net income, because the engine treats entered income as net/take-home (income sources are never taxed — tax is drawdown-only, ADR-013), so debiting it double-counts. New boolean `mrl:contributionFromPayroll`; when true the employee portion behaves cashflow-wise exactly like the employer portion — credits the balance, excluded from `year_contribution_spending` (`projection.py` step 2b) and from `compute_annual_contributions_series` (`budget.py`). UI: checkbox below the employer field. Budget footer now splits three ways: cashflow-counted total (non-payroll employee), payroll subtotal, employer subtotal. Backup/restore round-trips the flag. **Parity:** absent/false → bit-identical to v1.1.

---

## Changes in session 2 (2026-05-27)

_Shipped in commit **`fcdb386`** — "ADR-015 v1.1: employer contribution split + pin numpy" (items 41 + 42)._

41. **Numpy missing in venv — 500 on `/projection`.** On Mark's laptop the project's `.venv` didn't have numpy installed even though it's in `requirements.txt`. Hitting `/projection` after a fresh install with a partial profile bombed at `run_monte_carlo`'s `import numpy as np` (line 1351), which sits BEFORE the early-return guards (`if not profile: return None`; "no investment accounts → return None"). Fixed by `pip install numpy` (got 2.4.6) and pinned `numpy==2.4.6` in `requirements.txt:11` for reproducibility. Considered moving the import below the guards as defensive belt-and-braces — declined as scope creep; numpy is a hard requirement, missing it is an install bug, not a code path to harden.

42. **Employer contributions (ADR-015 v1.1) — DONE end-to-end.** Replaces the originally-deferred `isEmployerContribution` boolean with a per-period `mrl:employerContributionAmount` decimal on the existing `mrl:AccountContribution`. Single contribution row in the UI carries BOTH an employee amount and an optional employer amount; engine credits balance with their sum but only debits cashflow with the employee portion. Chosen over the "multi-row contributions UI + boolean flag" design (originally sketched in ADR-015) because it captures the dominant real-world pattern (one workplace pension with employer match) with one extra field instead of a form rewrite. ADR-015 amended with a v1.1 section documenting the design and the rejected alternative.
    - **Ontology 1.0.2 → 1.0.3** (`docs/ontology/mrl-ontology.ttl`): new property `mrl:employerContributionAmount` (xsd:decimal, domain `mrl:AccountContribution`). Standalone property declaration — the `AccountContribution` class itself is not declared in the TTL (pre-existing oversight; pyoxigraph is schema-less, runtime works regardless). Parses cleanly (1286 → 1291 triples). **Requires `python tools\reload_ontology.py` (app closed)** before the new property declaration appears in the live store, though backend writes don't depend on the declaration.
    - **Backend** (`accounts.py` + `investments.py`): `get_contribution()` now returns `employerAmount` + `employerAnnual`; `save_contribution()` takes a new `employer_amount` kwarg (default 0.0) and writes the triple only when non-zero. Contribution route signatures gain `employerContributionAmount: float = Form(0.0)`. Default behaviour preserved when the field is absent (zero = identical to v1.0).
    - **Engine** (`projection.py`): `load_all_contributions()` returns `employer_annual_amount` alongside `annual_amount`. `_simulate_run()` year-loop step 2b splits the growth factor across employee + employer portions: balance is credited with the sum, `year_contribution_spending` (which becomes a cashflow deduction at `pre_net = ... - year_contribution_spending`) accumulates only the employee portion. `account_contribution_history` records the sum so per-account chart shows total inflow. **Parity preserved**: pre-v1.1 contributions have no `employerContributionAmount` triple → `_float()` defaults to 0.0 → employer portion contributes nothing → bit-identical engine output. MC inherits this automatically (shared `_simulate_run`).
    - **Budget page** (`budget.py` + `budget.html`): `get_all_contributions_for_budget()` exposes `employerAmount` + `employerAnnual`. The read-only "Account contributions" table per-row Amount and Annual-total cells show a small "+ £X employer" sub-line when non-zero; footer separates "Total annual contributions (your portion — counted in cashflow)" from "Employer portion (credits balances, not your cashflow)". `compute_annual_contributions_series()` was NOT modified — it reads `c.get("annualAmount")` which is and always was the employee-only annual. So the chart's "Account contributions" stack stays cashflow-accurate without any function-body change.
    - **UI** (`accounts.html`): "Amount per period" relabelled "Your contribution per period". New full-width field "Employer contribution per period" placed below the Amount/Frequency pair, above Start/End. Help text on the section now distinguishes the two parts. Live annual-equivalent hint (`updateContribAnnual()` JS) shows the split when both are non-zero: "Annual: £X you + £Y employer = £Z total"; falls back to the old single-value hint when employer is zero. Account list table contribution badge now sums employee + employer (with title attribute showing the split) when employer > 0; appends a small `*` glyph as a visual hint that there's a split.
    - **Backup/restore** (`settings_route.py`): contribution export adds `employerAmount` (uses existing `_opt_float`); restore writes the triple when present and non-zero. Old backups without the field round-trip cleanly (treated as zero).
    - **No engine parity verification** done this session — the parity argument is structural (the new `employer_annual_amount` reads as 0.0 from existing data, contributing 0 to every accumulator). If Mark wants belt-and-braces verification: run a projection before reload, restore the same backup, run again — totals should match exactly.

## Changes earlier this session (2026-05-26 → 2026-05-27)

38. **Edit-form UX: stay in edit mode after save + universal scroll-to-form.** Two coupled fixes prompted by a bug report — Mark observed "the end date reverts to infinity" on a budget line and "it's not clear where the editing is supposed to happen as the screen does not switch focus" when clicking Edit on accounts / budget / income. After tracing the end-date save path end-to-end and finding no place where the data could be silently dropped, I concluded the most likely cause was a UX confusion: the POST `/edit` handlers re-rendered with `edit_line=None`, which dropped the form into "Add a budget line" mode showing empty fields — easy to mistake for the saved value reverting.
    - **Stay in edit mode after save.** All five edit POST handlers now re-fetch the just-saved row and pass it back as `edit_line` / `edit_source` / `edit_account` so the form re-renders with the actual persisted state visible. If the end-date bug is real (rather than a UX artefact), this makes it immediately diagnostic — the user sees empty-after-save on the very same form. Affected handlers: `POST /budget/{n}/edit`, `POST /income/{n}/edit`, `POST /accounts/{n}/edit`, `POST /accounts/asset/{label}/edit`, `POST /investments/{n}/edit`.
    - **Universal scroll-to-form on `/edit` URLs.** New script appended to `base.html` (outside `{% block scripts %}` so it inherits everywhere). Runs on any path ending `/edit`. Scrolls the form into view via `scrollIntoView({behavior: 'smooth', block: 'start'})` and calls `.focus({preventScroll: true})` on the first non-hidden/non-readonly/non-disabled input. Targets `#budget-form`, `#income-form`, `#account-form` selectors — added `id="income-form"` to the income template to match (budget and accounts already had IDs from earlier work).
    - **Note for next session — diagnostic path if the bug is real**: if Mark reports that AFTER the stay-in-edit-mode fix he still sees the end-year field empty on the form after saving, that's a real persistence bug. I traced the path in detail — `_segments_from_form` correctly preserves the string, `save_budget_line_segments` correctly converts it to int and forwards to `save_segment`, `save_segment` correctly writes `mrl:segmentEndYear "{year}"^^xsd:integer` to the data graph, `get_segments_for_line`'s `gv("segmentEndYear")` correctly returns the lexical form. Inspection didn't find a bug. If it persists, add a print/log to `save_budget_line_segments` showing `segments` arg, and to `get_segments_for_line` showing the read-back dict. Then have Mark reproduce.

37. **Budget chart — inflation toggle (loan-aware).** Follow-on to Phase 3 after Mark observed the chart staying flat over time. New "With inflation (X.X%/yr)" checkbox on the chart card sits next to the Category/Line toggle; default off (real terms — preserves Phase 3 behaviour). When on, the chart shows nominal £ — non-loan lines lifted by `(1 + inflation/100)^years_from_start`, loan-type lines kept fixed-nominal (matches the projection engine's loan treatment so the budget chart and projection page agree on the same numbers).
    - `budget.py`: `_sum_lines_per_year()`, `compute_annual_contributions_series()`, `compute_annual_spending_by_category()`, and `compute_annual_spending_by_line()` all gain an `inflation_rate: float = 0.0` parameter. `_page_context` now lazy-imports `get_projection_settings` (fallback 2.5% inflation) and precomputes four chart shapes — `chart_series = {by_category: {real, nominal}, by_line: {real, nominal}}`. Loans use only their `segmentChangeRate`; non-loans add `inflation_rate + segmentChangeRate` per year. Contributions inflate too (they're future cash commitments).
    - `budget.html`: chart card header gains the inflation checkbox; the dataset key on the chart `{{ chart_series | tojson }}` replaces the old `{{ by_category | tojson }}` + `{{ by_line | tojson }}` pair. JS tracks two state booleans (`currentGrouping`, `currentInflation`) and picks from the precomputed shapes on toggle change. Y-axis title and the chart's mode hint update with the toggle ("Annual spending (today's £)" ↔ "Annual spending (nominal £, X.X% inflation)"). Snapshot metrics are kept in real terms with a small footnote — swapping them too was scope creep and they're identical in both modes for the "Today" snapshot anyway.
    - **Why loans don't inflate on the chart**: the projection engine treats `BudgetLineType_Loan` as fixed nominal (item 8 in this CLAUDE_CONTEXT — "Loan-line inflation"). If the chart applied inflation uniformly, the chart and projection page would silently disagree for any plan with a mortgage or car loan. The loan-aware lift here is the correct behaviour and saves a future "why doesn't the chart match the projection" bug report.

36. **Dashboard `KeyError: 'annual_amount'` — FIXED.** Phase 2's engine refactor moved `annual_amount` from each `BudgetLine` dict onto its segments, but `app.py:209` (`get_dashboard_data()`) still summed `l["annual_amount"]` to build the "today's annual spending" headline figure. On first launch after the 1.0.2 ontology + Phase 2 deploy the dashboard 500'd. Fixed by importing `find_active_segment` from `projection.py` and computing `annual_spending` from each line's currently-active segment (lines whose schedule doesn't cover today contribute zero — semantically more correct than the pre-Phase 2 behaviour, which summed every line's raw amount regardless of `budgetStartYear`). Grep'd the rest of `src/` for any remaining line-level reads of the old `annual_amount` / `change_rate` / `start_year` / `end_year` / `loan_end_year` keys — that was the only occurrence outside `projection.py` itself.

35. **Budget restructure (ADR-017) — Phase 3 (UI) — DONE.** Final phase. `src/templates/budget.html` rewritten end-to-end. Highlights:
    - **Chart toggle** "Category / Line" (join-button, top-right of the chart card). Default = Category. Datasets computed server-side via `compute_annual_spending_by_category()` / `compute_annual_spending_by_line()` in `budget.py`; JS swaps Chart.js datasets in-place via `chart.update()` (no rebuild). Each category band gets a deterministic HSL colour from `_category_palette()` keyed off the category name (stable across sessions). System group **"Account contributions"** pinned to teal (rgba 20,184,166 — matches the existing 4th-band convention). **"Uncategorised"** group pinned to neutral gray (rgba 156,163,175).
    - **Schedule editor** — replaces the old single-row amount/freq/start/end/changeRate. One segment row by default; "+ Add stage" button appends a new row pre-populated from the previous (start = prev end + 1, amount/freq/rate carried over). Per-row "×" remove (refuses to delete the last remaining stage). Per-row annual-equivalent hint updates live. **Client-side overlap validation**: O(n²) pairwise check on submit/change; conflicting ranges disable Save and show a red `ti-alert-triangle` notice. Gaps between stages are intentional and pass validation cleanly.
    - **Category combobox** — HTML5 `<input list>` + `<datalist>` of all existing `mrl:BudgetCategory` names (renames flow through automatically since the input fires off a name-based lookup at save). Below the input: 9 starter chip buttons (Housing, Food, Transport, Travel, Health, Subscriptions, Personal, Bills, Taxes) — clicking a chip sets the input value via `setCategory(name)`. Chips materialise as `BudgetCategory_N` instances ONLY when the user clicks Save with the chip's name in the input.
    - **Table changes** — new **Category** column (text only when set; "—" when uncategorised). Type column collapsed to a single-letter badge (M / D / L) with hover tooltip. Multi-segment lines: a `N stages` ghost badge next to the name, "multi-stage" placeholder in Annual total, range collapsed to first-segment-start → last-segment-end in the Schedule column.
    - **Manage categories card** — small grid of inline rename/delete forms, one per existing category. Rename POSTs to `/budget/categories/{n}/rename`; delete POSTs to `/budget/categories/{n}/delete` and refuses (server-side) if any line still references the category.
    - Removed: separate "Loan end year" field (folded into segment end year). The legacy single-amount form is gone — the form now ONLY accepts the segment list shape, so `POST /budget` and `POST /budget/{n}/edit` route signatures change. Form submission contract: parallel `segmentStartYear[]`, `segmentEndYear[]` (str so blanks → None), `segmentAmount[]`, `segmentFrequency[]`, `segmentChangeRate[]` lists plus the scalar `budgetLineName`, `budgetLineType`, `budgetCategoryName`. FastAPI `list[T] = Form(...)` handles the parsing.
    - Backend additions in `src/api/routes/budget.py`: `CATEGORY_SUGGESTIONS` constant; `ACCOUNT_CONTRIBUTIONS_LABEL` / `UNCATEGORISED_LABEL`; `_category_palette(name)`; `_sum_lines_per_year()`; `compute_annual_spending_by_category()` / `compute_annual_spending_by_line()`; `save_budget_line_segments()` (replaces `save_budget_line`); `_segments_from_form()` helper.

34. **Budget restructure (ADR-017) — Phase 2 (engine) — DONE.** `src/api/routes/projection.py` and `src/api/routes/budget.py` switched to segment-walking.
    - `projection.py`: new module helpers `_int_or_none()` and `find_active_segment(line, year)`. Rewrote `load_budget_lines()` to read each line's `mrl:BudgetLineSegment` instances via the `mrl:segmentOwner` back-link, returning `{line_type, segments: [{annual_amount, change_rate, start_year, end_year}, ...]}`. **Backwards-compatible fallback**: lines with no segments (pre-migration data or projection runs before `/budget` has triggered migration) get an in-memory single segment synthesised from the legacy line-level fields. The year-loop body in `_simulate_run()` replaced the three start/end/loan-end skip checks with a single `find_active_segment()` call; gap years naturally contribute zero. Loan-line semantics preserved (no inflation lift when `line_type == BudgetLineType_Loan`).
    - `budget.py`: rewrote `compute_annual_spending_series()` to walk `line.segments` via a local `_find_active_segment_dict()` helper. Behaviour is real-terms only — base inflation is NOT applied here (the budget page is conceptually a real-terms plan; the projection layers inflation on top).
    - **Parity argument**: growth exponent stays `years_from_start = year - current_year` (NOT `year - segment.start_year`), so single-segment migrated lines produce bit-identical numbers to the pre-ADR-017 engine. A line specified as £6000/yr at +2.5% real in 3% inflation, starting in 2031 with current_year=2026: pre-ADR-017 gave `6000 × 1.055^5 = 7,847` in 2031; post-ADR-017 same number. For multi-segment lines, each segment's amount is interpreted as "in today's £ at the projection start, switched in at segment.start_year" — matching the user's mental model ("in 2049 when the kids leave home, my groceries drop to £600 in today's money" → engine inflates £600 to 2049 nominal terms).
    - `loanEndYear` is folded into `segment.end_year` during migration; the engine no longer distinguishes the two (they meant the same thing — "this line ends here").

33. **Budget restructure (ADR-017) — Phase 1b (backend CRUD + migration) — DONE.** `src/api/routes/budget.py` rewritten end-to-end; `src/api/routes/settings_route.py` extended for export/restore.
    - **BudgetCategory CRUD** (5 functions): `get_all_categories()`, `get_category_by_name()`, `_next_category_n()`, `create_category()` (raises ValueError on empty or reserved name; case-insensitive dedup), `rename_category()`, `delete_category()` (refuses if any line still references it), `get_lines_using_category()`. Reserved name set: `RESERVED_CATEGORY_NAMES = {"account contributions"}` — case-insensitive, blocks UI-defined collision with the synthetic system group.
    - **BudgetLineSegment CRUD** (4 functions): `get_segments_for_line(line_n)`, `_next_segment_n()`, `delete_segments_for_line(line_n)` (SPARQL DELETE WHERE on the `segmentOwner` back-link), `save_segment(n, line_n, …)`.
    - **Idempotent migration** `migrate_legacy_budget_lines_to_segments()` — called on every `GET /budget` render. Two guards (both cheap quad-pattern queries): if any `BudgetLineSegment` exists already, no-op; if no `BudgetLine` has `budgetLineAmount`, no-op. For each legacy line, creates ONE `BudgetLineSegment_N` copying amount / frequency (or `FrequencyType_Monthly`) / change_rate (or 0) / startYear (or current_year) / endYear (or loanEndYear). **Deprecated line-level properties are LEFT IN PLACE** per ADR-017 §3 — survives a re-run from a re-restored old backup. Originally had an in-memory `_migration_checked` cache; removed it once realised it would prevent re-migration after a backup restore wipes the data graph mid-session.
    - `get_all_budget_lines()` rewritten: reads each line's segments + category, returns the new shape AND a flattened first-segment view at the top level (`amount`, `frequency`, `annualAmount`, `changeRate`, `startYear`, `endYear`, `loanEndYear`) for backwards-compatible template rendering. Pre-migration legacy lines fall through to reading line-level fields directly.
    - `save_budget_line()` (Phase 1b version — superseded in Phase 3): accepts `category_name`, wipes existing line-level triples + segments, writes only `budgetLineName` / `budgetLineType` / `budgetOwner` / optional `budgetCategory` to the line, then writes ONE segment. Category resolution: case-insensitive lookup, create on demand if no match.
    - `_page_context` exposes `categories` and `category_suggestions`.
    - 3 new routes: `POST /budget/categories`, `POST /budget/categories/{n}/rename`, `POST /budget/categories/{n}/delete`. All return 303 redirect on success, re-render with `category_error` context key on `ValueError`.
    - `delete_budget_line` now calls `delete_segments_for_line(n)` before wiping the line itself.
    - **settings_route.py**: export adds `budget_categories` and `budget_line_segments` lists + `categoryN` field on each budget line. Restore order: **categories → lines → segments** so the linking IRIs are valid. Old v0.3 backups (no categories, no segments) still restore cleanly — legacy line fields are written, migration creates segments on next `/budget` render. New backups omit the legacy line-level fields (Phase 1b's save clears them); the segments block carries the truth.
    - Module re-parses cleanly; import-up-to-store-lock succeeded.

32. **Budget restructure (ADR-017) — Phase 1a (ontology) — DONE.** `docs/ontology/mrl-ontology.ttl`.
    - Version bumped 1.0.1 → 1.0.2.
    - New class `mrl:BudgetCategory` with 3 properties: `categoryName` (xsd:string; "Account contributions" name reserved for the synthetic system group), `categoryDisplayOrder` (xsd:integer, optional manual ordering), `categorySource` (xsd:string; reserved for future MFL Level-1 ingest — "user" by default, "mfl-level-1" when imported).
    - New property `mrl:budgetCategory` on `mrl:BudgetLine` (range `mrl:BudgetCategory`, optional). Applies to all line types incl. Loan — a mortgage is categorised as Housing alongside utilities, not in a separate Loans band.
    - 6 line-level properties marked `[DEPRECATED in 1.0.2 — see ADR-017]` in their comments (kept on the class for migration safety): `budgetLineAmount`, `budgetLineFrequency`, `annualChangeRate`, `loanEndYear`, `budgetStartYear`, `budgetEndYear`.
    - Repurposed the pre-existing post-MVP `mrl:BudgetLineSegment` stub. Section header rewritten (no longer "post-MVP" — quotes the family-stage groceries example from the ADR). Class comment rewritten. Property changes: dropped `segmentAmountOverride` (legacy "override" concept inconsistent with segments-as-source-of-truth), renamed `segmentOfLine` → `segmentOwner` (symmetric with `mrl:contributionOwner` on AccountContribution, ADR-015). Added: `segmentAmount` (required), `segmentFrequency` (object → skos:Concept). Existing `segmentStartYear` / `segmentEndYear` / `segmentChangeRate` kept with refreshed comments.
    - **rdflib parsed the result cleanly — 1286 triples, no syntax errors.**
    - **Requires `python tools\reload_ontology.py` (app closed)** before Phases 1b/2/3 can function.

31. **ADR-017 — Budget line segments and user-defined categories — drafted and Accepted.** Mark (business architect) flagged the budget shortcoming during planning: the current `mrl:BudgetLine` cannot represent life-stage spending changes continuously (e.g. groceries: £500/mo single → £1500/mo with kids for 18 years → £600/mo empty-nest) without splitting one logical category into multiple discontinuous lines, which then fragments the future by-category chart.
    - **Two coupled additions in one ADR** since they restructure the same `BudgetLine` shape:
      1. `mrl:BudgetCategory` (user-created, NOT a fixed enum). Categories are first-class instances so a rename is one edit; UI offers 9 starter chip suggestions that materialise only when adopted. Reserved name `"Account contributions"` collides with the synthetic system group (derived at render from `mrl:AccountContribution` instances, ADR-015) — UI rejects user-defined categories with that name. **Loans are NOT a system category** (Mark's call): a mortgage takes the Housing category like any other line. Line type (Mandatory / Discretionary / Loan) drives engine math only; category drives chart grouping. `mrl:categorySource` reserves provenance for a future MFL Level-1 ingest path (ADR-010).
      2. `mrl:BudgetLineSegment` linked via `mrl:segmentOwner` (mirrors `mrl:contributionOwner` from ADR-015). A line has one-or-more segments; in any given year at most one is active. Gaps between segments contribute £0 in that year — by design (Mark's example: pausing the Travel category for two years to pay down a mortgage faster).
    - **Decisions captured** (in addition to the two main ones): existing budget lines migrate idempotently on startup (one segment per legacy line, deprecated fields left in place); categories are optional for ALL line types (lines without one fall into the synthetic "Uncategorised" group on the chart); category management is inline only (no dedicated admin page) for v1; categories without references are NOT auto-deleted, but the delete endpoint refuses while references exist; chart default flips to by-category (Mandatory/Discretionary/Loans grouping retired).
    - `docs/adr/ADR-017-budget-line-segments-and-user-defined-categories.md` drafted, revised once on Mark's feedback (loans-not-a-system-group, chip list updated to 9 incl. Bills + Taxes, drop "Other" chip, no warning UI on gaps), flipped to Accepted. `docs/adr/README.md` index row + summary paragraph added.

---

## Changes earlier (2026-05-25)

30. **Asset model — Phase 4 (dashboard redesign) — DONE.** Final phase of the asset project: replaces the old setup-checklist + balance-trajectory mini-chart layout with a net-worth-by-account hero view. **User instruction:** replace the data-present dashboard wholesale; first-run welcome state and the setup-checklist-when-incomplete card stay (onboarding survives).
    - `src/api/app.py` `get_dashboard_data()`:
      - Loads physical assets via `load_all_assets()` (lazy import). New context keys: `asset_count`, `asset_total_balance`.
      - New `snapshots` dict computed from the projection — three points in time (today / retirement / final), each broken down into `cash` / `invest` / `assets` / `total`. Helper `_snapshot_at(idx)` sums per-class balances at that year index, using `projection.account_balances` + `projection.account_classes` + `projection.asset_balances` (all from Phase 3). Snapshot at retirement-year omitted if the retirement year is outside the projection range (defensive).
    - `src/templates/dashboard.html` data-present branch rewritten:
      - Confidence banner kept verbatim.
      - **Four snapshot cards**: Today's net worth · Years to retirement · At retirement · At life expectancy. Each net-worth card shows the total plus an inline per-class breakdown (blue dot = cash, green = invest, amber = assets; amber dot only renders when assets ≠ 0). Macro `nw_breakdown(snap)` shared across the three monetary cards. Final-year card flips to error colour with `−` prefix if net worth is negative.
      - **Hero net-worth chart**: full-width stacked-area Chart.js, one dataset per account + asset. Stack order cash → invest → assets so the "spendable" portion sits at the bottom and illiquid assets ride on top. Cash blue palette, invest green palette, assets amber palette. ★ marker on retirement year. Caption explains the class colour scheme.
      - **Per-account legend**: chip filter if ≤8 datasets, dropdown filter otherwise — same adaptive pattern as `/projection`'s By Account chart. Helpers `_buildChipFilter` / `_buildDropdownFilter` / `_updateNetworthDropdownLabel` are lifted from projection.html with namespace prefixes (`networthChartInstance`, `nw-filter-lbl`).
      - **Setup at a glance**: five compact clickable count cards replace the old vertical Quick access sidebar — Accounts · Investments · Assets · Income · Life events. Each links to the relevant section. Tabler icons coloured to match the class (blue/green/amber/primary).
      - Removed: old "Total savings" / "Annual spending" / "Balance at retirement" three-card row, balance-trajectory mini chart, vertical Quick access sidebar, old `miniChart` JS.
      - Kept: first-run welcome screen, setup-checklist card (when incomplete), drawdown-not-configured nudge banner.
    - `account_balances` is unchanged from the engine perspective (Phase 3 just added `asset_balances` as a parallel key); this dashboard is the first consumer of `asset_balances`.

29. **Asset model — Phase 2 (auto Life Event sync) + Phase 3 (engine) — DONE.** Asset sales now automatically generate a managed `LifeEventType_AssetSale` event linked back to the asset, and the engine projects each asset's value year-by-year and disposes it at the sale year. End-to-end: create an asset → save year → sale event auto-appears on `/life-events` and at sale year the engine zeroes the asset and credits proceeds to the destination account.
    - **`src/api/routes/life_events.py`:**
      - `EVENT_TYPE_LABELS` extended with `LifeEventType_AssetSale → "Asset sale"`. New `USER_EVENT_TYPE_OPTIONS` subset (excludes `AssetSale`) used by `_page_context()` so the form dropdown doesn't expose the auto-managed type.
      - `get_all_events()` now also reads `mrl:sourceAsset` and resolves the asset's `mrl:accountName` in the same pass, returning `sourceAsset` (label) + `sourceAssetName` (display) on every event dict. Empty for user-created events.
      - `save_event()` gains a `source_asset_label` parameter that writes the `mrl:sourceAsset` triple when set.
      - New helpers `find_event_n_by_source_asset(label) → int | None` and `delete_event_by_source_asset(label)`. Asset-event lookup is unique (one sale event per asset).
      - Route guards on `GET /life-events/{n}/edit`, `POST /life-events/{n}/edit`, `POST /life-events/{n}/delete`: if the target event has `sourceAsset` set, redirect (303) to `/accounts/asset/{sourceAsset}/edit` instead of allowing direct edits/deletes. User must change the asset to influence the sale event.
    - **`src/api/routes/accounts.py`:**
      - New `_sync_asset_sale_event(asset_label, asset_name, current_value, sale_year_str, sale_value_str, proceeds_account, appreciation_rate_str)` helper. Called from `save_asset()` after the asset's own triples are written. Logic:
        - Cleared/blank `sale_year` → delete any linked event.
        - Set `sale_year` → compute amount as `sale_value_str` if provided, else `current_value × (1 + appreciation/100)^(sale_year - today.year)`. Stored as NEGATIVE per the LifeEvent convention (positive = cost, negative = receipt). Reuses existing event N if found via `sourceAsset` lookup, else allocates next available LifeEvent N. Calls `save_event()` with name=`"Sale: {asset name}"`, type=`LifeEventType_AssetSale`, year=`sale_year`, amount, `received_by_account=proceeds_account`, `source_asset_label=asset_label`.
      - `delete_asset()`: now calls `delete_event_by_source_asset(asset_label)` first (replaces the prior defensive sourceAsset wipe), then deletes the asset's triples.
      - All life_events imports are LAZY (inside function bodies) to break the `accounts → life_events → projection → accounts` cycle.
    - **`src/templates/life_events.html`:** asset-sourced rows now show an inline "Auto · {asset name}" badge (warning colour) next to the event name. Edit button replaced with "Edit asset →" link routing to `/accounts/asset/{sourceAsset}/edit`. Delete button hidden for sourced events (user deletes the asset to remove the event). `LifeEventType_AssetSale` rendered with success-colour badge in the Type column.
    - **`src/api/routes/projection.py` (Phase 3 engine):**
      - New `load_all_assets()`: iterates the three PhysicalAsset subclasses, FX-converts the balance, reads `assetAppreciationRate`, `assetSaleYear`, `assetProceedsAccount` (as local-name string).
      - `_simulate_run()` gains optional `all_assets` parameter (defaults to `[]`). Pre-loop: forward-grows asset opening balances from `balance_date` to `current_year`; pre-zeros any assets already sold. Per-year (new step 7b): if `year >= sale_year`, zero the asset; else appreciate by `assetAppreciationRate`. Closing values recorded into `asset_history`. Result dict gains `asset_balances` (parallel to `account_balances`).
      - `run_projection()` loads assets, passes them to `_simulate_run()`, and adds `asset_balances` + `asset_names` + `asset_subclasses` to the response. **Parity preserved**: when no assets exist, `all_assets=[]` and every existing engine output is bit-identical (verified by the no-op path through the loop).
      - `run_monte_carlo()` deliberately does NOT load assets — MC chart shows only spendable balance (cash + invest), and asset sale proceeds still reach MC via the Life Event path (`life_events` is passed through). Saves N × n_years asset calculations per MC sim.
    - **Assets are NOT included in `balances` (the spendable total)** — they live in a parallel `asset_balances` dict. This means: the "runs out year" detection, MC success_rate, drawdown waterfall, surplus routing, and the existing per-account projection chart all behave identically with or without assets. Net worth (Phase 4) reads both dicts.
    - **Sale value alignment between Phase 2 and Phase 3**: Phase 2 computes sale value at save time using `current_value × (1+r)^(sale_year - today.year)`; Phase 3's engine appreciates the asset each year so the asset's value at start of `sale_year` equals the same formula. The asset is zeroed when `year >= sale_year` (before this year's appreciation runs) so values align cleanly.
    - **Requires**: `python tools\reload_ontology.py` (app closed) for the ontology additions from Phase 1a (still needed if not already done). Then smoke-test: edit a PropertyAsset, set sale year + proceeds account, save → `/life-events` should show "Sale: {name}" with the "Auto · {asset name}" badge; `/projection` per-account chart should show the proceeds account's balance step up at sale year and the asset's value (in `asset_balances`, not yet on a chart until Phase 4) step down to zero.

28. **Asset model — Phase 1b (backend) + Phase 1c (UI) — DONE.** End-to-end CRUD for physical assets on the unified `/accounts` page, with no engine integration yet (assets don't move balances in the projection — that's Phase 3).
    - `src/api/routes/accounts.py`:
      - New `ASSET_SUBCLASSES` dict mapping `PropertyAsset` / `VehicleAsset` / `CollectibleAsset` → display labels.
      - `_next_asset_n(subclass)`: per-subclass N counter (PropertyAsset_1, VehicleAsset_1 can coexist).
      - `get_all_asset_accounts()`: mirrors `get_all_accounts()` pattern, iterates the three concrete subclasses, returns merged list annotated with `asset_subclass` + `label` (e.g. `PropertyAsset_3`) + asset-specific fields (`appreciationRate`, `saleYear`, `saleValue`, `proceedsAccount`).
      - `save_asset()`: takes subclass + N + the shared Account fields + asset-specific fields. Sale value/proceeds only persisted when sale year is set. IRI = `mrl:{subclass}_{n}`.
      - `delete_asset()`: also wipes any `mrl:sourceAsset` back-links defensively (Phase 2 will extend this to delete the linked Life Event).
      - `_parse_asset_label()`: helper splitting `"PropertyAsset_3"` → `("PropertyAsset", 3)`.
      - Four new routes: `POST /accounts/asset` (create), `GET /accounts/asset/{label}/edit` (load form), `POST /accounts/asset/{label}/edit` (save), `POST /accounts/asset/{label}/delete`. Single URL family avoids per-subclass route duplication.
      - `get_all_accounts_combined()` now also returns assets annotated with `account_class="PhysicalAsset"` + `accountTypeLabel` from `ASSET_SUBCLASSES`. Also adds `label` to cash + invest entries for consistency (`CashAccount_2`, `InvestmentAccount_5`).
      - `_render_accounts()` context now exposes: `asset_subclasses` (for the form's class-locked subclass dropdown), `asset_total_balance` (header strip), `proceeds_account_options` (asset's proceeds-account dropdown — restricted to cash + invest accounts).
    - `src/templates/accounts.html`:
      - Header strip now shows "Cash · Investments · Assets" totals (assets only when > 0).
      - Table: amber dot for asset rows; subclass label in Type col; appreciation% (signed, red if negative) in Yield col; "Sell {year}" or "Hold" badge in Draw priority col for assets; "—" in tax + contribution cols; Detail link hidden for assets (no per-account projection page for them yet). Edit/Delete URLs use `/accounts/asset/{label}/...`.
      - Class tabs: third "Physical asset" (amber dot) tab. All three tabs lock-disable when editing a different class.
      - Generic tri-state JS toggle: `CLASS_NAMES = ['cash', 'invest', 'asset']`. New `applyClassVisibility(klass)` iterates `.class-field` elements and checks which of `.class-field-{cash|invest|asset}` they carry — supports fields that belong to MULTIPLE classes (e.g. jurisdiction is `class-field-cash class-field-invest`, hidden for asset). Form action mapping: `{cash: '/accounts', invest: '/investments', asset: '/accounts/asset'}`.
      - Asset-specific form fields (block of 5): subclass select (Property/Vehicle/Collectible — disabled + hidden-input back-pop when editing), annual appreciation rate %, planned sale year, sale value override, proceeds account dropdown (full-width). Tax/Drawdown collapsible and Contribution panel both hidden for asset class.
    - Verified `accounts.py` parses (no syntax issues). Templates untested in-browser — Mark to reload ontology (`python tools\reload_ontology.py`, app closed) then smoke-test before Phase 2 builds on top.

27. **Asset model — Phase 1a (ontology) — DONE.** Foundation for a 4-phase project introducing physical assets (property, vehicles, collectibles) as a third account class with planned-sale support, culminating in a new net-worth dashboard chart (Phase 4). **Design decision (user, business architect):** reuse the existing pre-staged `mrl:PropertyAsset` (used by sister app MFL) under a new `mrl:PhysicalAsset` intermediate class, with two new concrete subclasses for vehicles and collectibles. **Sale model (user):** sale fields live on the asset itself (single source of truth) but the engine auto-generates a managed `LifeEventType_AssetSale` linked back via `mrl:sourceAsset` — inherits all existing Life Event visualisation without re-implementing it.
    - `docs/ontology/mrl-ontology.ttl`:
      - New `mrl:PhysicalAsset` intermediate class (subClassOf `mrl:Account`). Comment notes physical assets contribute to net worth but do NOT participate in retirement drawdown.
      - Four new properties on `mrl:PhysicalAsset`: `assetAppreciationRate` (decimal %/yr — negative for depreciation), `assetSaleYear` (integer — optional), `assetSaleValue` (decimal — optional manual override; engine otherwise uses appreciated value), `assetProceedsAccount` (object property → `mrl:Account`).
      - `mrl:PropertyAsset` re-parented from `mrl:Account` to `mrl:PhysicalAsset`. Comment updated to reflect dual MRL/MFL use; retains property-specific extras (`propertyAddress`, `purchasePrice`, `isMortgaged`) for MFL compatibility.
      - New `mrl:VehicleAsset` and `mrl:CollectibleAsset` concrete subclasses of `mrl:PhysicalAsset`.
      - `mrl:OtherAsset` comment updated to flag as legacy / superseded by the PhysicalAsset hierarchy (kept in TTL for MFL compatibility; not used by MRL UI).
      - New `mrlx:LifeEventType_AssetSale` SKOS individual in the existing LifeEventType vocab. Description explicitly warns "do not create directly via the Life Events UI — auto-generated from a PhysicalAsset with a sale year set".
      - New `mrl:sourceAsset` object property on `mrl:LifeEvent` (range `mrl:PhysicalAsset`) — back-link enabling Phase 2's auto-event managed pattern.
    - **Requires `python tools\reload_ontology.py` (app closed)** before Phases 1b/1c can function.
    - Phases 1b (backend CRUD), 1c (Asset tab on `/accounts`), 2 (auto-Life-Event sync), 3 (engine: appreciate + dispose), 4 (net-worth dashboard) tracked in task list. See **In progress** section in backlog below.

26. **Pre-beta documentation — MC + deposit-account explainers + CHANGELOG.md.** User-facing context for the two big engine changes this session (items 23, 24). Wording is product-positive throughout — no "earlier versions" framing — since no external users have tried the app yet.
    - `src/templates/projection.html`: new collapsible `<details>` "How to read this" panel inside the MC card. Three paragraphs: success-rate definition (% of N sims where balance > 0 every year), shock model (same shock across all investments yearly, cash deterministic), and sequence-of-returns risk explaining why MC and the deterministic projection can disagree on the same plan.
    - `src/templates/income.html`: new collapsible `<details>` "How the deposit account affects your projection" panel below the Deposit account dropdown — explicit on the drawdown-priority caveat that drove the £2.66M divergence on test data (item 24). Field help text softened from "income behaves as before" to "credited to the projection's spending account and offsets that year's spending directly".
    - `CHANGELOG.md` (new, repo root): first changelog entry — `[Unreleased — beta engine updates] — 2026-05-25`. Keep a Changelog format. Engine section: MC refactor. Feature section: deposit account + caveat block. Fixed: personal-allowance over-shielding + Accounts header FX bug. Brief "added in earlier sessions" pointer to git log so the changelog isn't starting from zero.

25. **Accounts page header totals — FX-converted (bugfix).** The "Cash: £X · Investments: £Y" header on `/accounts` was summing raw `accountBalance` values without converting via `mrl:exchangeRateToBase`, so USD accounts were added as if they were GBP. On test data this displayed Investments as £1,824,139 (the raw USD sum) when the correct base-currency total was £1,276,897 (×0.7 FX). FIXED in `src/api/routes/accounts.py` `_render_accounts()`: new inline `_base_balance(a)` helper reads `a["balance"]` and `a["exchangeRate"]`, defaults FX to 1.0 when blank/invalid, and the cash/invest totals now sum the converted values.
    - **Scope of the bug:** display-only. The engine has always FX-converted via `load_all_accounts()` (`base_balance = raw_balance * fx_rate`), so projections, MC, dashboard `total_balance`, and the per-account balance arrays were already correct. Only the `accounts.html` header was misreporting.
    - `app.py` dashboard `total_balance` was checked and is correct — it uses the engine-side `load_accounts()` shim, which inherits the FX-correct `load_all_accounts()` output.

24. **Income deposit account UI — RESOLVED (using existing `mrl:creditedToAccount` predicate).** Each income source can now nominate the account that receives it each year. The ontology already defined `mrl:creditedToAccount` (range `mrl:Account`) as a Post-MVP property; this session is the post-MVP implementation.
    - `docs/ontology/mrl-ontology.ttl`: comment on `mrl:creditedToAccount` rewritten to describe the now-implemented semantics ("engine adds the year's income amount directly to this account's balance instead of treating it as cashflow against the projection's spending account"). No structural change — predicate already existed, no `tools\reload_ontology.py` needed.
    - `src/api/routes/income.py`: `get_all_income_sources()` reads `creditedToAccount` (stores the local name, e.g. `CashAccount_2`). `save_income_source()` accepts and persists it; falls through gracefully when unset. Add + edit POST handlers accept `creditedToAccount: str = Form("")`. `_page_context()` now also exposes `all_accounts` (via `get_all_accounts_combined`) so the template can render the dropdown.
    - `src/templates/income.html`: new full-width dropdown labelled "Deposit account (optional)". Options: `— follow projection surplus routing (default) —` plus every account (cash + investment, investment annotated). Option value is `{account_class}_{n}` (matches the engine's label). Help text frames the choice: "salary → current account, pension → ISA. When unset, income behaves as before — credited to the projection's spending account."
    - `src/api/routes/projection.py`: `load_all_income_sources()` now returns `deposit_account` (local name, or `None`). `_simulate_run` year loop changed:
      - `income_amount` still tracks total income earned for display (chart unaffected).
      - **New** `unrouted_income` accumulates income for sources WITHOUT a deposit account.
      - Sources WITH a deposit account: `balances[deposit] += amt` (direct credit).
      - Non-reinvested dividends always go to `unrouted_income` (dividends-routing is a future enhancement).
      - `pre_net = unrouted_income + general_receipts - total_spending - year_contribution_spending` (was `income_amount + ...`).
    - **Engine semantics — important user-facing implication, surfaced during testing:** routing income to a low-drawdown-priority account (e.g. priority 999, "drawn last") MATERIALLY changes outcomes. With unrouted income, the engine effectively offsets spending → smaller drawdown → investments compound longer. With routed income, drawdown covers the FULL spending → investments drain faster → ~30 yrs of compound growth lost on the high-priority drawdown accounts. On test data this produced a £2.66M divergence in final balance between with/without deposit on `CashAccount_1` (HSBC Premier, priority 999). This is correct behavior per the existing drawdown waterfall model — the deposit account choice is a real financial decision. Users who want income to fund spending should ensure the deposit account is in their drawdown waterfall (low priority number).
    - **Verification:** parity confirmed when no income source has a deposit account (`final_balance=398786`, `total_tax_paid=747689` — identical to pre-feature baseline). Per-account histories sensible. Browser smoke test: add, edit, save round-tripped via POST; dropdown options populate correctly using `{class}_{n}` labels.
    - **NOTE — heads-up about test data:** while round-tripping a POST during verification I overwrote `IncomeSource_1` (was "Remaining 2026 Salary"; now a "Rental Income" entry with `creditedToAccount=CashAccount_1`). Mirrors the placeholder-overwrite during the unified-accounts session (item 21). Real test data should be restored manually before end-to-end testing.
    - **Open consideration (not implemented):** when `deposit_account == spending_account`, the "with" and "without" cases still differ (the engine doesn't recognize that income flowing into the spending account effectively offsets spending). A future refinement could treat this case as equivalent to "unrouted" — but the current behavior is consistent with the per-account flow model and surfaces the cost of compounding correctly. Worth revisiting if user feedback indicates the divergence is surprising.

23. **MC model discrepancy — RESOLVED via shared year-loop refactor (ADR-012 §4 revised).** The Monte Carlo engine was an aggregate-pool model that ignored drawdown eligibility, tax (ADR-013), contributions (ADR-015), and life-event account routing; it also let the investment pool go arbitrarily negative because cash was never drained. Result: success rates ~100% even when the deterministic engine showed depletion. Fixed by extracting the year-loop body from `run_projection` into a shared helper `_simulate_run(...)` that takes optional per-year `return_shocks` / `inflation_shocks` arrays (in % units).
    - `src/api/routes/projection.py`: new `_simulate_run()` (~250 lines, pure function over loaded data + proj_settings + shock arrays). `run_projection()` becomes a thin wrapper calling it with zero shocks. `run_monte_carlo()` becomes a thin wrapper calling it N times with `numpy.random.normal(0, σ_profile, n_years)` shocks per sim, then computing P10/P50/P90 across sims and a `success_rate = % of sims where total balance > 0 every year`. Default `n_sims` reduced from 500 to 250 (per-account loop in pure Python is slower than the old vectorised aggregate-pool inner loop; trades MC granularity for full model coherence). Performance: ~0.4s for 250 sims × 37 years × 12 accounts on test data.
    - Pre/post parity proven: ran `tools/_baseline_projection.py` (throwaway) before refactor, captured all key scalars + year-level + per-account histories. Post-refactor `tools/_compare_baseline.py` (throwaway) reported "OK — outputs identical" across 37 years × 12 accounts. The deterministic engine's numbers are bit-for-bit unchanged.
    - Engine semantics for MC: same shock applied across all investment accounts each year (single market-wide move, not per-account independent). Cash interest stays deterministic (ADR-012 §2). Negative simulated investment rates clipped at −100%.
    - `src/templates/projection.html`: badge condition flipped from `mc.cash_floor` to `mc.has_cash` (the legacy cash_floor concept doesn't apply once cash is drained alongside investments); added a "Same model as projection" tooltip badge highlighting MC↔deterministic consistency; removed the dashed-line caption text (legacy cash_floor line no longer rendered). `cash_floor` key returned as `[]` for backward compatibility — existing template checks fall through cleanly.
    - `src/api/routes/projection.py` route handler: `run_monte_carlo()` now receives `proj_settings=proj_settings` so MC uses the full tax/drawdown configuration, not just inflation_rate + mc_profile.
    - **Behavioural impact for users:** MC success rates now reflect the true range of outcomes. On test data the deterministic engine reports green/"On track" (£399k final balance) but the new MC reports ~46-48% success — meaning under volatility, over half the stochastic paths run out before life expectancy. This is the gap the old MC was hiding.
    - `docs/adr/ADR-012-per-account-balance-tracking-and-monte-carlo-scope.md`: §2 amended (revision note pointing forward to §4), §4 fully rewritten to document the shared-helper architecture with rationale on the prior discrepancy and a performance note, §5 added (per-account history result keys, unchanged), §6 supersession note expanded to cover both engines.
    - **Future direction (per user, recorded here for context — not yet implemented):** post-1.0 beta will add per-account lot/position tracking with cost basis, enabling true GIA gains-only CGT calculation (ADR-013 §4.1). May come from MFL data portability (sister app) or live natively in MRL. With shared `_simulate_run`, lot-aware drawdown becomes a localized change to the helper's drawdown step + `_compute_source_tax` — both engines pick it up automatically.

22. **Backlog #9 — Personal-allowance aggregation (ADR-013 two-layer model).** Two distinct issues addressed:
    - **Engine bug (Problem 2):** `total_taxable_at_source` was summing `(gross − account_tax_free)` for every drawn account regardless of `tax_treatment`. So ISA / `PostTaxTaxFreeWithdrawal` and `TaxFree` withdrawals erroneously consumed the residence personal allowance. FIXED in `src/api/routes/projection.py`: new module constant `RESIDENCE_EXEMPT_TREATMENTS = {"TaxTreatment_PostTaxTaxFreeWithdrawal", "TaxTreatment_TaxFree"}`; `run_projection` year loop now guards the `total_taxable_at_source` accumulator with `if acc["tax_treatment"] not in RESIDENCE_EXEMPT_TREATMENTS`. GIA (`PostTaxGainsOnly`) still counts toward residence-taxable income (effective rate approximates CGT; refining this would need cost-basis data, out of scope until MFL portability).
    - **UI confusion (Problem 1 — the "double-applied" symptom):** users naturally enter their personal allowance figure into both the per-account "Annual tax-free withdrawal" and the projection-page "Annual personal allowance", which legitimately stacks the shields and silently under-taxes. Three changes:
      - `src/templates/accounts.html` field relabelled "Annual tax-free withdrawal (PCLS / instrument allowance)"; help text rewritten to call out "Instrument-level shield from this account's source tax — e.g. UK pension 25% PCLS spread annually. **Not your personal allowance** — that's a single residence-level figure on the Projection page; entering it here too would double-count."
      - `src/api/routes/projection.py` projection route now builds a `tax_shield_summary` context (personal_allowance, per-account list with name + amount + tax_treatment + account_class, accounts_total, combined, show flag).
      - `src/templates/projection.html` new "Tax shield summary" card inserted between the Assumptions card and the Drawdown settings card. Three-column metric layout (Personal allowance · Account allowances · Combined annual shield), per-account breakdown chips (blue dot = cash, green = investment), and an info alert explaining that the two layers intentionally stack but identical figures in both indicate over-shielding. Card hides itself when both layers are zero.
    - Verified end-to-end: dev server returned 200 on `/projection`, `/accounts`, `/accounts/1/edit`; new label, help text, and shield panel all rendered against the existing placeholder profile + MS 401(k) account (£12,000 PCLS shield).

---

## Changes earlier (2026-05-23)

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

13. **Backlog #6 (rest) — `£` sweep across remaining templates.** Commit `dd6298c`. `dashboard.html`, `settings.html`, `accounts.html`, `investments.html`, `investment_projection.html`, `projection.html`: every hardcoded `£` (Jinja and inline JS) replaced with `base_currency_symbol()` / a `BASE_SYMBOL` const injected at the top of each script block via `tojson`. Chart.js axis titles like `'Balance (£)'` become `'Balance (' + BASE_SYMBOL + ')'`. **Zero `£` left in any template** — switching `Person.baseCurrency` now flips every display in the app without code changes. Per-account balance displays keep using `account.currencySymbol` (each account's own currency), unaffected.

14. **Budget summary respects start/end years (mini-chart).** Commit `1b8c9d4`. `/budget`'s previous 4-card summary summed every line's `annualAmount` ignoring its active window, so non-overlapping lines double-counted in any given year (engine was already correct). Replaced with a stacked-area Chart.js chart of annual spending year-by-year + three snapshot metrics (Today, At retirement, Peak — each year-labelled). New helpers in `budget.py`: `compute_annual_spending_series()` and `get_budget_metrics()`. Chart is in today's pounds — applies each line's `change_rate` (real growth) but NOT base inflation; the projection page is where inflation layers in. Horizon comes from `load_profile()` with a 40-year fallback during onboarding.

15. **Backlog #7 — Contributions explicit on the budget chart.** Commit `08b7f0c`. Adds account contributions as a 4th teal stacked area on the `/budget` chart and as a breakdown line beneath each snapshot card. Each card's "total" is now spending + contributions — full cashflow commitment for that year — with a `£X spending · £Y contributions` sub-line. New helper `compute_annual_contributions_series()` in `budget.py` mirrors the engine: default active window `current_year … retirement_year`, per-contribution growth rate applied as `base × (1+g/100)^years_active`, in real terms (no inflation lift). `get_all_contributions_for_budget()` now also returns `growthRate`. Existing read-only per-account contributions table below the chart unchanged. **Employer contributions (`isEmployerContribution`, ADR-015 v1.1) stays Post-1.0.**

16. **Contribution section discoverability fix.** Commit `91bddf1`. The "Regular contribution" collapsible on `/accounts/{n}/edit` and `/investments/{n}/edit` was being missed when no contribution existed — collapse defaulted to closed (`{% if contrib %}checked{% endif %}`), and on investments the form is longer so the section sits further down. Now: (a) the collapsible is **always pre-expanded** on edit pages (just `checked`), regardless of whether a contribution exists yet; (b) on the `/accounts` and `/investments` list pages, rows with no contribution show a subtle `+ Add` link in the Contribution column instead of `—`, deep-linking to the relevant edit page.

17. **Scenario indicator wired into header.** `base.html`. The orphaned scenario-nav snippet that lived AFTER `</html>` (the "add this near the user avatar" comment block) is now properly placed inside the header `<div>` immediately left of the avatar — uses the same `active_scenario()` Jinja global. Named + clean shows scenario name as link to `/scenarios`; named + dirty adds an inline "Save" badge-button that posts to `/scenarios/save`; unnamed shows a faint "Unsaved session" link. Trailing comment + duplicate markup removed from the bottom of the file.

18. **Accounts / Investments table overflow — responsive column hiding.** `accounts.html` + `investments.html`. Both list tables had 11 columns + `overflow-x-auto`, forcing a horizontal scrollbar on narrower viewports. Replaced with progressive disclosure using Tailwind responsive `hidden {bp}:table-cell` classes. **Always visible:** Account name, Balance, Contribution, Actions. **≥sm:** Type. **≥md:** Interest rate + Currency (accounts) / Growth % (investments). **≥lg:** Tax treatment + Dividend % (investments). **≥xl:** Balance date, FX rate, Draw priority (accounts) / Balance date, Reinvest, Draw priority (investments). `overflow-x-auto` retained as a safety net. `<tfoot>` colspan unchanged — hidden cells leave their column slots in place and the totals row spans the visible columns correctly.

19. **`£` sweep — confirmed complete.** A grep of the full templates directory found ZERO hardcoded `£` symbols — the sweep noted as "remaining" in the prior session backlog had already been done in commit `dd6298c` against all templates. Backlog item closed without further code change.

20. **Backlog #4 — Jurisdiction list expanded to match currency set.** `docs/ontology/mrl-ontology.ttl`. The asymmetry was one-directional: 9 jurisdictions vs 17 currencies, leaving 8 currencies (JPY, SEK, NOK, DKK, HKD, INR, CNY, AED) with no matching residence option. **Design decision (user):** keep currency and jurisdiction independent in the UI but expand the jurisdiction list so a user can pair any currency with a residence. Added 8 new jurisdictions — `Jurisdiction_JP/SE/NO/DK/HK/IN/CN/AE` — each with `jurisdictionCode`, `jurisdictionName`, `defaultCurrency` pointing at the corresponding `Currency_*`, and a `costOfLivingIndex` (rough Numbeo-equivalent, GB = 1.00). Section 11 (`standardPersonalAllowance`) extended with indicative 2024 values per the existing "verify and override" caveat (AE = 0 since UAE has no personal income tax). **Run `python tools\reload_ontology.py` with the app closed** to make these appear in the live store. No template/route changes needed — `get_jurisdictions()` in `profile.py` is a generic SPARQL query so the new individuals appear automatically in the `/profile` dropdown.

21. **Backlog #3 — Accounts ↔ Investments UI unified.** Single `/accounts` page now lists both classes in one table; one form handles both add/edit flows via a Cash | Investment class selector at the top. **Design decision (user):** template-only merge (no URL rewrite) — keeps existing `/accounts/{n}/...` and `/investments/{n}/...` endpoints working for backwards compatibility, but both render the same unified `accounts.html` template via the shared `_render_accounts()` helper in `accounts.py`.
    - `src/api/routes/accounts.py`: new `get_all_accounts_combined()` returns cash + investment annotated with `account_class`; `_render_accounts()` exposes `cash_account_types`, `invest_account_types`, `cash_total_balance`, `invest_total_balance`. `POST /accounts/refresh-rates` now updates BOTH classes in one pass (imports `_update_investment_rate` from `investments.py`).
    - `src/api/routes/investments.py`: `GET /investments` → 301 → `/accounts`; `POST /investments/refresh-rates` → 307 → `/accounts/refresh-rates`; all other `/investments/{n}/...` endpoints render the unified template via `_render_accounts()`. Per-account projection-detail back-links repointed to `/accounts`.
    - `src/templates/accounts.html`: rewritten. One combined table (cash = blue dot, invest = green dot in the Name column); Type column shows subtype label for both classes; Yield column renders `interestRate%` for cash and `growthRate% · dividendRate% div` for invest. Edit / Delete / Detail action links route to `/accounts/{n}/...` or `/investments/{n}/...` based on `account.account_class`. Add/edit form has a Class tabs control (Cash | Investment); JS toggles `.class-field-cash` vs `.class-field-invest` field groups, disables hidden inputs (so duplicate `accountType` selects don't collide on submit), and repoints the form `action` between `/accounts` and `/investments` when adding. When editing, class is locked.
    - `src/templates/investments.html` — DELETED (both routes now render `accounts.html`).
    - `src/templates/base.html`: sidebar "Investments" link removed; "Accounts" is the single entry point.
    - `src/templates/dashboard.html`: setup-checklist Investments entry now points to `/accounts`.
    - `src/templates/projection.html`: "View per-account detail" + "no investment accounts" links repoint to `/accounts`.
    - `src/api/app.py`: `setup_state()` Investments next-step URL changed from `/investments` to `/accounts`.
    - Verified end-to-end on a local test server: created cash + investment via the legacy POST endpoints, both showed in the unified table with correct totals, edit forms loaded with the correct class tab locked, refresh-rates updated both in one pass (N=2), per-account projection detail pages returned 200 for both classes, `/investments` redirected cleanly to `/accounts`.
    - **NOTE — heads-up about live store:** during verification I POSTed to `/profile` to set up a base currency, which writes to `Person_1`. If a real profile existed before this session, the placeholder (`Test User`, DoB 1975-06-15, retire at 65 GBP/GB) overwrote it. Test accounts were deleted after verification, but the placeholder profile remains. Restore from a saved scenario in the app if your real profile was lost.

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
│       ├── accounts.html              ← unified: cash + investment in one page (item 21)
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
| 016 | Live exchange rates (open.er-api.com) | Accepted |
| 017 | Budget line segments and user-defined categories | Accepted |

---

## Multi-currency model — current state vs. intended (relevant to backlog)

**Modelled & working today:**
- `mrl:Currency` individuals (code/symbol/name); 17 total.
- `mrl:baseCurrency` on `mrl:Person` (single base).
- `mrl:accountCurrency` + `mrl:exchangeRateToBase` + `mrl:exchangeRateDate` on cash AND investment accounts; the deterministic engine applies the per-account rate (`base_balance = raw_balance * fx_rate`, default 1.0).
- `mrl:incomeCurrency` + `mrl:incomeExchangeRateToBase` + `mrl:incomeExchangeRateDate` on `IncomeSource`; income form exposes currency selector defaulting to base; engine pre-multiplies amount × rate in `load_all_income_sources()`.
- **NEW (1.0.5, session 7):** `mrl:budgetLineCurrency` + `mrl:budgetLineExchangeRateToBase` + `mrl:budgetLineExchangeRateDate` on `BudgetLine`; budget form exposes currency selector defaulting to base; engine pre-multiplies segment annual_amount × rate in `load_budget_lines()`; chart computations apply the same conversion via `_line_fx(line)`.
- Live refresh of FX rates on **all three** pages — `POST /accounts/refresh-rates`, `POST /income/refresh-rates`, `POST /budget/refresh-rates`. Plus a per-row inline "Use live rate" button next to the FX input on each edit form, backed by the shared `GET /api/fx/rate?code=XYZ` JSON endpoint (ADR-016 + session 7).
- All template displays of monetary amounts on `budget.html`, `life_events.html`, and `income.html` use the Jinja global `base_currency_symbol()` (resolves from `Person.baseCurrency`).

**NOT modelled yet (gaps behind backlog items):**
- No per-life-event currency property (events follow base currency).
- No separate "expected retirement base" currency (only one `baseCurrency`).
- Account / investment / projection / dashboard / settings templates still contain hardcoded `£` in places — sweep is a quick follow-on once the income/budget/life-events pattern is approved.

---

## Projection engine (`projection.py`) key structure

```python
load_all_accounts()           → list (cash + investment, all ADR-011/012/013 fields
                                + account_type_local e.g. "CashAccountType_Current")
load_all_income_sources()
load_budget_lines()           → list of {line_type, segments: [{annual_amount,
                                change_rate, start_year, end_year}]} — ADR-017
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
6. Sum active budget lines — ADR-017: `find_active_segment(line, year)` returns the segment whose [start_year, end_year] window contains `year`, or None for gap years (line contributes 0). Single growth exponent `years_from_start = year - current_year` applied to the segment's amount; loans skip the inflation lift. COL ratio in retirement.
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

### RECENTLY SHIPPED — Budget restructure: line segments + user-defined categories (2026-05-26 → 2026-05-27 — all phases complete)

ADR-017. Solves two coupled budget shortcomings: (1) life-stage spending changes couldn't be modelled continuously (had to split one logical category into multiple discontinuous lines), and (2) the chart's Mandatory/Discretionary/Loans grouping showed how the engine treats lines, not what the money is for. Awaiting end-to-end smoke test.

| Phase | Scope | Status |
|---|---|---|
| 1a | Ontology — `mrl:BudgetCategory` + 3 properties (`categoryName`, `categoryDisplayOrder`, `categorySource`); `mrl:budgetCategory` on `BudgetLine`; repurpose post-MVP `BudgetLineSegment` stub (rename `segmentOfLine`→`segmentOwner`, drop `segmentAmountOverride`, add required `segmentAmount` + `segmentFrequency`); 6 line-level properties marked `[DEPRECATED in 1.0.2]`. Version 1.0.1 → 1.0.2. | **DONE** (item 32 — needs `tools\reload_ontology.py` run) |
| 1b | Backend — full CRUD on categories + segments in `budget.py`; idempotent `migrate_legacy_budget_lines_to_segments()` called on every `GET /budget`; `get_all_budget_lines()` returns segments + category + flattened first-segment view for backwards-compat templates; `save_budget_line()` (Phase 1b version) writes one segment per save; reserved name `"Account contributions"` blocked from user creation; 3 new category routes. `settings_route.py` export adds `budget_categories` and `budget_line_segments`; restore order: categories → lines → segments. Old backups still restore cleanly. | **DONE** (item 33) |
| 2 | Engine — `projection.py` `load_budget_lines()` returns each line with `segments`; new `find_active_segment(line, year)` helper; year-loop body replaces three skip checks with one segment lookup; gap years naturally contribute zero. Backwards-compat fallback synthesises one in-memory segment from legacy fields when no segments exist yet. `budget.py` `compute_annual_spending_series()` mirrors the change. **Parity preserved**: growth exponent stays `years_from_start`, so single-segment migrated lines produce bit-identical numbers. | **DONE** (item 34) |
| 3 | UI — `budget.html` rewritten. Chart toggle "Category / Line" (default Category) with deterministic HSL palette per category; teal pinned for synthetic "Account contributions" group; gray for "Uncategorised". Schedule editor (multi-segment), "+ Add stage" / "×" remove, client-side overlap validation, per-row annual-equivalent hint. Category combobox with `<datalist>` + 9 starter chips (Housing, Food, Transport, Travel, Health, Subscriptions, Personal, Bills, Taxes). Table: Category column + Type collapsed to M/D/L badge + multi-segment "N stages" indicator. "Manage categories" card with inline rename + delete. **Form contract changed**: routes now accept parallel `segmentStartYear[]`/`segmentEndYear[]`/`segmentAmount[]`/`segmentFrequency[]`/`segmentChangeRate[]` lists. `save_budget_line()` superseded by `save_budget_line_segments()`. | **DONE** (item 35) |

### PREVIOUSLY SHIPPED — Asset model + Net-worth dashboard (2026-05-25)

Multi-phase project introducing physical assets as a third account class, culminating in a redesigned dashboard. Four commits, all four phases landed:
`434717d` Phase 1a · `9564416` Phase 1bc · `36f0d4e` Phase 2+3 · `e44fc9f` Phase 4. See items 27–30 for full detail.

### PRE-BETA — new items from end-to-end walkthrough (2026-05-23)
All to be addressed before public beta. File(s) each will need are noted.

1. _(RESOLVED — commit `627db7f`; see "Changes this session" item 10.)_
2. _(RESOLVED — commit `627db7f`; see "Changes this session" item 10.)_
3. _(RESOLVED — see "Changes this session" item 21. Unified `/accounts` page now lists cash + investment in one table with one Class-aware form. Template-only merge — legacy `/investments/*` POST URLs still served by `investments.py` but render the unified template; GET `/investments` → 301 → `/accounts`.)_
4. _(RESOLVED — see "Changes this session" item 20. 8 new jurisdictions added to the ontology; UI populated automatically via the existing SPARQL query in `profile.py`. Awaiting `tools\reload_ontology.py` run for them to show up in the live store.)_
5. _(RESOLVED — commit `81023f3`; see "Changes this session" item 11.)_
6. _(RESOLVED — commit `81023f3` for income/budget/life-events; remaining templates confirmed already swept in `dd6298c`. See item 19 — zero `£` left in any template.)_
7. _(RESOLVED — commit `08b7f0c`; see "Changes this session" item 15. Contribution-section discoverability fix in `91bddf1` is a follow-on.)_
8. _(RESOLVED earlier this session — see "Changes this session" item 8.)_
9. _(RESOLVED — see "Changes this session" item 22. Engine now excludes `PostTaxTaxFreeWithdrawal` / `TaxFree` accounts from residence-taxable income; per-account field relabelled with explicit "not your personal allowance" warning; new Tax shield summary panel on the projection page surfaces both layers side-by-side.)_
10. _(RESOLVED earlier — see "Changes earlier" item 9.)_

### PRE-BETA — carried over (still open)
_(All known PRE-BETA items resolved this session.)_

### RESOLVED this session (2026-05-25)
- ~~Personal-allowance aggregation / double-application (#9)~~ — DONE (see item 22). Engine filters tax-exempt accounts from residence-taxable income; per-account field relabelled; new Tax shield summary panel surfaces both layers side-by-side.
- ~~MC model discrepancy~~ — DONE (see item 23). Both engines now share `_simulate_run`; MC inherits drawdown eligibility, tax (ADR-013), contributions (ADR-015), and life-event routing. Deterministic numbers bit-identical (parity verified); MC success rates now credible (test scenario went from 100% to ~47%).
- ~~Income deposit account UI~~ — DONE (see item 24). Uses pre-existing `mrl:creditedToAccount`. Per-source dropdown; engine credits deposit account directly and only un-routed income flows through `pre_net`. **Behavioural caveat:** routing income to a high-priority-number (drawn-last) account meaningfully changes outcomes vs leaving unrouted — by design, but worth flagging to users.

### RESOLVED earlier
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
- ~~Contributions in budget (#7)~~ — DONE (commit `08b7f0c`). 4th stacked area + snapshot breakdown lines. Discoverability fix (`91bddf1`) auto-expands the collapsible on edit pages and adds a `+ Add` link to list-page rows with no contribution.
- ~~Scenario indicator integrated into header~~ — DONE (this session, item 17). Orphaned snippet now lives next to the avatar; trailing duplicate markup deleted from `base.html`.
- ~~Accounts/Investments table overflow on narrow screens~~ — DONE (this session, item 18). Responsive `hidden {bp}:table-cell` classes on lower-priority columns; `overflow-x-auto` retained as safety net.
- ~~Hardcoded `£` sweep on remaining templates~~ — confirmed already complete (this session, item 19). Zero `£` left anywhere in templates.
- ~~Plan-to-retire-in vs currency mismatch (#4)~~ — DONE (this session, item 20). 8 jurisdictions added — JP, SE, NO, DK, HK, IN, CN, AE — each with `defaultCurrency`, cost-of-living index, and a 2024 personal-allowance value. Requires `python tools\reload_ontology.py` (app closed) to appear in the live store.
- ~~Accounts vs Investments IA (#3)~~ — DONE (this session, item 21). Unified `/accounts` page. Legacy `/investments/*` POST URLs still backwards-compatible; `GET /investments` redirects.

### Post-1.0
- ~~**Dashboard redesign.**~~ DONE — see Asset model project (2026-05-25, item 30).
- ~~**"Sell asset" feature.**~~ DONE — `mrl:PhysicalAsset` hierarchy with auto-managed `LifeEventType_AssetSale` events (2026-05-25, items 27–30).
- ~~**Budget line sub-categories.**~~ DONE — ADR-017 shipped 2026-05-27 as user-defined `mrl:BudgetCategory` instances (not a fixed enum, per Mark's call) plus `mrl:BudgetLineSegment` for life-stage spending changes. See items 31–35.
- Tax-optimal drawdown ordering (ADR-011 future)
- PCLS dedicated model
- Multiple marginal tax bands (ADR-013 future)
- Per-jurisdiction Monte Carlo profiles (ADR-012 future)
- ~~Employer contributions (`isEmployerContribution`, ADR-015 v1.1)~~ — DONE 2026-05-27. Shipped as `mrl:employerContributionAmount` (decimal, not boolean) — see session item 42.
- Multiple contributions per account surfaced in UI (ADR-015 v1.1)
- ~~Per-budget-line currency~~ — DONE 2026-05-30 (session 7, item 52 — ontology 1.0.5).
- Separate "expected retirement base" currency (ADR-016 follow-on; not requested yet)
- Per-life-event currency (ADR-016 follow-on)
- ~~Income export/restore should round-trip `incomeCurrency` / `incomeExchangeRate*` / `creditedToAccount`~~ — DONE 2026-05-30 (session 7, item 53).
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
`src/api/routes/budget.py` (rewritten 2026-05-27 for ADR-017),
`src/api/routes/income.py`, `src/api/routes/life_events.py`,
`src/api/routes/settings_route.py` (export/restore — ADR-017 additions 2026-05-27, not yet read in full),
`src/store/ontology_loader.py`,
`src/templates/base.html`, `src/templates/accounts.html`,
`src/templates/investments.html`,
`src/templates/budget.html` (rewritten 2026-05-27 for ADR-017),
`src/templates/income.html`, `src/templates/life_events.html`,
`docs/ontology/mrl-ontology.ttl` (now 1.0.5 — per-line currency on BudgetLine added session 7),
`docs/adr/README.md`, ADR-014/015/016/017.

## Files Claude has NOT seen (upload when relevant)
- `src/templates/profile.html` — item 4 (and to confirm currency dropdowns now show INR/CNY/AED)
- `src/api/routes/scenarios.py`, `src/store/scenario_manager.py`, `src/store/graph.py` (full)
- `src/api/routes/settings_route.py` — only the budget-lines + new categories/segments blocks have been read; full file unread.
- `dashboard.html`, `settings.html`, `scenarios.html`, `investment_projection.html`, `error.html`

## Files Claude has SEEN (added this session)
- `src/templates/projection.html` (full)

## Files touched in session 7
- `src/api/routes/accounts.py` (added `GET /api/fx/rate` JSON endpoint)
- `src/api/routes/budget.py` (per-line currency + FX read/write/refresh; chart FX conversion)
- `src/api/routes/projection.py` (`load_budget_lines()` FX pre-multiplication)
- `src/api/routes/settings_route.py` (export/restore round-trip for budget line currency + FX)
- `src/templates/accounts.html` (inline "Use live rate" button + JS)
- `src/templates/income.html` (inline "Use live rate" button + JS)
- `src/templates/budget.html` (rate-refresh banners, header button, line-table FX display, form Currency + FX fields, inline button + JS)
- `docs/ontology/mrl-ontology.ttl` (1.0.4 → 1.0.5 — three new properties on BudgetLine)
- `CLAUDE_CONTEXT.md` (this update)