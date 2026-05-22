# ADR-014: Scenario Management — Named Save Slots and Session Switching

**Date:** 2026-05-18
**Status:** Accepted
**Deciders:** Project owner

---

## Context

The application currently supports a single dataset: one profile, one set of accounts,
one projection. All user data lives in a single Oxigraph named graph
(`https://myretirementlife.app/data/graph`).

This creates two practical problems:

1. **Testing.** Validating new features (drawdown strategies, tax settings, eligibility
   rules) requires materially different datasets. Without scenario switching, every test
   requires manually deleting the store directory — a destructive, error-prone workaround
   that also discards any data the user wants to keep.

2. **What-if analysis.** A core use case for retirement planning is comparing outcomes
   under different assumptions: retiring at 60 vs 67, drawing from ISA before SIPP vs
   the reverse, moving abroad vs staying. Without named scenarios, users must mentally
   track differences or maintain separate installations.

---

## Options considered

### Option A — Multiple Oxigraph stores (separate directories)

Each scenario has its own Oxigraph database directory. Switching scenarios changes the
active store path and requires an application restart.

**Rejected** because:
- Requires `store` to be a runtime-mutable singleton, which conflicts with the current
  module-level initialisation pattern in `src/store/graph.py`.
- An application restart is a poor UX for something as lightweight as "switch to
  scenario B".
- Store directories are large and not human-readable; scenarios cannot be inspected,
  shared, or version-controlled easily.

### Option B — Named graphs within the existing store

Each scenario occupies a uniquely-prefixed set of named graphs, e.g.
`https://myretirementlife.app/data/scenario-2/graph`. The active scenario is a
config value; all route code uses `DATA_GRAPH` which resolves to the active graph IRI.

**Rejected** because:
- Requires every SPARQL query and quad pattern call throughout the codebase to use a
  dynamic `DATA_GRAPH` rather than a module-level constant — a pervasive refactor.
- The Oxigraph store grows unboundedly with each scenario and cannot be pruned without
  SPARQL `DROP GRAPH` operations.
- Scenarios stored in named graphs are not portable: they cannot be copied to another
  machine, sent to a support request, or opened in a text editor.

### Option C — JSON file-based scenarios (chosen)

Each scenario is a JSON file on disk, produced by the existing `export_all_data()`
function in `settings_route.py`. The application's Oxigraph data graph always represents
the **currently active scenario**. Switching scenarios means restoring a different JSON
file into the data graph.

A `scenarios/` subdirectory in the platform data directory holds all saved scenario
files. A small metadata file (`active_scenario.json`) records the name of the currently
loaded scenario.

---

## Decision

**Scenarios are named JSON files stored in `{data_dir}/scenarios/`.
The Oxigraph data graph always holds the active scenario.
Switching scenarios replaces the data graph contents via the existing restore pathway.**

### Storage layout

```
{data_dir}/
    oxigraph/               ← Oxigraph store (unchanged)
    scenarios/
        "Base case.json"
        "Early retirement.json"
        "Retire abroad.json"
    active_scenario.json    ← { "name": "Base case", "saved": true }
```

`active_scenario.json` tracks:
- `name` — display name of the currently loaded scenario (empty string if unsaved)
- `saved` — whether the current data graph has been saved to a scenario file since the
  last change (used to prompt "Save before switching?")

The `saved` flag is set to `false` whenever any data-modifying route completes (profile
save, account create/edit/delete, budget change, etc.) and set to `true` after a
successful Save or Save As.

### Operations

| Operation | Behaviour |
|---|---|
| **Save** | Overwrite the current scenario file with `export_all_data()`. Only available when a named scenario is active. Sets `saved = true`. |
| **Save As** | Prompt for a name, write a new JSON file, set as active. Sets `saved = true`. |
| **New** | Optionally prompt "Save current scenario?" → clear data graph → set active to `""` (unsaved), `saved = false`. |
| **Load** | List saved scenarios → confirm "Save current?" if unsaved → restore selected file → set active. |
| **Rename** | Rename the file on disk, update `active_scenario.json`. |
| **Delete** | Delete the file. If it was the active scenario, set active to `""`. |
| **Duplicate** | Save As with a new name without switching. |

### Dirty-state tracking

Rather than hooking every route, dirty-state is tracked lazily:

- `active_scenario.json` is written with `saved = false` immediately after any
  successful `POST` to a data-modifying route (profile, accounts, investments, income,
  budget, life events, projection settings).
- `saved` is set to `true` only by Save and Save As.
- On startup, if `active_scenario.json` is absent, it is created with
  `{"name": "", "saved": false}`.

This approach requires no changes to existing route logic beyond adding a small
post-save hook.

### UI placement

A **Scenarios** card is added to the Settings page alongside Backup & Restore and
Projection Assumptions. It shows:

- Current scenario name (or "Unsaved session" if no name is set)
- Unsaved indicator badge if `saved = false`
- Buttons: Save, Save As, New, Load

Scenario switching is also accessible from a small indicator in the navigation header
showing the current scenario name — clicking it opens the Settings page at the
Scenarios section.

---

## Consequences

**Positive**
- No changes to the store initialisation, `DATA_GRAPH` constant, or any existing SPARQL
  queries — the data graph continues to be a stable module-level constant.
- Scenarios are portable JSON files: shareable, inspectable, version-controllable, and
  restorable on any installation.
- The existing export/import code (`export_all_data()`, `restore_all_data()`) is reused
  with no modification — scenario save/load is just named export/import.
- Users can maintain a "Base case" scenario and branch from it for what-if analysis
  without losing their primary data.
- Testing new features requires only a "New" + data entry, not a store deletion.

**Trade-offs accepted**
- The `saved` dirty-state flag requires the post-save hook to be applied consistently
  across all data-modifying routes. Missing a route means the flag may not be set
  accurately. This is a maintenance discipline requirement, not a hard failure — the
  worst outcome is a slightly stale `saved = true` state.
- Concurrent access is not protected (two browser tabs could both modify data). This is
  acceptable for a single-user local application.
- Scenario files are as large as the full JSON export (~10–50 KB per scenario). For
  users with many scenarios this is negligible.

**Implementation order**
1. `ScenarioManager` utility class in `src/store/scenario_manager.py`
2. `scenarios.py` route file (Save, Save As, New, Load, Rename, Delete)
3. Update `settings.html` with Scenarios card
4. Update `base.html` navigation header with scenario indicator
5. Add dirty-state hook to all data-modifying routes
6. Update `settings_route.py` to remove the now-redundant export-as-only-save UX
   (export remains available for portability; scenarios are the primary session
   management mechanism)
