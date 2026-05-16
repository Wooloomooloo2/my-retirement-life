# My Retirement Life Ontology

**Namespace:** `https://myretirementlife.app/ontology#` (prefix: `mrl:`)  
**Extended vocabulary namespace:** `https://myretirementlife.app/ontology/ext#` (prefix: `mrlx:`)  
**Version:** 0.9.0  
**File:** [mrl-ontology.ttl](mrl-ontology.ttl)  
**Python loader:** `src/store/ontology_loader.py`

---

## Design principles

- **Simple class hierarchy** — classes defined for human understanding and extensibility, not OWL reasoning
- **Independent reference entities** — currencies, jurisdictions, and other shared concepts are named individuals, not string literals
- **Two namespaces** — `mrl:` for ontology terms and instance data; `mrlx:` for controlled vocabularies and enumeration values
- **SKOS concept schemes** for all taxonomical vocabularies — hierarchy expressed via `skos:broader`/`skos:narrower`
- **Consistent IRI patterns** — see below
- **Language-tagged labels** — all labels carry `@en` so additional languages can be added as extra triples
- **SKOS for controlled vocabularies** — `mrlx:` individuals use `skos:prefLabel`, `skos:definition`, `skos:notation`, `skos:scopeNote`
- **Named graph separation** — ontology loaded into its own named graph, separate from user data
- **TTL as truth** — the `.ttl` file is the authoritative source, loaded into Oxigraph on startup

---

## IRI patterns

| Pattern | Example | Used for |
|---------|---------|----------|
| `mrl:ClassName` | `mrl:CashAccount` | Classes |
| `mrl:propertyName` | `mrl:accountBalance` | Properties (camelCase) |
| `mrl:ClassName_Code` | `mrl:Currency_GBP` | Named individuals (reference data) |
| `mrlx:ClassName_Value` | `mrlx:BudgetLineType_Mandatory` | Controlled vocabulary individuals |
| `mrl:ClassName_N` | `mrl:Person_1`, `mrl:CashAccount_3` | User instance data (runtime, ADR-006) |

---

## Named graphs

| Named graph IRI | Contents |
|----------------|----------|
| `https://myretirementlife.app/ontology/graph` | All triples from `mrl-ontology.ttl` |
| `https://myretirementlife.app/data/graph` | User instance data created at runtime |

---

## Class hierarchy

```
owl:Thing
├── mrl:Currency                     (reference individuals: mrl:Currency_GBP etc.)
├── mrl:Jurisdiction                 (reference individuals: mrl:Jurisdiction_GB etc.)
├── mrl:Person                       ✅ MVP
├── mrl:IncomeSource                 ✅ MVP
├── mrl:Account
│   ├── mrl:CashAccount              ✅ MVP
│   ├── mrl:InvestmentAccount        ✅ v0.2 (ADR-009)
│   ├── mrl:PensionAccount           🔮 post-MVP
│   ├── mrl:PropertyAsset            🔮 post-MVP
│   └── mrl:OtherAsset               🔮 post-MVP
├── mrl:BudgetLine                   ✅ MVP
├── mrl:BudgetLineSegment            🔮 post-MVP (time-segmented growth rates)
├── mrl:LifeEvent                    ✅ MVP
└── mrl:ProjectionSettings           ✅ MVP
```

---

## SKOS concept schemes (mrlx:)

All controlled vocabularies are modelled as SKOS concept schemes with `skos:broader`/`skos:narrower` hierarchy.

### IncomeSourceTypeScheme
Top-level income source taxonomy with two hierarchical branches:

```
mrlx:IncomeSourceTypeScheme
├── mrlx:IncomeSourceType_Employment
├── mrlx:IncomeSourceType_BusinessIncome
├── mrlx:IncomeSourceType_InterestIncome
├── mrlx:IncomeSourceType_Property
├── mrlx:IncomeSourceType_Retirement
│   ├── mrlx:IncomeSourceType_Retirement_StatePension
│   ├── mrlx:IncomeSourceType_Retirement_StateIncome
│   ├── mrlx:IncomeSourceType_Retirement_WorkplacePension
│   ├── mrlx:IncomeSourceType_Retirement_PrivatePension
│   ├── mrlx:IncomeSourceType_Retirement_FourOOneK
│   └── mrlx:IncomeSourceType_Retirement_Other
├── mrlx:IncomeSourceType_Investment
│   ├── mrlx:IncomeSourceType_Investment_Annuity
│   ├── mrlx:IncomeSourceType_Investment_Dividends
│   ├── mrlx:IncomeSourceType_Investment_BondIncome
│   ├── mrlx:IncomeSourceType_Investment_FundIncome
│   └── mrlx:IncomeSourceType_Investment_Other
└── mrlx:IncomeSourceType_Other
```

### AccountTypeScheme
Extended in v0.2 to include `InvestmentAccountType` as a sibling top concept alongside `CashAccountType`.

```
mrlx:AccountTypeScheme
├── mrlx:CashAccountType
│   ├── mrlx:CashAccountType_Current
│   ├── mrlx:CashAccountType_Savings
│   ├── mrlx:CashAccountType_FixedTerm
│   ├── mrlx:CashAccountType_TaxAdvantaged
│   └── mrlx:CashAccountType_Other
└── mrlx:InvestmentAccountType             ✅ v0.2
    ├── mrlx:InvestmentAccountType_StocksShares
    ├── mrlx:InvestmentAccountType_TaxAdvantaged
    ├── mrlx:InvestmentAccountType_Pension
    ├── mrlx:InvestmentAccountType_UnitTrust
    ├── mrlx:InvestmentAccountType_Bonds
    └── mrlx:InvestmentAccountType_Other
```

Post-MVP: `PensionAccountType` will be added as a further sibling top concept when `mrl:PensionAccount` is implemented.

### FrequencyTypeScheme
Used on `mrl:BudgetLine` to specify recurrence. The projection engine normalises to annual amounts.

```
mrlx:FrequencyTypeScheme
├── mrlx:FrequencyType_Weekly          (× 52)
├── mrlx:FrequencyType_Fortnightly     (× 26)
├── mrlx:FrequencyType_TwiceMonthly    (× 24)
├── mrlx:FrequencyType_Monthly         (× 12)
├── mrlx:FrequencyType_Quarterly       (× 4)
└── mrlx:FrequencyType_Annually        (× 1)
```

### MonteCarloProfileScheme                ✅ v0.2
Named volatility profiles for the Monte Carlo retirement simulation. Each profile carries `mrlx:returnVolatility` and `mrlx:inflationVolatility` as datatype properties (standard deviations in percentage points), allowing parameters to be adjusted in the TTL without code changes.

```
mrlx:MonteCarloProfileScheme
├── mrlx:MonteCarloProfile_Conservative   (returnVol=3.0%, inflationVol=0.8%)
├── mrlx:MonteCarloProfile_Moderate       (returnVol=6.0%, inflationVol=1.5%)  ← default
└── mrlx:MonteCarloProfile_Aggressive     (returnVol=10.0%, inflationVol=2.5%)
```

### Other flat vocabularies (owl:Class with named individuals)
- `mrlx:EmploymentStatus` — Employed, SelfEmployed, NotWorking, Retired
- `mrlx:BudgetLineType` — Mandatory, Discretionary, Loan
- `mrlx:LifeEventType` — LargeExpenditure, Windfall, PropertyTransaction, RelocationAbroad, CaringResponsibility

---

## Key property notes

### Exchange rates
`mrl:exchangeRateToBase` on `mrl:Account` stores a user-maintained exchange rate for converting non-base-currency account balances into the base currency for projection calculations. Expressed as: 1 unit of account currency = N units of base currency (e.g. 0.79 for USD→GBP).

Only required when account currency differs from the person's base currency. Post-MVP will support live rate fetching from an exchange rate API.

### Interest rates
`mrl:annualInterestRate` on `mrl:CashAccount` represents the **current rate only**. Rate history is a future feature — users should update this value when their rate changes.

MVP projection applies a weighted average return rate across all accounts (cash and investment). Post-MVP will track interest per account independently.

### Investment account rates  ✅ v0.2
`mrl:annualGrowthRate` and `mrl:annualDividendRate` on `mrl:InvestmentAccount` represent expected annual capital appreciation and income yield respectively, both as percentages. `mrl:reinvestDividends` (boolean) controls whether dividend income is compounded back into the pot or treated as annual cashflow income in the projection.

The projection engine includes investment accounts in the blended weighted return rate. Non-reinvested dividends are modelled as a separate annual income stream growing at the account's capital growth rate.

### Budget line growth rates
`mrl:annualChangeRate` on `mrl:BudgetLine` is the default annual percentage change for MVP. Post-MVP introduces `mrl:BudgetLineSegment` for time-segmented growth rates.

### Budget line active dates  ✅ v0.2
`mrl:budgetStartYear` and `mrl:budgetEndYear` on `mrl:BudgetLine` allow time-bounded spending. If absent, the line is active from the current year indefinitely. `mrl:loanEndYear` remains a separate property specifically for loan-type lines (drives the "ends YYYY" badge in the UI).

### Retirement jurisdiction  ✅ v0.2
`mrl:plansToRetireIn` on `mrl:Person` optionally points to a `mrl:Jurisdiction` individual. If set and different from `mrl:residesIn`, the projection engine multiplies all spending from the retirement year onward by `retire_col / current_col` where each COL index comes from `mrl:costOfLivingIndex` on the respective `mrl:Jurisdiction` individual.

`mrl:costOfLivingIndex` on `mrl:Jurisdiction` is indexed to UK = 1.00. Values are approximate and based on broad cross-country comparisons — users should adjust their budget lines directly for precision.

### Monte Carlo profile  ✅ v0.2
`mrl:monteCarloProfile` on `mrl:ProjectionSettings` points to a `mrlx:MonteCarloProfile_*` individual. Defaults to `mrlx:MonteCarloProfile_Moderate` if not set. The projection engine reads `mrlx:returnVolatility` and `mrlx:inflationVolatility` from the selected individual at runtime.

---

## Seed data

**Currencies:** GBP, USD, EUR, AUD, CAD, CHF, JPY, NZD, SEK, NOK, DKK, SGD, HKD, ZAR

**Jurisdictions:** GB, US, EU, AU, CA, NZ, CH, SG, ZA — each with a `mrl:costOfLivingIndex` value (GB = 1.00 base). Values: US=1.05, EU=0.88, AU=0.92, CA=0.90, NZ=0.88, CH=1.38, SG=1.08, ZA=0.52.

---

## Loading and reloading

Loaded by `src/store/ontology_loader.py` on startup. Idempotent — skips if already loaded. Force reload after editing:

```python
from src.store.graph import store
from src.store.ontology_loader import load_ontology
load_ontology(store.store, force=True)
```

Or delete the Oxigraph store folder and restart — the loader will rebuild from the TTL on next startup.

Verify at runtime: `http://127.0.0.1:8000/ontology/status`

---

## SPARQL examples

**All cash accounts with base-currency equivalent balance:**
```sparql
PREFIX mrl: <https://myretirementlife.app/ontology#>

SELECT ?name ?balance ?fxRate ?currencyCode
WHERE {
    GRAPH <https://myretirementlife.app/data/graph> {
        ?acc a mrl:CashAccount ;
             mrl:accountName ?name ;
             mrl:accountBalance ?balance .
        OPTIONAL { ?acc mrl:exchangeRateToBase ?fxRate }
        OPTIONAL { ?acc mrl:accountCurrency ?curr }
    }
    OPTIONAL {
        GRAPH <https://myretirementlife.app/ontology/graph> {
            ?curr mrl:currencyCode ?currencyCode .
        }
    }
}
```

**All income source types (top level only):**
```sparql
PREFIX mrlx: <https://myretirementlife.app/ontology/ext#>
PREFIX skos:  <http://www.w3.org/2004/02/skos/core#>

SELECT ?concept ?label
WHERE {
    GRAPH <https://myretirementlife.app/ontology/graph> {
        ?concept skos:topConceptOf mrlx:IncomeSourceTypeScheme ;
                 skos:prefLabel ?label .
        FILTER(LANG(?label) = "en")
    }
}
```

**All Monte Carlo profiles with their volatility parameters:**
```sparql
PREFIX mrlx: <https://myretirementlife.app/ontology/ext#>
PREFIX skos:  <http://www.w3.org/2004/02/skos/core#>

SELECT ?profile ?label ?returnVol ?inflationVol
WHERE {
    GRAPH <https://myretirementlife.app/ontology/graph> {
        ?profile skos:inScheme mrlx:MonteCarloProfileScheme ;
                 skos:prefLabel ?label ;
                 mrlx:returnVolatility ?returnVol ;
                 mrlx:inflationVolatility ?inflationVol .
        FILTER(LANG(?label) = "en")
    }
}
ORDER BY ?returnVol
```

**All investment accounts with effective annual return:**
```sparql
PREFIX mrl: <https://myretirementlife.app/ontology#>

SELECT ?name ?balance ?growthRate ?dividendRate ?reinvest
WHERE {
    GRAPH <https://myretirementlife.app/data/graph> {
        ?acc a mrl:InvestmentAccount ;
             mrl:accountName ?name ;
             mrl:accountBalance ?balance ;
             mrl:annualGrowthRate ?growthRate ;
             mrl:annualDividendRate ?dividendRate ;
             mrl:reinvestDividends ?reinvest .
    }
}
```
