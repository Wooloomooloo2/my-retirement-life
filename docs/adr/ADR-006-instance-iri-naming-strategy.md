# ADR-006: Instance IRI naming strategy

**Date:** 2026-05-10  
**Status:** Accepted

---

## Context

The ontology defines a consistent pattern for reference individuals (`mrl:Currency_GBP`, `mrl:Jurisdiction_GB` etc.) and controlled vocabulary individuals (`mrlx:EmploymentStatus_Employed` etc.). A separate pattern was needed for user-created instance data — the `mrl:Person`, `mrl:CashAccount`, `mrl:IncomeSource` and similar instances created at runtime when a user enters their data.

Several approaches were considered.

### Options considered

| Option | Example | Notes |
|--------|---------|-------|
| UUID | `mrl:Person_a3f9b2c1...` | Globally unique, opaque. Hard to read in SPARQL, logs, or the TTL. Defeats the principle of human-readable IRIs. |
| Name-derived slug | `mrl:BudgetLine_Mortgage` | Readable and self-describing. Requires slugification of user input (stripping special characters, replacing spaces). Risk of collision if user creates two items with similar names. |
| Type + sequence number | `mrl:IncomeSource_Employment_1` | More descriptive than plain sequence but inconsistent across classes — some have a natural type qualifier, others don't. |
| Simple sequence number | `mrl:Person_1`, `mrl:CashAccount_2` | Consistent across all classes. Readable. Predictable. Easy to generate and query. |

---

## Decision

**All user-created instance IRIs follow the pattern `mrl:ClassName_N`**, where N is a simple incrementing integer starting at 1.

Examples:

| IRI | Represents |
|-----|-----------|
| `mrl:Person_1` | The single user profile (MVP is single-user) |
| `mrl:IncomeSource_1` | First income source |
| `mrl:IncomeSource_2` | Second income source |
| `mrl:CashAccount_1` | First cash account |
| `mrl:BudgetLine_1` | First budget line item |
| `mrl:LifeEvent_1` | First life event |
| `mrl:ProjectionSettings_1` | First projection settings instance |

The integer N is determined at creation time by querying the store for the highest existing N for that class and incrementing by 1. This is handled by a reusable utility function in `src/store/graph.py`.

The SPARQL pattern for determining the next N is:

```sparql
PREFIX mrl: <https://myretirementlife.app/ontology#>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>

SELECT (MAX(?n) AS ?maxN)
WHERE {
    GRAPH <https://myretirementlife.app/data/graph> {
        ?s a mrl:CashAccount .
        BIND(xsd:integer(STRAFTER(STR(?s), "CashAccount_")) AS ?n)
    }
}
```

If no instances exist yet, MAX returns no result and N defaults to 1.

---

## Consequences

**Positive**
- Completely consistent pattern across all instance types — no special cases
- IRIs are human-readable in SPARQL queries, log output, and the TTL
- Simple to generate programmatically — no slugification, no collision risk
- Easy to reason about in development and debugging
- Consistent with the readable IRI principle established for reference individuals

**Trade-offs accepted**
- IRIs are not globally unique — two installations of the app will both have `mrl:Person_1`. This is acceptable for a single-user local application where data from different installations is never merged
- If records are deleted, the sequence numbers will have gaps (e.g. `mrl:CashAccount_1`, `mrl:CashAccount_3` if 2 was deleted). This is cosmetic and does not affect correctness
- If the application ever moves to multi-user or data sharing, IRIs would need to be migrated to a globally unique scheme — this is noted as a future consideration but is not in scope

**Future consideration**
- The application will offer an option to use opaque (non-readable) IRIs as a privacy/security feature, as noted in the product roadmap. When enabled, this would generate IRIs using a hash or UUID instead of the readable pattern. The switch would be a configuration option and would apply to new instances only.
