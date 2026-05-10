# MVP Outline

This document defines the scope of the Minimum Viable Product (MVP) for My Retirement Life.

The MVP is intentionally narrow. The goal is a working, usable application that delivers genuine value for the simplest case — a single user, single currency, cash-only financial picture — before expanding to the full feature set.

---

## MVP Scope

### 1. Personal Profile

The user enters basic information about themselves:

- Date of birth / current age
- Employment status (employed, self-employed, not working, retired)
- Annual net income (take-home pay after tax)
- Target retirement age or year
- Life expectancy (used as the planning horizon)
- Base currency (single currency for MVP)

---

### 2. Financial Picture — Cash Only

For the MVP, only cash-based assets are supported. Multi-currency and other asset classes (investments, pensions, property) are deferred to post-MVP releases.

The user can add one or more cash accounts:

- Account name (e.g. "Current account", "ISA", "Savings account")
- Current balance
- Annual interest rate
- Whether the account is a saving or spending account

---

### 3. Budget

The user enters a high-level annual or monthly budget:

- **Income adjustments** — ability to increase or decrease annual income by a percentage per year (e.g. expected pay rises, or reduction to part-time before retirement)
- **Mandatory spending** — essential outgoings (housing costs, utilities, food, transport, insurance, loan repayments)
- **Discretionary spending** — lifestyle spending (holidays, dining, hobbies, subscriptions)
- Each budget line can optionally have an annual percentage increase or decrease applied (for modelling inflation or lifestyle changes)

---

### 4. Life Events — Simple Expenditures

A basic life events system allowing the user to add one-off large expenditures at a specific future year:

- Event name (e.g. "New car", "Home renovation", "Help child with deposit")
- Year the expenditure occurs
- Amount

This gives the user a way to see the impact of known future costs on their retirement trajectory.

---

### 5. Retirement Projection — Burndown Chart

The core output of the MVP: a year-by-year visualisation of the user's projected cash position from now through to their life expectancy.

The chart shows:
- Projected cash balance each year
- The point at which cash runs out (if applicable)
- The effect of interest, inflation, budget, and life events

Calculations for MVP:
- Apply annual interest rate to savings
- Apply a configurable inflation rate to spending
- Deduct annual budget from cash position each year
- Apply one-off life event expenditures in the relevant year
- Income continues until retirement year, then stops

---

### 6. Confidence Score

A simple indicator shown alongside the chart:

- **Green** — cash lasts beyond life expectancy with a comfortable margin
- **Amber** — cash runs out within 5 years of life expectancy
- **Red** — cash runs out before life expectancy

The score is deliberately simple for MVP — a straightforward calculation, not a probabilistic model. Monte Carlo simulation and scenario modelling are post-MVP features.

---

## Out of Scope for MVP

The following are explicitly deferred to later releases:

- Multi-currency support
- Pensions (state or private)
- Investments (stocks, funds, bonds)
- Property assets
- Other asset classes (business interests, art, vehicles etc.)
- Future windfalls (inheritance, bonuses, asset sales)
- International pension systems (Social Security, 401k etc.)
- Scenario comparison (side-by-side what-if analysis)
- Monte Carlo / probabilistic confidence scoring
- Data import/export
- Integration with My Financial Life companion app
- User accounts or cloud sync

---

## MVP Success Criteria

The MVP is considered complete when a user can:

1. Enter their personal profile
2. Add one or more cash accounts
3. Enter a budget with income and spending lines
4. Add at least one life event
5. View a burndown chart showing their projected cash position to life expectancy
6. See a confidence score indicating whether their plan is on track

---

## Post-MVP Roadmap (indicative)

| Release | Focus |
|---------|-------|
| v0.2 | Add pension income (state and private) |
| v0.3 | Add investments and other assets |
| v0.4 | Multi-currency support |
| v0.5 | Property assets and equity release |
| v0.6 | International asset types (401k, Social Security etc.) |
| v0.7 | Life events expanded (income changes, moving abroad, caring costs) |
| v0.8 | Scenario comparison and what-if modelling |
| v1.0 | Full feature set, packaging for distribution |
