# ADR-001: Backend language and triple store

**Date:** 2026-05-09
**Status:** Accepted

---

## Context

My Retirement Life requires a backend capable of storing and querying richly interconnected personal data — life events, financial projections, health milestones, housing plans, and the relationships between them. The project lead has a professional background in knowledge graphs, RDF triple stores, and ontology design, making a semantic data model a natural fit for the domain.

The backend must:
- Run reliably on modest consumer hardware, including machines 10 or more years old with limited RAM
- Operate on both Windows and Linux without platform-specific code
- Be packageable into a single distributable without requiring the user to install a database server separately
- Be built on technology with a credible long-term support horizon

Several backend language and triple store combinations were evaluated.

### Options considered

**Language options**

| Option | Notes |
|--------|-------|
| Python | Cross-platform, mature, large ecosystem, strong RDF library support via RDFLib. Widely used in data and ontology tooling. |
| .NET (C#) | Cross-platform on .NET 8+, strong typing, but heavier runtime; less natural fit for RDF ecosystem. |
| Node.js | Cross-platform, but RDF ecosystem is thin compared to Python; less familiar to the team. |

**Triple store options**

| Option | Notes |
|--------|-------|
| Apache Jena Fuseki | Mature, feature-rich, SPARQL 1.1 compliant. Runs on JVM — high memory footprint, unsuitable for modest hardware. Requires a separate server process. |
| Oxigraph | Written in Rust, very low memory footprint, fast startup, embeddable via `pyoxigraph` Python library. No separate server process required. SPARQL 1.1 compliant. |
| RDFLib (file-backed) | Pure Python, lightweight, but slow for complex queries and not production-grade for persistent storage. |

---

## Decision

**Backend language: Python**
**Triple store: Oxigraph, embedded via the `pyoxigraph` library**

Python is selected for its cross-platform maturity, strong alignment with the RDF/ontology ecosystem (RDFLib, pyoxigraph), and the team's familiarity with data modelling concepts that map naturally to Python's data handling model.

Oxigraph is selected as the triple store because it can be embedded directly into the Python process via `pyoxigraph`, eliminating the need for a separate database server. This is critical for the packaging requirement (see ADR-002). Its Rust-based implementation gives it a very small memory footprint suitable for older consumer hardware. It is fully SPARQL 1.1 compliant, preserving the ability to use standard W3C query patterns throughout the application.

The API layer will use **FastAPI**, which provides a clean, async-capable HTTP interface between the triple store and the frontend.

---

## Consequences

**Positive**
- No database server for the user to install, configure, or manage
- Low memory and CPU footprint at rest — suitable for machines with 4GB RAM
- SPARQL 1.1 compliance means queries are portable to other triple stores if requirements grow
- Python's open-source ecosystem ensures long-term maintainability
- The data model can be grounded in a formal OWL ontology from the outset, enabling future interoperability with the companion app My Financial Life

**Trade-offs accepted**
- Oxigraph is a smaller project than Apache Jena; it warrants monitoring for ongoing maintenance activity
- For very large data volumes or multi-user deployment, a standalone triple store server would be preferable — this is not a requirement for the current scope (single-user, personal data)
- Python's Global Interpreter Lock (GIL) limits true parallelism, though this is not a concern for a single-user desktop application

**Future considerations**
- If the app later requires multi-user or networked deployment, the architecture can be migrated to a standalone Oxigraph server or Apache Jena without changing the SPARQL query layer
- The ontology design should be documented separately and versioned in `/docs/ontology/`
