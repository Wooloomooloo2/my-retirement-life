# My Retirement Life Ontology

**File:** `mrl-ontology.ttl`
**Version:** 1.0.0
**Last updated:** 2026-05-17

This document describes the OWL ontology that is the single source of truth for
all data structures in My Retirement Life. The Python application never defines
data structure in code — every class, property, and controlled vocabulary is
declared here first.

---

## File locations

| Copy | Path | Purpose |
|------|------|---------|
| Authoritative | `docs/ontology/mrl-ontology.ttl` | Edit this one |
| Runtime | `src/store/mrl-ontology.ttl` | Keep in sync — copy from above |

After editing, copy the file and delete the store folder so Oxigraph reloads:

- **Windows:** `C:\Users\<user>\AppData\Local\MyRetirementLife\`
- **macOS:** `/Users/<user>/Library/Application Support/MyRetirementLife/`

---

## Namespaces

| Prefix | URI | Purpose |
|--------|-----|---------|
| `mrl:` | `https://myretirementlife.app/ontology#` | Core classes, properties, and reference individuals |
| `mrlx:` | `https://myretirementlife.app/ontology/ext#` | Controlled vocabularies, SKOS schemes, and concept type classes |

---

## Naming conventions

| Pattern | Example | Used for |
|---------|---------|---------|
| `mrl:ClassName` | `mrl:CashAccount` | OWL classes |
| `mrl:propertyName` | `mrl:accountBalance` | Properties (camelCase) |
| `mrl:ClassName_Code` | `mrl:Currency_GBP`, `mrl:Jurisdiction_GB` | Reference individuals |
| `mrl:ClassName_N` | `mrl:Person_1`, `mrl:CashAccount_3` | User instance data |
| `mrlx:VocabName` | `mrlx:BudgetLineType` | owl:Class controlled vocabularies |
| `mrlx:VocabName_Value` | `mrlx:BudgetLineType_Mandatory` | Individuals in owl:Class vocabularies |
| `mrlx:SchemeName` | `mrlx:FrequencyTypeScheme` | SKOS ConceptSchemes |
| `mrlx:ShortName_Value` | `mrlx:FrequencyType_Monthly` | SKOS Concepts |
| `mrlx:TypeName` | `mrlx:TaxTreatmentType` | OWL range-stub classes for SKOS properties |

---

## Named graphs

| Constant | IRI | Contents |
|---------|-----|---------|
| `ONTOLOGY_GRAPH` | `https://myretirementlife.app/ontology/graph` | Ontology triples — read-only at runtime |
| `DATA_GRAPH` | `https://myretirementlife.app/data/graph` | User instance data — read/write |

---

## Classes

### `mrl:Person`
The individual whose retirement is being planned. Always a single instance: `mrl:Person_1`.

| Property | Type | Notes |
|----------|------|-------|
| `mrl:firstName` | `xsd:string` | |
| `mrl:lastName` | `xsd:string` | |
| `mrl:dateOfBirth` | `xsd:date` | |
| `mrl:targetRetirementAge` | `xsd:integer` | |
| `mrl:lifeExpectancy` | `xsd:integer` | Planning horizon in years of age |
| `mrl:employmentStatus` | `→ mrlx:EmploymentStatus` | |
| `mrl:baseCurrency` | `→ mrl:Currency` | Currency for projection display |
| `mrl:residesIn` | `→ mrl:Jurisdiction` | Current country of residence |
| `mrl:plansToRetireIn` | `→ mrl:Jurisdiction` | Retirement jurisdiction if different from current; drives COL adjustment |

---

### `mrl:IncomeSource`
A single income stream. A person may have multiple. Instance pattern: `mrl:IncomeSource_N`.

| Property | Type | Notes |
|----------|------|-------|
| `mrl:incomeSourceName` | `xsd:string` | e.g. "Main salary", "Rental — Manchester" |
| `mrl:incomeAnnualAmount` | `xsd:decimal` | |
| `mrl:incomeIsNetOfTax` | `xsd:boolean` | True = take-home; False = gross |
| `mrl:incomeGrowthRate` | `xsd:decimal` | Annual % change |
| `mrl:incomeStartYear` | `xsd:integer` | Null = already active |
| `mrl:incomeEndYear` | `xsd:integer` | Null = continues indefinitely |
| `mrl:incomeSourceType` | `→ skos:Concept` | From `mrlx:IncomeSourceTypeScheme` |
| `mrl:incomeCurrency` | `→ mrl:Currency` | |
| `mrl:incomeOwner` | `→ mrl:Person` | |
| `mrl:creditedToAccount` | `→ mrl:Account` | Post-MVP: specific account for this income stream |

---

### `mrl:Account` and subtypes
Superclass for all financial accounts and asset holdings. Instance pattern: `mrl:ClassName_N`.

**Properties on `mrl:Account` (inherited by all subtypes):**

| Property | Type | Notes |
|----------|------|-------|
| `mrl:accountName` | `xsd:string` | |
| `mrl:accountBalance` | `xsd:decimal` | In account's own currency |
| `mrl:accountNotes` | `xsd:string` | |
| `mrl:balanceDate` | `xsd:date` | Date the balance was recorded |
| `mrl:isLiability` | `xsd:boolean` | True for credit cards, mortgages; balance subtracted from net worth |
| `mrl:drawdownPriority` | `xsd:integer` | Lower = drawn first. Used by Waterfall strategy |
| `mrl:drawdownRatio` | `xsd:decimal` | Share of shortfall under Proportional strategy; normalised at runtime |
| `mrl:drawdownMinAge` | `xsd:decimal` | Minimum age to draw (decimal supports e.g. 59.5) |
| `mrl:drawdownMaxAge` | `xsd:decimal` | Optional maximum age |
| `mrl:drawdownEarliestDate` | `xsd:date` | Fixed-term start; takes precedence over `drawdownMinAge` |
| `mrl:drawdownLatestDate` | `xsd:date` | Maturity/expiry date |
| `mrl:effectiveWithdrawalTaxRate` | `xsd:decimal` | Effective rate at withdrawal after treaty relief; user-specified |
| `mrl:annualTaxFreeWithdrawal` | `xsd:decimal` | Annual tax-free withdrawal allowance; resets each projection year |
| `mrl:exchangeRateToBase` | `xsd:decimal` | 1 unit account currency = N units base currency |
| `mrl:exchangeRateDate` | `xsd:date` | Date rate was last updated |
| `mrl:accountCurrency` | `→ mrl:Currency` | |
| `mrl:accountJurisdiction` | `→ mrl:Jurisdiction` | Where the account is domiciled |
| `mrl:accountType` | `→ skos:Concept` | From `mrlx:AccountTypeScheme` |
| `mrl:taxTreatment` | `→ mrlx:TaxTreatmentType` | Structural tax type; drives UI guidance |
| `mrl:ownedBy` | `→ mrl:Person` | |

**Subtypes:**

#### `mrl:CashAccount` — `rdfs:subClassOf mrl:Account`
Cash deposit accounts: current, savings, fixed-term, cash ISA, etc.

| Property | Type | Notes |
|----------|------|-------|
| `mrl:annualInterestRate` | `xsd:decimal` | Current rate as %; history is a future feature |

#### `mrl:InvestmentAccount` — `rdfs:subClassOf mrl:Account`
Stocks, funds, bonds, SIPPs, 401(k)s, and other investment holdings.

| Property | Type | Notes |
|----------|------|-------|
| `mrl:annualGrowthRate` | `xsd:decimal` | Expected annual capital appreciation % |
| `mrl:annualDividendRate` | `xsd:decimal` | Expected annual income yield % |
| `mrl:reinvestDividends` | `xsd:boolean` | True = compound balance; False = treat as annual income |

#### `mrl:CreditCardAccount` — `rdfs:subClassOf mrl:Account`
Revolving credit accounts. Balance is a liability (`mrl:isLiability = true`).

| Property | Type | Notes |
|----------|------|-------|
| `mrl:creditLimit` | `xsd:decimal` | Maximum borrowing limit |
| `mrl:statementDay` | `xsd:integer` | Day of month for statement (1–31); optional |

#### `mrl:PropertyAsset` — `rdfs:subClassOf mrl:Account`
Real property held as an asset. `mrl:accountBalance` stores current estimated value.

| Property | Type | Notes |
|----------|------|-------|
| `mrl:propertyAddress` | `xsd:string` | Free-text postal address |
| `mrl:purchasePrice` | `xsd:decimal` | Original acquisition price |
| `mrl:purchaseDate` | `xsd:date` | Date of acquisition |
| `mrl:isMortgaged` | `xsd:boolean` | True = a corresponding liability account should be maintained |

#### `mrl:PensionAccount` — `rdfs:subClassOf mrl:Account` — *Post-MVP*
Defined contribution or defined benefit pension. Declared; not yet implemented.

#### `mrl:OtherAsset` — `rdfs:subClassOf mrl:Account` — *Post-MVP*
Vehicles, business interests, art, etc. Declared; not yet implemented.

---

### `mrl:BudgetLine`
A single spending line item. Instance pattern: `mrl:BudgetLine_N`.

| Property | Type | Notes |
|----------|------|-------|
| `mrl:budgetLineName` | `xsd:string` | |
| `mrl:budgetLineAmount` | `xsd:decimal` | Amount at the stated frequency |
| `mrl:annualChangeRate` | `xsd:decimal` | Annual % growth/reduction; 0 = use inflation rate |
| `mrl:loanEndYear` | `xsd:integer` | For Loan type: year repayments end |
| `mrl:budgetStartYear` | `xsd:integer` | First year active; null = active from projection start |
| `mrl:budgetEndYear` | `xsd:integer` | Last year active; null = indefinite |
| `mrl:budgetLineType` | `→ mrlx:BudgetLineType` | Mandatory, Discretionary, or Loan |
| `mrl:budgetLineFrequency` | `→ skos:Concept` | From `mrlx:FrequencyTypeScheme` |
| `mrl:budgetOwner` | `→ mrl:Person` | |

---

### `mrl:BudgetLineSegment` — *Post-MVP*
Time-bounded segments of a budget line with independent growth rates. Instance pattern: `mrl:BudgetLineSegment_N`.

| Property | Type | Notes |
|----------|------|-------|
| `mrl:segmentStartYear` | `xsd:integer` | |
| `mrl:segmentEndYear` | `xsd:integer` | Null = continues indefinitely |
| `mrl:segmentChangeRate` | `xsd:decimal` | Annual % change for this segment |
| `mrl:segmentAmountOverride` | `xsd:decimal` | Optional: replaces the budget line amount entirely for this segment |
| `mrl:segmentOfLine` | `→ mrl:BudgetLine` | Parent budget line |

---

### `mrl:LifeEvent`
A significant future event with a financial impact. Instance pattern: `mrl:LifeEvent_N`.

| Property | Type | Notes |
|----------|------|-------|
| `mrl:lifeEventName` | `xsd:string` | |
| `mrl:lifeEventYear` | `xsd:integer` | Calendar year the event occurs |
| `mrl:lifeEventAmount` | `xsd:decimal` | Positive = expenditure; negative = receipt |
| `mrl:lifeEventNotes` | `xsd:string` | |
| `mrl:lifeEventType` | `→ mrlx:LifeEventType` | |
| `mrl:lifeEventOwner` | `→ mrl:Person` | |
| `mrl:fundedByAccount` | `→ mrl:Account` | Optional: account that funds an expenditure event |
| `mrl:receivedByAccount` | `→ mrl:Account` | Optional: account that receives a windfall/receipt |

---

### `mrl:ProjectionSettings`
Global assumptions for the retirement projection. Typically a single instance per user. Instance pattern: `mrl:ProjectionSettings_N`.

| Property | Type | Notes |
|----------|------|-------|
| `mrl:inflationRate` | `xsd:decimal` | Annual inflation % applied to spending |
| `mrl:annualPersonalAllowance` | `xsd:decimal` | Total income before residence-country tax applies |
| `mrl:residenceIncomeTaxRate` | `xsd:decimal` | Marginal rate above personal allowance in country of residence |
| `mrl:projectionOwner` | `→ mrl:Person` | |
| `mrl:monteCarloProfile` | `→ skos:Concept` | From `mrlx:MonteCarloProfileScheme` |
| `mrl:drawdownStrategy` | `→ mrlx:DrawdownStrategyType` | Waterfall or Proportional |
| `mrl:surplusStrategy` | `→ mrlx:SurplusStrategyType` | SweepToAccount or ReduceDrawdown |
| `mrl:spendingAccount` | `→ mrl:Account` | Account into which all drawdown cash is deposited |
| `mrl:surplusAccount` | `→ mrl:Account` | Account that receives swept surplus |

---

### `mrl:Currency`
Reference entity for currencies. Individuals are defined in the ontology and never stored as string literals on accounts.

| Property | Type |
|----------|------|
| `mrl:currencyCode` | `xsd:string` (ISO 4217) |
| `mrl:currencySymbol` | `xsd:string` |
| `mrl:currencyName` | `xsd:string` |

**Defined individuals:** GBP, USD, EUR, AUD, CAD, CHF, JPY, NZD, SEK, NOK, DKK, SGD, HKD, ZAR

---

### `mrl:Jurisdiction`
Reference entity for legal/tax jurisdictions.

| Property | Type | Notes |
|----------|------|-------|
| `mrl:jurisdictionCode` | `xsd:string` | ISO 3166-1 alpha-2 |
| `mrl:jurisdictionName` | `xsd:string` | |
| `mrl:costOfLivingIndex` | `xsd:decimal` | GB = 1.00 base; used for COL adjustment on retirement abroad |
| `mrl:standardPersonalAllowance` | `xsd:decimal` | Reference personal allowance in jurisdiction's default currency; indicative 2024/25 values |
| `mrl:defaultCurrency` | `→ mrl:Currency` | |

**Defined individuals and reference values:**

| Individual | Country | COL Index | Personal Allowance |
|------------|---------|-----------|-------------------|
| `mrl:Jurisdiction_GB` | United Kingdom | 1.00 | £12,570 |
| `mrl:Jurisdiction_US` | United States | 1.05 | $14,600 (standard deduction) |
| `mrl:Jurisdiction_EU` | European Union | 0.88 | — (varies by member state) |
| `mrl:Jurisdiction_AU` | Australia | 0.92 | A$18,200 |
| `mrl:Jurisdiction_CA` | Canada | 0.90 | C$15,705 |
| `mrl:Jurisdiction_NZ` | New Zealand | 0.88 | NZ$14,000 (planning threshold) |
| `mrl:Jurisdiction_CH` | Switzerland | 1.38 | CHF 17,000 (approx, federal) |
| `mrl:Jurisdiction_SG` | Singapore | 1.08 | S$22,000 (approx) |
| `mrl:Jurisdiction_ZA` | South Africa | 0.52 | R95,750 |

---

## Controlled vocabularies

### owl:Class vocabularies (`mrlx:` prefix)
These use the `owl:Class` pattern with named individuals. The class is the range of an object property; individuals are typed as that class.

#### `mrlx:EmploymentStatus`
Used on `mrl:Person` via `mrl:employmentStatus`.

| Individual | Label |
|------------|-------|
| `mrlx:EmploymentStatus_Employed` | Employed |
| `mrlx:EmploymentStatus_SelfEmployed` | Self-employed |
| `mrlx:EmploymentStatus_NotWorking` | Not working |
| `mrlx:EmploymentStatus_Retired` | Retired |

#### `mrlx:BudgetLineType`
Used on `mrl:BudgetLine` via `mrl:budgetLineType`.

| Individual | Label |
|------------|-------|
| `mrlx:BudgetLineType_Mandatory` | Mandatory |
| `mrlx:BudgetLineType_Discretionary` | Discretionary |
| `mrlx:BudgetLineType_Loan` | Loan |

#### `mrlx:LifeEventType`
Used on `mrl:LifeEvent` via `mrl:lifeEventType`.

| Individual | Label | Notes |
|------------|-------|-------|
| `mrlx:LifeEventType_LargeExpenditure` | Large expenditure | |
| `mrlx:LifeEventType_Windfall` | Windfall | |
| `mrlx:LifeEventType_PropertyTransaction` | Property transaction | Post-MVP |
| `mrlx:LifeEventType_RelocationAbroad` | Relocation abroad | Post-MVP |
| `mrlx:LifeEventType_CaringResponsibility` | Caring responsibility | Post-MVP |

---

### SKOS ConceptSchemes (`mrlx:` prefix)
These use the full SKOS pattern with `skos:ConceptScheme`, `skos:topConceptOf`, `skos:broader`, and `skos:notation`. Where a property has a typed range (e.g. `mrlx:TaxTreatmentType`), the type class is a stub declared as `rdfs:subClassOf skos:Concept`.

#### `mrlx:AccountTypeScheme`
Used on `mrl:Account` via `mrl:accountType`.

```
CashAccountType
  └── CashAccountType_Current         (CASH_CURRENT)
  └── CashAccountType_Savings         (CASH_SAVINGS)
  └── CashAccountType_FixedTerm       (CASH_FIXED)
  └── CashAccountType_TaxAdvantaged   (CASH_TAX_ADV)
  └── CashAccountType_Other           (CASH_OTHER)
InvestmentAccountType
  └── InvestmentAccountType_StocksShares   (INVEST_STOCKS)
  └── InvestmentAccountType_TaxAdvantaged  (INVEST_TAX_ADV)
  └── InvestmentAccountType_Pension        (INVEST_PENSION)
  └── InvestmentAccountType_UnitTrust      (INVEST_UNIT_TRUST)
  └── InvestmentAccountType_Bonds          (INVEST_BONDS)
  └── InvestmentAccountType_Other          (INVEST_OTHER)
CreditCardAccountType
  └── CreditCardAccountType_Standard   (CC_STANDARD)
  └── CreditCardAccountType_ChargeCard (CC_CHARGE)
```

#### `mrlx:FrequencyTypeScheme`
Used on `mrl:BudgetLine` via `mrl:budgetLineFrequency`. The projection engine multiplies the stored amount by the frequency multiplier to get the annual equivalent.

| Concept | Notation | Annual multiplier |
|---------|----------|-------------------|
| `mrlx:FrequencyType_Weekly` | WEEKLY | × 52 |
| `mrlx:FrequencyType_Fortnightly` | FORTNIGHTLY | × 26 |
| `mrlx:FrequencyType_TwiceMonthly` | TWICE_MONTHLY | × 24 |
| `mrlx:FrequencyType_Monthly` | MONTHLY | × 12 |
| `mrlx:FrequencyType_Quarterly` | QUARTERLY | × 4 |
| `mrlx:FrequencyType_Annually` | ANNUALLY | × 1 |

#### `mrlx:IncomeSourceTypeScheme`
Used on `mrl:IncomeSource` via `mrl:incomeSourceType`.

```
Employment
BusinessIncome
InterestIncome
Property
Retirement
  └── Retirement_StatePension
  └── Retirement_StateIncome
  └── Retirement_WorkplacePension
  └── Retirement_PrivatePension
  └── Retirement_FourOOneK
  └── Retirement_Other
Investment
  └── Investment_Annuity
  └── Investment_Dividends
  └── Investment_BondIncome
  └── Investment_FundIncome
  └── Investment_Other
Other
```

#### `mrlx:MonteCarloProfileScheme`
Used on `mrl:ProjectionSettings` via `mrl:monteCarloProfile`. Each profile carries `mrlx:returnVolatility` and `mrlx:inflationVolatility` as standard deviations (percentage points). The Monte Carlo engine applies these to investment accounts only — cash accounts are deterministic.

| Concept | Notation | Return σ | Inflation σ |
|---------|----------|----------|-------------|
| `mrlx:MonteCarloProfile_Conservative` | MC_CONSERVATIVE | 3.0% | 0.8% |
| `mrlx:MonteCarloProfile_Moderate` | MC_MODERATE | 6.0% | 1.5% |
| `mrlx:MonteCarloProfile_Aggressive` | MC_AGGRESSIVE | 10.0% | 2.5% |

#### `mrlx:TaxTreatmentScheme` *(v1.0.0)*
Used on `mrl:Account` via `mrl:taxTreatment`. Drives UI guidance only — effective rates are always user-specified. Range type class: `mrlx:TaxTreatmentType`.

| Concept | Notation | Description |
|---------|----------|-------------|
| `mrlx:TaxTreatment_PreTaxWholeWithdrawal` | TAX_PRETAX_WHOLE | Contributions pre-tax; full withdrawal is taxable income. Examples: 401(k), SIPP |
| `mrlx:TaxTreatment_PostTaxGainsOnly` | TAX_POSTTAX_GAINS | Contributions post-tax; only gains are taxable. Examples: GIA, brokerage |
| `mrlx:TaxTreatment_PostTaxTaxFreeWithdrawal` | TAX_POSTTAX_FREE | Contributions post-tax; withdrawals fully exempt. Examples: ISA, Roth IRA |
| `mrlx:TaxTreatment_TaxFree` | TAX_FREE | No tax at any stage. Examples: Premium Bonds, NS&I |

#### `mrlx:DrawdownStrategyScheme` *(v1.0.0)*
Used on `mrl:ProjectionSettings` via `mrl:drawdownStrategy`. Range type class: `mrlx:DrawdownStrategyType`.

| Concept | Notation | Description |
|---------|----------|-------------|
| `mrlx:DrawdownStrategy_Waterfall` | DRAW_WATERFALL | Drain lowest-priority-numbered eligible account first, then next |
| `mrlx:DrawdownStrategy_Proportional` | DRAW_PROPORTIONAL | Draw from all eligible accounts simultaneously by `drawdownRatio` |

#### `mrlx:SurplusStrategyScheme` *(v1.0.0)*
Used on `mrl:ProjectionSettings` via `mrl:surplusStrategy`. Range type class: `mrlx:SurplusStrategyType`.

| Concept | Notation | Description |
|---------|----------|-------------|
| `mrlx:SurplusStrategy_SweepToAccount` | SURPLUS_SWEEP | Unspent drawdown swept to `mrl:surplusAccount` |
| `mrlx:SurplusStrategy_ReduceDrawdown` | SURPLUS_REDUCE | Drawdown reduced proportionally; money stays invested |

---

## Version history

| Version | Date | Changes |
|---------|------|---------|
| 0.9.0 | 2026-05-16 | Initial release with Person, IncomeSource, CashAccount, InvestmentAccount, BudgetLine, LifeEvent, ProjectionSettings, Monte Carlo profiles, COL adjustment |
| 0.9.1 | 2026-05-17 | ADR-010: CreditCardAccount, PropertyAsset, isLiability, CreditCardAccountType SKOS concepts |
| 1.0.0 | 2026-05-17 | ADR-011/012/013: drawdown eligibility properties, drawdown and surplus strategies, spending/surplus account links, life event account links, tax treatment model (TaxTreatmentScheme, effectiveWithdrawalTaxRate, annualTaxFreeWithdrawal), residence-level tax properties on ProjectionSettings, standardPersonalAllowance on Jurisdiction |