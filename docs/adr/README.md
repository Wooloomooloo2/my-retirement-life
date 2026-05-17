# Architecture Decision Records

This directory contains the Architecture Decision Records (ADRs) for **My Retirement Life**. ADRs capture significant technical and architectural decisions made during the project, including the context that motivated them, the options considered, and the consequences of the decision taken.

---

## What is an ADR?

An Architecture Decision Record is a short document that captures a single architectural decision. Each ADR records:
- **Context** — the situation or problem that required a decision
- **Options considered** — the alternatives evaluated
- **Decision** — what was decided and why
- **Consequences** — the positive outcomes, trade-offs accepted, and ongoing responsibilities

ADRs are written at the time a decision is made and are not retrospective documents. Once accepted, an ADR is not edited to reflect subsequent changes — instead, a new ADR is written that supersedes or amends it.

---

## Index

| ADR | Title | Date | Status |
|-----|-------|------|--------|
| [ADR-001](ADR-001-backend-language-and-triple-store.md) | Backend language and triple store | 2026-05-09 | Accepted |
| [ADR-002](ADR-002-packaging-strategy.md) | Packaging strategy | 2026-05-09 (updated 2026-05-14) | Accepted |
| [ADR-003](ADR-003-frontend-stack.md) | Frontend stack | 2026-05-09 | Accepted |
| [ADR-004](ADR-004-cross-platform-portability.md) | Cross-platform portability approach | 2026-05-09 | Accepted |
| [ADR-005](ADR-005-ontology-loading-strategy.md) | Ontology loading strategy and named graph separation | 2026-05-10 | Accepted |
| [ADR-006](ADR-006-instance-iri-naming-strategy.md) | Instance IRI naming strategy | 2026-05-10 | Accepted |
| [ADR-007](ADR-007-data-access-patterns.md) | Data access patterns — quad patterns vs SPARQL | 2026-05-11 | Accepted |
| [ADR-008](ADR-008-multiple-income-sources.md) | Multiple income sources with independent start/end dates in MVP | 2026-05-14 | Accepted |
| [ADR-009](ADR-009-investment-accounts-and-monte-carlo.md) | Investment account model and Monte Carlo simulation design | 2026-05-16 | Implemented |
| [ADR-010](ADR-010-sister-app-ontology-sharing-strategy.md) | Sister app ontology sharing strategy | 2026-05-17 | Accepted |
| [ADR-011](ADR-011-per-account-drawdown-eligibility-ordering-and-surplus.md) | Per-account drawdown eligibility, ordering, and surplus handling | 2026-05-17 | Accepted |
| [ADR-012](ADR-012-per-account-balance-tracking-and-monte-carlo-scope.md) | Per-account balance tracking and revised Monte Carlo scope | 2026-05-17 | Accepted |
| [ADR-013](ADR-013-generic-tax-treatment-model.md) | Generic tax treatment model for accounts and withdrawals | 2026-05-17 | Accepted |

---

## Summaries

### ADR-001 — Backend language and triple store
Selects **Python** as the backend language and **Oxigraph** (via `pyoxigraph`) as the embedded triple store. Oxigraph runs inside the Python process with no separate server, has a very low memory footprint suitable for older consumer hardware, and is fully SPARQL 1.1 compliant. The API layer uses **FastAPI**. Apache Jena Fuseki was rejected due to its JVM memory footprint; RDFLib was rejected as not production-grade for persistent storage.

### ADR-002 — Packaging strategy
Defines the distribution approach for non-technical end users across all three target platforms: **Windows** (PyInstaller → `.exe`), **macOS** (PyInstaller → `.app` bundle), and **Linux** (PyInstaller → AppImage via appimagetool). A single build toolchain (PyInstaller) produces all platform targets. macOS was added as a target platform after initial design, reflecting the disproportionate representation of Apple hardware among the target demographic. Unsigned macOS builds will show a Gatekeeper warning on first launch until code signing is implemented for v1.0.

### ADR-003 — Frontend stack
Selects **HTMX + Tailwind CSS + DaisyUI** as the frontend stack. HTMX enables server-driven UI updates from the FastAPI backend without a JavaScript build pipeline. DaisyUI provides a complete component library including built-in light/dark theming. **Chart.js** (CDN) is used for data visualisation. React and Vue were rejected as requiring a separate build toolchain and JavaScript codebase inconsistent with the project's maintainability goals.

### ADR-004 — Cross-platform portability approach
Defines the engineering practices that enforce Windows/Linux/macOS portability throughout the codebase: `pathlib.Path` for all file path construction, `platformdirs` for OS-appropriate data directories, `.gitattributes` enforcing LF line endings, `python-dotenv` for configuration, and a prohibition on platform-specific runtime dependencies. A `devcontainer.json` is provided for optional Linux development on Windows.

### ADR-005 — Ontology loading strategy and named graph separation
Defines how the OWL ontology (`docs/ontology/mrl-ontology.ttl`) is loaded into the Oxigraph store: on first startup only (skipped if already present), with a `force=True` option for reloading after edits. Two named graphs separate ontology triples from user instance data: `https://myretirementlife.app/ontology/graph` and `https://myretirementlife.app/data/graph`. The `.ttl` file is the authoritative source; Python code never defines ontology structure.

### ADR-006 — Instance IRI naming strategy
All user-created instance IRIs follow the pattern **`mrl:ClassName_N`** where N is a simple incrementing integer (e.g. `mrl:Person_1`, `mrl:CashAccount_2`). The next N is determined by querying the store for the highest existing N for that class. This is consistent across all instance types, human-readable in SPARQL and logs, and free of collision risk. UUID-based IRIs are noted as a future privacy option.

### ADR-007 — Data access patterns — quad patterns vs SPARQL
Establishes a clear split between the two Oxigraph read mechanisms: **`quads_for_pattern`** (quad pattern matching) is used for fetching all properties of a known IRI (e.g. `mrl:Person_1`) and checking existence, as it is reliable regardless of how literals were stored and avoids datatype matching failures in SPARQL. **SPARQL SELECT** is reserved for filtering, aggregation, multi-hop traversal, and projection calculations. All writes use **SPARQL UPDATE** with explicit XSD datatype annotations on numeric and boolean values.

### ADR-008 — Multiple income sources with independent start/end dates in MVP
Extends the MVP from a single Employment income source to **multiple income sources with independent start and end years**, managed via a dedicated `/income` screen. This was necessary to accurately model common retirement income patterns: employment stopping at retirement while rental, partner, state pension, and part-time income continue on their own timelines. The ontology's `mrl:IncomeSource` class was already designed for this; only the application layer needed to be built. A bug was also fixed: `mrl:incomeEndYear` was previously stored as an age rather than a calendar year.

### ADR-009 — Investment account model and Monte Carlo simulation design
Adds **investment accounts** modelled as aggregate pots (current balance, annual growth rate %, annual dividend rate %, reinvest dividends flag) rather than individual holdings. Introduces **Monte Carlo simulation** with three named profiles — Conservative, Moderate, and Aggressive — each defining a standard deviation for annual returns and inflation; 500 simulations are run per projection. Profile parameters are stored as `mrlx:` individuals in the ontology TTL, adjustable without code changes. Also adds `mrl:plansToRetireIn` on `mrl:Person` for cost-of-living adjustment from the retirement year onward. `numpy` is added as a dependency for random number generation and percentile calculation.

### ADR-010 — Sister app ontology sharing strategy
Establishes how the companion application **My Finance Life (MFL)** — a Quicken-like personal finance and transaction tracker built on the identical tech stack — relates to the MRL ontology. MFL loads `mrl-ontology.ttl` as a read-only bundled dependency and defines its own extension ontology (`mfl-ontology.ttl`) for finance-specific concepts (`mfl:Transaction`, `mfl:Payee`, etc.), reusing `mrl:Account`, `mrl:CashAccount`, `mrl:InvestmentAccount`, `mrl:Currency`, `mrl:Person` and others directly. Extraction to a neutral `mrl-core` namespace is explicitly deferred until both applications are stable. As a consequence, the MRL ontology was updated to v0.9.1 with four backward-compatible additions to support MFL: `mrl:CreditCardAccount` (new subclass of `mrl:Account`), `mrl:PropertyAsset` (promoted from stub to active class), `mrl:isLiability` (boolean property on `mrl:Account`), and `mrlx:CreditCardAccountType` with subtypes `Standard` and `ChargeCard`.

### ADR-011 — Per-account drawdown eligibility, ordering, and surplus handling
Replaces the v0.2 assumption that all accounts are equally and immediately available for drawdown. Each account now carries eligibility constraints — mrl:drawdownMinAge, mrl:drawdownMaxAge, mrl:drawdownEarliestDate, and mrl:drawdownLatestDate — so the projection engine can exclude accounts until they are legally or contractually accessible (e.g. a UK pension before age 57, a fixed-term bond before maturity). Two drawdown strategies are introduced via mrlx:DrawdownStrategyScheme: Waterfall, which drains accounts in priority order and is suited to tax-sequencing strategies, and Proportional, which draws simultaneously from all eligible accounts by ratio. A mrl:spendingAccount on mrl:ProjectionSettings designates where drawn cash lands, and a mrl:surplusStrategy determines what happens when spending is below budget in a given year — either sweep the underspend to a nominated mrl:surplusAccount, or reduce drawdown so unspent funds remain invested. Life events gain mrl:fundedByAccount and mrl:receivedByAccount links so expenditures and windfalls can be directed to specific accounts rather than the general pool.

### ADR-012 — Per-account balance tracking and revised Monte Carlo scope
Supersedes the ADR-009 single-pool approach for the deterministic projection engine. Each account's balance is now tracked as an independent scalar per year, enabling per-account chart visibility and correct application of the drawdown eligibility and strategy rules introduced in ADR-011. The Monte Carlo simulation is narrowed from the entire blended balance to the investment account pool only: cash accounts have predictable interest rates and do not warrant equity-style volatility modelling. Total projected balance is therefore the sum of a deterministic cash trajectory and the P10/P50/P90 investment band. The projection chart gains a By Account stacked area view alongside the existing aggregate view, and a secondary per-account chart plots annual drawdown against annual return to make the break-even crossover visible. The ADR-009 weighted return rate approach is retained for the investment pool mean return (μ), with the profile σ applied around it in the simulation loop.

### ADR-013 — Generic tax treatment model for accounts and withdrawals
Introduces a two-layer tax model without encoding jurisdiction-specific tax law, which would require annual maintenance and is outside the scope of a personal planning tool. The first layer is account-level: each account carries mrl:effectiveWithdrawalTaxRate (the rate the user expects to pay at source, after any treaty relief) and mrl:annualTaxFreeWithdrawal (an annual tax-free allowance, covering instruments such as the UK pension PCLS equivalent). The second layer is residence-level, on mrl:ProjectionSettings: mrl:annualPersonalAllowance and mrl:residenceIncomeTaxRate capture the user's aggregate income threshold and marginal rate in their country of residence. The engine deducts source tax at point of withdrawal, aggregates taxable income across all accounts for the year, then applies or refunds residence-level tax against the personal allowance. A mrlx:TaxTreatmentScheme with four structural concepts — PreTaxWholeWithdrawal, PostTaxGainsOnly, PostTaxTaxFreeWithdrawal, and TaxFree — drives UI guidance and tooltips without being used directly in the calculation. Cost basis tracking for GIA accounts is deferred to the sister application (My Financial Life).

---

## Status values

| Status | Meaning |
|--------|---------|
| **Proposed** | Under discussion; not yet decided |
| **Accepted** | Decision made and adopted; the approach described is in effect |
| **Implemented** | Accepted and fully built; implementation notes may record divergences from the original design |
| **Superseded** | Replaced by a later ADR; kept for historical reference |
| **Deprecated** | No longer applicable but not replaced by a specific decision |

---

## Adding a new ADR

1. Copy the filename pattern: `ADR-NNN-short-description-of-decision.md`
2. Use the next available number in sequence
3. Fill in Context, Options considered, Decision, and Consequences
4. Set status to `Proposed` until the decision is agreed
5. Add a row to the index table and a summary paragraph above
6. Once agreed, update status to `Accepted`
