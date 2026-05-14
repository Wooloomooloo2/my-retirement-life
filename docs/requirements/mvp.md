# MVP Outline

This document defines the scope of the Minimum Viable Product (MVP) for My Retirement Life.

The MVP is intentionally narrow. The goal is a working, usable application that delivers genuine value for the simplest case — a single user, cash-only financial picture — before expanding to the full feature set.

---

## MVP Scope

### 1. Personal Profile

The user enters basic information about themselves:

- First and last name
- Date of birth / current age
- Employment status (employed, self-employed, not working, retired)
- Target retirement age
- Life expectancy (used as the planning horizon)
- Base currency
- Country / jurisdiction

Income is managed separately on the Income screen (see section 2).

---

### 2. Income Sources

The user can add multiple income sources, each with independent start and end dates. This enables modelling of:

- Employment income stopping at retirement
- Rental income continuing indefinitely through retirement
- Spouse or partner income with its own timeline
- Any income that begins or ends at a specific year

Each income source has:
- Name (e.g. "Main salary", "Rental income — Manchester")
- Type (from the Income Source Type taxonomy)
- Annual net amount
- Annual growth rate (% change per year)
- Start year (optional — blank if already active)
- End year (optional — blank if indefinite)
- Net of tax flag

**Note:** This is an expansion beyond the originally planned single Employment income. Multiple income sources with independent start/end dates were implemented in MVP because they directly enable the core use case of modelling rental income, spouse income, and other non-employment income that does not stop at retirement.

---

### 3. Financial Picture — Cash Only

For the MVP, only cash-based assets are supported. Other asset classes are deferred to post-MVP releases.

The user can add one or more cash accounts:

- Account name
- Account type (Current, Savings, Fixed term, Tax-advantaged, Other)
- Current balance and balance date
- Currency (any supported currency with a manual exchange rate for non-base currencies)
- Annual interest rate
- Country / jurisdiction
- Optional notes

MVP projection applies a weighted average interest rate across all accounts. Per-account interest tracking is post-MVP.

---

### 4. Budget

The user enters spending as individual budget lines with flexible frequency:

- Name (e.g. "Mortgage", "Groceries", "Netflix")
- Type (Mandatory, Discretionary, Loan)
- Amount and frequency (Weekly, Fortnightly, Twice monthly, Monthly, Quarterly, Annually)
- Annual growth rate % (for modelling inflation or lifestyle changes)
- Loan end year (for loan repayments — line is automatically removed after this year)

The projection engine normalises all frequencies to annual amounts.

---

### 5. Life Events

One-off financial events at a specific future year:

- Name and optional notes
- Year the event occurs
- Amount (positive = cost, negative = receipt/windfall)
- Type (Large expenditure, Windfall, and post-MVP types)

---

### 6. Retirement Projection — Burndown Chart

The core output of the MVP: a year-by-year visualisation of the user's projected cash position from now through to their life expectancy.

The chart shows:
- Stacked annual spending bars by type (mandatory, discretionary, loans, life events)
- Annual income bars
- Running balance line on secondary axis
- Retirement year marked on x-axis

Calculations for MVP:
- Weighted average interest rate applied to total balance
- Each income source active only within its start/end year window
- Budget lines grown at their individual annual change rate (or default inflation rate if not set)
- Life events applied as lump sums in their specified year
- Loan repayments removed after their end year

---

### 7. Confidence Score

A simple indicator shown on both the dashboard and projection page:

- **Green** — cash lasts beyond life expectancy with a comfortable margin
- **Amber** — cash runs out within 5 years of life expectancy
- **Red** — cash runs out before life expectancy

---

## Multi-currency support (MVP)

Multi-currency is supported at the account level via user-maintained exchange rates. The user enters a manual exchange rate (e.g. 1 USD = 0.79 GBP) and the date it was set. The projection engine converts all account balances to the base currency using these rates. Live exchange rate fetching is post-MVP.

---

## Out of Scope for MVP

The following are explicitly deferred to later releases:

- Pensions (state or private) as account types
- Investment accounts (stocks, funds, bonds)
- Property assets
- Other asset classes (business interests, art, vehicles etc.)
- International pension systems (Social Security, 401k etc.) as dedicated account types
- Per-account interest tracking (MVP uses weighted average)
- Time-segmented budget growth rates (MVP uses single rate per line)
- Scenario comparison (side-by-side what-if analysis)
- Monte Carlo / probabilistic confidence scoring
- Data import/export
- Integration with My Financial Life companion app
- User accounts or cloud sync
- Auto-update mechanism for packaged distributions

---

## MVP Success Criteria

The MVP is considered complete when a user can:

1. Enter their personal profile
2. Add one or more income sources with start and end years
3. Add one or more cash accounts with balances
4. Enter a budget with spending lines at flexible frequencies
5. Add life events (costs and windfalls)
6. View a burndown chart showing their projected cash position to life expectancy
7. See a confidence score indicating whether their plan is on track

---

## Post-MVP Roadmap (indicative)

| Release | Focus |
|---------|-------|
| v0.2 | Retirement income account types (state pension, workplace pension, private pension, 401k) |
| v0.3 | Investment income and investment accounts |
| v0.4 | Property assets and equity release |
| v0.5 | Per-account interest tracking and drawdown prioritisation |
| v0.6 | Time-segmented budget growth rates (BudgetLineSegment) |
| v0.7 | Life events expanded (property transactions, relocation, caring costs) |
| v0.8 | Scenario comparison and what-if modelling |
| v0.9 | Packaging (PyInstaller / AppImage) for distribution |
| v1.0 | Full feature set, public release |
