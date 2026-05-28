# ADR-015: Account Contributions

**Date:** 2026-05-18
**Status:** Accepted
**Deciders:** Project owner

---

## Context

The projection engine currently models account balances as a closed system: each
account starts at its recorded balance, grows at its configured rate, and is drawn
down when spending exceeds income. There is no mechanism to model the regular inflows
that most users have in the accumulation phase — pension contributions, ISA top-ups,
investment account transfers.

This creates two problems:

1. **Inaccurate projections.** A user contributing £800/month to a SIPP is adding
   £9,600/year to that account. The engine ignores this entirely, producing a
   materially lower projected balance at retirement for any user still in accumulation.

2. **Missing budget item.** Regular contributions are a real cashflow commitment —
   money that leaves the user's income and enters a savings vehicle. Without modelling
   them, the budget is understated and the net cashflow available for spending is
   overstated.

Both effects compound over a multi-decade projection and represent a significant
accuracy gap for any user who has not yet retired.

---

## Options considered

### Option A — Properties directly on `mrl:Account`

Add `mrl:regularContributionAmount`, `mrl:regularContributionFrequency`,
`mrl:contributionStartYear`, and `mrl:contributionEndYear` as datatype/object properties
on `mrl:Account`.

**Limitation:** One set of contribution properties per account. Cannot model employee +
employer contributions separately, or a contribution that changes amount over time.
Would require a breaking data migration if multiple contributions per account are ever
needed.

### Option B — Dedicated `mrl:AccountContribution` class (chosen)

A lightweight class linked to accounts via `mrl:hasContribution`. Each contribution
instance carries its own amount, frequency, start/end years, and an optional note.
Multiple `AccountContribution` instances can be linked to the same account, enabling
future scenarios such as employee + employer contributions.

**For v1.0:** the UI presents a single contribution section per account (add/edit/remove
one contribution). The multi-contribution capability exists in the data model but the
UI does not surface it until a future release.

### Option C — Extend `mrl:BudgetLine` with a contribution flag

Add an `isContribution` boolean and `mrl:contributionAccount` pointer to `mrl:BudgetLine`.
Contributions are budget lines that also credit a specific account.

**Rejected** because:
- Contributions are semantically different from spending: they do not reduce net worth,
  they transfer wealth between a cashflow pool and an investment vehicle.
- Mixing them with regular budget lines clutters the budget management UI.
- It couples the account model to the budget model in a way that complicates both.

---

## Decision

### 1. New ontology class: `mrl:AccountContribution`

```
mrl:AccountContribution a owl:Class ;
    rdfs:label "Account Contribution"@en ;
    rdfs:comment "A regular scheduled contribution to an account."@en .
```

Properties on `mrl:AccountContribution`:

| Property | Type | Description |
|---|---|---|
| `mrl:contributionAmount` | `xsd:decimal` | Amount per period (in the account's currency) |
| `mrl:contributionFrequency` | `→ mrlx:FrequencyType_*` | Reuses existing frequency vocabulary |
| `mrl:contributionStartYear` | `xsd:integer` | First year contributions are active (optional; defaults to current year) |
| `mrl:contributionEndYear` | `xsd:integer` | Last year contributions are active (optional; defaults to retirement year) |
| `mrl:contributionNote` | `xsd:string` | Optional free-text note (e.g. "Employer match included") |
| `mrl:contributionOwner` | `→ mrl:Account` | The account this contribution credits |

New object property on `mrl:Account`:

| Property | Type | Description |
|---|---|---|
| `mrl:hasContribution` | `→ mrl:AccountContribution` | Links zero or more contributions to an account |

### 2. Projection engine changes

Contributions are processed in the year loop **after growth is applied, before
cashflow netting**:

```
For each active AccountContribution in year Y:
    annual_amount = contributionAmount × frequency_multiplier
    balances[account_label] += annual_amount     ← credits the account
    contribution_spending   += annual_amount     ← debits the cashflow
```

`contribution_spending` is added to the total spending figure before computing
`pre_net = income - total_spending`. This correctly models the dual nature of a
contribution: it is simultaneously a cashflow outflow (money leaves income) and a
balance inflow (money enters the account).

A contribution is **active** in year Y if:
- `contributionStartYear` is absent, OR `Y >= contributionStartYear`
- `contributionEndYear` is absent, OR `Y <= contributionEndYear`

Default behaviour if start/end years are not set: contribution is active from the
current year until the retirement year. This is the most common real-world pattern
(contributing during working life, drawing in retirement).

**New projection output fields:**

`run_projection()` returns two new series:
- `account_contributions` — `{label: [annual_contribution_y0, y1, ...]}` for the
  per-account contribution detail chart
- `total_contributions` — cumulative sum of all contributions over the projection
  (displayed in the projection summary)

**Monte Carlo:** contributions are pre-computed deterministically (one value per year,
no σ). In the MC loop they are subtracted from the investment pool cashflow in the
same pass as income and spending.

### 3. UI placement

Contributions are managed on the account add/edit form for both cash and investment
accounts, in a collapsible **"Contributions"** section (same DaisyUI collapse pattern
as the Tax & Drawdown section). Fields:

- Amount (numeric)
- Frequency (select — same options as budget lines)
- Start year (optional; hint: "Leave blank to start from current year")
- End year (optional; hint: "Leave blank to stop at retirement year")
- Note (optional free-text)

A **remove contribution** button clears the contribution from the account.

### 4. Budget page visibility

The budget page gains a read-only **"Account contributions"** section derived from
account data at render time — not stored as `BudgetLine` instances. This section lists
each active contribution with the account name, amount, frequency, and annualised total.
The budget page totals include contributions in the overall spending calculation so the
user has a complete picture of cashflow commitments.

### 5. Projection page display

The projection assumptions section shows `total_contributions` alongside
`total_tax_paid` and other summary figures. The per-account detail chart
(`/accounts/{n}/projection`, `/investments/{n}/projection`) gains a third bar
series showing the annual contribution alongside growth earned and drawdown taken,
making the full per-account cashflow picture visible.

---

## Consequences

**Positive**
- Projections are materially more accurate for users still in the accumulation phase.
- Contributions appear in both the account form and the budget overview — visible
  in both contexts where users would expect them.
- The frequency vocabulary (`mrlx:FrequencyType_*`) is reused without modification.
- `mrl:AccountContribution` is cleanly separable from both `mrl:Account` and
  `mrl:BudgetLine` — no coupling between those two existing classes.
- Multiple contributions per account (employee + employer) are supported by the data
  model from day one, even if the v1.0 UI only exposes one.

**Trade-offs accepted**
- A new ontology class requires an ontology version bump and a force-reload.
- The projection engine year loop gains a contribution processing pass — a minor
  performance cost, negligible at the scale of a personal projection.
- The budget page "Account contributions" section is derived at render time, not
  from stored BudgetLine instances. This means it is not editable from the budget
  page — only from the account form.

**Backup / restore**
`settings_route.py` must be updated to export and restore `mrl:AccountContribution`
instances alongside accounts.

**Future considerations**
- Contribution growth modelling (contribution amount increasing at inflation or a
  fixed annual rate). Currently contributions are fixed in nominal terms. Deferred.
- Multiple active contributions per account surfaced in the UI (v1.1).

---

## v1.1 (2026-05-27) — Employer-portion split

Initially this ADR deferred `isEmployerContribution` to a future revision. v1.1
implements employer contributions using a different shape than the originally
sketched boolean flag: instead of two `AccountContribution` instances per account
(one employee, one employer), a single contribution carries both an employee and
an employer amount in the same currency and frequency. This keeps the v1.0
constraint of one contribution per account in the UI and avoids a multi-row form
rewrite that was the larger blocker for the original design.

### Ontology additions (1.0.3)

| Property | Type | Description |
|---|---|---|
| `mrl:employerContributionAmount` | `xsd:decimal` | Employer portion, per period in the account's currency. Shares the contribution's frequency. Optional; defaults to 0 (no employer portion). |

### Engine semantics

In a given active year for a contribution:
- Account balance is credited with `(employee_amount + employer_amount) * frequency_multiplier`, scaled by the contribution's growth rate.
- `year_contribution_spending` (deducted from cashflow) is credited with only the **employee** portion.

When `employerContributionAmount` is absent or zero, the engine produces
bit-identical output to v1.0 — verified by the `_float()` default-to-zero read
path.

### UI placement

The account/investment edit form's "Regular contribution" collapsible gains one
new field, "Employer contribution per period", placed below the existing
Amount/Frequency pair and above Start/End. The existing "Amount per period"
field is relabelled "Your contribution per period". Help text on the section
explains the cashflow asymmetry. The live annual-equivalent hint shows the
split when both parts are non-zero: "Annual: £X you + £Y employer = £Z total".

### Budget page

The read-only "Account contributions" table on `/budget` shows each
contribution's employee portion in the primary cells and the employer portion
as a small subscript line ("+ £200 employer"). The footer separates the two
sums and labels the employee total as "your portion — counted in cashflow" and
the employer total as "credits balances, not your cashflow". The budget chart's
contributions stacked area continues to show only the cashflow-accurate
employee portion.

### Backup/restore

`settings_route.py` exports `employerAmount` on each contribution and restores
it. Old backups without the field round-trip cleanly (the engine treats absent
as zero).

### Rejected alternative

A multi-row contributions UI with one `AccountContribution` per row and a
boolean `isEmployerContribution` flag was considered. Closer to the original
ADR-015 design intent but requires a larger form rewrite (add/remove rows, list
rendering, multiple deletion paths). The split-fields-on-one-contribution
design captures the dominant real-world pattern (one workplace pension with
employee + matching employer contribution) with a single new field. A future
revision can move to the multi-row design if users need independent start/end
dates per side, vesting tiers, or multiple employer matches.

---

## v1.2 (2026-05-28) — Payroll / salary-sacrifice flag

v1.1 always debited the employee portion (`mrl:contributionAmount`) from
cashflow. That is correct only when the contribution is paid from take-home pay
(e.g. an ISA top-up from your bank account). For an **occupational pension or
salary-sacrifice** arrangement the contribution is deducted from gross pay
*before* you receive net pay, so it was never part of the net income the app
models. Debiting it again double-counts the reduction.

The engine never taxes income sources — tax is applied only on drawdown
(ADR-013), so entered income is treated as net/take-home. v1.2 adds a boolean
that lets the employee portion behave, cashflow-wise, exactly like the employer
portion: it credits the balance but is excluded from cashflow.

### Ontology additions (1.0.4)

| Property | Type | Description |
|---|---|---|
| `mrl:contributionFromPayroll` | `xsd:boolean` | True when the employee portion is deducted at source from gross pay. Credits the balance but is excluded from cashflow and from the budget chart's account-contributions stack. Optional; defaults to false (paid from net income, debits cashflow as in v1.0/v1.1). |

### Engine semantics

In a given active year, `from_payroll` only changes the cashflow side:
- Account balance is still credited with `(employee + employer) × growth_factor` (unchanged).
- `year_contribution_spending` (the cashflow deduction) adds the employee portion **only when `from_payroll` is false**. Employer portions are excluded regardless (v1.1).

When `contributionFromPayroll` is absent or false the engine produces
bit-identical output to v1.1 — the `_val(...) == "true"` read defaults to false.

### UI

The contribution form gains a checkbox, "Your contribution is taken from
payroll (pre-tax / salary sacrifice)", below the employer field. Its help text
explains that the amount still credits the account but won't be deducted from
net income again, so the user should enter income as take-home pay. The live
annual hint appends "· your portion is pre-tax (not deducted from net income)"
when ticked.

### Budget page

`compute_annual_contributions_series()` skips payroll contributions (they are
not a cashflow cost). The read-only table marks a payroll row "from payroll
(pre-tax — not from net income)" and de-emphasises its annual figure. The footer
splits into three lines: the cashflow-counted total (non-payroll employee
portions), a payroll/salary-sacrifice subtotal, and the employer subtotal — the
latter two labelled "credits balances, not your cashflow".

### Backup/restore

`settings_route.py` exports `fromPayroll` on each contribution and restores it
(writes the triple only when true). Old backups without the field round-trip as
false.

### Rejected alternative

Modelling gross income with a full gross→net tax engine in the accumulation
phase (so a salary-sacrifice contribution would reduce taxable income and tax)
was considered and rejected: the app deliberately treats income as net
(ADR-013 taxes only withdrawals), and a per-period accumulation-phase tax model
is a much larger change than the one real distinction users need here — whether
a contribution comes out before or after they're paid.
