# ADR-009: Investment account model and Monte Carlo simulation design

**Date:** 2026-05-16  
**Status:** Implemented

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
    ├── mrlx:InvestmentAccountType_StocksShares
    ├── mrlx:InvestmentAccountType_TaxAdvantaged
    ├── mrlx:InvestmentAccountType_Pension
    ├── mrlx:InvestmentAccountType_UnitTrust
    ├── mrlx:InvestmentAccountType_Bonds
    └── mrlx:InvestmentAccountType_Other
```

---

## Decision 3: Monte Carlo simulation with named profiles

**Decision:** Monte Carlo simulation is implemented with three named profiles — Conservative, Moderate, and Aggressive — each defining a standard deviation for annual returns and inflation. 500 simulations are run per projection. The UI shows the median outcome, a 10th–90th percentile confidence band, and the probability of not running out of money before life expectancy.

The named profiles are declared as `mrlx:` individuals in the ontology so their parameters can be adjusted without code changes.

### Profile parameters as implemented

| Profile | Return σ | Inflation σ |
|---------|----------|-------------|
| `mrlx:MonteCarloProfile_Conservative` | 3.0% | 0.8% |
| `mrlx:MonteCarloProfile_Moderate` | 6.0% | 1.5% |
| `mrlx:MonteCarloProfile_Aggressive` | 10.0% | 2.5% |

Parameters are stored on the named individuals as `mrlx:returnVolatility` and `mrlx:inflationVolatility` datatype properties so they can be updated in the TTL without touching Python code.

**Number of simulations:** 500. This gives statistically stable percentile bands for a personal finance application without noticeable performance impact on modest hardware.

**Variables randomised per year:**
- Annual return rate: drawn from N(weighted_rate, returnVolatility). `weighted_rate` is the blended weighted average return across all cash and investment accounts.
- Annual inflation: drawn from N(inflation_rate, inflationVolatility). Applied to all budget lines without an individual rate.

**Variables held fixed per simulation run:**
- Income growth rates (per income source)
- Individual budget line growth rates (where set by the user)
- Life events (deterministic — a known expenditure in a known year)
- Non-reinvested dividend income (grows at the investment account's capital growth rate, not perturbed)

**Rationale for named profiles over user-defined parameters:** Monte Carlo parameters are not intuitive for most users. Named profiles with meaningful labels communicate the scenario clearly without requiring financial modelling knowledge. Users who want fine-grained control can edit the TTL directly.

---

## Decision 4: Retirement jurisdiction

`mrl:plansToRetireIn` is added as an object property on `mrl:Person`, pointing to a `mrl:Jurisdiction` individual. From the retirement year onward, the projection engine applies a cost-of-living adjustment by computing `retire_col / current_col` where each COL value comes from `mrl:costOfLivingIndex` on the respective jurisdiction.

`mrl:costOfLivingIndex` (indexed to UK = 1.00) is added to `mrl:Jurisdiction` and populated for all seed jurisdiction individuals. If `plansToRetireIn` is absent or identical to `residesIn`, no adjustment is applied.

---

## Build order (as implemented)

1. Budget start/stop dates
2. Retirement jurisdiction
3. Investment accounts
4. Monte Carlo

Note: the build order differs from the order listed in the original ADR. Retirement jurisdiction was moved earlier as it was a simpler, self-contained change that improved the projection engine before the more complex investment account work.

---

## Implementation notes (divergences from original design)

The following aspects of the implementation differ from what was originally specified. These are recorded here for traceability.

**Profile names:** The original ADR specified Pessimistic / Conservative / Optimistic. The implemented names are Conservative / Moderate / Aggressive. This better reflects what the profiles actually model (market volatility scenarios) and avoids the negative connotation of "Pessimistic" as a label users interact with.

**Profile parameters:** The original ADR specified mean return rates per profile (e.g. Conservative growth mean = 5%). The implementation does not override mean return rates — it only adds volatility (standard deviation) around the user's own account rates. This is a deliberate simplification: overriding the mean would conflict with the rates the user has already entered on their accounts. The profiles control uncertainty only, not the central expectation.

**InvestmentAccountType subtypes:** The original ADR listed `StocksAndShares`, `ISA`, `PensionPot`, `Bonds`, `Other`. The implemented subtypes are `StocksShares`, `TaxAdvantaged`, `Pension`, `UnitTrust`, `Bonds`, `Other`. `TaxAdvantaged` and `UnitTrust` replace `ISA` and the ISA-specific naming to keep the vocabulary jurisdiction-neutral (covering UK ISAs, US Roth IRAs, Canadian TFSAs, etc.).

**numpy dependency:** The Monte Carlo engine uses numpy for random number generation and percentile calculation. This is not mentioned in the original ADR. Added to `requirements.txt` as an unpinned dependency.

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
