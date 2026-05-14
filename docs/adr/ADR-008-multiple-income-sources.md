# ADR-008: Multiple income sources with independent start/end dates in MVP

**Date:** 2026-05-14  
**Status:** Accepted

---

## Context

The original MVP specification defined a single Employment income source, entered on the profile setup screen. The income was assumed to start immediately and stop at the user's target retirement year. This was deliberately conservative to keep the MVP scope manageable.

During early use of the application, it became clear that limiting income to a single Employment source significantly reduced the app's usefulness for the exact users it was designed for — people approaching or in retirement who often have multiple income streams that behave very differently:

- **Employment income** stops at retirement
- **Rental income** from property often continues indefinitely through retirement
- **Spouse or partner income** has its own independent timeline
- **State pension** starts at a specific age, not at the user's chosen retirement date
- **Part-time work in retirement** may start after full retirement and stop later

Without the ability to model these separately, the projection was misleading — either overstating income (if rental income was included in employment) or understating it (if it was excluded entirely).

The ontology already included `mrl:incomeStartYear` and `mrl:incomeEndYear` on `mrl:IncomeSource`, and the class was designed to support multiple instances. The data model was ready; only the application layer needed to be built.

### Options considered

| Option | Notes |
|--------|-------|
| Keep single Employment income for MVP, defer multiple sources | Conservative. Keeps profile screen simple. But produces misleading projections for anyone with rental income, a working spouse, or non-employment income. |
| Add multiple income sources to MVP with a dedicated Income screen | Slightly more scope, but the data model already supports it. Directly enables the use case for the target audience. |
| Add multiple sources but keep them on the profile screen | Awkward UX — the profile screen would become overloaded. Income management is a distinct concern from personal details. |

---

## Decision

**Multiple income sources with independent start and end dates are implemented in MVP**, managed via a dedicated `/income` screen separate from the profile.

The profile screen retains a single Employment income source as the default onboarding path (users enter their main income when setting up their profile). The Income screen then allows adding, editing, and deleting any number of additional income sources.

Each income source has:
- A name and type (from `mrlx:IncomeSourceTypeScheme`)
- An annual amount and growth rate
- An optional start year (blank = already active)
- An optional end year (blank = indefinite)

The projection engine was updated to sum all active income sources per year, checking each source's start and end year window. This replaces the previous single-source model that hardcoded income stopping at the retirement year.

A bug was also fixed as part of this change: the profile screen was storing `incomeEndYear` as an **age** (e.g. 57) rather than a **calendar year** (e.g. 2031). This has been corrected — the profile now calculates the retirement calendar year from date of birth and retirement age before storing it.

---

## Consequences

**Positive**
- The projection correctly models the most common real-world income pattern: employment stopping at retirement while other income (rental, pension, investment) continues
- Users with complex income situations — multiple income streams, income starting in the future, income that stops before or after retirement — can now model their situation accurately
- The Income screen is cleanly separated from the profile, keeping the profile focused on personal details
- The ontology's `mrl:IncomeSource` class, which was designed for this from the start, is now fully utilised

**Trade-offs accepted**
- Slightly more scope than originally planned — the Income screen is an additional feature
- Users must now manage income separately from their profile after initial setup; this is the correct separation of concerns but adds a navigation step
- The profile's Employment income (IncomeSource_1) and any Income screen entries are separate — a user who updates their salary on the profile will update IncomeSource_1, while Income screen entries are managed independently

**Bug fix**
- `mrl:incomeEndYear` is now stored as a calendar year (e.g. 2031), not an age (e.g. 57). Existing data stored with the age value should be updated by re-saving the profile.

**Future considerations**
- Income frequency (monthly, weekly etc.) could be added to income sources in the same way budget lines support frequency — deferred to post-MVP
- State pension and defined benefit pension income will be added as dedicated income types in v0.2, using the existing `mrlx:IncomeSourceType_Retirement` hierarchy
