# Assumptions

This document records all assumptions made in implementing the Retirement Calculator.

## Tax Assumptions

1. **Income Tax Brackets (2025-26 onward)**: Based on ATO published rates:
   - $0–$18,200: Nil
   - $18,201–$45,000: 16c per $1 over $18,200
   - $45,001–$135,000: $4,288 + 30c per $1 over $45,000
   - $135,001–$190,000: $31,288 + 37c per $1 over $135,000
   - $190,001+: $51,638 + 45c per $1 over $190,000
   - Medicare levy: 2% applied to all taxable income
   - **Assumption**: Tax brackets are NOT indexed for inflation over the projection period.

2. **Low Income Tax Offset (LITO)**: $700 for income up to $37,500; phases out at 1.5c per $1 from $37,500 to $45,000; further phases out at 1.5c per $1 from $45,001 to $66,667.

3. **Medicare Levy Reduction**: Individuals with income below $26,000 (approx.) get a reduction; not modelled for simplicity.

4. **Division 293 Tax**: Additional 15% tax on concessional super contributions for individuals earning over $250,000. Included in model.

## May 12, 2026 Budget Changes (as specified)

5. **Discretionary Trust Minimum Credit (30%)**: Income distributed from discretionary trusts is assumed to carry a minimum 30% non-refundable franking-style credit. **Assumption**: This applies to the "distributions" component of NRE assets (ETF distributions treated as trust-like).

6. **CGT – Inflation-Adjusted Real Gains**: For assets sold after May 12, 2026, the cost base is indexed by CPI from the acquisition date to the sale date to determine the "real" gain. The old 50% CGT discount is replaced by this inflation indexation.
   - **Assumption**: CPI indexation only applies to assets held for at least 12 months (same holding period rule).
   - **Assumption**: The 50% CGT discount is removed; replaced by inflation adjustment.

7. **Minimum CGT Rate (30% floor)**: The effective CGT rate cannot be less than 30% of the real (inflation-adjusted) gain.
   - **Assumption**: This means the marginal rate applied to the real gain is max(marginal_rate, 30%).

8. **Negative Gearing Ring-Fence**: For real estate purchased after May 12, 2026, net rental losses can only offset rental income, not wage/investment income. For RE purchased before this date, negative gearing remains unrestricted.

## Superannuation Assumptions

9. **Super Guarantee (SG) Rate**: 12% from FY2025-26 onward (confirmed from ATO).

10. **Concessional Contributions Cap**:
    - 2025-26: $30,000
    - 2026-27+: $32,500 (indexed; kept fixed at $32,500 for simplicity unless otherwise specified)
    - **Assumption**: Cap grows by $2,500 every ~3–4 years with AWOTE; modelled as fixed $32,500 for the projection horizon unless the user specifies otherwise.

11. **Carry-Forward Concessional Contributions**: Available if total super balance < $500,000 on 30 June of the prior year. Unused amounts from up to 5 years prior can be added to the current year cap.

12. **Super Tax Rate (Accumulation Phase)**: 15% on concessional contributions and earnings within super.

13. **Super Tax Rate (Pension Phase)**: 0% on earnings and withdrawals from a taxed super fund after preservation age.

14. **Preservation Age**: Age 60 (applying to individuals born after June 30, 1964; conservative assumption used for all users).

15. **Super Account Growth**: A single user-specified growth rate applies to the entire super balance (no internal asset allocation split modelled).

## NRE Asset Assumptions

16. **ETF Distributions**: Annual distribution yield is a user-specified percentage of current portfolio value. The distribution is split:
    - 70% ordinary income (dividends/interest — taxed at marginal rate)
    - 30% capital return / capital gain distribution (treated as "reinvested" CGT event with new cost base)
    - **Assumption**: This 70/30 split is a rough approximation; actual splits vary by fund.

17. **ETF Franking**: **Not modelled** for simplicity. Australian equity ETFs may carry franking credits, but this requires fund-specific data.

18. **Parcel Tracking**: Every contribution creates a new parcel. CGT is calculated per-parcel on disposal.

## RE Asset Assumptions

19. **Rental Income Net Yield**: Gross rental income minus 5% property management fee minus 5% maintenance = net rent. Modelled as user-provided gross rent with a 10% deduction applied.

20. **RE Valuation Base Date**: July 1, 2027 is the reference date for RE valuations (as specified). CPI indexation is used to determine cost base at time of sale.

21. **Depreciation**: Not modelled (simplification).

22. **Mortgage Interest**: Not modelled (simplification — user provides net rent; leverage effects outside scope).

## Inflation and Rate Assumptions

23. **Base Year**: 2026 (current year). All "today's value" amounts are in 2026 dollars.

24. **CPI series**: A constant rate or normally-distributed random rate is used; default 2.5% p.a. (mid-point of RBA target band 2–3%).

25. **NRE Growth Rates**: Applied to stock and bond ETF components separately.

## Simulation Assumptions

26. **Annual Timestep**: Simulation runs year by year.

27. **Age Pension**: Not included in this version.

28. **Death/Estate**: Simulation ends at age 99.

29. **Salary Increases**: Not modelled; salary is assumed constant in real terms (inflation-adjusted automatically).

30. **Cash Buffer**: No explicit cash buffer modelled; withdrawals from NRE assets fill any funding gap.
