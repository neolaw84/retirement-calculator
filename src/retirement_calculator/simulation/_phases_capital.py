"""Capital event phase functions for the annual simulation loop.

Covers: CGT step-up (2027), trust dissolution, RE sales, mortgage payments,
NRE contributions, super growth, and surplus reinvestment.
"""

from __future__ import annotations

import numpy as np

from retirement_calculator.models import Parcel, REAssetConfig
from retirement_calculator.tax import super_fund_tax
from retirement_calculator.tax.cgt import (
    cgt_on_parcel,
    re_cgt_on_sale,
    INDEXATION_START_YEAR,
)
from retirement_calculator.simulation._config import CalculatorConfig
from retirement_calculator.simulation._phase_types import (
    _TrustDissolutionResult,
    _RESalesResult,
    _REMortgageResult,
    _SuperGrowthResult,
)


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

    non_invested = remaining_savings - investible
    cash_balance = remaining_savings if target == "cash" else non_invested
    return cash_balance, super_acc_balance
