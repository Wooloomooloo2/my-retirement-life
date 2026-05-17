# My Retirement Life — Claude Context Document

This document is read at the start of each new Claude conversation to provide
full project context without needing the entire chat history.

**Last updated:** 2026-05-17
**Current version:** v1.0.0 ontology complete; v0.3 coding not yet started

---

## What this project is

A local, privacy-first retirement planning application. Users input their
financial picture (income, savings, spending, life events) and see a year-by-year
projection of their retirement trajectory with a confidence score.

Runs entirely on the user's machine. No cloud, no accounts, no external data.
Target platforms: Windows, macOS, Linux.

GitHub: https://github.com/Wooloomooloo2/my-retirement-life

---

## Tech stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.13 + FastAPI |
| Data store | Oxigraph (embedded via pyoxigraph) — RDF triple store |
| Templating | Jinja2 (server-rendered HTML) |
| Frontend | HTMX + Tailwind CSS + DaisyUI + Chart.js |
| Packaging (planned) | PyInstaller (Windows .exe), AppImage (Linux), PyInstaller (macOS .app) |

---

## Project structure

```
my-retirement-life/
├── main.py                          # Entry point — loads ontology, starts uvicorn
├── requirements.txt                 # Includes numpy (added v0.2)
├── .env.example
├── docs/
│   ├── adr/                         # Architecture Decision Records (ADR-001 to ADR-013)
│   ├── ontology/
│   │   ├── mrl-ontology.ttl         # THE ONTOLOGY — source of truth, v1.0.0
│   │   └── README.md                # Full ontology documentation (rewritten 2026-05-17)
│   └── requirements/
│       ├── mvp.md
│       └── user-stories.md
└── src/
    ├── config.py                    # Settings, paths (uses platformdirs)
    ├── api/
    │   ├── app.py                   # FastAPI app, routers, exception handlers,
    │   │                            # Jinja2 globals (user_initials, setup_state)
    │   ├── templates.py             # Shared Jinja2Templates instance
    │   └── routes/
    │       ├── profile.py           # GET/POST /profile
    │       ├── income.py            # GET/POST /income (CRUD)
    │       ├── accounts.py          # GET/POST /accounts (CRUD)
    │       ├── investments.py       # GET/POST /investments (CRUD) — v0.2
    │       ├── budget.py            # GET/POST /budget (CRUD)
    │       ├── life_events.py       # GET/POST /life-events (CRUD)
    │       ├── projection.py        # GET /projection (engine + chart + Monte Carlo)
    │       └── settings_route.py    # GET/POST /settings (export/import/inflation)
    ├── store/
    │   ├── graph.py                 # RetirementStore wrapper, next_iri(), MRL, DATA_GRAPH
    │   ├── ontology_loader.py       # Loads TTL into Oxigraph on startup
    │   └── mrl-ontology.ttl         # COPY — do not edit here, edit docs/ontology/
    └── templates/
        ├── base.html                # Layout, sidebar, setup banner (calls setup_state())
        ├── dashboard.html           # First-run wizard + live dashboard
        ├── profile.html             # Personal details (incl. retirement jurisdiction)
        ├── income.html              # Multiple income sources with start/end years
        ├── accounts.html            # Cash accounts with FX rates
        ├── investments.html         # Investment accounts — v0.2
        ├── budget.html              # Budget lines with frequency and start/end years
        ├── life_events.html
        ├── projection.html          # Stacked chart + confidence score + Monte Carlo
        ├── settings.html            # Export/import/inflation rate
        └── error.html               # Friendly 404/500 page
```

---

## Critical conventions — always follow these

### 1. Data access pattern (ADR-007)
- **Reads of known instances** → `quads_for_pattern` (NOT SPARQL SELECT)
- **Queries/filtering/aggregation** → SPARQL SELECT
- **All writes** → SPARQL UPDATE

```python
# Reading a known instance — always use quad patterns
def get_val(prop: str) -> str:
    qs = list(store.store.quads_for_pattern(
        subject_iri, og.NamedNode(f"{MRL}{prop}"), None, DATA_GRAPH))
    return str(qs[0].object.value) if qs else ""
```

### 2. IRI patterns (ADR-006)
- Classes: `mrl:CashAccount`
- Properties: `mrl:accountBalance` (camelCase)
- Reference individuals: `mrl:Currency_GBP`, `mrl:Jurisdiction_GB`
- Controlled vocab: `mrlx:BudgetLineType_Mandatory`, `mrlx:FrequencyType_Monthly`
- User instance data: `mrl:ClassName_N` (e.g. `mrl:Person_1`, `mrl:CashAccount_3`)

### 3. Named graphs
- `https://myretirementlife.app/ontology/graph` — ontology (read-only at runtime)
- `https://myretirementlife.app/data/graph` — user data (read/write)

In code: `DATA_GRAPH = og.NamedNode("https://myretirementlife.app/data/graph")`
In code: `ONTOLOGY_GRAPH = og.NamedNode("https://myretirementlife.app/ontology/graph")`

### 4. Shared templates
ALL routes import from `src.api.templates`:
```python
from src.api.templates import templates
# NEVER: templates = Jinja2Templates(directory=...)  in route files
```

### 5. Jinja2 globals (set in app.py after helpers defined)
- `user_initials()` — reads Person_1 first/last name, returns initials
- `setup_state()` — returns dict with setup completion flags for the banner in base.html

### 6. Ontology file locations
- **Authoritative copy:** `docs/ontology/mrl-ontology.ttl` (edit this one)
- **Runtime copy:** `src/store/mrl-ontology.ttl` (keep in sync — copy from docs/ontology)
- After editing TTL: delete the store folder so it reloads fresh on next startup
- Store location on Windows: `C:\Users\<user>\AppData\Local\MyRetirementLife\`
- Store location on macOS: `/Users/<user>/Library/Application Support/MyRetirementLife/`

### 7. Cross-platform paths
Always use `pathlib.Path` — never string concatenation or hardcoded separators.

---

## Ontology summary (v1.0.0)

**Namespaces:**
- `mrl:` = `https://myretirementlife.app/ontology#`
- `mrlx:` = `https://myretirementlife.app/ontology/ext#`

**Key classes:**
- `mrl:Person` — single user (Person_1)
- `mrl:IncomeSource` — multiple, with start/end years
- `mrl:Account` → `mrl:CashAccount`, `mrl:InvestmentAccount`, `mrl:CreditCardAccount`, `mrl:PropertyAsset`, `mrl:PensionAccount` (post-MVP), `mrl:OtherAsset` (post-MVP)
- `mrl:BudgetLine` — with frequency, growth rate, and optional start/end years
- `mrl:BudgetLineSegment` — post-MVP time-segmented growth rates (declared, not implemented)
- `mrl:LifeEvent`
- `mrl:ProjectionSettings` — inflation, Monte Carlo profile, drawdown settings, tax settings
- `mrl:Currency`, `mrl:Jurisdiction` — reference individuals

**Properties on `mrl:Account` (all subtypes) — v1.0.0 additions:**
- `mrl:drawdownMinAge`, `mrl:drawdownMaxAge` — decimal; eligibility age window
- `mrl:drawdownEarliestDate`, `mrl:drawdownLatestDate` — xsd:date; fixed-term windows
- `mrl:drawdownRatio` — decimal; proportion for Proportional strategy
- `mrl:effectiveWithdrawalTaxRate` — decimal; user-specified rate after treaty relief
- `mrl:annualTaxFreeWithdrawal` — decimal; annual tax-free withdrawal allowance
- `mrl:taxTreatment` — → `mrlx:TaxTreatmentType`; structural type for UI guidance
- `mrl:accountJurisdiction` — → `mrl:Jurisdiction`; already existed pre-v1.0.0

**Properties on `mrl:ProjectionSettings` — v1.0.0 additions:**
- `mrl:drawdownStrategy` — → `mrlx:DrawdownStrategyType` (Waterfall or Proportional)
- `mrl:surplusStrategy` — → `mrlx:SurplusStrategyType` (SweepToAccount or ReduceDrawdown)
- `mrl:spendingAccount` — → `mrl:Account`; drawdown destination account
- `mrl:surplusAccount` — → `mrl:Account`; surplus sweep destination
- `mrl:annualPersonalAllowance` — decimal; residence-country income threshold
- `mrl:residenceIncomeTaxRate` — decimal; marginal rate above allowance

**Properties on `mrl:LifeEvent` — v1.0.0 additions:**
- `mrl:fundedByAccount` — → `mrl:Account`; account that funds an expenditure event
- `mrl:receivedByAccount` — → `mrl:Account`; account that receives a windfall

**Properties on `mrl:Jurisdiction` — v1.0.0 additions:**
- `mrl:standardPersonalAllowance` — decimal; reference allowance in jurisdiction currency

**Key mrlx: SKOS schemes:**
- `mrlx:IncomeSourceTypeScheme` — Employment, Property, Retirement (subtypes), Investment (subtypes), etc.
- `mrlx:AccountTypeScheme` — CashAccountType subtypes + InvestmentAccountType subtypes + CreditCardAccountType subtypes
- `mrlx:FrequencyTypeScheme` — Weekly×52, Fortnightly×26, TwiceMonthly×24, Monthly×12, Quarterly×4, Annually×1
- `mrlx:BudgetLineType` — Mandatory, Discretionary, Loan
- `mrlx:LifeEventType` — LargeExpenditure, Windfall, etc.
- `mrlx:EmploymentStatus` — Employed, SelfEmployed, NotWorking, Retired
- `mrlx:MonteCarloProfileScheme` — Conservative (σ=3%/0.8%), Moderate (σ=6%/1.5%), Aggressive (σ=10%/2.5%)
- `mrlx:CreditCardAccountType` — Standard, ChargeCard
- `mrlx:TaxTreatmentScheme` — PreTaxWholeWithdrawal, PostTaxGainsOnly, PostTaxTaxFreeWithdrawal, TaxFree — v1.0.0
- `mrlx:DrawdownStrategyScheme` — Waterfall, Proportional — v1.0.0
- `mrlx:SurplusStrategyScheme` — SweepToAccount, ReduceDrawdown — v1.0.0

---

## Projection engine summary

File: `src/api/routes/projection.py`

**Current state (v0.2 — not yet refactored for v0.3):**

Key functions:
- `load_profile()`
- `load_all_income_sources()` — returns list with start/end years
- `load_accounts()` — returns list with FX-adjusted balances (cash only)
- `load_investment_accounts()` — returns list with growth/dividend/reinvest (v0.2)
- `load_budget_lines()` — returns list with annual amounts, start/end years
- `load_life_events()`
- `load_col_ratio()` — returns retirement_col / current_col from Jurisdiction COL indices
- `get_projection_settings()` — returns inflation_rate and mc_profile
- `run_projection(inflation_rate)` — deterministic year-by-year projection
- `run_monte_carlo(inflation_rate, mc_profile_local, n_sims=500)` — Monte Carlo simulation

**v0.2 engine logic per year (deterministic):**
1. Sum active income sources (checking start/end year windows)
2. Add non-reinvested investment dividends as income
3. Apply weighted average return (cash interest + investment growth) to total balance
4. Grow each budget line by its rate (or inflation_rate if 0), respecting start/end years
5. Remove loan lines after their end year
6. Apply COL ratio to spending from retirement year (if retiring abroad)
7. Apply life event amounts (costs and receipts separately)
8. Accumulate balance

**v0.2 Monte Carlo:** 500 simulations on entire blended balance (cash + investments).
Returns P10/P50/P90 balance arrays and success rate.

**v0.3 target engine architecture (ADR-012 — not yet implemented):**
- Deterministic engine tracks each account's balance independently per year
- Monte Carlo runs on investment account pool only; cash accounts are deterministic
- Total = deterministic cash balance + investment P10/P50/P90
- Engine return type changes to a structured dict:
  ```python
  {
    "accounts": {"mrl:CashAccount_1": [y0, y1, ...], ...},
    "total": [y0_total, y1_total, ...],
    "tax_paid": [y0_tax, y1_tax, ...]
  }
  ```
- Tax applied per ADR-013 logic at point of withdrawal per account
- Drawdown eligibility filtered per year per ADR-011 rules

**Confidence scoring (unchanged for v0.3):**
- Green: never runs out
- Amber: runs out within 5 years of life expectancy
- Red: runs out before life expectancy

---

## Setup wizard (5 steps)

The persistent banner in `base.html` guides first-time users through:
1. Profile
2. Income
3. Accounts (cash)
4. Investments
5. Budget

`get_setup_state()` in `app.py` drives this. It imports `get_all_investment_accounts`
from `investments.py` (not from `projection.py`) for the investments check.

---

## What was completed in v0.2

1. ✅ Budget start/stop dates — `mrl:budgetStartYear`, `mrl:budgetEndYear` on BudgetLine
2. ✅ Retirement jurisdiction — `mrl:plansToRetireIn`, `mrl:costOfLivingIndex`, COL adjustment in projection
3. ✅ Investment accounts — full CRUD at `/investments`, `mrl:InvestmentAccount` properties, projection engine integration
4. ✅ Monte Carlo simulation — 500 runs, P10/P50/P90 band chart, named profiles in ontology, profile selector on projection page
5. ✅ Life event receipts visible as teal bars on projection chart
6. ✅ Setup wizard updated to 5 steps (investments added)
7. ✅ Sidebar investments active state fixed
8. ✅ ADR-009 updated to Implemented with implementation notes
9. ✅ Ontology README updated to v0.9.0

## What was completed post-v0.2 (2026-05-17 session)

1. ✅ ADR README.md recreated — full index and summaries for ADR-001 to ADR-010
2. ✅ Ontology updated to v0.9.1 (ADR-010) — `mrl:CreditCardAccount`, `mrl:PropertyAsset` promoted, `mrl:isLiability`, `mrlx:CreditCardAccountType` SKOS concepts
3. ✅ Backup/restore bug fixed — `settings_route.py` exports/restores investment accounts, retirement jurisdiction, budget start/end dates, Monte Carlo profile; `APP_VERSION` updated to `"0.2.0"`
4. ✅ ADR-010 accepted — sister app (My Finance Life) ontology sharing strategy documented
5. ✅ ADR-011 written — per-account drawdown eligibility, ordering, spending account, surplus handling
6. ✅ ADR-012 written — per-account balance tracking, Monte Carlo restricted to investment accounts
7. ✅ ADR-013 written — two-layer tax treatment model (account-level + residence-level)
8. ✅ Ontology updated to v1.0.0 — all v0.3 properties and SKOS schemes added (ADR-011/012/013)
9. ✅ Ontology README rewritten from scratch covering v1.0.0 in full
10. ✅ ADR README updated with ADR-011, ADR-012, ADR-013 entries

---

## What's next — v0.3 coding phases

### Phase B — UI additions (start here; no engine changes)
Add new fields to existing pages in collapsible "Tax & Drawdown" sections:

**accounts.html / investments.html:**
- Drawdown eligibility: min age, max age, earliest date, latest date
- Drawdown priority (already exists in ontology; expose in UI)
- Drawdown ratio (for Proportional strategy)
- Tax treatment selector (mrlx:TaxTreatmentScheme)
- Effective withdrawal tax rate
- Annual tax-free withdrawal allowance
- Spending account / surplus account designation flags

**settings.html:**
- Drawdown strategy selector (Waterfall / Proportional)
- Surplus strategy selector (SweepToAccount / ReduceDrawdown)
- Spending account picker (from user's account list)
- Surplus account picker (from user's account list)
- Annual personal allowance
- Residence income tax rate

**life_events.html:**
- Funded by account picker (for expenditure events)
- Received by account picker (for windfall events)

**settings_route.py:**
- Export/restore all new account-level and projection-settings properties

### Phase C — Per-account projection engine + chart (biggest lift)
- Refactor `run_projection()` to track per-account balances
- Restrict `run_monte_carlo()` to investment accounts only; add cash deterministically
- Update projection chart: Aggregate view (current) + By Account stacked view (new)
- Add secondary drawdown-vs-growth chart per investment account
- Update `projection.html` for new result structure and chart mode toggle

### Phase D — Tax model in engine
- Wire `effectiveWithdrawalTaxRate` and `annualTaxFreeWithdrawal` into drawdown calculations
- Apply residence-level `annualPersonalAllowance` / `residenceIncomeTaxRate` at year level
- Surface `tax_paid[year]` in projection chart data table

### Phase E — Life event account association
- Use `fundedByAccount` / `receivedByAccount` in projection engine
- Draw expenditure events from named account; deposit windfalls into named account

---

## ADR summary

| # | Decision | Status |
|---|---------|--------|
| 001 | Python + FastAPI + Oxigraph backend | Implemented |
| 002 | PyInstaller (Windows/macOS) + AppImage (Linux) packaging | Accepted |
| 003 | HTMX + Tailwind + DaisyUI frontend | Implemented |
| 004 | Cross-platform portability practices | Implemented |
| 005 | Ontology loaded from TTL into named graph on startup | Implemented |
| 006 | Instance IRIs follow mrl:ClassName_N pattern | Implemented |
| 007 | Quad patterns for reads, SPARQL UPDATE for writes | Implemented |
| 008 | Multiple income sources with start/end dates in MVP | Implemented |
| 009 | Investment accounts as pots; Monte Carlo with named profiles | Implemented |
| 010 | Sister app (MFL) loads and extends MRL ontology as shared foundation | Accepted |
| 011 | Per-account drawdown eligibility, ordering, spending account, surplus handling | Accepted |
| 012 | Per-account balance tracking; Monte Carlo restricted to investment accounts | Accepted |
| 013 | Two-layer tax treatment model (account-level source tax + residence personal allowance) | Accepted |