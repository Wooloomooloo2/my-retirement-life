# ADR-020: Import from My Financial Life (MFL)

**Date:** 2026-06-23
**Status:** Proposed
**Deciders:** Project owner

---

## Context

My Retirement Life (MRL) and its sister app **My Financial Life (MFL)** are sold
as a bundle: **MFL = your money today → MRL = your money's future.** A user who
already tracks their accounts, holdings, property and budget in MFL should not
have to re-key all of it into MRL by hand. MRL needs to **seed its "today"
picture from MFL**, after which the user adds the retirement-specific layer
(target retirement age, income, drawdown strategy, tax, life events) that MFL
has no concept of.

This is the **final large feature before the two apps can be distributed
together**. The owner's intended usage is not a one-off: a user will **re-import
from MFL periodically (monthly, or preferably yearly) to refresh their
projection** as their real finances move. The importer must therefore be
**idempotent** — a re-import updates the previously-imported items rather than
duplicating them.

### What MFL actually is (investigated against `mfl_public.mfl`, the public "Jordan Avery" demo)

MFL is a **transaction-ledger application backed by SQLite**. Its backup,
snapshot and data-library files all carry the `.mfl` extension but are plain
SQLite 3 databases — **MFL has no JSON export**. Relevant tables:

- `person` — `name`, `base_currency` only. **No date of birth, retirement age or
  life expectancy** — confirming the retirement profile is MRL-only.
- `account` — `name`, `family`, `type`, `currency`, `is_liability`,
  `opening_balance` (minor units / pennies, INTEGER), `credit_limit`,
  `folder_id`. Families present: `cash`, `credit`, `investment`, `loan`,
  `property`, `vehicle`. **Current balances are not stored** — they are derived
  as `opening_balance + Σ txn.amount` over the ledger.
- `security` / `lot` / `security_price` — investment holdings. A `lot`
  (`account_id`, `symbol`, `quantity`, `unit_cost`, `open_date`, `close_date`)
  is an open position while `close_date IS NULL`; current value =
  `Σ quantity × latest security_price`.
- `valuation` — `account_id`, `valued_on`, `value` (pennies): manual valuations,
  used for property/vehicle current worth.
- `loan` — `original_amount`, `principal_paid`, `interest_rate`, `term_months`,
  `payment`, `start_date`, … : amortising-loan detail.
- `category` (hierarchical via `parent_id`, with `kind`) + `budget` /
  `budget_line` / `budget_allocation` — a **forward** per-category budget
  (`budget.start_month`, `length_months`; per-month allocations).
- `fx_rate` (`date`, `base`, `quote`, `rate`), `setting` (`base_currency`, …),
  `schema_version`.
- `txn` / `txn_split` / `transfer` / `payee` / `statement` / `scheduled_txn` /
  `report` / `rule` — ledger history and bookkeeping; **not** imported (MRL is
  forward-looking and does not model transaction history).

MFL's `person.iri` is `mrl:Person_1` and accounts carry an `iri` — the two apps
already share ontology DNA, which gives us a stable identity key for re-import.

## Options considered

**Import source.**
- *Require a new JSON export in MFL, then ingest JSON in MRL.* Rejected: MFL has
  no export today, so this is work across two apps for no gain, and couples MRL
  to a second serialisation we'd have to keep in sync.
- **Read the `.mfl` SQLite file directly, read-only, via Python's stdlib
  `sqlite3` (chosen).** No new dependency, no change to MFL, and the schema is
  already stable and inspectable. MRL opens the user's chosen `.mfl` with
  `mode=ro` and never writes to it.

**Re-import behaviour.**
- *Replace-all (wipe + seed, like a backup restore).* Rejected as the only mode:
  it destroys the retirement layer the user added in MRL and can't support the
  recurring-refresh use case.
- **Provenance-matched create/update/merge (chosen).** First import into an
  empty MRL creates everything. Later imports match each MFL item to the MRL
  entity it previously created (by stored provenance key), and **update** it,
  **add** new ones, and **flag** ones that disappeared — all surfaced for the
  user to review before applying. The retirement layer is never touched.

**Loans & credit cards (MRL has no account type for either).**
- **Loans → MRL `BudgetLineType_Loan` budget lines (chosen)**, derived from the
  `loan` row (payment, term, start) — this is how MRL already models debt as a
  repayment stream. **Credit cards are skipped** (revolving balances aren't
  retirement-relevant; importing them would produce misleading figures).

**Investment growth/dividend rates.** MFL records actual returns, not forward
assumptions, but MRL's engine needs an annual growth and dividend rate per
investment account. **Chosen: import the balance and flag each investment
account in the wizard as requiring a growth/dividend rate before finishing**
(rather than seeding a possibly-misleading default that silently drives the
projection).

**Budget granularity.** **Chosen: roll MFL's hierarchical categories up to their
top-level parent by default** (long-term planning needs less detail than
day-to-day tracking), map each top-level category to an MRL `BudgetCategory` +
`BudgetLine`, and seed the amount from MFL's per-category **budget allocations**
(already a forward plan). The wizard must let the user **set each line's from/to
range and add stages (segments) for changes over time** (ADR-017), since MFL's
budget is a single 12-month window and MRL plans across decades.

## Decision

Build an **Import from My Financial Life** wizard that reads a user-selected
`.mfl` SQLite file read-only and seeds MRL's balance sheet and budget, with an
idempotent refresh path for recurring re-imports.

### Mapping (MFL → MRL)

| MFL | MRL | Derivation |
|---|---|---|
| `account.family='cash'` | `CashAccount` | balance = `(opening_balance + Σ txn.amount)/100`; `accountType` from `type` (`cash_std`→Current, `savings_std`→Savings) |
| `account.family='investment'` | `InvestmentAccount` | balance = `Σ open-lot quantity × latest security_price` (+ any account cash); **growth/dividend rate flagged for user** |
| `account.family='property'` | `PropertyAsset` | balance = latest `valuation.value/100`; appreciation rate flagged/defaulted |
| `account.family='vehicle'` | `VehicleAsset` | balance = latest `valuation.value/100` |
| `account.family='loan'` | `BudgetLine` (`BudgetLineType_Loan`) | from `loan.payment` (monthly), `start_date`, `term_months` → line + from/to years |
| `account.family='credit'` | — | **skipped** |
| `category` (rolled up to top-level) + `budget_allocation` | `BudgetCategory` + `BudgetLine` (+ first `BudgetLineSegment`) | annualised allocation; wizard sets from/to + segments |
| `account.currency` vs `setting.base_currency` | `exchangeRateToBase` | from latest `fx_rate`; `1.0` if base; flagged if missing |
| `person.name`, `base_currency` | profile name + base currency only | DOB/ages stay MRL-only |

**Not imported** (MRL-only — the wizard nudges the user to complete them after):
the retirement profile (DOB, target retirement age, life expectancy), income
sources, account contributions, drawdown order & tax treatments, life events,
projection settings, emergency-fund config — plus MFL transactions, payees,
scheduled txns, reports, and credit-card accounts.

### Idempotent re-import (provenance)

Each MRL entity created by an import stores a **provenance reference** to its MFL
source (the MFL `account.iri`, falling back to `account.id`), plus the import
timestamp. Requires an **ontology bump (1.0.7 → 1.0.8)** adding, on the relevant
classes:
- `mrl:importSourceApp` (string, e.g. `"MFL"`)
- `mrl:importSourceRef` (string — the stable MFL key)
- `mrl:importedAt` (date)

On re-import the wizard matches by `importSourceRef`: **update** matched entities
(balances, valuations), **add** new ones, and **flag** MRL entities whose source
vanished from the `.mfl` (never auto-deleted — user decides). User-entered MRL
fields (growth rates, drawdown, tax, retirement layer) are preserved across a
refresh; only the imported facts (balances, holdings, valuations) are updated.

### Wizard flow (new `/import` route + templates)

1. **Choose file** — pick a `.mfl` file (native file dialog via pywebview, with
   a path fallback). Opened read-only; `schema_version` checked and a clear
   message shown if it's a version the importer doesn't understand.
2. **Preview** — a summary of what was found (n accounts by family, total
   balances, n holdings, n budget categories) and, on re-import, a
   create/update/flagged diff against existing MRL data.
3. **Review & map** — per section: accounts & balances; physical assets;
   investments (**with a required growth/dividend rate per account**); loans →
   budget lines; budget (top-level rollup, with **from/to and add-stage**
   controls). Each item can be edited or skipped.
4. **Apply** — writes/updates MRL entities with provenance refs in one pass.
5. **Next steps** — a checklist nudging the user to set their retirement
   profile, income, drawdown/tax, and life events (the parts MFL can't supply).

### Module shape

- `src/mfl_import/reader.py` — read-only `sqlite3` access to a `.mfl`; pure
  functions returning an in-memory "MFL snapshot" (accounts with derived
  balances, holdings, valuations, loans, rolled-up budget). Schema-guarded.
  Unit-testable against `mfl_public.mfl`.
- `src/mfl_import/mapping.py` — pure transform: MFL snapshot → proposed MRL
  entities (with provenance), including the category roll-up and loan→budget
  conversion. No store writes.
- `src/api/routes/import_mfl.py` — the wizard routes; applies the mapping to the
  store and handles match/update/merge on re-import.
- `src/templates/import_*.html` — the wizard steps.

## Consequences

- **No new runtime dependency** (`sqlite3` is stdlib) and **no change to MFL**.
- A user can stand up a realistic MRL plan in minutes from their MFL data, then
  refresh it yearly — the core of the bundle's value.
- **Risks / things to watch:**
  - *Balance-derivation fidelity.* MRL must reproduce MFL's balance maths
    (opening + ledger, lots × price, latest valuation). Phase 1 is verified
    against `mfl_public.mfl` with known totals.
  - *MFL schema drift.* The importer pins/guards on `schema_version` and fails
    loudly rather than mis-mapping a newer schema.
  - *Growth-rate gap.* Imported investments are inert until the user supplies a
    rate — surfaced as a required wizard step, not a silent default.
  - *FX.* Cross-currency accounts need a rate; missing rates are flagged, not
    guessed.
- **Privacy:** the `.mfl` is read locally and read-only; nothing leaves the
  device — consistent with both apps' local-first ethos (note in the MRL privacy
  policy that the import reads a user-selected MFL file).

## Phased implementation plan

1. **Reader** (`reader.py`) — `.mfl` → snapshot, schema-guarded; tests vs the
   public demo DB.
2. **Mapping** (`mapping.py`) — snapshot → proposed MRL entities (category
   roll-up, loan→budget, provenance); pure + tested.
3. **Ontology 1.0.8 + persistence** — provenance properties; create path
   (first import) and identity-matched update path; `tools/reload_ontology.py`.
4. **Wizard UI** — file pick → preview → review/map → apply → next-steps.
5. **Refresh mode** — create/update/merge/flag-removed with a review diff.

Each phase is independently testable against `mfl_public.mfl` before the UI
exists, and the engine/projection is never modified — this is purely an
additive data-in path.

## Implementation notes

**Phase 1 (reader) — done.** `src/mfl_import/reader.py` reads a `.mfl` read-only
into an `MflSnapshot`, verified against the committed public demo
(`tests/fixtures/mfl_public.mfl`) by `tools/verify_mfl_reader.py` (29 checks,
all account balances reconcile to the penny incl. bond ×10 / option ×100 price
multipliers). Two refinements to the design wording, found against real data:

- The `lot` and `valuation` tables are **empty in practice** — MFL derives
  positions by replaying the share legs of the ledger, so the reader does the
  same (net quantity per security × latest price × multiplier) rather than
  reading `lot`. Property/vehicle worth **prefers a `valuation` row when present
  but falls back to the recorded balance** (`opening_balance + Σ txn.amount`).
- "Top-level" budget category means the **child of a kind-root**
  (Housing, Groceries, …), not the kind-root itself (Expense/Income/Transfer/
  Interest/Uncategorised are organisational and excluded as line names).
