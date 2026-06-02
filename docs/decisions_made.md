# Decisions Made

This document records deliberate design decisions and known avoided paths. Coding agents must read this before brainstorming architectural alternatives to avoid reinventing the wheel or undoing intentional choices.

Each entry records: the decision, the rationale, and (where applicable) what was explicitly rejected and why.

---

## Tax Modelling

### D01 – Tax brackets are NOT indexed for inflation
**Decision**: The simulation keeps 2025-26 tax brackets fixed for the entire projection horizon.  
**Rationale**: ATO brackets historically change infrequently and unpredictably. Indexing them introduces false precision. Documented in `docs/assumptions.md` (item 1).  
**Rejected**: Automatically inflating thresholds by CPI each year — adds complexity without reliable historical basis.

### D02 – LITO Phase 1 rate is 5c per $1 (not 1.5c)
**Decision**: `_LITO_PHASE1_RATE = 0.05` (corrected from 0.015 in the initial MVP).  
**Rationale**: ATO-published LITO rules state 5c per $1 phaseout from $37,500 to $45,000, then 1.5c per $1 from $45,001 to $66,667. The MVP had a bug; it was corrected in the first review cycle.

### D03 – Tax bracket for $18,201–$45,000 is permanently fixed at 16%
**Decision**: The 16% rate is permanently fixed. The Budget 2026 announcements of 15% (from 1 July 2026) and 14% (from 1 July 2027) **will never be modelled** in this simulation.  
**Rationale**: The target audience is planning retirement over 30–60 year horizons where the bracket level has negligible impact on the outcome. Implementing year-aware brackets adds complexity and maintenance burden with no meaningful precision gain over the projection horizon.  
**Rejected permanently**: Year-indexed bracket schedules for this specific change.

### D04 – Working Australians Tax Offset (WATO, $250) will never be modelled
**Decision**: WATO is **assumed non-existent** in this simulation. It is not applied to any income calculation.  
**Rationale**: WATO is a small, employment-dependent offset that phases out at higher incomes. The target user's pre-retirement salary phase is not the primary modelling concern; the retirement drawdown phase (where WATO is irrelevant) is the core focus.  
**Rejected permanently**: Implementing WATO as a configurable offset.

### D05 – $1,000 instant work-related expense deduction will never be modelled
**Decision**: The instant $1,000 tax deduction (from 2026-27) is **not implemented and will not be implemented**.  
**Rationale**: In the context of retirement planning over decades, a fixed $1,000 deduction applicable only during working years has an immaterial effect on long-term projections. Noted as a deliberate simplification.

### D06 – Trust minimum 30% non-refundable credit (May 2026 Budget) IS modelled
**Decision**: The 30% non-refundable credit on discretionary trust distributions is applied inside `income_tax()` as a non-refundable credit (capped at gross tax, cannot produce a refund).  
**Rationale**: Direct implementation of the Budget 2026 rule.  
**Character retention**: The CGT component of a trust distribution retains its character (assessed at CGT rates with 30% floor post-2027), not as ordinary income.

### D07 – Div 293 threshold is total taxable income (not just salary)
**Decision**: `division_293_tax()` receives `total_taxable` (all income including NRE, rent, trust, CGT) as its income base, not just salary.  
**Rationale**: ATO rules: Div 293 threshold is income + concessional contributions. "Income" includes all assessable income. Bug fixed in second review cycle.

### D08 – CGT 2027 transition: bifurcated pre/post-2027 gain (NOT a cost-base forgiveness)
**Decision**: The CGT 2027 transition is implemented as a **bifurcated gain model**, not a cost-base forgiveness ("step-up") as in US tax law.

**Mechanism (from Budget 2026 Tax Explainer):**
1. **At simulation year 2027**: record each parcel's market value on 1 July 2027 as `value_at_2027`. The original cost base is retained.
2. **Pre-2027 gain** (crystallised at eventual sale, not at 2027): `(value_at_2027 − original_cost_base) × 50%` = assessable gain. Stored in `Parcel.discounted_gain_at_2027`.
3. **Post-2027 gain** (from 1 July 2027 onwards): the asset's *new effective cost base* for this portion is `value_at_2027`. Post-2027 real gain = `sale_price − (value_at_2027 × CPI_factor)` where `CPI_factor = CPI_at_sale / CPI_at_2027`. Taxed at `max(marginal_rate, 30%)`.
4. **At sale**: total assessable capital gain = `discounted_gain_at_2027 + post_2027_real_gain`.

**Verified example (Jane, from Budget Explainer)**:
- Bought 1 July 2022 for $800,000; value at 1 July 2027 = $1,131,371; sold 1 July 2032 for $1,600,000.
- Pre-2027: $331,371 × 50% = **$165,685** assessable.
- Post-2027: $1,600,000 − $1,131,371 × 1.025⁵ ≈ $468,629 − $148,671 = **$319,958** real gain.
- Total assessable = **$485,643**.

**What the code does**: `Parcel.discounted_gain_at_2027` stores the pre-2027 50%-discounted assessable gain. The parcel's `cost_base` is reset to `value_at_2027` only for the purpose of computing post-2027 CPI-indexed gains. This correctly implements the bifurcation.

**Why D08 is NOT the American step-up**: In the US, a step-up forgives the pre-death gain entirely. Here, pre-2027 gains are **deferred** (not forgiven) and assessed at sale via the 50% discount.

**Rejected**: Applying the 50% discount uniformly to the entire holding period gain (would understate tax for high-return assets and overstate for low-return assets post-2027).

### D09 – RE CGT uses `base_taxable_income` (not just salary) as the income base for rate calculation
**Decision**: RE sale CGT marginal rate is calculated on `base_taxable_income` (salary + NRE income + rent + trust distributions).  
**Rationale**: Bug fixed in second review cycle. Marginal rates must reflect the full taxable income picture for the year.

---

## Superannuation

### D10 – Superannuation modelled as a single balance with one growth rate
**Decision**: Super is tracked as `super_accumulation_balance` and `super_pension_balance`, both growing at `super_growth_rate`. No internal stock/bond split inside super.  
**Rationale**: The simulation's primary purpose is to model the interaction of all asset classes at the individual level. Internal super fund allocation is better handled by the fund itself. Adding it would require more configuration with marginal benefit given the simulation timestep.  
**Rejected**: Modelling super with an internal `NREAssetConfig`-style allocation — over-engineering for the current use case.

### D11 – Concessional contributions cap fixed at $32,500 post-2026
**Decision**: `_concessional_cap()` returns $30,000 for 2025-26, $32,500 for 2027+.  
**Rationale**: The cap is indexed to AWOTE and changes every few years. Modelling as fixed at the next known level is a documented approximation. See `docs/assumptions.md` (item 10).

### D12 – Carry-forward uses a 5-year rolling window
**Decision**: Unused concessional contributions are tracked in a list of up to 5 values (oldest entry dropped when a 6th is added).  
**Rationale**: ATO rules allow carry-forward unused amounts from the previous 5 years. The rolling window directly matches this rule.

### D13 – Preservation age is 60; super_kicks_in_age is user-configurable; super minimum drawdown mandatory from age 65
**Decision**:
- `super_access_age` (preservation age) = 60 for all users (non-configurable).
- `super_kicks_in_age` (the age at which the user *chooses* to start drawing from **superannuation**) is user-configurable. It must be ≥ 60.
- At age **65**, ATO account-based pension minimum drawdown rates apply to the **super pension balance** regardless of user preference. This rule applies to superannuation only and has no bearing on NRE (non-super investment) drawdowns.

**Minimum drawdown rates (account-based pension, ATO)**:
| Age bracket | Minimum % of balance per year |
|-------------|-------------------------------|
| Under 65    | 4% |
| 65–74       | 5% |
| 75–79       | 6% |
| 80–84       | 7% |
| 85–89       | 9% |
| 90–94       | 11% |
| 95+         | 14% |

**Rationale**: All individuals born after 30 June 1964 have a preservation age of 60. `super_kicks_in_age` being configurable lets users model conservative strategies (e.g., draw super at 65, 67, or 70). Age 65 minimum drawdown rules are legislated and non-optional.

### D14 – Transfer Balance Cap (TBC) is inflation-indexed in the simulation
**Decision**: `tbc_nominal = config.transfer_balance_cap * (cpi_now / 100.0)` — the TBC is scaled by CPI each year.  
**Rationale**: The ATO adjusts the TBC periodically by CPI. Applying the configured CPI rate is a reasonable approximation.

---

## Real Estate

### D15 – Negative gearing: two critical dates; three property categories
**Decision**: The negative gearing ring-fence is governed by **two dates** from the Budget 2026 Tax Explainer:

1. **7:30pm AEST, 12 May 2026** — Budget night (announcement date)
2. **1 July 2027** — Policy commencement date

**Rules by category (established housing only; see below for new builds):**

| Property acquired | Negative gearing treatment |
|---|---|
| Before announcement (7:30pm AEST 12 May 2026) | Fully grandfathered — unrestricted negative gearing until property is sold |
| Between announcement and 30 June 2027 | May negatively gear during FY2026-27 (i.e., the period of ownership in that year), but from 1 July 2027 losses are ring-fenced to residential property income only (carry-forward allowed) |
| From 1 July 2027 onwards | Losses can only offset residential property income from day 1 of ownership (carry-forward allowed, but never deductible against wages/other income) |

**New builds** (properties that genuinely add to supply per Budget definition) are **exempt**: unrestricted negative gearing before and after 1 July 2027.

**Simulator simplification (annual timestep)**: The simulator cannot distinguish intra-year purchase dates. All RE assets are treated as established housing (new builds not modelled). The mapping used:
- `year_bought <= 2025`: fully grandfathered
- `year_bought == 2026` or `2027`: ring-fenced from simulation year `2028` onwards (can negatively gear in the year of purchase)
- `year_bought >= 2028`: ring-fenced from day 1 of ownership

**Current code state**: **FIXED in refactoring (2026-06-02)**. `simulation/_phases.py` now uses the correct two-date categorisation logic in `_process_re_income()` and `_compute_re_assessable()`:
- `is_new = (year_bought >= 2028) or (year_bought in (2026, 2027) and year >= 2028)`
- Ring-fence assessment only activates from year 2028 (`if year >= 2028:`).

**Rejected**: Modelling new builds as a separate RE asset type — too much data complexity for the current use case.

### D16 – RE expenses are 1% of property value per year (not 10% of gross rent)
**Decision**: `re_expenses = current_re_value * 0.01`.  
**Rationale**: The simulator uses a value-based expense model. This approximates ongoing maintenance and management.  
**Status**: **FIXED in refactoring (2026-06-02)**. `docs/assumptions.md` item 23 now correctly documents the `1% of current property value` model, replacing the earlier incorrect "10% of gross rent" description.

### D17 – Mortgage amortised over 30 years from purchase date
**Decision**: Annual mortgage payment uses the standard annuity formula with the sampled loan interest rate. Remaining term = `max(0, 30 - years_elapsed)`.  
**Rationale**: Standard 30-year P&I loan is the most common Australian residential mortgage structure.

### D18 – Depreciation is not modelled
**Decision**: No building depreciation or plant & equipment deductions.  
**Rationale**: Requires fund/property-specific schedules and adds data complexity. Documented as a simplification in `docs/assumptions.md` (item 21).

---

## NRE Assets

### D19 – NRE asset price starts at $1.00 per unit
**Decision**: `nre_price = {"stock": 1.0, "bond": 1.0}` at simulation start.  
**Rationale**: Simplification. The initial parcel has `cost_base = initial_value` and `units = initial_value`. The unit price tracks growth multiplicatively from that base.

### D20 – NRE capital gain distribution is reinvested as new parcels
**Decision**: The `capital_gain_component_pct` fraction of NRE distributions creates new parcels proportional to the target allocation.  
**Rationale**: In Australian ETFs, the capital return/gain component of a distribution is a realised CGT event (new cost base = distribution amount). The cash is received and re-deployed.

### D21 – Franking credits are not modelled
**Decision**: ETF franking credits are ignored.  
**Rationale**: Franking credit rates vary by fund and require fund-specific data. Adding a configurable franking rate is a future enhancement.

---

## Simulation Engine

### D22 – Annual timestep
**Decision**: The simulation runs year-by-year, not month-by-month.  
**Rationale**: Long-horizon retirement projections (30–60 years) have inherent uncertainty that makes monthly precision misleading. The annual timestep keeps the model comprehensible and fast.  
**Rejected**: Monthly timestep — adds 12× complexity and state, with no meaningful accuracy gain over the projection horizon.

### D23 – Iterative solver capped at 5 iterations
**Decision**: The funding gap / drawdown / tax loop runs at most 5 times per year.  
**Rationale**: In practice, convergence occurs in 2–3 iterations. 5 is a safe upper bound that prevents infinite loops.  
**Rejected**: Full Newton-Raphson solver — over-engineered for a loop that converges quickly.

### D24 – Age Pension is not modelled (v1)
**Decision**: Age Pension entitlements are not calculated or included in income.  
**Rationale**: Age Pension is means-tested, assets-tested, and complex. The target user is pursuing FIRE and may not be eligible, or may prefer to exclude it for conservative planning.

### D25 – `simulate()` orchestrator; `_drawdown.py` is a size exception
**Decision**: After refactoring (2026-06-02), `simulation/__init__.py` is a thin orchestrator (~120 lines). The per-year phase logic lives in `_phases.py` (~250 lines) and `_config.py` (~120 lines). The drawdown solver lives in `_drawdown.py` (~400 lines) — this is an intentional exception to the 300-line file guideline.  
**Rationale**: The four drawdown modes (waterfall, blended, rebalanced, greedy) plus the iterative solver and draw helpers are intrinsically interconnected; splitting them across multiple files would require passing `_DrawState` across module boundaries and would lose clarity. `_drawdown.py` is a single cohesive algorithm.

### D26 – Drawdown state is accumulated across iterations (not reset)
**Decision**: `nre_drawdown_final`, `nre_cgt_total`, etc. are accumulated across the 5 solver iterations — they are not reset on each pass.  
**Rationale**: Each iteration sells additional parcels to fill a remaining gap; the total is the sum of all iterations. This is correct behaviour.

### D27 – `DrawdownOrchestrator` is a stub
**Decision**: `DrawdownOrchestrator` in `strategies/__init__.py` exists but its `calculate_drawdown()` method returns `None`.  
**Rationale**: The orchestration logic currently lives inside `simulate()`. The stub is a placeholder for a future refactoring that will extract this responsibility.

---

## Testing

### D28 – Minimum 80% test coverage enforced
**Decision**: `--cov-fail-under=80` is required in pytest configuration.  
**Rationale**: Established in the second architectural review. Financial calculations must be tested to a high standard.

### D29 – Integration tests (full `simulate()` runs) are first-class tests
**Decision**: Tests that run the full simulator with specific scenarios are not considered "too coarse". They complement unit tests of individual functions.  
**Rationale**: Many bugs in this codebase were found only through end-to-end scenario testing, not unit tests alone.

---

## Capital Gains Tax Mechanics

### D30 – CGT income stacks on top of ordinary income for marginal rate calculation
**Decision**: CGT is added on top of `base_taxable_income` (salary + NRE income + rent + trust distributions) when determining the effective marginal rate. The marginal rate is computed on the total stack, with the CGT portion potentially spanning multiple tax brackets.

**Example (from user specification)**:
A person earning $130,000 base income (marginal rate: 30%) realises a $100,000 capital gain:
- First $5,000 of CGT stacks into the 30% bracket (fills $130,000 → $135,000)
- Next $55,000 stacks into the 37% bracket ($135,000 → $190,000)
- Remaining $40,000 stacks into the 45% bracket ($190,000 → $230,000)
- Plus 2% Medicare levy on the entire CGT amount

The blended effective rate on the $100,000 CGT in this example is well above 30%, so the minimum tax floor does not apply; the actual stacked rate applies.

**Implementation note**: The simulation computes marginal rate for CGT using `base_taxable_income` as the stacking base. Post-2027 gains are taxed at `max(marginal_rate_at_stack, 30%)`.

**Rejected**: Using a flat "current bracket" rate for CGT without considering bracket spill-over — this understates tax for large CGT events in boundary income cases.

### D31 – Age 65 mandatory minimum super drawdown (ATO account-based pension rules — superannuation only)
**Decision**: Once the user reaches age 65, the simulation enforces the ATO minimum drawdown percentage on the **super pension balance** regardless of `super_kicks_in_age` or user-defined drawdown strategy. This rule applies **only to superannuation** (account-based pension); NRE assets (shares, ETFs, RE held outside super) are not subject to any mandatory drawdown schedule.

**Minimum rates** (see D13 table for full schedule): 4% for under 65, then 5%/6%/7%/9%/11%/14% increasing with age.

**Rationale**: These minimums are legislated (SIS Regulations). Failure to draw the minimum results in the pension phase losing its tax-exempt status.

**Interaction with `DrawdownPolicy`**: If the user's configured super drawdown produces less than the ATO minimum, the simulation overrides it with the minimum. Any excess super drawn (above what was needed to fund expenses) is treated as surplus cash available for reinvestment into NRE assets.
