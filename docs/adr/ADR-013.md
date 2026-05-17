# ADR-013: Generic Tax Treatment Model for Accounts and Withdrawals

**Date:** 2026-05-17
**Status:** Accepted
**Deciders:** Project owner

---

## Context

Drawdown tax has two dimensions that must both be captured:

1. **Account jurisdiction** — the country where the account is domiciled determines
   source-country tax treatment at point of withdrawal. A US 401(k) has pre-tax
   contributions and fully taxable withdrawals; a UK ISA has post-tax contributions
   and fully exempt withdrawals; a GIA/brokerage account taxes only the gains
   portion.

2. **Residence jurisdiction** — the person's country of residence determines their
   aggregate annual tax liability: income below the personal allowance is untaxed,
   income above it is taxed at the marginal rate.

For individuals with accounts in multiple countries, bilateral tax treaties govern
withholding rates and foreign tax credits. Fully encoding these treaty rules is out
of scope for a privacy-first personal retirement planning tool:

- Treaties change; encoding them would require annual maintenance.
- Their application is interpretation-dependent and fact-specific.
- Cross-border situations require professional tax advice.

A model is needed that correctly structures the two-layer problem and gives the
user full control over the effective rates, without encoding jurisdiction-specific
tax law.

---

## Decision

### 1. Two-layer model, user-specified effective rates

The engine separates account-level (source jurisdiction) tax from residence-level
(aggregate income) tax. Both layers use user-supplied rates rather than computed
rules.

#### Account level — source jurisdiction

Added to `mrl:Account` (all subtypes):

| Property | Type | Purpose |
|---|---|---|
| `mrl:accountJurisdiction` | `→ mrl:Jurisdiction` | Where the account is domiciled. Informational; drives UI guidance on typical treatment. Does not trigger automatic rate lookup. |
| `mrl:taxTreatment` | `→ mrlx:TaxTreatmentType` | Structural type (see §2). Drives UI prompts, tooltips, and documentation. |
| `mrl:effectiveWithdrawalTaxRate` | `xsd:decimal` | The rate the user expects to pay at point of withdrawal from this account, **after** any applicable treaty relief. For a UK ISA: 0. For a US 401(k) held by a UK resident: typically 0–25% depending on treaty and circumstances. User-specified. |
| `mrl:annualTaxFreeWithdrawal` | `xsd:decimal` | Amount withdrawable per year from this account before the effective rate applies. Handles instruments such as the UK pension 25% PCLS lump sum (modelled as an annual allowance equivalent) or annual ISA-equivalent allowances. |

#### Residence level — on `mrl:ProjectionSettings`

| Property | Type | Purpose |
|---|---|---|
| `mrl:annualPersonalAllowance` | `xsd:decimal` | Total income threshold in the person's country of residence before income tax applies. Covers income from all accounts and income sources. |
| `mrl:residenceIncomeTaxRate` | `xsd:decimal` | Marginal income tax rate above the personal allowance, in the country of residence. |

#### Jurisdiction reference data — on `mrl:Jurisdiction`

| Property | Type | Purpose |
|---|---|---|
| `mrl:standardPersonalAllowance` | `xsd:decimal` | Reference personal allowance for this jurisdiction. Used as a default starting point in the settings UI; the user overrides the live figure in `mrl:ProjectionSettings` as rates change annually. |

### 2. Tax treatment structural types (`mrlx:TaxTreatmentScheme`)

The structural type is informational and drives the UI, not the tax calculation.
The calculation uses the user-specified effective rates above.

| Concept | Description | Common examples |
|---|---|---|
| `mrlx:TaxTreatment_PreTaxWholeWithdrawal` | Contributions were pre-tax; the full withdrawal amount is treated as taxable income. | 401(k), Traditional IRA, SIPP, workplace defined-contribution pension |
| `mrlx:TaxTreatment_PostTaxGainsOnly` | Contributions were post-tax; only the gains portion of a withdrawal is taxable. Cost basis tracking is handled by the sister application (My Financial Life); this application uses an effective rate approximation. | GIA, general brokerage account |
| `mrlx:TaxTreatment_PostTaxTaxFreeWithdrawal` | Contributions were post-tax; withdrawals are fully exempt from tax. | ISA (cash and stocks & shares), Roth IRA, KiwiSaver (after qualifying age) |
| `mrlx:TaxTreatment_TaxFree` | No tax at any stage. | Premium bonds, NS&I accounts, cash savings below threshold |

### 3. Engine logic per year

```
For each account drawn in year Y:
  gross_withdrawal         = amount drawn from this account
  tax_free_used            = min(mrl:annualTaxFreeWithdrawal, gross_withdrawal)
  taxable_at_source        = gross_withdrawal − tax_free_used
  source_tax               = taxable_at_source × mrl:effectiveWithdrawalTaxRate
  net_cash_from_account    = gross_withdrawal − source_tax

Aggregate across all accounts drawn in year Y:
  total_taxable_income     = Σ taxable_at_source  (for all accounts)
  total_source_tax_paid    = Σ source_tax

Residence-level adjustment:
  if total_taxable_income ≤ mrl:annualPersonalAllowance:
    # Over-withheld at source in low-income years
    excess_tax = total_source_tax_paid  (in full, or prorated if partially over)
    residence_tax = 0
  else:
    income_above_allowance = total_taxable_income − mrl:annualPersonalAllowance
    residence_tax = income_above_allowance × mrl:residenceIncomeTaxRate
    # Net of tax already withheld at source:
    residence_tax = max(0, residence_tax − total_source_tax_paid)

net_annual_tax = total_source_tax_paid + residence_tax
```

The `net_annual_tax` figure feeds into the year's total balance calculation as an
additional outflow. It is also surfaced separately in the projection chart's data
table so the user can see the tax impact year by year.

### 4. No tax advice

The application provides a planning approximation, not a tax computation. The UI
must make this clear:

- Tooltips on `effectiveWithdrawalTaxRate` must read: *"Enter the rate you expect
  to pay on withdrawals from this account, after any tax treaty relief. For
  cross-border accounts, consult a tax adviser to confirm the applicable rate."*
- A notice on the projection page must state that tax figures are estimates based
  on user-supplied rates and do not constitute tax advice.

---

## Consequences

- The `projection.py` engine must track `annualTaxFreeWithdrawal` usage per account
  per year as a running counter within the projection loop (reset to zero at the
  start of each year).
- The projection results must expose `tax_paid[year]` as a first-class output
  alongside the balance arrays.
- The projection chart should offer an optional "show post-tax drawdown" overlay so
  users can see gross vs net drawdown amounts.
- Settings export/restore (`settings_route.py`) must include all new account-level
  and projection-settings tax properties.
- The accounts and investments UI pages must add tax treatment fields, preferably
  in a collapsible "Tax & Drawdown" section to avoid overwhelming users who do not
  have cross-border complexity.

### Future considerations

- **GIA cost basis.** `mrlx:TaxTreatment_PostTaxGainsOnly` currently uses an
  effective rate approximation because cost basis tracking is handled by the sister
  application (My Financial Life). When inter-application data portability is
  implemented (estimated v0.5+), actual cost basis data could be passed across,
  enabling a precise gains-only tax calculation for GIA accounts.
- **Per-jurisdiction tax profiles.** A future `mrl:MarketProfile` linked from
  `mrl:Jurisdiction` (see ADR-012 future considerations) could carry standard tax
  reference data alongside return statistics — personal allowances, marginal rates,
  treaty withholding rates — as an aide-memoire for the user rather than as
  computed values.
- **Multiple marginal rates.** Most jurisdictions have progressive tax bands, not a
  single marginal rate. The current model uses one user-specified rate. A future
  enhancement could support a list of band thresholds and rates on
  `mrl:ProjectionSettings`, computing the correct blended rate on total income.
  Deferred; adds significant UI complexity for a marginal accuracy gain in most
  retirement scenarios where income is typically in one or two bands.
