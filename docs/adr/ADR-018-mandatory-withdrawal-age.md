# ADR-018: Mandatory (RMD-style) withdrawal age — retiring the drawdown cutoff

**Date:** 2026-06-03
**Status:** Accepted
**Deciders:** Project owner

---

## Context

ADR-011 gave each account a `mrl:drawdownMaxAge` defined as a **hard cutoff**:
once the person's age exceeds it, `_is_eligible()` returns `False` and the
account can no longer be drawn. This produced a serious, silent modelling
failure, surfaced while testing the new Drawdown Strategy page:

An account (a US 401(k)) had `drawdownMaxAge = 75`. From age 75 the engine
treated it as undrawable. By that year every other account was exhausted, so
the year's spending shortfall had **no eligible account to draw from**. The
engine does not record an uncovered shortfall — it simply draws nothing — while
the ~£3M pot kept compounding, untouched, to ~£9M. The projection therefore
reported "never runs out / On track" on the strength of money the model itself
said could never be spent.

Two things were wrong:

1. **The semantics.** A "you may never touch this account again after age N"
   rule does not correspond to any real product. What the owner actually meant
   by an age limit is the opposite: the age at which withdrawals are *forced to
   begin* — the US 401(k)/IRA Required Minimum Distribution (RMD) pattern, and
   similar forced-decumulation rules elsewhere.

2. **The silent under-funding.** When drawdown cannot meet spending, the engine
   should make that visible rather than quietly continuing — but that is a
   separate, broader engine concern (tracked as a follow-on) and is not decided
   here.

## Options considered

- **Delete `drawdownMaxAge` entirely.** Removes the misleading cutoff but loses
  the ability to model forced decumulation, which is a real and common rule the
  owner wants.
- **Keep the cutoff but warn when it strands money.** Leaves the wrong mental
  model in place; the warning treats a symptom.
- **Redefine it as a forced minimum withdrawal from an age (chosen).** Matches
  the real-world rule, removes the stranding, and makes the projection honest.

For the forced amount, three sub-options were weighed: deplete-over-remaining-
life (`balance ÷ years left`), a per-account user-set percentage, and the US IRS
Uniform Lifetime Table. The **user-set percentage** was chosen — it is
jurisdiction-neutral (the tool spans countries), simple to enter and reason
about, and avoids baking a single country's tax table into a generic engine.

## Decision

Retire the `mrl:drawdownMaxAge` cutoff and replace it with a forced-withdrawal
pair on `mrl:Account` (ontology **1.0.6**):

- **`mrl:mandatoryWithdrawalAge`** (`xsd:decimal`) — the age from which a minimum
  withdrawal is compulsory each year.
- **`mrl:mandatoryWithdrawalRate`** (`xsd:decimal`) — the minimum percentage of
  the account's current balance that must come out each year once that age is
  reached.

Engine behaviour:

- `_is_eligible()` **no longer** consults `drawdownMaxAge`; an account is never
  blocked from access by age-upper-bound. (Min-age, earliest-date, and
  latest-date eligibility are unchanged.)
- Each year, after the normal shortfall drawdown, any account whose
  `mandatoryWithdrawalAge` is reached and whose `mandatoryWithdrawalRate > 0` is
  topped up to its required minimum (`balance × rate%`), counting whatever was
  already withdrawn from it that year. The forced amount is taxed through the
  existing ADR-013 two-layer model, and the after-tax surplus (it was not needed
  for spending) is swept to the spending account via the existing surplus-
  routing fallback. Setting the age **without** a rate does nothing — the
  account is simply normally drawable, so nothing strands.

Migration: `drawdownMaxAge` is marked deprecated but retained on the class. On
data load, any account carrying `drawdownMaxAge` with no `mandatoryWithdrawalAge`
has the age copied across; the rate is left unset. The immediate effect is that
previously-stranded accounts become normally drawable again; the owner opts into
forced withdrawals by setting a rate.

## Consequences

- **Honest projections.** Tax-advantaged pots can no longer hide as un-spendable
  net worth; either they fund spending when needed or they are forced out
  (taxed) and re-banked.
- **A real capability gained.** 401(k)/IRA RMDs and similar rules are now
  expressible, jurisdiction-neutrally, with one age + one rate per account.
- **Parity preserved.** With no `mandatoryWithdrawalRate` set anywhere, engine
  output is byte-identical to the pre-1.0.6 engine; the only behavioural change
  from migration alone is the removal of the cutoff (accounts that were stranded
  become drawable).
- **Requires `tools/reload_ontology.py`** (app closed) for the new properties to
  appear in the live store; backend writes do not depend on the declaration.
- **The forced amount is an approximation** — a flat user percentage of the
  current in-loop balance, not an IRS divisor on the prior year-end balance.
  Adequate for a planning tool; a jurisdiction-accurate table is a possible
  future refinement.
- **Carried-forward concern (not decided here):** the engine still does not
  flag a spending shortfall it cannot fund from eligible accounts. Removing the
  cutoff makes this far less likely to bite, but a "spending unfunded from year
  N" signal remains a worthwhile follow-on.
