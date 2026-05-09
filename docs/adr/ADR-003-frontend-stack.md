# ADR-003: Frontend stack

**Date:** 2026-05-09
**Status:** Accepted

---

## Context

My Retirement Life uses a browser-based UI served by the local Python backend. The frontend must:
- Produce a professional, polished user interface suitable for a personal finance and life planning application
- Be maintainable over the long term without a complex JavaScript build pipeline
- Work consistently across modern browsers on both Windows and Linux
- Avoid introducing a large tree of JavaScript dependencies that require ongoing management

The application's UI patterns are primarily dashboards, data entry forms, charts, timelines, and summary views. It does not require real-time collaborative editing, offline-first capabilities, or highly stateful client-side interactions.

### Options considered

| Option | Notes |
|--------|-------|
| React + Tailwind CSS | Industry-standard SPA framework. Requires Node.js build pipeline (Vite/Webpack), hundreds of npm dependencies, and a separate JavaScript codebase. Excellent component ecosystem. Overkill for the interaction patterns required. |
| HTMX + Tailwind CSS + DaisyUI | Server-driven UI. Python backend renders HTML; HTMX handles dynamic updates without page reloads. No build pipeline. DaisyUI provides a full component library on top of Tailwind. One codebase (Python). |
| Vue.js | Similar trade-offs to React; lighter but still requires a build pipeline. |
| Plain HTML + Vanilla JS | Maximum simplicity and longevity, but no component library and significant manual work for interactive elements. |
| Django + Django templates | Full-stack Python framework. Heavier than FastAPI; adds ORM complexity not needed when the data layer is a triple store. |

---

## Decision

**Frontend: HTMX + Tailwind CSS + DaisyUI**

HTMX allows the Python backend (FastAPI) to return HTML fragments in response to user interactions, updating the page without a full reload. This eliminates the need for a separate JavaScript application layer and keeps the entire codebase in Python and HTML templates.

Tailwind CSS provides utility-class styling without requiring a compilation step at runtime (the CDN version is sufficient for a single-user local application). DaisyUI adds a complete set of pre-built UI components (modals, cards, tables, navigation, badges, progress bars) on top of Tailwind, enabling a professional-quality interface without hand-writing component CSS.

For data visualisation (charts, projections), **Chart.js** will be loaded from CDN. It is mature, well-documented, and integrates cleanly with server-rendered HTML.

---

## Consequences

**Positive**
- No Node.js, npm, or JavaScript build toolchain required — significantly reduces maintenance burden
- Single language (Python) for the entire backend and template layer
- DaisyUI provides theming support, including a built-in light/dark mode toggle with no additional work
- Tailwind and DaisyUI are built on CSS standards; they will remain usable as long as browsers exist
- HTMX is a thin library (14kB) with a stable, conservative API — low risk of breaking changes
- Packaging (ADR-002) is simpler without a compiled JavaScript bundle to manage

**Trade-offs accepted**
- Highly stateful client-side interactions (drag-and-drop reordering, multi-step wizards with complex branching) require more manual JavaScript than React would
- The HTMX ecosystem of pre-built components is smaller than React's; some UI patterns will require more custom work
- Tailwind via CDN includes the full utility class set; for production optimisation, a build step with PurgeCSS would reduce file size — deferred to a future release

**Future considerations**
- If a specific feature genuinely requires rich client-side state (e.g. an interactive financial modelling tool), a small self-contained Alpine.js or Stimulus component can be added without migrating the whole frontend
- The Tailwind/DaisyUI CDN approach can be replaced with a compiled bundle in a future release if bundle size becomes a concern
