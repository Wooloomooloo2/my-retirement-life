# My Retirement Life — Claude Context Document

This document is read at the start of each new Claude conversation to provide
full project context without needing the entire chat history.

**Last updated:** 2026-05-17
**Current version:** v0.2 complete

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
│   ├── adr/                         # Architecture Decision Records (ADR-001 to ADR-009)
│   ├── ontology/
│   │   ├── mrl-ontology.ttl         # THE ONTOLOGY — source of truth, v0.9.0
│   │   └── README.md
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

## Ontology summary (v0.9.0)

**Namespaces:**
- `mrl:` = `https://myretirementlife.app/ontology#`
- `mrlx:` = `https://myretirementlife.app/ontology/ext#`

**Key classes:**
- `mrl:Person` — single user (Person_1)
- `mrl:IncomeSource` — multiple, with start/end years
- `mrl:Account` → `mrl:CashAccount` (MVP), `mrl:InvestmentAccount` (v0.2)
- `mrl:BudgetLine` — with frequency, growth rate, and optional start/end years
- `mrl:LifeEvent`
- `mrl:ProjectionSettings` — inflation rate + Monte Carlo profile
- `mrl:Currency`, `mrl:Jurisdiction` — reference individuals

**Key properties added in v0.2:**
- `mrl:budgetStartYear`, `mrl:budgetEndYear` — on `mrl:BudgetLine`
- `mrl:plansToRetireIn` — on `mrl:Person` (points to `mrl:Jurisdiction`)
- `mrl:costOfLivingIndex` — on `mrl:Jurisdiction` (GB = 1.00 base)
- `mrl:annualGrowthRate`, `mrl:annualDividendRate`, `mrl:reinvestDividends` — on `mrl:InvestmentAccount`
- `mrl:monteCarloProfile` — on `mrl:ProjectionSettings`

**Key mrlx: SKOS schemes:**
- `mrlx:IncomeSourceTypeScheme` — Employment, Property, Retirement (subtypes), Investment (subtypes), etc.
- `mrlx:AccountTypeScheme` — CashAccountType subtypes + InvestmentAccountType subtypes (v0.2)
- `mrlx:FrequencyTypeScheme` — Weekly×52, Fortnightly×26, TwiceMonthly×24, Monthly×12, Quarterly×4, Annually×1
- `mrlx:BudgetLineType` — Mandatory, Discretionary, Loan
- `mrlx:LifeEventType` — LargeExpenditure, Windfall, etc.
- `mrlx:EmploymentStatus` — Employed, SelfEmployed, NotWorking, Retired
- `mrlx:MonteCarloProfileScheme` — Conservative (σ=3%/0.8%), Moderate (σ=6%/1.5%), Aggressive (σ=10%/2.5%) — v0.2

---

## Projection engine summary

File: `src/api/routes/projection.py`

**Key functions:**
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

**Engine logic per year (deterministic):**
1. Sum active income sources (checking start/end year windows)
2. Add non-reinvested investment dividends as income
3. Apply weighted average return (cash interest + investment growth) to total balance
4. Grow each budget line by its rate (or inflation_rate if 0), respecting start/end years
5. Remove loan lines after their end year
6. Apply COL ratio to spending from retirement year (if retiring abroad)
7. Apply life event amounts (costs and receipts separately)
8. Accumulate balance

**Monte Carlo:** 500 simulations, numpy for random draws and percentiles. Pre-computes per-year deterministic values (income, active budget lines, life events) before the simulation loop for performance. Returns P10/P50/P90 balance arrays and success rate (% of sims where balance never goes negative).

**Confidence scoring (deterministic):**
- Green: never runs out
- Amber: runs out within 5 years of life expectancy
- Red: runs out before life expectancy

**Investment account projection approach (ADR-009):**
- Investment accounts merged into total balance pool (not tracked separately)
- Effective rate = growth_rate + dividend_rate (if reinvested)
- Non-reinvested dividends modelled as annual income stream growing at growth_rate
- Weighted return rate computed across cash + investment accounts

---

## Setup wizard (5 steps)

The persistent banner in `base.html` guides first-time users through:
1. Profile
2. Income
3. Accounts (cash)
4. Investments
5. Budget

`get_setup_state()` in `app.py` drives this. It imports `get_all_investment_accounts` from `investments.py` (not from `projection.py`) for the investments check.

---

## What was just completed (v0.2)

1. ✅ Budget start/stop dates — `mrl:budgetStartYear`, `mrl:budgetEndYear` on BudgetLine
2. ✅ Retirement jurisdiction — `mrl:plansToRetireIn`, `mrl:costOfLivingIndex`, COL adjustment in projection
3. ✅ Investment accounts — full CRUD at `/investments`, `mrl:InvestmentAccount` properties, projection engine integration
4. ✅ Monte Carlo simulation — 500 runs, P10/P50/P90 band chart, named profiles in ontology, profile selector on projection page
5. ✅ Life event receipts visible as teal bars on projection chart
6. ✅ Setup wizard updated to 5 steps (investments added)
7. ✅ Sidebar investments active state fixed
8. ✅ ADR-009 updated to Implemented with implementation notes
9. ✅ Ontology README updated to v0.9.0

---

## What's next (v0.3 — not yet planned)

No ADR exists for v0.3 yet. Likely candidates based on ADR consequences and future considerations:

- **Drawdown ordering** — `mrl:drawdownPriority` already exists on `mrl:Account`; implement user-defined ordering in projection engine
- **PensionAccount** — declared in ontology as post-MVP; similar pattern to InvestmentAccount
- **BudgetLineSegment** — time-segmented growth rates, already declared in ontology
- **Sequence-of-returns risk** — extend Monte Carlo to model order of good/bad years
- **Tax-efficient drawdown** — ISA before pension, GIA before ISA etc.
- **FX rate volatility** — currently FX rates are held fixed; could be perturbed in Monte Carlo
- **Dashboard improvements** — investment account balance visible in dashboard metrics

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