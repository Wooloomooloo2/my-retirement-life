# Architecture Decision Records

This directory contains the Architecture Decision Records (ADRs) for My Retirement Life.

ADRs capture significant architectural decisions made during the project, including the context that motivated them, the options considered, and the rationale for the chosen approach. They are intended to be read by future contributors (and future us) to understand *why* the project is built the way it is, not just *how*.

## Format

Each ADR follows the structure:
- **Status** — Proposed / Accepted / Deprecated / Superseded
- **Context** — The situation or problem that prompted the decision
- **Decision** — What was decided
- **Consequences** — What the decision means going forward, including trade-offs accepted

## Index

| ID | Title | Status |
|----|-------|--------|
| [ADR-001](ADR-001-backend-language-and-triple-store.md) | Backend language and triple store | Accepted |
| [ADR-002](ADR-002-packaging-strategy.md) | Packaging strategy | Accepted |
| [ADR-003](ADR-003-frontend-stack.md) | Frontend stack | Accepted |
| [ADR-004](ADR-004-cross-platform-portability.md) | Cross-platform portability approach | Accepted |
| [ADR-005](ADR-005-ontology-loading-strategy.md) | Ontology loading strategy and named graph separation | Accepted |

## Guiding Principles

All architectural decisions for this project are evaluated against three primary requirements:

1. **Portability** — The application must run on both Windows and Linux without significant rework.
2. **Accessibility** — End users should not be required to install unfamiliar software or use a terminal.
3. **Longevity** — The technology stack must be built on open standards and actively maintained projects with long support horizons.
