# ADR-007: Data access patterns — quad patterns vs SPARQL

**Date:** 2026-05-11  
**Status:** Accepted

---

## Context

Oxigraph (via the `pyoxigraph` library) supports two mechanisms for reading data from the store:

1. **SPARQL SELECT queries** — full W3C SPARQL 1.1 query language, supporting filtering, joining, aggregation, graph traversal, and named graph targeting
2. **Quad pattern matching** — direct low-level access via `store.quads_for_pattern(subject, predicate, object, graph)`, where any parameter can be `None` to act as a wildcard

During development of the profile screen, SPARQL SELECT queries were used initially to read back known instance data (e.g. fetching all properties of `mrl:Person_1`). These queries failed silently because Oxigraph's SPARQL engine performed strict datatype matching on literals — values written as plain string literals (e.g. `"88"`) did not match SPARQL variable bindings expecting typed literals (e.g. `"88"^^xsd:integer`).

Quad pattern matching bypassed this issue entirely by reading triples directly without type coercion, returning raw values that the Python layer then handles.

This experience established a clear pattern for when to use each mechanism.

---

## Decision

**Writes: always SPARQL UPDATE**

All data writes use SPARQL UPDATE (`INSERT DATA`, `DELETE WHERE`, `DELETE/INSERT`). This is the standard, expressive, and well-understood mechanism for modifying RDF stores.

**Reads: quad patterns for known instances, SPARQL SELECT for queries**

| Scenario | Mechanism | Reason |
|----------|-----------|--------|
| Fetch all properties of a known IRI (e.g. `mrl:Person_1`) | `quads_for_pattern` | Direct, fast, no datatype matching issues, no query parser overhead |
| Find instances matching criteria (e.g. all cash accounts owned by Person_1) | SPARQL SELECT | Filtering and joining require query language expressiveness |
| Aggregate values (e.g. sum all budget lines) | SPARQL SELECT | Aggregation functions require SPARQL |
| Traverse relationships (e.g. account → currency → symbol) | SPARQL SELECT | Multi-hop joins require SPARQL |
| Check existence of a known IRI | `quads_for_pattern` | Single pattern check, no query overhead |
| Projection calculations (burndown chart data) | SPARQL SELECT | Complex multi-join queries spanning multiple classes |

**Datatype handling**

To avoid future datatype matching issues in SPARQL queries, numeric and boolean values written via SPARQL UPDATE should use explicit XSD datatype annotations:

```sparql
mrl:targetRetirementAge "67"^^xsd:integer ;
mrl:annualAmount "45000.00"^^xsd:decimal ;
mrl:isNetOfTax "true"^^xsd:boolean ;
```

Plain untyped literals should be reserved for string values only.

**Reusable access utilities**

The quad pattern read approach is encapsulated in reusable helper functions within each route module, following the pattern established in `src/api/routes/profile.py`:

```python
def get_val(prop: str) -> str:
    quads = list(store.store.quads_for_pattern(
        subject_iri, og.NamedNode(f"{MRL}{prop}"), None, DATA_GRAPH))
    return str(quads[0].object.value) if quads else ""
```

---

## Consequences

**Positive**
- Quad pattern reads are reliable regardless of how literals were stored — no silent failures from datatype mismatches
- SPARQL UPDATE remains for all writes — the full expressiveness of the update language is preserved
- SPARQL SELECT is reserved for scenarios where it genuinely adds value (filtering, aggregation, traversal)
- The pattern is simple and consistent — developers know which mechanism to reach for in each scenario

**Trade-offs accepted**
- Quad pattern reads are more verbose than a single SPARQL SELECT for fetching multiple properties of one subject
- The datatype annotation discipline for SPARQL writes must be maintained consistently — inconsistent typing will cause issues in future SPARQL SELECT queries that filter or compare values

**Ongoing discipline**
- All new SPARQL UPDATE statements must use explicit XSD datatype annotations for numeric and boolean values
- Existing writes that used untyped literals (the initial profile save) should be noted as technical debt and corrected when the data model stabilises
