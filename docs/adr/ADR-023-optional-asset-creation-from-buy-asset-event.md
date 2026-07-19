# ADR-023: Optional asset creation from a Buy asset life event

**Date:** 2026-07-19
**Status:** Proposed
**Deciders:** Project owner

---

## Context

A user planning to buy a car in 2035 for £40,000 and sell it in 2045 for
£20,000 can already model it: two life events, a Large expenditure and a
Windfall. It works, and it is exactly what a spreadsheet would do. What it
doesn't do is let them **see the car** while planning — the two records are
unlinked, and nothing on the balance sheet says they own anything between 2035
and 2045.

The obvious attempt to fix that by hand makes the projection **worse**. Adding
the car on the Accounts page puts £40,000 on the balance sheet **from today**,
because:

- `mrl:Account` has no acquisition date. Its only date, `mrl:balanceDate`, means
  *"when this balance was recorded"* (`mrl-ontology.ttl:1051-1055`). There is no
  `startYear` / `openDate` anywhere on `Account` or its subclasses, and
  `mrl:assetSaleYear` is the only forward-dated lifecycle field that exists.
- A future date is **silently clamped**, not honoured. Opening balances
  (`projection.py:956-965`, and identically for assets at `1006`) compute
  `ye = max(0, current_year - balance_date.year)`, so a 2035 date evaluated in
  2026 gives `ye = 0` — full value, year 0.

So the user's cash correctly leaves in 2035 *and* the asset sits on the balance
sheet for the nine years before they own it. `LifeEventType_BuyAsset` (ontology
1.0.11) records the outlay only and creates nothing —
`mrl-ontology.ttl:106` says so and calls the gap "a natural follow-on".

This is a **cognitive-load problem, not an accounting one**. The workaround
exists and is arithmetically fine. The question is whether MRL makes the fixed
half of net worth trackable, or leaves the user doing it in their head.

## Options considered

- **Document the workaround.** Warn on the form that the asset must be added
  separately and will count from today. Zero risk, but the app keeps punishing
  the honest attempt and the user keeps the pairing in their head.
- **Full write-through mirroring Sell asset.** Make the asset the single source
  of truth and the life event a derived front door, as `set_asset_sale()`
  (`accounts.py:518`) does for sales. Rejected as over-built: a sale is
  *inherently* about an asset you own, so the asset must be truth there or the
  proceeds double-count. An outlay is a real cash fact whether or not the user
  chooses to capitalise it. Forcing symmetry adds concepts without serving the
  goal.
- **Optional asset creation from the Buy asset event (chosen).** The user picks
  "Buy asset", and a checkbox on that form optionally creates the linked asset.
  The outlay stands alone if they decline. One extra field on a form they were
  already filling in.

## Decision

Let a **Buy asset** life event optionally create the asset it pays for.

### Ontology (version **1.0.12**) — one new property

- **`mrl:assetAcquisitionYear`** (`owl:DatatypeProperty`, `rdfs:domain
  mrl:PhysicalAsset`, `rdfs:range xsd:integer`) — the year the asset is
  acquired. Before it, the engine values the asset at **zero**. **Absent means
  already owned**, so every existing asset keeps its current meaning.

The link needs no new property: **`mrl:sourceAsset` already exists**
(`mrl-ontology.ttl:1486`) as the back-link from an auto-generated sale event to
its asset, and the purchase event reuses it.
`mrlx:LifeEventType_BuyAsset`'s definition loses its "does not yet create"
caveat.

### UI — a checkbox on the Buy asset form

The user selects **Buy asset** as the type, as now. That form gains an optional
**"Add as an asset"** checkbox which reveals an asset-type picker (Property /
Vehicle / Collectible) and an appreciation rate defaulting to **0**. The asset's
name and value default from the event's name and amount.

**The purchase price is the asset's value** — one number, no separate field.
That an asset may be worth slightly less the moment it's bought is real and
deliberately ignored; the planning question is what it's worth to sell later,
and `mrl:assetSaleValue` already answers that directly as a manual override. A
flat 0% rate with a stated sale value models the car example exactly, with no
depreciation curve to invent.

Leaving the box unticked stores the outlay and nothing else — the current
behaviour, unchanged. **`LifeEventType_LargeExpenditure` is untouched** and is
still the right type for spending that buys nothing lasting.

### Acquisition year is never entered directly

`mrl:assetAcquisitionYear` is set **only** by the funding event, and is shown
read-only on the asset form with a link back to that event.

This is a load-bearing restriction, not tidiness. If the year were typed
directly on an asset, a user could conjure a 2035 car with **no £40,000 ever
leaving an account** — net worth inflated from nothing, the inverse of the bug
being fixed and harder to spot, since neither screen looks wrong. Making the
event the only door is also less UI, not more.

### Engine (`projection.py`)

- `load_all_assets()` (L369-418) reads `acquisition_year` (`None` when absent).
- **Opening balances** (L999-1011): an asset whose acquisition year is in the
  future opens at **0.0**, with no forward-growth from `balance_date`.
- **Per-year valuation** (L1364-1375) gains a leading guard, bounding an asset's
  life at both ends:

  ```python
  if asset["acquisition_year"] is not None and year < asset["acquisition_year"]:
      asset_balances[label] = 0.0
  elif asset["sale_year"] is not None and year >= asset["sale_year"]:
      asset_balances[label] = 0.0
  elif asset_balances[label] > 0:
      asset_balances[label] *= (1 + asset["appreciation_rate"] / 100)
  ```

  The asset is present at full value in its acquisition year, appreciating from
  the year after — matching the whole-year treatment of disposal.
- **The life-event step (L1163-1184) is not touched**, and the engine stays
  type-blind (`load_life_events()` at L525-554 never reads `lifeEventType`). The
  outlay debiting cash while the asset appears in the same year is what makes the
  pair correctly net-worth-neutral.

### Validation

- **Future `balanceDate` is rejected** on the account and asset forms
  (`_account_form.html:243`). It means "when this balance was recorded"; a future
  one is a data-entry error, and forward-dating now has its own field.
  **Restore (`restore_all_data`) and MFL import must not hard-reject** — that
  would make existing backups unrestorable. They clamp as today and warn.
- **Sale year must be strictly after acquisition year.** Not tidiness: under the
  guard above, a same-year buy-and-sell zeroes the asset (sale wins) while the
  proceeds still credit — free money.

### Deletion is asymmetric, deliberately

Deleting the **asset** leaves the event: the money was still spent. Deleting the
**event** offers to delete the asset too. (Contrast the sale side, where
deleting the asset deletes its managed event.)

### Export / restore (`settings_route.py`, schema **0.3.4**)

`export_all_data()` adds `acquisitionYear` beside `saleYear` (L283);
`restore_all_data()` writes it back when present (beside L667). **Mandatory:**
per ADR-014 `restore_all_data()` wipes the data graph first, so an unexported
property is silently destroyed on the next scenario load. Pre-0.3.4 backups
restore as already-owned, which is what they meant.

### Migration — nothing automatic

Existing `BuyAsset` events are not retro-linked to assets: a user who followed
the documented workaround already has a companion asset, and creating a second
would double-count. Existing future `balanceDate`s are ambiguous between
forward-dating and a typo. Both are **surfaced on the Accounts page** for the
user to resolve. The live store (2 property assets, 5 life events) is small
enough to audit by hand at reload.

## Consequences

- **The fixed half of net worth becomes visible.** A planned purchase shows up as
  something owned, from the year it's bought, and its sale hangs off it instead
  of floating as an unrelated windfall.
- **The double-count goes.** A future purchase stops inflating net worth for
  every year before it happens. This **changes projected figures** for any
  scenario with a forward-dated asset — the first engine change since session 15.
- **Parity where nothing is set.** With no `assetAcquisitionYear` anywhere, the
  engine is byte-identical: the new guard is never true, opening balances are
  unchanged, the life-event step wasn't edited. Test this first.
- **Buy and sell are not symmetric, by design.** Sell derives an event from an
  asset; buy optionally derives an asset from an event. The asymmetry follows
  from the facts — an outlay is real whether or not it's capitalised, a sale
  isn't. Worth remembering before anyone "fixes" it.
- **ADR-021 rental income improves for free.** Yield is derived from
  `asset_balances[label]`, which is 0 before acquisition — so a not-yet-bought
  rental produces **no rent before its purchase year**, with no extra code.
- **Capital gains become computable, and stay out of scope.** Recording a
  purchase price means acquisition cost is known for the first time (ADR-013
  taxes withdrawals, not disposals). Noted as enabled, deliberately not taken.
- **Financed purchases remain out of scope.** A Buy asset debits the full amount
  from one account; part-cash-part-mortgage needs a liability model MRL lacks.
  `mrl:isMortgaged` stays a flag.
- **Requires `tools/reload_ontology.py`** (app closed) for the new property to
  appear in the live store.
