# ADR-021: Rental income as a yield on a linked property's value

**Date:** 2026-06-28
**Status:** Accepted
**Deciders:** Project owner

---

## Context

MRL already models rental income, but only as a **standalone income source**:
the user types a fixed annual amount (income type `IncomeSourceType_Property`,
"Property (rental income)") with an optional growth rate and start/end years
(ADR-008). It has **no connection to the property it comes from**. Two problems
follow from that disconnect:

1. **Selling the property does not stop the rent.** A `mrl:PhysicalAsset` with
   an `mrl:assetSaleYear` is auto-disposed by the engine (step 7b zeroes its
   value and routes proceeds via a `LifeEventType_AssetSale`), but the rental
   income source keeps paying out forever unless the user **remembers** to
   end-date it by hand. The two facts — "I own a rental flat worth £300k" and
   "it pays me £14k/yr" — are entered and maintained independently, so they drift
   out of sync.
2. **The rent doesn't track the asset.** A property appreciating at 3%/yr should,
   all else equal, command rising rent. Today the user must guess a separate
   `incomeGrowthRate` that has no link to the property's own appreciation, and
   re-tune it whenever they revise the property.

The physical-asset model is already rich enough to anchor rental income:
`mrl:PhysicalAsset` carries a per-year value (`asset_balances` in the engine,
compounded at `mrl:assetAppreciationRate` and zeroed on sale), and properties
are a first-class subclass (`mrl:PropertyAsset`). What's missing is a **link**
from a rental income source to its property and a **yield** to derive the rent.

## Options considered

- **Keep generic, polish UX.** Leave rental as a standalone source; just add a
  reminder to end-date it when selling the property. Smallest change, but leaves
  both root problems (manual sync, no tracking) unsolved.
- **Link income source → property, keep a fixed amount.** Add only the link, so a
  sale auto-stops the rent, but the amount stays a hand-typed figure. Solves
  problem 1, not problem 2.
- **Yield % of the linked property's value (chosen).** The income source links to
  a property and stores an annual **yield rate**; the engine derives the rent
  each year as `yield% × property value that year`. Solves both problems: the
  rent rises and falls with the property and stops automatically on sale, with a
  single source of truth (the property's value).

## Decision

Derive rental income from a linked property's projected value via a yield rate.

### Ontology (version **1.0.9**) — two new properties on `mrl:IncomeSource`

- **`mrl:rentalProperty`** (`owl:ObjectProperty`, range `mrl:PhysicalAsset`) —
  links this income source to the property that generates it. Optional; only
  meaningful for rental sources.
- **`mrl:rentalYieldRate`** (`owl:DatatypeProperty`, range `xsd:decimal`) — the
  annual rental yield as a percentage of the linked property's current value,
  e.g. `4.5` for 4.5%. Interpreted as a **net** yield (after letting costs and
  tax), consistent with MRL's convention that income figures are take-home
  (ADR-015). A source is "yield-driven" only when **both** properties are set.

No change to the `mrl:PhysicalAsset` side — the link is one-directional, from the
income source to the asset, mirroring `mrl:assetProceedsAccount` and
`mrl:creditedToAccount`.

### Engine behaviour (`projection.py`)

- `load_all_income_sources()` reads the two new fields onto each income dict
  (`rental_property` = linked asset's local label or `None`, `rental_yield`).
- In the year loop **step 3 (income)**, for a yield-driven source the annual
  amount becomes:

  ```
  amt = rental_yield% × asset_value_at_start_of_year(rental_property)
  ```

  using `asset_balances[label]` **before** that year's appreciation/disposal
  (step 7b). Because step 7b zeroes the asset on and after `assetSaleYear`, the
  derived rent is **0 from the year after the sale onward**, with no end-date
  needed. The source's `incomeStartYear` / `incomeEndYear` window is still
  honoured (so a residence converted to a let mid-projection, or a let that ends
  early, both model correctly), and routing is unchanged (`deposit_account` vs
  unrouted, ADR-011 / item 54).
- A yield-driven source **ignores** its static `incomeAnnualAmount` and
  `incomeGrowthRate` — growth comes entirely from the property's appreciation, so
  applying a separate growth rate would double-count. Those fields are retained
  on the source (for non-linked rentals and all other income types) but unused
  when a property link + yield are present.
- If `rentalProperty` points to an asset that no longer exists (deleted), the
  source falls back to its static amount, so a dangling link degrades safely.

### UI (`income.html` / `income.py`)

- The add/edit income form, when the type is **Property (rental income)**,
  reveals an optional **Linked property** dropdown (the user's `PropertyAsset` /
  `PhysicalAsset` instances) and a **Net annual yield %** field.
- When a property is linked, the manual **annual amount** field is shown disabled
  with a "computed from property value × yield" note, and a live hint shows the
  first-year derived figure (`yield% × current property value`).
- `POST /income` and `/income/{n}/edit` gain `rentalProperty` /
  `rentalYieldRate` form params, persisted via the existing save path.

### Export / restore (`settings_route.py`)

`export_all_data()` adds `rentalProperty` / `rentalYieldRate` to each income
source; `restore_all_data()` writes them back (skipping absent values). Per
ADR-014, anything `export_all_data()` omits is destroyed on the next scenario
load, so this must ship together with the engine change. Pre-1.0.9 backups
round-trip unchanged (no link → static amount).

## Consequences

- **One source of truth.** Rental income is anchored to the property: revise the
  property's value or appreciation and the rent follows; set a sale year and the
  rent stops on its own. The "owns a flat / earns rent" pair can no longer drift.
- **Parity preserved.** With no `rentalProperty` set on any source, the income
  step is byte-identical to the current engine — existing rentals and every other
  income type are untouched.
- **Net-yield simplification.** The yield produces a net figure (after costs and
  tax), matching MRL's take-home income model. Users who want to model gross rent
  minus explicit letting costs can lower the yield or add a budget line; a
  dedicated gross-yield-plus-costs model is a deferred refinement.
- **Sale-year edge.** Income (step 3) runs before disposal (step 7b), and the
  rent uses the asset's start-of-year value, so rent is earned in every year the
  property is held at the **start** of the year — **including the sale year** —
  and is 0 from the year after the sale onward. A part-year proration in the sale
  year is intentionally not modelled (consistent with the engine's whole-year
  treatment of asset disposal).
- **Mortgage out of scope.** The yield is applied to the property's gross value,
  not its equity; an outstanding mortgage stays a separate liability / budget
  line (`mrl:isMortgaged`), unchanged.
- **Link is generic, UI is property-scoped.** `mrl:rentalProperty` ranges over
  `mrl:PhysicalAsset`, so the engine treats any linked asset uniformly (a
  depreciating asset simply yields a falling income); the form restricts the
  picker to properties to keep the concept clear.
- **Requires `tools/reload_ontology.py`** (app closed) for the new properties to
  appear in the live store; backend writes do not depend on the declaration.
