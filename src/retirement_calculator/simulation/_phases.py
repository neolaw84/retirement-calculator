"""Per-year income and liquidation phase functions for the simulation.

Each function handles one logical phase of the year loop and returns its
computed outputs. List/dict parameters are mutated in-place where noted.
"""

from __future__ import annotations

from typing import NamedTuple

import numpy as np

from retirement_calculator.models import Parcel, REAssetConfig, TrustAssetConfig
from retirement_calculator.rates import RateFunction
from retirement_calculator.tax import income_tax, marginal_rate, super_fund_tax
from retirement_calculator.tax.cgt import (
    cgt_on_parcel,
    re_cgt_on_sale,
    INDEXATION_START_YEAR,
    MIN_CGT_RATE,
)
from retirement_calculator.simulation._config import (
    CalculatorConfig,
    _concessional_cap,
)


# ---------------------------------------------------------------------------
# Return-value containers
# ---------------------------------------------------------------------------

class _NREGrowthResult(NamedTuple):
    nre_ordinary_income: float
    nre_capital_gain_dist: float
    nre_distribution: float


class _TrustIncomeResult(NamedTuple):
    distribution_income: float
    cgt_gain_dist: float
    tax_paid: float
    distribution_net_cash: float
    contribution_this_year: float
    cash_added: float


class _REIncomeResult(NamedTuple):
    net_rent_legacy: float
    net_rent_new: float
    re_price_per_prop: dict[int, float]
    re_rate_by_prop: dict[int, float]
    cash_from_rent: float


class _TrustDissolutionResult(NamedTuple):
    dissolution_gain: float
    dissolution_tax: float
    cash_added: float


class _RESalesResult(NamedTuple):
    re_cgt_events: list[tuple[float, float]]
    sale_proceeds: float
    investment_target: str


class _REMortgageResult(NamedTuple):
    contribution_nominal: float
    interest_nominal: float
    principal_nominal: float


class _SuperGrowthResult(NamedTuple):
    acc_balance: float
    pen_balance: float
    tax_paid: float


# ---------------------------------------------------------------------------
# Phase functions
# ---------------------------------------------------------------------------

def _apply_cgt_stepup_2027(
    year: int,
    nre_parcels: list[Parcel],
    nre_price: dict[str, float],
    trust_parcels: list[Parcel],
    trust_price: float,
    cpi: dict[int, float],
    re_assets: list[REAssetConfig],
) -> None:
    """Capture discounted pre-2027 gains and reset cost-bases on the step-up date.

    Mutates parcel attributes and REAssetConfig.discounted_gain_at_2027 in-place.
    Only does anything when year == 2027.
    """
    if year != 2027:
        return

    for p in nre_parcels:
        if p.year_acquired < 2027:
            nominal_gain = max(0.0, (p.units * nre_price[p.asset_type]) - p.cost_base)
            p.discounted_gain_at_2027 = nominal_gain * 0.5
            p.cost_base = p.units * nre_price[p.asset_type]
            p.cpi_at_acquisition = cpi[2027]

    for p in trust_parcels:
        if p.year_acquired < 2027:
            nominal_gain = max(0.0, (p.units * trust_price) - p.cost_base)
            p.discounted_gain_at_2027 = nominal_gain * 0.5
            p.cost_base = p.units * trust_price
            p.cpi_at_acquisition = cpi[2027]

    for re in re_assets:
        if re.year_bought < 2027:
            nominal_gain = max(0.0, re.valuation_at_base_date - re.purchase_price)
            re.discounted_gain_at_2027 = nominal_gain * 0.5


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
        for p in nre_parcels
        if p.asset_type == "stock"
    )
    nre_bond_value = sum(
        p.units * nre_price[p.asset_type]
        for p in nre_parcels
        if p.asset_type == "bond"
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

    return _REIncomeResult(net_rent_legacy, net_rent_new, re_price_per_prop, re_rate_by_prop, cash_from_rent)


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


def _handle_trust_dissolution(
    year: int,
    config: CalculatorConfig,
    trust_parcels: list[Parcel],
    trust_price: float,
    cpi_now: float,
    base_taxable_income: float,
) -> _TrustDissolutionResult:
    """Handle trust dissolution event if this is the dissolution year.

    Returns a result; caller must set trust_parcels = [] after calling.
    """
    if config.trust_assets is None or config.trust_assets.dissolution_year != year:
        return _TrustDissolutionResult(0.0, 0.0, 0.0)

    diss_proceeds = sum(p.units * trust_price for p in trust_parcels)
    total_gain = 0.0
    total_tax = 0.0
    for p in trust_parcels:
        g, t = cgt_on_parcel(p, trust_price, year, cpi_now, base_taxable_income)
        total_gain += g
        total_tax += t
    return _TrustDissolutionResult(total_gain, total_tax, diss_proceeds)


def _handle_re_sales(
    year: int,
    config: CalculatorConfig,
    re_values: dict[int, float],
    re_mortgage_balance: dict[int, float],
    cpi: dict[int, float],
    cpi_now: float,
    base_taxable_income: float,
) -> _RESalesResult:
    """Handle all RE sale events in the current year. Mutates re_values in-place."""
    re_cgt_events: list[tuple[float, float]] = []
    sale_proceeds = 0.0
    investment_target = "nre"

    for re in config.re_assets:
        if year < re.year_bought:
            continue
        if re.sale_year is None or year != re.sale_year:
            continue

        current_value = re_values[re.property_id]
        sale_costs = current_value * re.sale_costs_pct
        outstanding = re_mortgage_balance.get(re.property_id, float(re.loan_balance))
        net_proceeds = current_value - outstanding - sale_costs
        sale_proceeds += net_proceeds
        investment_target = re.sale_reinvestment_target

        assessable_gain, cgt_re = re_cgt_on_sale(
            re, year, current_value, cpi, cpi_now, base_taxable_income
        )
        re_cgt_events.append((assessable_gain, cgt_re))
        re_values.pop(re.property_id)

    return _RESalesResult(re_cgt_events, sale_proceeds, investment_target)


def _compute_re_mortgages(
    year: int,
    config: CalculatorConfig,
    re_assets: list[REAssetConfig],
    re_mortgage_balance: dict[int, float],
    re_rate_by_prop: dict[int, float],
    rng: np.random.Generator,
) -> _REMortgageResult:
    """Compute and apply annual mortgage P+I payments. Mutates re_mortgage_balance."""
    total_payment = 0.0
    total_interest = 0.0
    total_principal = 0.0

    for re in re_assets:
        if year < re.year_bought:
            continue
        if re.sale_year is not None and year > re.sale_year:
            continue
        pid = re.property_id
        principal = re_mortgage_balance.get(pid, float(re.loan_balance))
        years_elapsed = year - re.year_bought
        remaining_years = max(0, 30 - years_elapsed)
        if principal <= 0.0 or remaining_years <= 0:
            continue

        rate = re_rate_by_prop.get(pid, config.loan_interest_rate.sample(rng))
        if rate <= 0.0:
            payment = principal / remaining_years
        else:
            r, n = rate, remaining_years
            try:
                payment = principal * (r * (1.0 + r) ** n) / (((1.0 + r) ** n) - 1.0)
            except OverflowError:
                payment = principal / n

        interest = principal * rate
        principal_reduction = max(0.0, payment - interest)
        if principal_reduction > principal:
            principal_reduction = principal
            payment = interest + principal_reduction

        re_mortgage_balance[pid] = max(0.0, principal - principal_reduction)
        total_payment += payment
        total_interest += interest
        total_principal += principal_reduction

    return _REMortgageResult(total_payment, total_interest, total_principal)


def _apply_nre_contributions(
    config: CalculatorConfig,
    year: int,
    is_retired: bool,
    nre_parcels: list[Parcel],
    nre_price: dict[str, float],
    cpi_now: float,
) -> float:
    """Add annual NRE contributions as new parcels. Returns contribution amount."""
    if is_retired or config.nre_config.annual_contribution <= 0:
        return 0.0
    amount = config.nre_config.annual_contribution
    alloc = config.nre_config.allocation
    stock_contrib = amount * alloc.stock
    bond_contrib = amount * alloc.bond
    if stock_contrib > 0:
        nre_parcels.append(Parcel(
            asset_type="stock",
            year_acquired=year,
            cost_base=stock_contrib,
            cpi_at_acquisition=cpi_now,
            units=stock_contrib / nre_price["stock"],
        ))
    if bond_contrib > 0:
        nre_parcels.append(Parcel(
            asset_type="bond",
            year_acquired=year,
            cost_base=bond_contrib,
            cpi_at_acquisition=cpi_now,
            units=bond_contrib / nre_price["bond"],
        ))
    return amount


def _grow_super(
    acc_balance: float,
    pen_balance: float,
    total_concessional: float,
    config: CalculatorConfig,
    rng: np.random.Generator,
) -> _SuperGrowthResult:
    """Apply one year of super growth and tax. Returns updated balances."""
    earn_rate = config.super_growth_rate.sample(rng)
    acc_earnings = acc_balance * earn_rate
    acc_tax = super_fund_tax(
        concessional_contributions=total_concessional,
        investment_earnings=acc_earnings,
        in_pension_phase=False,
    )
    new_acc = acc_balance + total_concessional + acc_earnings - acc_tax
    new_pen = pen_balance + pen_balance * earn_rate
    return _SuperGrowthResult(new_acc, new_pen, acc_tax)


def _reinvest_surplus(
    remaining_savings: float,
    year: int,
    config: CalculatorConfig,
    nre_parcels: list[Parcel],
    nre_price: dict[str, float],
    trust_parcels: list[Parcel],
    trust_price: float,
    super_acc_balance: float,
    cpi_now: float,
    re_sale_proceeds: float,
    re_investment_target: str,
) -> tuple[float, float]:
    """Invest the annual surplus according to config. Returns (cash_balance, super_acc).

    Mutates nre_parcels and trust_parcels in-place.
    """
    if remaining_savings <= 1.0:
        return max(0.0, remaining_savings), super_acc_balance

    investible = remaining_savings * config.surplus_reinvestment_pct
    target = re_investment_target if re_sale_proceeds > 1.0 else config.surplus_reinvestment_target

    if target == "nre":
        alloc = config.nre_config.allocation
        si = investible * alloc.stock
        bi = investible * alloc.bond
        if si > 0:
            nre_parcels.append(Parcel("stock", year, si, cpi_now, si / nre_price["stock"]))
        if bi > 0:
            nre_parcels.append(Parcel("bond", year, bi, cpi_now, bi / nre_price["bond"]))
    elif target == "trust" and config.trust_assets is not None:
        trust_parcels.append(Parcel("stock", year, investible, cpi_now, investible / trust_price))
    elif target == "super":
        super_acc_balance += investible
    # target == "cash": investible stays in cash

    non_invested = remaining_savings - investible
    cash_balance = remaining_savings if target == "cash" else non_invested
    return cash_balance, super_acc_balance
