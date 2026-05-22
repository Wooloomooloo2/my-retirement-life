# CLAUDE_CONTEXT — My Retirement Life (MRL)

> Drop this file into a new conversation to restore full project context.
> Keep it updated at the end of each session.
> Last updated: 2026-05-22

---

## Project overview

**My Retirement Life (MRL)** is a local-first personal retirement planning application.
The user is a business architect and data modeller — Claude does all coding.

- **GitHub:** `Wooloomooloo2/my-retirement-life`
- **Stack:** Python 3.13 + FastAPI, pyoxigraph (Oxigraph triple store), HTMX + Tailwind + DaisyUI, Chart.js, NumPy
- **Platform:** Windows (VS Code), may migrate to Linux
- **Data storage:** Oxigraph RDF triple store at `AppData/Local/MyRetirementLife/`
- **Ontology:** `mrl-ontology.ttl`, version 1.0.1 + ADR-015 additions (see below)

---

## Repository structure

```
my-retirement-life/
├── src/
│   ├── api/
│   │   ├── app.py                    ← FastAPI app, middleware, dashboard route
│   │   ├── templates.py              ← Jinja2 templates instance
│   │   └── routes/
│   │       ├── profile.py
│   │       ├── accounts.py           ← Cash accounts CRUD + contribution CRUD
│   │       ├── investments.py        ← Investment accounts CRUD + contribution CRUD
│   │       ├── income.py
│   │       ├── budget.py             ← Includes get_all_contributions_for_budget()
│   │       ├── life_events.py
│   │       ├── projection.py         ← Engine + projection settings routes
│   │       ├── settings_route.py     ← Backup/restore/export (incl. contributions)
│   │       └── scenarios.py          ← Scenario management routes
│   ├── store/
│   │   ├── graph.py                  ← Store singleton, MRL/DATA_GRAPH constants
│   │   ├── ontology_loader.py
│   │   └── scenario_manager.py       ← Named scenario file management
│   └── templates/
│       ├── base.html
│       ├── dashboard.html
│       ├── profile.html
│       ├── accounts.html             ← Includes contribution collapsible section
│       ├── investments.html          ← Full rewrite; includes contribution section
│       ├── investment_projection.html ← Per-account detail chart (incl. contribution bar)
│       ├── income.html
│       ├── budget.html               ← Includes read-only contributions section
│       ├── life_events.html          ← Fixed amount sign UX
│       ├── projection.html           ← Includes surplus_dest_name in assumptions
│       ├── settings.html
│       ├── scenarios.html
│       └── error.html
└── docs/
    └── adr/
        ├── ADR-010 through ADR-015
```

---

## ADR summary

| # | Decision | Status |
|---|---------|--------|
| 001 | Python + FastAPI + Oxigraph backend | Implemented |
| 002 | PyInstaller/AppImage packaging | Accepted |
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
| 015 | Account contributions | **Implemented** |

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
    or first cash account, or first account — in that priority order). Both ReduceDrawdown and
    SweepToAccount strategies now credit the surplus rather than discarding it.
11. Record closing balances, withdrawals, contributions per account

### Confidence scoring

- **Runs out year:** first year where `balance <= 0` (changed from `< 0` — catches the
  common case where balances are clamped at 0 by `max(0.0, ...)` and never go negative)
- Green: never runs out
- Amber: runs out within 5 years of life expectancy
- Red: runs out before life expectancy

### Surplus routing fallback priority

When no spending account is configured, surplus flows to accounts in this order:
1. Configured `spending_account` (explicit — always wins)
2. First `CashAccountType_Current` account (prefers current/checking over savings/ISA)
3. First cash account of any type
4. First account of any class (last resort)

### Contribution growth rate (ADR-015)

```python
# In year loop — compound growth from first active year:
years_active = year - c_start   # 0 in the first active year
contrib_this_year = base_annual * ((1 + growth_rate / 100) ** years_active)
```

---

## Account contributions (ADR-015) — COMPLETE

### Data model
- `mrl:AccountContribution` class; linked to account via `mrl:contributionOwner`
- Properties: `contributionAmount`, `contributionFrequency`, `contributionStartYear`,
  `contributionEndYear`, `contributionNote`, `contributionGrowthRate`, `contributionOwner`
- IRI pattern: `mrl:AccountContribution_N`
- One contribution per account in v1.0 UI (data model supports multiples)

### Routes
- `POST /accounts/{n}/contribution` — save/replace contribution for cash account N
- `POST /accounts/{n}/contribution/delete` — delete contribution for cash account N
- `POST /investments/{n}/contribution` — same for investment account N
- `POST /investments/{n}/contribution/delete` — same

### Engine dual effect
Credits account balance **and** deducts from cashflow (treated as mandatory spending).
Default active window: current year → retirement year (inclusive) if start/end not set.

### UI
- Contribution collapsible section appears **after** the main `</form>` in each account card
  (separate `<form>` to avoid nested-form HTML invalidity)
- Only shown when editing (not adding); new accounts redirect to edit after creation
- Annual equivalent hint updates live as amount/frequency changes
- Growth rate field: compound growth per year, positive or negative
- Budget page shows read-only contributions table with annual totals

### Export/restore
`settings_route.py` exports `account_contributions` list keyed by `ownerLabel`;
restores with fresh `AccountContribution_N` IRIs. Backward-compatible with pre-ADR-015 backups.

---

## Life events — amount sign convention

- **Stored:** positive = cost (reduces balance), negative = receipt/windfall (increases balance)
- **UI input:** always enter a positive number; sign badge (+/−) and hint text update based on
  event type. On submit, JS negates the amount for `LifeEventType_Windfall` automatically.
- **Table display:** +£ in green for receipts, −£ in red for costs
- `RECEIPT_TYPES` set in `life_events.html` JS: currently `{'LifeEventType_Windfall'}`
  — extend this if additional receipt types are added to the ontology

---

## Store / ontology patterns

**Constants in `src/store/graph.py`:**
```python
MRL       = "https://myretirementlife.app/ontology#"
MRL_EXT   = "https://myretirementlife.app/ontology/ext#"
DATA_GRAPH = NamedNode("https://myretirementlife.app/data/graph")
```

**IRI naming:** `mrl:ClassName_N` where N = MAX(existing) + 1

**Data access pattern (ADR-007):**
- Known instances → `quads_for_pattern`
- Queries/filtering → SPARQL SELECT
- All writes → SPARQL UPDATE

**Tax rate storage:** decimals in store (0.20), percentages in forms (20). Divide by 100 on save.

**DELETE pattern for contributions:**
```sparql
DELETE { GRAPH <data_graph> { ?c ?p ?o . } }
WHERE  { GRAPH <data_graph> { ?c mrl:contributionOwner <account_iri> ; ?p ?o . } }
```

---

## app.py Jinja2 globals

- `user_initials` — returns "JS" style initials from Person_1
- `active_scenario` — returns scenario state dict (`name`, `saved`, `display_name`, `is_named`, `is_clean`)
- `setup_state` — returns setup checklist completion dict

---

## Projection route context keys

```python
{
    "projection":              dict,   # run_projection() result
    "mc":                      dict,   # run_monte_carlo() result
    "proj_settings":           dict,
    "all_accounts":            list,   # includes account_type_local
    "surplus_dest_name":       str,    # name of account receiving surplus (for UI display)
    "surplus_dest_configured": bool,   # True if explicitly set in projection settings
}
```

---

## Key UX conventions

- **Tax rate fields:** 0–100% in forms, stored as 0–1 decimal in triple store
- **Chart heights:** always `position:relative; height:Npx` wrapper + `maintainAspectRatio: false`
- **Form sections:** DaisyUI collapse/collapse-arrow pattern
- **Contribution sections:** separate `<form>` placed AFTER the main account `</form>`,
  still inside the same `card-body` div — avoids nested-form HTML invalidity
- **New account flow:** `POST /accounts` and `POST /investments` redirect to
  `/accounts/{n}/edit` and `/investments/{n}/edit` after creation, so the contribution
  section is immediately available
- **Frequency multipliers:**
  ```python
  FREQUENCY_MULTIPLIERS = {
      "FrequencyType_Weekly": 52, "FrequencyType_Fortnightly": 26,
      "FrequencyType_TwiceMonthly": 24, "FrequencyType_Monthly": 12,
      "FrequencyType_Quarterly": 4, "FrequencyType_Annually": 1,
  }
  ```
- **Life event amounts:** always positive in forms; JS negates for receipt types on submit
- **Account label format:** `CashAccount_N`, `InvestmentAccount_N`, `AccountContribution_N`
- **Scenario dirty state:** set by HTTP middleware in `app.py`, NOT by route handlers

---

## Ontology additions to apply manually (TTL snippets)

These have been implemented in code but still need adding to both copies of `mrl-ontology.ttl`
(`docs/ontology/mrl-ontology.ttl` and `src/store/mrl-ontology.ttl`).
After editing, delete the store folder to force a reload on next startup.

### ADR-015 — Account Contribution class and properties

```turtle
mrl:AccountContribution a owl:Class ;
    rdfs:label "Account Contribution"@en ;
    rdfs:comment "A regular scheduled contribution to an account."@en .

mrl:contributionAmount a owl:DatatypeProperty ;
    rdfs:domain mrl:AccountContribution ;
    rdfs:range  xsd:decimal ;
    rdfs:label  "contribution amount"@en .

mrl:contributionFrequency a owl:ObjectProperty ;
    rdfs:domain mrl:AccountContribution ;
    rdfs:label  "contribution frequency"@en .

mrl:contributionStartYear a owl:DatatypeProperty ;
    rdfs:domain mrl:AccountContribution ;
    rdfs:range  xsd:integer ;
    rdfs:label  "contribution start year"@en .

mrl:contributionEndYear a owl:DatatypeProperty ;
    rdfs:domain mrl:AccountContribution ;
    rdfs:range  xsd:integer ;
    rdfs:label  "contribution end year"@en .

mrl:contributionNote a owl:DatatypeProperty ;
    rdfs:domain mrl:AccountContribution ;
    rdfs:range  xsd:string ;
    rdfs:label  "contribution note"@en .

mrl:contributionGrowthRate a owl:DatatypeProperty ;
    rdfs:domain mrl:AccountContribution ;
    rdfs:range  xsd:decimal ;
    rdfs:label  "contribution annual growth rate"@en .

mrl:contributionOwner a owl:ObjectProperty ;
    rdfs:domain mrl:AccountContribution ;
    rdfs:range  mrl:Account ;
    rdfs:label  "contribution owner"@en .

mrl:hasContribution a owl:ObjectProperty ;
    rdfs:domain mrl:Account ;
    rdfs:range  mrl:AccountContribution ;
    rdfs:label  "has contribution"@en .
```

---

## Current backlog

### Pre-1.0 polish
- **Income deposit account UI** — income sources should specify which account receives the
  income. Engine surplus routing already delivers most of the value (unspent income accumulates
  in spending/current account). Full per-source routing requires uploading `income.py` and
  `income.html` for UI changes.
- Load/Save quick-action buttons in top banner (`base.html` — Claude has not seen this file)
- `drawdown_configured` dashboard flag fires too early (any settings save, not just spending account)
- Accounts table overflow on narrower screens
- **MC model discrepancy:** Monte Carlo shows high success rates even when deterministic engine
  shows the money running out. MC uses an aggregate pool that doesn't model per-account
  depletion — known limitation of ADR-012, noted in backlog for future improvement.

### Post-1.0
- Tax-optimal drawdown ordering (ADR-011 future)
- Pension commencement lump sum (PCLS) dedicated model
- Multiple marginal tax bands (ADR-013 future)
- Per-jurisdiction Monte Carlo profiles (ADR-012 future)
- Employer contributions (`isEmployerContribution` flag, ADR-015 v1.1)
- Multiple contributions per account surfaced in UI (ADR-015 v1.1)
- GIA cost basis from MFL data portability
- `mrl-core` namespace extraction when MFL is stable
- MFL sister app

---

## Files Claude has NOT seen (will need uploading when relevant)

- `src/templates/base.html` — needed for: top banner Load/Save buttons, nav indicator
- `src/api/routes/income.py` — needed for: income deposit account UI
- `src/templates/income.html` — needed for: income deposit account UI
- `src/api/routes/life_events.py` — not seen; auto-sign fix is entirely in HTML/JS
- `mrl-ontology.ttl` — not seen; ontology additions are provided as TTL snippets above