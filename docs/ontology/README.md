# My Retirement Life Ontology

**Namespace:** `https://myretirementlife.app/ontology#` (prefix: `mrl:`)  
**Extended vocabulary namespace:** `https://myretirementlife.app/ontology/ext#` (prefix: `mrlx:`)  
**Version:** 0.8.0  
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
│   ├── mrl:InvestmentAccount        🔮 post-MVP
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
```
mrlx:AccountTypeScheme
└── mrlx:CashAccountType (top concept)
    ├── mrlx:CashAccountType_Current
    ├── mrlx:CashAccountType_Savings
    ├── mrlx:CashAccountType_FixedTerm
    ├── mrlx:CashAccountType_TaxAdvantaged
    └── mrlx:CashAccountType_Other
```
Post-MVP: `InvestmentAccountType`, `PensionAccountType` etc. will be added as sibling top concepts.

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

MVP projection applies a weighted average interest rate across all accounts. Post-MVP will track interest per account independently.

### Budget line growth rates
`mrl:annualChangeRate` on `mrl:BudgetLine` is the default annual percentage change for MVP. Post-MVP introduces `mrl:BudgetLineSegment` for time-segmented growth rates (e.g. holidays up 5%/year until 2035, then up 50%/year, then stops).

---

## Seed data

**Currencies:** GBP, USD, EUR, AUD, CAD, CHF, JPY, NZD, SEK, NOK, DKK, SGD, HKD, ZAR  
**Jurisdictions:** GB, US, EU, AU, CA, NZ, CH, SG, ZA

---

## Loading and reloading

Loaded by `src/store/ontology_loader.py` on startup. Idempotent — skips if already loaded. Force reload after editing:

```python
from src.store.graph import store
from src.store.ontology_loader import load_ontology
load_ontology(store.store, force=True)
```

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
        FILTER(LANG(?label) = \"en\")
    }
}
```

**All budget line subtypes of Retirement income:**
```sparql
PREFIX mrlx: <https://myretirementlife.app/ontology/ext#>
PREFIX skos:  <http://www.w3.org/2004/02/skos/core#>

SELECT ?concept ?label
WHERE {
    GRAPH <https://myretirementlife.app/ontology/graph> {
        ?concept skos:broader mrlx:IncomeSourceType_Retirement ;
                 skos:prefLabel ?label .
        FILTER(LANG(?label) = \"en\")
    }
}
```
