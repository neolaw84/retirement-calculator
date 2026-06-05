# Retirement Calculator

## Core Calculator

Given the following inputs:

* Current year/age
* Retirement start year/age
* The year/age the user's superannuation kicks in
* Salary income (to calculate super contribution)
* Inflation rate function (see Rate Functions below)
* Non Real-Estate (NRE) Assets outside of super (see Assets below)
* The contribution of user to NRE Assets outside of super before Retirement Start Age
* Dividends/Distribution/Interest (any ordinary income) component from Non Real-Estate Assets
* Capital Gain component from NRE Assets (especially if they are ETFs) 
* High-level Drawdown Policies (Waterfall, Blended, Greedy)
* Real Estate (RE) Assets outside of super (see RE Assets below)
* Additional concessional contribution to super
* Carry-forward concessional contribution to super (yes/no)
* Expenses (today's dollars)
* Expected Expenses after retirement (today's dollars)
* Expected growth rate of NRE/RE/Super assets

The output is a data frame containing assets, income, expenses, drawdown split, and tax paid for each year until age 99.

### Tax Regime

Assume Australian Federal Income tax with May 12, 2026 Budget's Tax changes:

* **Trust Distributions**: 30% non-refundable credit (Budget 2026 rule). Character of income is retained.
* **CGT Transition (2027)**: 
    * Pre-2027-07-01: 50% discount on nominal gains.
    * Post-2027-07-01: No discount. Taxed on **Inflation-indexed Real Gains** with a **30% floor** on the tax rate.
* **Negative Gearing**: Losses from property acquired after 2026-05-13 are ring-fenced to the real estate pool.

### Rate Functions

* **Constant**: Steady rate.
* **Normal**: Randomly drawn from normal distribution.
* **Historical**: Random sampling from provided historical returns.

### Drawdown Policies (Orchestration)

* **Waterfall**: Draws from buckets in sequence (e.g., Trust → NRE → Super).
* **Blended**: Draws from multiple buckets simultaneously (e.g., 50/50).
* **Greedy**: Global selection of the lowest-tax-friction parcel across NRE and Trust.

### Drawdown Strategies (Asset-level)

* **Last In First Out (LIFO)**
* **First In First Out (FIFO)**
* **Tax Optimized (Greedy)**: Sells parcels with minimum tax liability first.
* **Rebalancing**: Forces (Age - 10)% Bonds / remainder Stocks split.

### RE Assets

* **property id**: 1-based auto-increment.
* **valuation at 2027, July 1st**: Reference cost-base for the 2026 Budget CGT regime.
* **rent income**: Net of expenses.
* **growth rate**: Rate function.

---

## Delivery Contract for Code Changes (Spec-driven + TDD)

Every behaviour change must follow this sequence:

1. **Spec first**: update this file (`docs/specs.md`) with the behaviour, inputs, outputs, and acceptance criteria.
2. **Test first**: add/update a failing test in `tests/` that demonstrates the expected behaviour.
3. **Implementation**: make the minimum code change required to pass tests.
4. **Refactor**: improve structure without changing semantics.

### Definition of Done for behavioural changes

- Spec section updated and unambiguous.
- Relevant tests added/updated and passing.
- If assumptions changed: `docs/assumptions.md` updated.
- If design decisions/exceptions were made: `docs/decisions_made.md` updated.

### Size and SOLID guardrails

- Function guideline: **40–60 lines**.
- Module guideline: **200–300 lines**.
- Exceptions are allowed only with clear rationale and must be documented in `docs/decisions_made.md`.
- Automated CI guardrail: `scripts/check_size_guardrails.py` prevents new unapproved size exceptions and prevents growth of existing exceptions.
