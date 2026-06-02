# Assumptions

This document records all assumptions made in implementing the Retirement Calculator.

## Tax Assumptions

1. **Income Tax Brackets (2025-26 onward — permanently fixed)**: Based on ATO published rates:
   - $0–$18,200: Nil
   - $18,201–$45,000: 16c per $1 over $18,200 (rate permanently fixed; see D03)
   - $45,001–$135,000: $4,288 + 30c per $1 over $45,000
   - $135,001–$190,000: $31,288 + 37c per $1 over $135,000
   - $190,001+: $51,638 + 45c per $1 over $190,000
   - Medicare levy: 2% applied to all taxable income
   - **Assumption**: Tax brackets are NOT indexed for inflation over the projection period (see D01).

2. **Low Income Tax Offset (LITO)**: **NEVER MODELLED** — assumed non-existent. See D03.

3. **Working Australians Tax Offset (WATO)**: **NEVER MODELLED** — assumed non-existent. See D04.

4. **$1,000 instant work-related expense deduction**: **NEVER MODELLED**. See D05.

5. **Medicare Levy Reduction**: Individuals with income below $26,000 (approx.) get a reduction; not modelled for simplicity.

6. **Division 293 Tax**: Additional 15% tax on concessional super contributions for individuals earning over $250,000. Included in model.

7. **CGT bracket stacking**: Capital gains are stacked on top of other income when calculating the marginal rate. Large CGT events can push income into higher brackets. Example: $130,000 base income + $100,000 CGT → first $5,000 of CGT at 30%, next $55,000 at 37%, remaining $40,000 at 45%. See D30.

## May 12, 2026 Budget Changes

8. **Discretionary Trust Minimum Credit (30%)**: Income distributed from discretionary trusts carries a minimum 30% non-refundable credit (similar to a franking credit). **Assumption**: This applies to the "distributions" component of NRE assets (ETF distributions treated as trust-like). Modelled as a non-refundable credit capped at gross tax (see D06).

9. **CGT 2027 Transition — Bifurcated Pre/Post-2027 Gains**: The Budget 2026 CGT reform applies from **1 July 2027** only to gains accruing after that date. The mechanism for assets held across the transition is:
   - **Pre-2027 gain** (cost_base → value_at_2027): the 50% CGT discount applies. Assessable amount = 50% × (value_at_2027 − original_cost_base). Deferred until sale.
   - **Post-2027 gain** (value_at_2027 → sale_price): CPI-indexed cost base applies. Real gain = sale_price − (value_at_2027 × CPI_at_sale / CPI_at_2027). Minimum 30% tax rate on the real gain.
   - **At sale**: total assessable = pre_2027_discounted_gain + post_2027_real_gain.
   - **Assets acquired after 1 July 2027**: entirely under new rules (indexed cost base, no 50% discount, 30% floor).
   - **Budget Explainer (Jane's scenario)**: bought $800k July 2022; value at July 1, 2027 = $1,131,371; sold July 1, 2032 for $1,600,000 → pre-2027 assessable = $165,685; post-2027 real gain = $319,958; total = $485,643.
   - **Assumption**: 12-month holding period rule unchanged (same asset must be held ≥ 12 months for indexation/discount to apply).
   - **Assumption**: CPI for indexation purposes uses the same CPI series as the simulation.
   - **NOT modelled**: new-build exemption (investor choice between 50% discount and indexation for new builds).

10. **Minimum CGT Rate (30% floor)**: For post-2027 real gains, the marginal rate applied = max(stacked_marginal_rate, 30%). The 30% floor does not apply to pre-2027 50%-discounted gains. Exemption: recipients of means-tested government payments (Age Pension, JobSeeker) in the year of realisation are exempt — not modelled (Age Pension not in scope).

11. **Negative Gearing Ring-Fence — Two Critical Dates**: (see D15 for full detail)
    - **Date 1 — 7:30pm AEST 12 May 2026 (Budget night)**: Properties held at or before this moment are fully grandfathered — unrestricted negative gearing in all future years until sold.
    - **Date 2 — 1 July 2027 (policy commencement)**: From this date, negative gearing for established residential property is restricted to new builds only.
    - **Established properties bought between announcement and 30 June 2027**: Can negatively gear in FY2026-27; ring-fenced from 1 July 2027 onwards (losses carry forward to future RE income only).
    - **Established properties bought from 1 July 2027**: Ring-fenced from day one of ownership.
    - **New builds**: Fully unrestricted negative gearing before and after 1 July 2027 — NOT modelled (all RE treated as established housing).
    - **Simulator simplification**: Due to annual timestep, `year_bought == 2026` and `year_bought == 2027` properties have ring-fencing applied from simulation year 2028 onwards. `year_bought <= 2025` = grandfathered. `year_bought >= 2028` = ring-fenced from day 1.

## Superannuation Assumptions

12. **Super Guarantee (SG) Rate**: 12% from FY2025-26 onward (confirmed from ATO).

13. **Concessional Contributions Cap**:
    - 2025-26: $30,000
    - 2026-27+: $32,500 (indexed; kept fixed at $32,500 for simplicity unless otherwise specified)
    - **Assumption**: Cap grows by $2,500 every ~3–4 years with AWOTE; modelled as fixed $32,500 for the projection horizon unless the user specifies otherwise.

14. **Carry-Forward Concessional Contributions**: Available if total super balance < $500,000 on 30 June of the prior year. Unused amounts from up to 5 years prior can be added to the current year cap.

15. **Super Tax Rate (Accumulation Phase)**: 15% on concessional contributions and earnings within super.

16. **Super Tax Rate (Pension Phase)**: 0% on earnings and withdrawals from a taxed super fund after preservation age.

17. **Preservation Age and Drawdown Configuration**: Preservation age = 60 for all users (non-configurable; applies to all born after 30 June 1964). `super_kicks_in_age` is user-configurable (must be ≥ 60). See D13.

18. **Age 65 Mandatory Minimum Drawdown (superannuation only)**: From age 65, ATO account-based pension minimum drawdown rates apply to the **super pension balance** regardless of user preference (see D31 and D13 for rate schedule). This rule applies to superannuation only — NRE assets held outside super have no mandatory drawdown schedule.

19. **Super Account Growth**: A single user-specified growth rate applies to the entire super balance (no internal asset allocation split modelled).

## NRE Asset Assumptions

20. **ETF Distributions**: Annual distribution yield is a user-specified percentage of current portfolio value. The distribution is split:
    - 70% ordinary income (dividends/interest — taxed at marginal rate)
    - 30% capital return / capital gain distribution (treated as "reinvested" CGT event with new cost base)
    - **Assumption**: This 70/30 split is a rough approximation; actual splits vary by fund.

21. **ETF Franking**: **Not modelled** for simplicity. Australian equity ETFs may carry franking credits, but this requires fund-specific data.

22. **Parcel Tracking**: Every contribution creates a new parcel. CGT is calculated per-parcel on disposal.

## RE Asset Assumptions

23. **Rental Expenses**: Modelled as `1% of current property value per year` (`current_re_value * 0.01`). This approximates ongoing maintenance and management costs. Note: an earlier draft described a "10% of gross rent" formula — the implementation uses the value-based model (see D16).

24. **RE Valuation Base Date**: July 1, 2027 is the reference date for RE valuations (as specified). CPI indexation is used to determine cost base at time of sale.

25. **Depreciation**: Not modelled (simplification).

26. **Mortgage Interest**: Not modelled (simplification — user provides net rent; leverage effects outside scope).

## Inflation and Rate Assumptions

27. **Base Year**: 2026 (current year). All "today's value" amounts are in 2026 dollars.

28. **CPI series**: A constant rate or normally-distributed random rate is used; default 2.5% p.a. (mid-point of RBA target band 2–3%).

29. **NRE Growth Rates**: Applied to stock and bond ETF components separately.

## Simulation Assumptions

30. **Annual Timestep**: Simulation runs year by year.

31. **Age Pension**: Not included in this version.

32. **Death/Estate**: Simulation ends at age 99.

33. **Salary Increases**: Not modelled; salary is assumed constant in real terms (inflation-adjusted automatically).

34. **Cash Buffer**: No explicit cash buffer modelled; withdrawals from NRE assets fill any funding gap.
