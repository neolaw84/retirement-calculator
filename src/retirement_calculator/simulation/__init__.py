"""Core retirement simulator.

Runs a year-by-year simulation from current_year to age 99, tracking:
* NRE (Non-Real-Estate) assets with per-parcel CGT tracking
* Real Estate (RE) assets with negative gearing rules
* Superannuation accumulation and drawdown
* Income tax, CGT, super fund tax

Output: pandas DataFrame with one row per simulated year.

See docs/assumptions.md for all modelling assumptions.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from retirement_calculator.models import (
    NREAssetConfig, REAssetConfig, TrustAssetConfig,
    Parcel, AssetAllocation, DrawdownPolicy,
)
from retirement_calculator.tax.cgt import INDEXATION_START_YEAR
from retirement_calculator.strategies import (
    LIFOStrategy, FIFOStrategy, TaxOptimisedGreedyStrategy, RebalancingStrategy,
)

from retirement_calculator.simulation._config import (
    CalculatorConfig, _build_cpi_series, _concessional_cap, _pension_min_drawdown_rate,
)
from retirement_calculator.simulation._phases import (
    _apply_cgt_stepup_2027, _apply_cash_interest, _compute_salary,
    _compute_super_contributions, _grow_nre, _process_trust_income,
    _process_re_income, _compute_re_assessable, _handle_trust_dissolution,
    _handle_re_sales, _compute_re_mortgages, _apply_nre_contributions,
    _grow_super, _reinvest_surplus,
)
from retirement_calculator.simulation._solver import (
    _apply_super_transition, _apply_mandatory_super_draw, run_iterative_solver,
)
from retirement_calculator.simulation._year_record import _build_year_record


def simulate(config: CalculatorConfig) -> pd.DataFrame:
    """Run the retirement simulation and return a results DataFrame.

    Returns one row per year with nominal and real values for all tracked quantities.

    Note (D25): this orchestrator calls 20 extracted phase functions and threads
    their results together. Its length (~150 lines) is a deliberate documented
    exception — splitting it further would require a complex state object with
    no gain in readability.
    """
    rng = np.random.default_rng(config.seed)
    end_year = config.current_year + (99 - config.current_age)
    cpi = _build_cpi_series(config.current_year, end_year, config.inflation_rate, rng)

    _strategies = {
        "fifo": FIFOStrategy(), "lifo": LIFOStrategy(),
        "tax_optimised": TaxOptimisedGreedyStrategy(), "rebalancing": RebalancingStrategy(),
    }
    strategy = _strategies.get(config.drawdown_strategy, FIFOStrategy())

    # --- Initialise NRE parcels ---
    nre_parcels: list[Parcel] = []
    nre_price = {"stock": 1.0, "bond": 1.0}
    if config.nre_config.initial_value > 0:
        alloc = config.nre_config.allocation
        base_cpi = cpi[config.current_year]
        sv = config.nre_config.initial_value * alloc.stock
        bv = config.nre_config.initial_value * alloc.bond
        if sv > 0:
            nre_parcels.append(Parcel("stock", config.current_year, sv, base_cpi, sv))
        if bv > 0:
            nre_parcels.append(Parcel("bond", config.current_year, bv, base_cpi, bv))

    # --- Initialise RE and trust state ---
    re_values: dict[int, float] = {
        re.property_id: re.valuation_at_base_date / (
            (1.0 + re.growth_rate.sample(rng)) ** max(0, 2027 - config.current_year)
        )
        for re in config.re_assets
    }
    re_mortgage_balance: dict[int, float] = {
        re.property_id: float(re.loan_balance) for re in config.re_assets
    }
    trust_parcels: list[Parcel] = []
    trust_price = 1.0
    if config.trust_assets is not None:
        val = config.trust_assets.initial_value
        trust_parcels.append(Parcel("stock", config.current_year, val, cpi[config.current_year], val))

    # --- Initialise super / cash state ---
    super_acc = config.initial_super_balance
    super_pen = 0.0
    unused_concessional: list[float] = []
    records = []
    salary_real = config.salary
    cash_balance = 0.0

    for year in range(config.current_year, end_year + 1):
        age = config.current_age + (year - config.current_year)
        is_retired = age >= config.retirement_age
        cpi_now = cpi[year]
        deflator = 100.0 / cpi_now

        # 1. CGT step-up on 2027-07-01 (per D08)
        _apply_cgt_stepup_2027(year, nre_parcels, nre_price, trust_parcels, trust_price, cpi, config.re_assets)

        # 2. Cash interest
        cash_balance = _apply_cash_interest(cash_balance, config, rng)
        available_cash = cash_balance

        # 3. Salary
        salary_nominal, salary_real = _compute_salary(is_retired, salary_real, config, rng, cpi_now)
        available_cash += salary_nominal

        # 4. Super contributions
        total_concessional, unused_concessional = _compute_super_contributions(
            is_retired, salary_nominal, year, super_acc, super_pen,
            config, unused_concessional, cpi_now,
        )

        # 5. NRE growth and distributions
        nre_result = _grow_nre(config, rng, nre_parcels, nre_price)
        available_cash += nre_result.nre_distribution

        # 6. Trust growth, distribution, contribution
        trust_result, trust_price = _process_trust_income(
            year, is_retired, config, trust_parcels, trust_price, cpi_now, rng,
        )
        available_cash += trust_result.cash_added

        # 7. RE income (growth + rent)
        re_result = _process_re_income(
            year, config, config.re_assets, re_values, re_mortgage_balance, rng, cpi_now,
        )
        available_cash += re_result.cash_from_rent

        # 8. RE assessable income (D15 ring-fence)
        re_assessable = _compute_re_assessable(year, re_result.net_rent_legacy, re_result.net_rent_new)

        # 9. Base taxable income (pre-CGT)
        base_taxable_income = (
            salary_nominal
            + nre_result.nre_ordinary_income
            + re_assessable
            + trust_result.distribution_income
        )

        # 10. Trust dissolution
        trust_diss = _handle_trust_dissolution(
            year, config, trust_parcels, trust_price, cpi_now, base_taxable_income,
        )
        if config.trust_assets is not None and config.trust_assets.dissolution_year == year:
            available_cash += trust_diss.cash_added
            trust_parcels = []

        # 11. RE sales
        re_sales = _handle_re_sales(
            year, config, re_values, re_mortgage_balance, cpi, cpi_now, base_taxable_income,
        )
        available_cash += re_sales.sale_proceeds

        # 12. RE mortgage payments
        mortgage = _compute_re_mortgages(
            year, config, config.re_assets, re_mortgage_balance, re_result.re_rate_by_prop, rng,
        )
        available_cash -= mortgage.contribution_nominal

        # 13. NRE contributions
        nre_contrib = _apply_nre_contributions(config, year, is_retired, nre_parcels, nre_price, cpi_now)
        available_cash -= nre_contrib

        # 14. Super pension phase transition
        super_acc, super_pen = _apply_super_transition(age, config, cpi_now, super_acc, super_pen)

        # 15. Mandatory minimum pension drawdown (super only)
        super_min_draw, super_pen = _apply_mandatory_super_draw(age, super_pen)
        available_cash += super_min_draw

        # 16. Iterative drawdown solver
        expenses_nominal = (
            (config.retirement_expenses if is_retired else config.expenses) * (cpi_now / 100.0)
        )
        draw_state, actual_tax, personal_tax, div293, total_taxable = run_iterative_solver(
            config=config, year=year, age=age, cpi_now=cpi_now,
            base_taxable_income=base_taxable_income,
            trust_distribution_income=trust_result.distribution_income,
            nre_capital_gain_dist=nre_result.nre_capital_gain_dist,
            trust_cgt_gain_dist=trust_result.cgt_gain_dist,
            total_concessional=total_concessional,
            re_cgt_events=re_sales.re_cgt_events,
            trust_dissolution_gain=trust_diss.dissolution_gain,
            trust_dissolution_tax=trust_diss.dissolution_tax,
            expenses_nominal=expenses_nominal,
            available_cash_pre_draw=available_cash,
            super_acc_balance=super_acc, super_pen_balance=super_pen,
            nre_parcels=nre_parcels, trust_parcels=trust_parcels,
            nre_price=nre_price, trust_price=trust_price, strategy=strategy,
        )

        nre_parcels = draw_state.nre_parcels
        trust_parcels = draw_state.trust_parcels
        super_acc = draw_state.super_accumulation_balance
        super_pen = draw_state.super_pension_balance
        available_cash = draw_state.available_cash

        # 17. Surplus reinvestment
        remaining_savings = available_cash - (expenses_nominal + actual_tax)
        cash_balance, super_acc = _reinvest_surplus(
            remaining_savings, year, config, nre_parcels, nre_price,
            trust_parcels, trust_price, super_acc, cpi_now,
            re_sales.sale_proceeds, re_sales.investment_target,
        )

        # 18. Super growth and tax
        super_result = _grow_super(super_acc, super_pen, total_concessional, config, rng)
        super_acc = super_result.acc_balance
        super_pen = super_result.pen_balance
        super_tax = super_result.tax_paid
        super_balance = super_acc + super_pen

        # 19. Compute end-of-year asset totals
        nre_end_value = sum(p.units * nre_price[p.asset_type] for p in nre_parcels)
        re_end_value = sum(re_values.values())
        trust_end_value = sum(p.units * trust_price for p in trust_parcels)
        total_assets = nre_end_value + re_end_value + super_balance + trust_end_value + cash_balance
        total_liabilities = sum(re_mortgage_balance.values()) if re_mortgage_balance else 0.0
        net_worth_nominal = total_assets - total_liabilities
        super_draw = super_min_draw + draw_state.super_pension_draw + draw_state.super_accumulation_draw
        trust_active_cap_gain = (
            (trust_result.cgt_gain_dist * 0.5 if year < INDEXATION_START_YEAR else trust_result.cgt_gain_dist)
            + draw_state.trust_gain_total + trust_diss.dissolution_gain
        )
        trust_diss_tax_final = max(0.0, trust_diss.dissolution_tax - trust_diss.dissolution_gain * 0.30)
        trust_sales_tax = max(0.0, draw_state.trust_cgt_total - draw_state.trust_gain_total * 0.30)

        rec = _build_year_record(
            year=year, age=age, deflator=deflator, cpi_now=cpi_now,
            salary_nominal=salary_nominal, nre_result=nre_result,
            re_result=re_result, trust_result=trust_result,
            expenses_nominal=expenses_nominal, actual_tax=actual_tax,
            personal_tax=personal_tax, div293=div293, super_tax=super_tax,
            super_balance=super_balance, super_acc=super_acc, super_pen=super_pen,
            super_min_draw=super_min_draw, super_draw=super_draw,
            total_taxable=total_taxable, nre_end_value=nre_end_value,
            re_end_value=re_end_value, trust_end_value=trust_end_value,
            total_assets=total_assets, total_liabilities=total_liabilities,
            net_worth_nominal=net_worth_nominal, cash_balance=cash_balance,
            nre_contrib=nre_contrib, mortgage=mortgage, re_sales=re_sales,
            trust_diss_gain=trust_diss.dissolution_gain,
            trust_diss_tax=trust_diss.dissolution_tax,
            trust_active_cap_gain=trust_active_cap_gain,
            trust_sales_tax=trust_sales_tax,
            trust_diss_tax_final=trust_diss_tax_final,
            draw_nre_drawdown=draw_state.nre_drawdown,
            draw_nre_gain_total=draw_state.nre_gain_total,
            draw_nre_cgt_total=draw_state.nre_cgt_total,
            draw_trust_drawdown=draw_state.trust_drawdown,
            draw_trust_cgt_total=draw_state.trust_cgt_total,
            draw_funding_gap=draw_state.funding_gap,
            draw_initial_funding_gap=draw_state.initial_funding_gap,
            available_cash=available_cash, remaining_savings=remaining_savings,
        )
        rec["super_contribution_concessional"] = total_concessional
        records.append(rec)

    return pd.DataFrame(records)
