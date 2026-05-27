# ADR-017: Budget line segments and user-defined categories

**Date:** 2026-05-26
**Status:** Accepted
**Deciders:** Project owner

---

## Context

The current `mrl:BudgetLine` model treats each line as a single, time-flat
commitment: one amount, one frequency, one real-growth rate (`mrl:annualChangeRate`),
and an optional `mrl:budgetStartYear` / `mrl:budgetEndYear` window. Two unrelated
problems flow from this shape.

**Problem 1 — life-stage spending cannot be modelled continuously.**
Most real budgets are not flat. Groceries for a single person at £500/month rise
to £1,500/month with children for ~18 years, then fall back. The only available
workaround is to split the logical category into multiple budget lines —
"Groceries 2026–2031", "Groceries 2031–2049", "Groceries 2049–end" — each with
its own amount. Functionally correct for totals, but it fractures one
financial concept into several rows.

**Problem 2 — the chart cannot show category trends over a lifetime.**
The `/budget` page today plots Mandatory / Discretionary / Loans as three
stacked series. This is a procedural grouping (how the engine treats the
line) rather than a spending grouping (what the money is *for*). Users want
to see spending broken out by purpose — housing, food, travel, etc. — with
mortgage payments showing up in Housing alongside utilities and insurance,
not in a separate "Loans" band. The natural shape — colour each line by its
category — collides head-on with Problem 1: the three "Groceries" lines
from the workaround above would render as three distinct, discontinuous
bands instead of one continuous Food trend.

Solving either problem alone is unsatisfying:
- Categories alone leave the splitting hack in place and surface its
  side-effect (broken continuity) more visibly.
- Segments alone leave the chart locked to the existing Mandatory /
  Discretionary / Loans grouping that users have already flagged as
  insufficient.

Both problems are also tied to the same datatype properties on `mrl:BudgetLine`
(`budgetLineAmount`, `annualChangeRate`, `budgetStartYear`, `budgetEndYear`) —
addressing them in a single ADR avoids reworking the line shape twice.

A third concern shaped the category design: the sister application **My Financial
Life (MFL, ADR-010)** is expected to eventually export a "Level 1" category
taxonomy from real transaction history. The MRL category model should be
compatible with that future import without committing to it now.

---

## Options considered

### Categories

**Option C1 — Fixed enumerated vocabulary.**
A small SKOS scheme (`mrlx:BudgetCategoryScheme`) with ~8 hard-coded categories
(Housing, Food, Transport, Travel, Health, Subscriptions, Personal, Other),
identical in pattern to `mrlx:DrawdownStrategyScheme` or `mrlx:TaxTreatmentScheme`.

**Rejected** because:
- No two users budget in exactly the same categories. Forcing the user's
  mental model into eight predefined buckets means most users will end up
  using "Other" as a catch-all, defeating the purpose of the chart.
- The eventual MFL Level-1 import will define its own taxonomy. Hard-coding
  one here creates a migration cliff.

**Option C2 — User-defined free-text strings on each budget line.**
Add `mrl:budgetCategoryName` as an `xsd:string` directly on `mrl:BudgetLine`.

**Rejected** because:
- Renaming a category requires editing every line that uses it.
- Typos fragment the category space silently — "Food" and "food" become two
  categories.
- Cannot attach metadata (colour, display order, MFL import source) to a
  category if it is not an instance.

**Option C3 — User-created `mrl:BudgetCategory` instances + one system-derived category (chosen).**
Each category is a first-class instance in the data graph, created on demand
by the user. A small suggestion list in the UI (rendered as quick-pick chips)
helps users start without forcing them into a fixed vocabulary; suggestions
are *not* pre-created — they materialise as `BudgetCategory_N` instances only
when the user adopts one. One system category — "Account contributions" — is
computed at render time from `mrl:AccountContribution` instances (which live
on accounts, not budget lines) and cannot be created, renamed, or deleted by
the user. Loans are NOT a system category: a mortgage line is categorised as
"Housing" (or whatever the user chooses) and shown alongside the rest of that
category's spending. The line type (`BudgetLineType_Loan`) continues to drive
engine behaviour — no inflation lift on the payment, ADR earlier item 8 —
but is orthogonal to the chart grouping.

**Why this option:**
- Users keep full control over their own taxonomy.
- Categories are renameable in one place (the category instance).
- A future MFL Level-1 import can populate `mrl:BudgetCategory` instances
  without schema changes — only a new `mrl:categorySource` property is needed
  to track provenance.
- The model accommodates an eventual parent-category hierarchy
  (`mrl:parentCategory` → `mrl:BudgetCategory`) without breaking existing
  data, should MFL bring nested taxonomies.

### Segments

**Option S1 — Properties directly on `mrl:BudgetLine`, repeated.**
Add `mrl:secondAmount`, `mrl:secondStartYear`, etc. for a fixed number of
stages.

**Rejected** as obviously inflexible: caps the number of life-stage changes,
and clutters the line with optional properties that are mostly unused.

**Option S2 — A single ordered list of `(year, amount)` pairs serialised
into one literal.**

**Rejected** because storing structured data inside a string literal defeats
the point of using a triple store; SPARQL queries cannot reach inside the
literal; and it precludes per-segment metadata (per-segment growth rate,
notes, etc.).

**Option S3 — A new `mrl:BudgetLineSegment` class linked to its line via
`mrl:segmentOwner` (chosen).**

Each segment is an independent instance carrying its own `startYear`,
`endYear`, `amount`, `frequency`, and `changeRate`. A budget line has one or
more segments. The line itself retains identity (name, category, line type,
note) but no amount or window — those move to the segments.

**Why this option:**
- Symmetric with the `mrl:AccountContribution` pattern (ADR-015) — a
  lightweight class linked back to its owner.
- Reads with `quads_for_pattern` (ADR-007) per the existing access pattern.
- Per-segment growth rate accommodates the realistic case where a stage has
  its own real-growth profile (e.g. childcare grows faster than groceries).
- Per-segment frequency is permitted but the v1 UI will default each segment
  to the line's first segment's frequency to avoid clutter.

### Where to anchor the "Account contributions" system category

Account contributions (ADR-015) are not budget lines — they live on accounts
as `mrl:AccountContribution` instances and are not editable from `/budget`.
The existing budget chart already shows them as a separate stacked band
(item 15 in `CLAUDE_CONTEXT.md`). Under the by-category model they need to
appear *somewhere* in the legend.

**Option SY1 — Pre-create "Account contributions" as a `BudgetCategory`
instance flagged with `mrl:isSystemCategory = true`.**

**Rejected** because the membership is derived, not stored. A contribution
is in the group by virtue of being a `mrl:AccountContribution`, not by
being explicitly tagged. Creating a parallel tag duplicates state and
invites the question "what if the user tags some lines with this category
too?".

**Option SY2 — Compute at render time (chosen).**
The chart-grouping helper attributes the total of all
`mrl:AccountContribution` instances to a synthetic "Account contributions"
group, separate from any user-defined category. The name is reserved — UI
validation rejects user-defined categories with this name to prevent
collision. The group is unchangeable, undeletable, and unnameable from the
UI.

Loans are explicitly **not** a system group: each loan line carries its own
user-chosen `mrl:budgetCategory` and is rendered in that category's band.

---

## Decision

### 1. New ontology classes and properties

```
mrl:BudgetCategory a owl:Class ;
    rdfs:label "Budget Category"@en ;
    rdfs:comment
        "A user-created spending category. Account contributions are NOT "
        "BudgetCategory instances — they are derived at render time from "
        "mrl:AccountContribution instances and rendered as a separate "
        "synthetic group."@en .

mrl:BudgetLineSegment a owl:Class ;
    rdfs:label "Budget Line Segment"@en ;
    rdfs:comment
        "A time-bounded amount within a budget line. A budget line has one "
        "or more segments; in any given year at most one segment is active."@en .
```

Properties on `mrl:BudgetCategory`:

| Property | Type | Description |
|---|---|---|
| `mrl:categoryName` | `xsd:string` | Display name (e.g. "Food") |
| `mrl:categoryDisplayOrder` | `xsd:integer` | Optional manual ordering on the chart legend; ties broken alphabetically |
| `mrl:categorySource` | `xsd:string` | Optional provenance — `"user"` (default) or `"mfl-level-1"` when imported. Reserved for the future MFL ingest path; not surfaced in v1 UI. |

Properties on `mrl:BudgetLineSegment`:

| Property | Type | Description |
|---|---|---|
| `mrl:segmentStartYear` | `xsd:integer` | First year this segment is active. Required. |
| `mrl:segmentEndYear` | `xsd:integer` | Last year this segment is active. Optional — open-ended segments run to the end of the projection. |
| `mrl:segmentAmount` | `xsd:decimal` | Amount per period in the base currency |
| `mrl:segmentFrequency` | `→ mrlx:FrequencyType_*` | Reuses the existing frequency vocabulary |
| `mrl:segmentChangeRate` | `xsd:decimal` | Real growth rate (above inflation), default 0 |
| `mrl:segmentOwner` | `→ mrl:BudgetLine` | The budget line this segment belongs to |

New property on `mrl:BudgetLine`:

| Property | Type | Description |
|---|---|---|
| `mrl:budgetCategory` | `→ mrl:BudgetCategory` | The category this line belongs to. Optional for all line types — lines without a category fall into the "Uncategorised" group on the chart until the user assigns one. Applies to `Mandatory`, `Discretionary`, AND `Loan` lines: a mortgage is categorised as "Housing", a car loan as "Transport", etc. |

**Deprecated** on `mrl:BudgetLine` (kept in the ontology for backwards
compatibility, no longer written by new code):

- `mrl:budgetLineAmount`
- `mrl:budgetLineFrequency`
- `mrl:annualChangeRate`
- `mrl:budgetStartYear`
- `mrl:budgetEndYear`
- `mrl:loanEndYear` *(folded into the segment model — a loan line is a
  single segment with `segmentEndYear` set)*

### 2. IRI naming

Per ADR-006: `mrl:BudgetCategory_N` and `mrl:BudgetLineSegment_N`, each
class with its own independent N counter.

### 3. Migration of existing budget lines

Run-once migration on app startup (idempotent — guarded by a check that the
data graph contains zero `BudgetLineSegment` instances and at least one
`BudgetLine` with a `budgetLineAmount` literal):

For each existing `mrl:BudgetLine`:

1. Allocate `BudgetLineSegment_N` and copy:
   - `segmentStartYear` ← `budgetStartYear` if set, else current year
   - `segmentEndYear` ← `budgetEndYear` (or `loanEndYear` for loan lines) if set
   - `segmentAmount` ← `budgetLineAmount`
   - `segmentFrequency` ← `budgetLineFrequency`
   - `segmentChangeRate` ← `annualChangeRate`
   - `segmentOwner` ← the budget line's IRI
2. Leave the deprecated properties in place on the original line (the engine
   ignores them once segments exist; removing them would lose data if the
   migration is rolled back).
3. No `mrl:budgetCategory` is assigned — existing lines stay uncategorised
   until the user opens them and picks a category. The chart's "Uncategorised"
   group catches them until then.

System categories ("Loan repayments", "Account contributions") need no
migration — they are derived at render time from existing typed data.

### 4. Projection engine changes

`load_budget_lines()` in `projection.py` returns each line with a
`segments: list[dict]` field instead of the line-level amount/window/rate.
Each segment dict carries `start_year`, `end_year` (or `None`),
`annual_amount` (already multiplied through by the frequency), and
`change_rate`.

The per-year loop in `_simulate_run()` changes from:

```python
# Today
for line in lines:
    if active_in_year(line, year):
        spending += line["annual_amount"] * growth_factor(line, year)
```

to:

```python
# Proposed
for line in lines:
    seg = find_active_segment(line, year)
    if seg is not None:
        years_active  = year - seg["start_year"]
        growth_factor = (1 + seg["change_rate"] / 100) ** years_active
        spending     += seg["annual_amount"] * growth_factor
```

`find_active_segment(line, year)` returns the unique segment whose
`[start_year, end_year]` window contains `year`, or `None` if no segment is
active in that year (the line contributes zero). The UI prevents overlapping
segments so the "unique" assumption holds.

Loan-line treatment per ADR earlier (item 8 in CLAUDE_CONTEXT): a loan
segment's effective rate is `segmentChangeRate` only — no inflation lift.
This logic moves from the line to the segment unchanged.

`compute_annual_spending_series()` in `budget.py` follows the same change:
iterate segments per line, not the line itself.

### 5. Category grouping on the budget chart

A new helper `group_lines_by_category(lines, contributions)` produces the
data for the by-category chart:

- For each `mrl:BudgetLine` (any type, including `BudgetLineType_Loan`):
  attribute its annualised spending to its `budgetCategory` name, or to
  "Uncategorised" if none is set.
- For all `mrl:AccountContribution` instances: attribute the total to the
  synthetic "Account contributions" group.

The chart on `/budget` defaults to **by-category grouping**. A toggle
switches to **by-line** for detail. The existing Mandatory / Discretionary /
Loans grouping is retired — the line type still drives engine behaviour
(loans skip inflation, etc.) but is no longer a chart dimension.

Gaps between segments within a line are intentional and render naturally on
a stacked chart: the category contributes that line's amount in active
years and zero in gap years. Example: paying down a mortgage faster by
pausing the "Travel" category for two years shows up as a Travel band that
drops to zero and resumes — visible on the chart, no special handling
required.

Colour palette: deterministic palette generation from category name hash
(stable across sessions, no manual colour management), with the
"Account contributions" system group pinned to a fixed teal (matching item
15's existing convention).

### 6. UI changes

**`/budget` page:**

- Chart hero card unchanged in size and position; legend reflects the new
  grouping. Default view: by category. Toggle: chart-controls dropdown
  "Group by · Category / Line" beside the existing controls.
- Per-line table gains a **Category** column. The Type column collapses to a
  small badge (M/D/L) to make room.

**Budget line add/edit form:**

- New **Category** field, shown for all line types (Mandatory,
  Discretionary, Loan). Combobox: type to search existing categories,
  press Enter or click "+ Create" to make a new one. Below the input,
  small chip suggestions: **Housing, Food, Transport, Travel, Health,
  Subscriptions, Personal, Bills, Taxes** — clicking a chip creates the
  category and selects it. No "Other" chip; users who genuinely want an
  Other bucket can type and create it themselves.
- The single amount/frequency/start/end/change-rate row is replaced by a
  **Schedule** sub-section: one segment row by default, with an "Add stage"
  button to append more.
- Each segment row: start year, end year (blank = open-ended), amount,
  frequency, real growth %. Inline validation: overlapping segments
  rejected. Gaps between segments are permitted by design — they render as
  a year of £0 for that line, which on a stacked chart is the natural way
  to express "I'm pausing this for a couple of years to pay down debt
  faster". No warning UI needed.

**Category management:**

- No dedicated `/budget/categories` admin page in v1. Categories are
  managed inline:
  - Created from the line form (combobox).
  - Renamed from the line form (a small ✎ icon next to the selected
    category opens a rename input).
  - Deleted: only via "no lines reference this category any more" cleanup
    — deletion is implicit, not exposed. Avoids the "what happens to my
    lines?" UX question entirely in v1.

### 7. Backup / restore

`settings_route.py` exports and restores `mrl:BudgetCategory` and
`mrl:BudgetLineSegment` instances alongside the existing `mrl:BudgetLine`
export. The deprecated line-level properties remain in the export bundle
during the migration window (until the next ontology version bump removes
them entirely).

### 8. Ontology version

Bump `docs/ontology/mrl-ontology.ttl` `owl:versionInfo` to **1.0.2**.
Requires `python tools\reload_ontology.py` with the app closed for the
classes and properties to appear in the live store.

---

## Consequences

**Positive**

- A single budget line can represent one logical spending category across
  the user's entire life, with explicit life-stage transitions visible in
  one place.
- The by-category chart shows continuous trends per category instead of
  fragmented bands. Adding children, moving house, downsizing — all visible
  as continuous lines that step up or down.
- The category model is user-controlled, with no fixed taxonomy to argue
  about, and is forward-compatible with an eventual MFL Level-1 import via
  `mrl:categorySource`.
- Loans appear in the categories they semantically belong to — mortgage in
  Housing, car loan in Transport, student loan wherever the user prefers
  — making the chart reflect *what the money is for*, not *which engine
  rule applies*.
- The "Account contributions" system group stays derived from
  `mrl:AccountContribution` instances, so it cannot drift out of sync with
  the underlying data — and the user cannot delete it.

**Trade-offs accepted**

- An ontology bump and a force-reload are required. The migration runs once
  on first launch after the bump and is idempotent.
- The budget line form gets longer when multi-segment scheduling is used.
  Default state remains a single segment, so casual users see the same
  density as today.
- The Mandatory / Discretionary / Loans chart grouping is retired. Existing
  screenshots and any external documentation referring to it will become
  stale.
- The "Uncategorised" group will be large immediately after migration until
  the user revisits each line. This is acceptable for a pre-beta release;
  a one-click "categorise all" wizard is a possible Post-1.0 follow-on.

**Future considerations**

- `mrl:parentCategory` → `mrl:BudgetCategory` for the MFL Level-1/Level-2
  hierarchy when that import lands.
- Per-segment notes (`mrl:segmentNote`) for the user to record why a stage
  exists ("kids leave home", "downsize"). Deferred — a comment on the line
  itself is sufficient for v1.
- A dedicated `/budget/categories` admin page if the inline-management
  approach proves insufficient as the category list grows.
- Bulk recategorisation tooling once category history matters.
- Per-budget-line currency (ADR-016 follow-on) becomes a per-segment
  property in this model instead of a per-line one — cleaner for users
  living through a currency change mid-life.
