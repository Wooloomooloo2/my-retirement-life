# ADR-010 — Sister app ontology sharing strategy

**Date:** 2026-05-17
**Status:** Accepted

---

## Context

A second application in the same suite — **My Finance Life (MFL)** — is being built using the identical tech stack (Python 3.13, FastAPI, Oxigraph/pyoxigraph, HTMX, Tailwind, DaisyUI, PyInstaller). MFL is a personal finance and transaction tracking application, analogous to Quicken, with the explicit long-term goal of sharing a database with My Retirement Life so that financial events (asset purchases or sales, income changes, large expenditures) recorded in MFL can feed directly into MRL's retirement projections.

MFL needs to model many of the same concepts already defined in the MRL ontology: currencies, jurisdictions, persons, and the full account hierarchy (cash accounts, investment accounts, property assets). Designing these concepts independently in MFL would produce duplication, semantic divergence, and eventual pain when the shared-database goal is pursued.

The question is: how should the MRL ontology and MFL's data model relate to each other at this stage?

---

## Options considered

### Option 1 — Extract shared concepts to a neutral `mrl-core` library immediately

Create a new repository (`mrl-core`) with a neutral namespace (e.g. `https://mrl-suite.app/ontology#`) containing the shared concepts. Both applications depend on this library.

**Rejected** because:
- Requires renaming the existing `mrl:` namespace, which is a breaking change requiring migration of all existing MRL user data.
- Introduces a third repository and a dependency management problem before MFL has written a line of code.
- The shared concepts are not yet fully understood — extracting prematurely risks building the wrong abstraction. Both apps must be stable before the boundary is clear.

### Option 2 — Duplicate the ontology in MFL

MFL defines its own independent ontology that re-models currencies, accounts, and persons in its own namespace.

**Rejected** because:
- Duplication is the problem this decision exists to avoid.
- Two independent definitions of `Currency` or `CashAccount` will diverge over time, making the shared-database goal expensive or impossible.
- Any future extraction effort would need to reconcile two ontologies rather than simply renaming one.

### Option 3 — MFL loads and extends the MRL ontology (chosen)

MFL treats `mrl-ontology.ttl` as a shared dependency. The file is shipped alongside MFL (read-only, not modifiable by MFL) and loaded into MFL's Oxigraph store on startup into the same ontology named graph. MFL defines its own extension namespace (`mfl:` / `mflx:`) for finance-specific concepts that have no counterpart in MRL. MRL concepts are reused directly — no redefinition.

A small number of additions to `mrl-ontology.ttl` are required to support MFL's account types (see Consequences). These are committed to the MRL repository and are backward-compatible additions.

The extraction to a neutral `mrl-core` namespace is explicitly deferred until both applications are stable and the correct shared boundary is well understood.

---

## Decision

**MFL will load and extend the MRL ontology. The MRL ontology is the shared foundation.**

Specifically:

- `mrl-ontology.ttl` is the authoritative source for all shared concepts (Currency, Jurisdiction, Person, Account hierarchy, account type vocabulary, frequency vocabulary).
- MFL ships a copy of `mrl-ontology.ttl` as a read-only bundled asset. MFL never modifies this file at runtime.
- MFL defines a new ontology file (`mfl-ontology.ttl`) in its own repo under `docs/ontology/`, using namespaces `mfl: <https://myfinancelife.app/ontology#>` and `mflx: <https://myfinancelife.app/ontology/ext#>`.
- The `mfl:` ontology declares `mfl:Transaction`, `mfl:Payee`, `mfl:CategoryRule`, `mfl:ImportBatch`, and `mfl:ValuationEvent` as new classes. It reuses `mrl:Account`, `mrl:CashAccount`, `mrl:InvestmentAccount`, `mrl:PropertyAsset`, `mrl:Currency`, `mrl:Jurisdiction`, and `mrl:Person` wholesale — no redefinition.
- Both ontology files are loaded into MFL's Oxigraph store on startup, each into the same ontology named graph.
- MRL's named graph IRI (`https://myretirementlife.app/ontology/graph`) and data graph IRI (`https://myretirementlife.app/data/graph`) are reused when the shared database mode is active. In standalone mode, MFL uses its own graph IRIs.
- When the shared-database feature is implemented (future ADR), both apps point at a single Oxigraph store. No data migration is required because shared concepts already use `mrl:` IRIs in both apps.

---

## Consequences

### Additions to `mrl-ontology.ttl` (this repository)

The following are backward-compatible additions required to support MFL's account model. They extend the existing `mrl:Account` hierarchy and `mrlx:AccountTypeScheme` SKOS scheme:

1. **`mrl:CreditCardAccount`** — a new subclass of `mrl:Account` for credit card accounts. Credit card balances (liabilities) are relevant to net worth in both MRL and MFL.
2. **`mrl:PropertyAsset`** — already declared in the class hierarchy as post-MVP; this decision promotes it to active status to support MFL's property tracking from day one. MRL will implement its own property UI in a future release.
3. **`mrlx:CreditCardAccountType`** — a new top concept in `mrlx:AccountTypeScheme` with subtypes `Standard` and `ChargeCard`, following the existing SKOS pattern.
4. **`mrl:isLiability`** — a boolean datatype property on `mrl:Account` indicating whether the account balance represents a liability (negative net worth contribution). Defaults to `false`; set to `true` on credit card accounts.

These additions are committed to the MRL repo in a minor ontology version bump (0.9.0 → 0.9.1) and require no changes to existing MRL application code.

### Responsibilities

- **MRL repo** owns `mrl-ontology.ttl`. Any change to shared concepts is committed here and the updated file is copied into MFL's bundled assets.
- **MFL repo** owns `mfl-ontology.ttl`. Changes to MFL-specific concepts are made there independently.
- A future ADR (in both repos) will govern the extraction to `mrl-core` and namespace migration when the time is right.

### ADR index update required

Add the following row to the ADR index in `docs/adr/README.md`:

```
| [ADR-010](ADR-010-sister-app-ontology-sharing-strategy.md) | Sister app ontology sharing strategy | 2026-05-17 | Accepted |
```

And add a summary paragraph to the Summaries section.
