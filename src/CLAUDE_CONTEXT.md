# My Retirement Life — Claude Context Document

This document is read at the start of each new Claude conversation to provide
full project context without needing the entire chat history.

**Last updated:** 2026-05-16
**Current version:** MVP complete + v0.2 design agreed

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
├── requirements.txt
├── .env.example
├── docs/
│   ├── adr/                         # Architecture Decision Records (ADR-001 to ADR-009)
│   ├── ontology/
│   │   ├── mrl-ontology.ttl         # THE ONTOLOGY — source of truth, v0.8.0
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
    │       ├── budget.py            # GET/POST /budget (CRUD)
    │       ├── life_events.py       # GET/POST /life-events (CRUD)
    │       ├── projection.py        # GET /projection (engine + chart)
    │       └── settings_route.py    # GET/POST /settings (export/import/inflation)
    ├── store/
    │   ├── graph.py                 # RetirementStore wrapper, next_iri(), MRL, DATA_GRAPH
    │   ├── ontology_loader.py       # Loads TTL into Oxigraph on startup
    │   └── mrl-ontology.ttl         # COPY — do not edit here, edit docs/ontology/
    └── templates/
        ├── base.html                # Layout, sidebar, setup banner (calls setup_state())
        ├── dashboard.html           # First-run wizard + live dashboard
        ├── profile.html             # Personal details only (no income)
        ├── income.html              # Multiple income sources with start/end years
        ├── accounts.html            # Cash accounts with FX rates
        ├── budget.html              # Budget lines with frequency
        ├── life_events.html
        ├── projection.html          # Stacked chart + confidence score
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

## Ontology summary (v0.8.0)

**Namespaces:**
- `mrl:` = `https://myretirementlife.app/ontology#`
- `mrlx:` = `https://myretirementlife.app/ontology/ext#`

**Key classes:**
- `mrl:Person` — single user (Person_1)
- `mrl:IncomeSource` — multiple, with start/end years
- `mrl:Account` → `mrl:CashAccount` (MVP), `mrl:InvestmentAccount` (next)
- `mrl:BudgetLine` — with frequency and growth rate
- `mrl:LifeEvent`
- `mrl:ProjectionSettings`
- `mrl:Currency`, `mrl:Jurisdiction` — reference individuals

**Key mrlx: SKOS schemes:**
- `mrlx:IncomeSourceTypeScheme` — Employment, Property, Retirement (subtypes), Investment (subtypes), etc.
- `mrlx:AccountTypeScheme` — CashAccountType (Current, Savings, FixedTerm, TaxAdvantaged, Other)
- `mrlx:FrequencyTypeScheme` — Weekly×52, Fortnightly×26, TwiceMonthly×24, Monthly×12, Quarterly×4, Annually×1
- `mrlx:BudgetLineType` — Mandatory, Discretionary, Loan
- `mrlx:LifeEventType` — LargeExpenditure, Windfall, etc.
- `mrlx:EmploymentStatus` — Employed, SelfEmployed, NotWorking, Retired

---

## Projection engine summary

File: `src/api/routes/projection.py`

**Key functions:**
- `load_all_income_sources()` — returns list with start/end years
- `load_accounts()` — returns list with FX-adjusted balances
- `load_budget_lines()` — returns list with annual amounts (frequency normalised)
- `load_life_events()`
- `run_projection(inflation_rate)` — year-by-year from today to life expectancy

**Engine logic per year:**
1. Sum active income sources (checking start/end year windows)
2. Apply weighted average interest to total balance
3. Grow each budget line by its rate (or inflation_rate if 0)
4. Remove loan lines after their end year
5. Apply life event amounts
6. Accumulate balance

**Confidence scoring:**
- Green: never runs out
- Amber: runs out within 5 years of life expectancy
- Red: runs out before life expectancy

---

## What was just completed (MVP polish)

1. ✅ `.vscode/settings.json` — suppresses Jinja2 false positives
2. ✅ Settings page — export/import JSON backup, inflation rate, data directory info
3. ✅ First-run experience — welcome card, progress steps, persistent setup banner in base.html
4. ✅ Profile cleanup — income removed from profile, points to /income screen
5. ✅ Sidebar order — Profile → Income → Accounts → Budget → Life events
6. ✅ Error handling — friendly error.html for 404/500
7. ✅ Projection assumptions — removed form, replaced with read-only summary + link to Settings

---

## What's next (v0.2)

Per ADR-009 and the agreed build order:

**1. Budget start/stop dates**
- Add `mrl:budgetStartYear` and `mrl:budgetEndYear` to `mrl:BudgetLine` in ontology
- Update `accounts.html` form to show start/end year fields (same pattern as income)
- Update projection engine to respect start/end years on budget lines

**2. Retirement jurisdiction**
- Add `mrl:plansToRetireIn` to `mrl:Person` ontology
- Add `mrl:costOfLivingIndex` to `mrl:Jurisdiction`
- Add field to profile screen
- Update projection to switch currency/COL from retirement year

**3. Investment accounts** (ADR-009)
- Add `mrl:InvestmentAccountType` SKOS scheme to ontology
- Add `mrl:annualGrowthRate`, `mrl:annualDividendRate`, `mrl:reinvestDividends` to `mrl:InvestmentAccount`
- Build /investments screen (same pattern as /accounts)
- Update projection engine to include investment account growth

**4. Monte Carlo** (ADR-009)
- Add `mrlx:MonteCarloProfile` SKOS individuals with parameter properties
- Add `numpy` to requirements (for normal distribution sampling)
- New projection function running 500 simulations
- Chart showing median + 10th/90th percentile band

---

## ADR summary

| # | Decision |
|---|---------|
| 001 | Python + FastAPI + Oxigraph backend |
| 002 | PyInstaller (Windows/macOS) + AppImage (Linux) packaging |
| 003 | HTMX + Tailwind + DaisyUI frontend |
| 004 | Cross-platform portability practices |
| 005 | Ontology loaded from TTL into named graph on startup |
| 006 | Instance IRIs follow mrl:ClassName_N pattern |
| 007 | Quad patterns for reads, SPARQL UPDATE for writes |
| 008 | Multiple income sources with start/end dates in MVP |
| 009 | Investment accounts as pots; Monte Carlo with named profiles |