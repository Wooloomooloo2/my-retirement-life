# ADR-009: Investment account model and Monte Carlo simulation design

**Date:** 2026-05-16  
**Status:** Accepted

---

## Context

The next major feature release adds investment accounts to the financial picture. Unlike cash accounts (which earn a fixed interest rate on a known balance), investment accounts carry variable returns, may generate income separately from growth, and introduce uncertainty into projections that a single deterministic calculation cannot capture.

Three design decisions needed to be made:

1. How to model investment accounts — as individual holdings or as pots
2. How to model investment returns in the projection engine
3. How to communicate projection uncertainty to the user

---

## Decision 1: Investment accounts as pots

**Decision:** Each investment account is modelled as a single pot with aggregate growth and income rates, not as a collection of individual holdings.

Individual holding tracking (stock X at price Y, fund Z with N units) is deferred to a future release. For the initial investment account feature, each account has:

- A current balance and balance date
- An annual growth rate % (capital appreciation)
- An annual dividend/income rate % (income distributed from the pot)
- A reinvest dividends flag — if true, dividends compound into the pot; if false, they flow as income into the projection's annual cashflow

**Rationale:** Most users think about their investments in aggregate terms ("my ISA is worth £80k and returns about 7% a year"). Individual holding tracking adds significant complexity — price feeds, unit tracking, corporate actions — that is out of scope for the current release and would add friction to the setup experience.

**Future path:** `mrl:InvestmentAccount` is already declared as a subclass of `mrl:Account`. Individual holdings will be modelled as a new `mrl:Holding` class linked to `mrl:InvestmentAccount` in a future release. The pot-level rates on `mrl:InvestmentAccount` will become derived/override values at that point.

**Drawdown:** Investment accounts are included in the total pot proportionally alongside cash accounts in MVP. `mrl:drawdownPriority` is already declared on `mrl:Account` for when user-defined drawdown ordering is implemented.

---

## Decision 2: Investment account ontology properties

The following properties are added to `mrl:InvestmentAccount`:

| Property | Type | Description |
|----------|------|-------------|
| `mrl:annualGrowthRate` | `xsd:decimal` | Expected annual capital appreciation as a percentage |
| `mrl:annualDividendRate` | `xsd:decimal` | Expected annual income/dividend yield as a percentage |
| `mrl:reinvestDividends` | `xsd:boolean` | If true, dividends compound into the pot; if false, treated as annual income |

A new `mrlx:InvestmentAccountType` SKOS concept scheme is added as a sibling top concept to `mrlx:CashAccountType` within `mrlx:AccountTypeScheme`:

```
mrlx:AccountTypeScheme
├── mrlx:CashAccountType (existing)
└── mrlx:InvestmentAccountType (new)
    ├── mrlx:InvestmentAccountType_StocksAndShares
    ├── mrlx:InvestmentAccountType_ISA
    ├── mrlx:InvestmentAccountType_PensionPot (DC pension)
    ├── mrlx:InvestmentAccountType_Bonds
    └── mrlx:InvestmentAccountType_Other
```

---

## Decision 3: Monte Carlo simulation with named profiles

**Decision:** Monte Carlo simulation is implemented with three named profiles — Pessimistic, Conservative, and Optimistic — each defining a mean and standard deviation for annual growth rate and inflation rate. 500 simulations are run per projection. The UI shows the median outcome, a 10th–90th percentile confidence band, and the probability of not running out of money before life expectancy.

The named profiles are declared as `mrlx:` individuals in the ontology so their parameters can be adjusted without code changes.

### Initial profile parameters

| Profile | Growth rate mean | Growth rate σ | Inflation mean | Inflation σ |
|---------|-----------------|---------------|----------------|-------------|
| `mrlx:MonteCarloProfile_Pessimistic` | 3% | 4% | 5.5% | 0.5% |
| `mrlx:MonteCarloProfile_Conservative` | 5% | 3% | 3.0% | 0.5% |
| `mrlx:MonteCarloProfile_Optimistic` | 8% | 3% | 2.0% | 0.5% |

Parameters are stored on the named individuals as datatype properties so they can be updated in the TTL without touching Python code.

**Number of simulations:** 500. This gives statistically stable percentile bands for a personal finance application without noticeable performance impact on modest hardware.

**Variables randomised per year:**
- Annual investment return (drawn from a normal distribution around the account's growth rate, with σ from the selected profile)
- Annual inflation (applied to all budget lines without an individual rate, drawn from a normal distribution)

**Variables held fixed per simulation run:**
- Income growth rates (per income source)
- Individual budget line growth rates (where set by the user)
- Life events (deterministic — a known expenditure in a known year)

**Rationale for named profiles over user-defined parameters:** Monte Carlo parameters are not intuitive for most users. Named profiles with meaningful labels (Pessimistic, Conservative, Optimistic) communicate the scenario clearly without requiring financial modelling knowledge. Users who want fine-grained control can edit the TTL directly.

---

## Decision 4: Retirement jurisdiction

`mrl:plansToRetireIn` is added as an object property on `mrl:Person`, pointing to a `mrl:Jurisdiction` individual. From the retirement year onward, the projection engine uses the target jurisdiction's default currency for display purposes and optionally applies a cost-of-living differential.

A `mrl:costOfLivingIndex` datatype property is added to `mrl:Jurisdiction` (indexed to UK = 100) to support this calculation. This property is populated for common jurisdictions as seed data.

---

## Build order

1. Budget start/stop dates — small ontology addition, completes income/budget symmetry
2. Investment accounts — main feature, new UI screen and projection engine update
3. Monte Carlo — builds on top of investment account projection
4. Retirement jurisdiction — self-contained addition to profile and projection engine

---

## Consequences

**Positive**
- The pot-based model is simple to set up and covers the majority of user needs
- Named Monte Carlo profiles make uncertainty accessible to non-technical users
- All profile parameters are in the TTL — adjustable without code changes
- The `mrl:drawdownPriority` property already in the ontology is ready for when ordering is needed
- `mrl:Holding` as a future class is clearly anticipated in the design — no refactoring needed

**Trade-offs accepted**
- Pot-level rates are approximations; users with complex portfolios will get less accurate projections than individual holding tracking would provide
- Monte Carlo does not model sequence-of-returns risk (the specific order of good/bad years), only aggregate volatility — this is a known limitation
- Cost-of-living differentials are approximate; exact figures vary by lifestyle and location

**Future considerations**
- Individual holding tracking (`mrl:Holding`) as a future class
- Sequence-of-returns risk modelling
- Tax-efficient drawdown ordering (ISA before pension, etc.)
- Real-time price data integration for individual holdings
