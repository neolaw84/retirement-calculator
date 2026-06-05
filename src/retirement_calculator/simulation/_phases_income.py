"""Income and growth phase functions for the annual simulation loop.

Covers: cash interest, salary, super contributions, NRE growth,
trust income, RE income, and RE assessable income computation.
"""

from __future__ import annotations

import numpy as np

from retirement_calculator.models import Parcel, REAssetConfig, TrustAssetConfig
from retirement_calculator.tax import income_tax
from retirement_calculator.simulation._config import (
    CalculatorConfig,
    _concessional_cap,
)
from retirement_calculator.simulation._phase_types import (
    _NREGrowthResult,
    _TrustIncomeResult,
    _REIncomeResult,
)


def _apply_cash_interest(
    cash_balance: float,
    config: CalculatorConfig,
    rng: np.random.Generator,
) -> float:
    """Apply one year of interest/growth to the cash balance."""
    if cash_balance <= 0.0:
        return cash_balance
    rate = (
        config.cash_interest_rate.sample(rng)
        if config.cash_interest_rate is not None
        else config.inflation_rate.sample(rng)
    )
    return cash_balance * (1.0 + rate)


def _compute_salary(
    is_retired: bool,
    salary_real: float,
    config: CalculatorConfig,
    rng: np.random.Generator,
    cpi_now: float,
) -> tuple[float, float]:
    """Return (salary_nominal, updated_salary_real) for the current year."""
    if is_retired:
        return 0.0, salary_real
    salary_real = salary_real * (1.0 + config.salary_growth_rate.sample(rng))
    return salary_real * (cpi_now / 100.0), salary_real


def _compute_super_contributions(
    is_retired: bool,
    salary_nominal: float,
    year: int,
    acc_bal: float,
    pen_bal: float,
    config: CalculatorConfig,
    unused_concessional: list[float],
    cpi_now: float,
) -> tuple[float, list[float]]:
    """Compute total concessional super contributions and update carry-forward list.

    Returns (total_concessional, updated_unused_concessional).
    """
    sg = salary_nominal * 0.12 if not is_retired else 0.0
    addl = (
        config.additional_concessional_super * (cpi_now / 100.0)
        if not is_retired
        else 0.0
    )

    base_cap = _concessional_cap(year)
    if config.use_carry_forward_super and (acc_bal + pen_bal) < 500_000:
        effective_cap = base_cap + sum(unused_concessional[-5:])
    else:
        effective_cap = base_cap

    total_concessional = min(sg + addl, effective_cap)
    unused_this_year = max(0.0, base_cap - total_concessional)

    new_unused = list(unused_concessional)
    new_unused.append(unused_this_year)
    if len(new_unused) > 5:
        new_unused.pop(0)

    return total_concessional, new_unused


def _grow_nre(
    config: CalculatorConfig,
    rng: np.random.Generator,
    nre_parcels: list[Parcel],
    nre_price: dict[str, float],
) -> _NREGrowthResult:
    """Grow NRE prices and compute distributions. Mutates nre_price in-place."""
    nre_price["stock"] *= (1.0 + config.nre_config.stock_growth_rate.sample(rng))
    nre_price["bond"] *= (1.0 + config.nre_config.bond_growth_rate.sample(rng))

    nre_stock_value = sum(
        p.units * nre_price[p.asset_type]
        for p in nre_parcels if p.asset_type == "stock"
    )
    nre_bond_value = sum(
        p.units * nre_price[p.asset_type]
        for p in nre_parcels if p.asset_type == "bond"
    )
    nre_distribution = (
        nre_stock_value * config.nre_config.stock_yield
        + nre_bond_value * config.nre_config.bond_yield
    )
    cg_pct = config.nre_config.capital_gain_component_pct
    nre_ordinary_income = nre_distribution * (1.0 - cg_pct)
    nre_capital_gain_dist = nre_distribution * cg_pct
    return _NREGrowthResult(nre_ordinary_income, nre_capital_gain_dist, nre_distribution)


def _process_trust_income(
    year: int,
    is_retired: bool,
    config: CalculatorConfig,
    trust_parcels: list[Parcel],
    trust_price: float,
    cpi_now: float,
    rng: np.random.Generator,
) -> tuple[_TrustIncomeResult, float]:
    """Grow trust, compute distribution, and record any contribution.

    Mutates trust_parcels in-place (appends contribution parcel).
    Returns (result, updated_trust_price).
    """
    if config.trust_assets is None:
        empty = _TrustIncomeResult(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        return empty, trust_price

    ta = config.trust_assets
    trust_price = trust_price * (1.0 + ta.growth_rate.sample(rng))
    trust_val = sum(p.units * trust_price for p in trust_parcels)

    raw_dist = trust_val * ta.distribution_yield
    trust_cgt_gain_dist = ta.annual_capital_gain_dist
    trust_tax_paid = raw_dist * 0.30
    trust_dist_net = raw_dist - trust_tax_paid

    contrib_nominal = (
        ta.annual_post_retirement_contribution if is_retired else ta.annual_contribution
    ) * (cpi_now / 100.0)
    if contrib_nominal > 0:
        trust_parcels.append(Parcel(
            asset_type="stock",
            year_acquired=year,
            cost_base=contrib_nominal,
            cpi_at_acquisition=cpi_now,
            units=contrib_nominal / trust_price,
        ))

    cash_added = trust_dist_net + trust_cgt_gain_dist
    result = _TrustIncomeResult(
        distribution_income=raw_dist,
        cgt_gain_dist=trust_cgt_gain_dist,
        tax_paid=trust_tax_paid,
        distribution_net_cash=trust_dist_net,
        contribution_this_year=contrib_nominal,
        cash_added=cash_added,
    )
    return result, trust_price


def _process_re_income(
    year: int,
    config: CalculatorConfig,
    re_assets: list[REAssetConfig],
    re_values: dict[int, float],
    re_mortgage_balance: dict[int, float],
    rng: np.random.Generator,
    cpi_now: float,
) -> _REIncomeResult:
    """Grow RE values, compute rent and expenses. Mutates re_values in-place.

    D15 fix: uses correct two-date ring-fence categorisation.
    """
    net_rent_legacy = 0.0
    net_rent_new = 0.0
    re_price_per_prop: dict[int, float] = {}
    re_rate_by_prop: dict[int, float] = {}
    cash_from_rent = 0.0

    for re in re_assets:
        if year < re.year_bought:
            continue
        if re.sale_year is not None and year > re.sale_year:
            continue

        re_values[re.property_id] *= (1.0 + re.growth_rate.sample(rng))
        current_value = re_values[re.property_id]

        gross_rent = re.gross_annual_rent * (cpi_now / 100.0)
        re_expenses = current_value * 0.01
        outstanding = re_mortgage_balance.get(re.property_id, float(re.loan_balance))
        rate = config.loan_interest_rate.sample(rng)
        re_rate_by_prop[re.property_id] = rate
        re_interest = outstanding * rate

        net_rent_for_tax = gross_rent - re_expenses - re_interest

        # D15: categorise into legacy vs ring-fenced bucket
        is_new = (re.year_bought >= 2028) or (
            re.year_bought in (2026, 2027) and year >= 2028
        )
        if is_new:
            net_rent_new += net_rent_for_tax
        else:
            net_rent_legacy += net_rent_for_tax

        cash_from_rent += gross_rent - re_expenses
        re_price_per_prop[re.property_id] = current_value

    return _REIncomeResult(
        net_rent_legacy, net_rent_new,
        re_price_per_prop, re_rate_by_prop, cash_from_rent,
    )


def _compute_re_assessable(
    year: int,
    net_rent_legacy: float,
    net_rent_new: float,
) -> float:
    """Return total assessable RE income applying D15 ring-fence rules.

    Ring-fence assessment only starts from simulation year 2028
    (FY 2027-28, the policy commencement date of 1 July 2027).
    """
    pool_total = net_rent_legacy + net_rent_new
    if year >= 2028:
        deductible_legacy_loss = min(0.0, net_rent_legacy)
        leg_profit = max(0.0, net_rent_legacy)
        effective_new = max(net_rent_new, -leg_profit)
        return deductible_legacy_loss + leg_profit + effective_new
    return pool_total
