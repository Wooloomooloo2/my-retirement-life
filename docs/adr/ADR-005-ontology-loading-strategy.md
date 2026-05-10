# ADR-005: Ontology loading strategy and named graph separation

**Date:** 2026-05-10  
**Status:** Accepted

---

## Context

The application uses an OWL ontology (defined in `docs/ontology/mrl-ontology.ttl`) as the schema for all data stored in the Oxigraph triple store. This ontology includes class definitions, property definitions, controlled vocabulary individuals (currencies, jurisdictions, employment statuses etc.), and their labels and annotations.

A strategy was needed for:
1. How and when the ontology is loaded into the store
2. How ontology triples are kept separate from user instance data
3. How the ontology can be updated during development without data loss

### Options considered

**Loading strategy options**

| Option | Notes |
|--------|-------|
| Hardcode ontology triples in Python | Ontology becomes invisible to anyone working in RDF; TTL file loses its value as a human-editable artefact |
| Load TTL on every startup | Simple, but wasteful and risks overwriting changes if the store format differs |
| Load TTL on first startup only, skip if already present | Efficient; idempotent; supports force-reload when the ontology changes |
| Separate ontology server (e.g. Fuseki) | Overkill for a single-user application; contradicts ADR-001 |

**Graph separation options**

| Option | Notes |
|--------|-------|
| All triples in the default graph | Simple, but ontology and user data become indistinguishable; difficult to reload or clear independently |
| Ontology and data in separate named graphs | Clean separation; each graph can be queried, reloaded, or cleared independently |
| Separate stores for ontology and data | Overly complex; loses the ability to join ontology and data in a single SPARQL query |

---

## Decision

**Loading strategy: load on first startup, skip if already present, support force reload**

The ontology TTL is loaded into the Oxigraph store by `src/store/ontology_loader.py` as part of the application startup sequence in `main.py`. The loader checks whether the ontology named graph already contains triples before loading. If triples are present it skips loading, making restarts efficient. A `force=True` parameter allows the ontology to be reloaded after the TTL has been edited.

**Graph separation: two named graphs**

| Named graph | IRI | Contents |
|-------------|-----|----------|
| Ontology graph | `https://myretirementlife.app/ontology/graph` | All triples from `mrl-ontology.ttl` |
| Data graph | `https://myretirementlife.app/data/graph` | User instance data created at runtime |

All SPARQL queries targeting user data use the data graph. Queries that need to join user data with ontology labels (e.g. to resolve a currency symbol from a currency IRI) query both graphs explicitly.

**TTL as the authoritative source**

The `.ttl` file in `docs/ontology/` is the authoritative definition of the ontology. It is version-controlled alongside the application code. Changes to the ontology are made in the TTL first, then reloaded into the store. Python code never defines ontology structure — it only loads what the TTL declares.

---

## Consequences

**Positive**
- The TTL file remains a first-class, human-readable, editable artefact — accessible to anyone who understands RDF without needing to read Python
- Ontology triples and user data triples are cleanly separated and independently queryable
- The ontology can be reloaded after changes without touching user data
- The idempotent loader means application restarts are fast — the ontology is not re-parsed on every startup
- A diagnostic endpoint (`/ontology/status`) provides runtime verification that the ontology loaded correctly

**Trade-offs accepted**
- SPARQL queries that join ontology labels with user data must reference both named graphs explicitly — slightly more verbose than querying a single default graph
- If the ontology TTL changes significantly (e.g. a class is renamed), a migration strategy will be needed for existing user data — this is deferred until the data model stabilises post-MVP
- The force-reload mechanism is currently only accessible programmatically; a future admin UI endpoint would make this more accessible

**Ongoing discipline**
- All ontology changes must be made in the TTL first
- After editing the TTL, the store must be force-reloaded for changes to take effect in a running instance
- New classes and properties added to the TTL do not affect existing user data and do not require migration
