"""Iterative drawdown solver and per-iteration tax computation.

Extracted from _drawdown.py to keep module sizes within limits.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from retirement_calculator.models import Parcel
from retirement_calculator.tax import income_tax, marginal_rate, division_293_tax
from retirement_calculator.tax.cgt import INDEXATION_START_YEAR
from retirement_calculator.simulation._drawdown import (
    _DrawState,
    _run_waterfall,
    _run_blended,
    _run_rebalanced,
    _run_greedy,
)
from retirement_calculator.simulation._config import _pension_min_drawdown_rate

if TYPE_CHECKING:
    from retirement_calculator.simulation._config import CalculatorConfig


# ---------------------------------------------------------------------------
# Super phase-transition helpers
# ---------------------------------------------------------------------------

def _apply_super_transition(
    age: int,
    config,
    cpi_now: float,
    super_acc_balance: float,
    super_pen_balance: float,
) -> tuple[float, float]:
    """Move super from accumulation to pension up to TBC when eligible.

    Returns (new_acc_balance, new_pen_balance).
    """
    in_pension_mode = age >= config.super_access_age and (
        age >= config.retirement_age or age >= 65
    )
    if not in_pension_mode:
        return super_acc_balance, super_pen_balance

    tbc_nominal = config.transfer_balance_cap * (cpi_now / 100.0)
    room = max(0.0, tbc_nominal - super_pen_balance)
    if room > 0 and super_acc_balance > 0:
        transfer = min(room, super_acc_balance)
        super_pen_balance += transfer
        super_acc_balance -= transfer
    return super_acc_balance, super_pen_balance


def _apply_mandatory_super_draw(
    age: int,
    super_pen_balance: float,
) -> tuple[float, float]:
    """Apply ATO minimum pension drawdown. Returns (draw_amount, new_pen_balance)."""
    if super_pen_balance <= 0.0:
        return 0.0, super_pen_balance
    min_draw = super_pen_balance * _pension_min_drawdown_rate(age)
    return min_draw, super_pen_balance - min_draw


# ---------------------------------------------------------------------------
# Tax computation
# ---------------------------------------------------------------------------

def _compute_trust_dist_cgt_tax(
    year: int,
    total_taxable: float,
    trust_cgt_gain_dist: float,
    trust_cgt_gain_dist_assessable: float,
) -> float:
    """Compute CGT tax on trust distribution capital gains.

    Returns trust_dist_cgt_tax (after 30% non-refundable credit).
    """
    if year < INDEXATION_START_YEAR:
        base_cgt_tax = income_tax(total_taxable) - income_tax(
            total_taxable - trust_cgt_gain_dist_assessable
        )
    else:
        tcgd_rate = max(marginal_rate(total_taxable), 0.30)
        base_cgt_tax = trust_cgt_gain_dist_assessable * tcgd_rate
    return max(0.0, base_cgt_tax - trust_cgt_gain_dist * 0.30)


def _compute_iteration_tax(
    year: int,
    base_taxable_income: float,
    trust_distribution_income: float,
    nre_capital_gain_dist: float,
    trust_cgt_gain_dist: float,
    total_concessional: float,
    re_cgt_events: list[tuple[float, float]],
    trust_dissolution_gain: float,
    trust_dissolution_tax: float,
    state: _DrawState,
) -> tuple[float, float, float, float]:
    """Compute personal tax for one solver iteration.

    Returns (actual_tax_paid, personal_tax_ordinary, div293, total_taxable).
    """
    if year < INDEXATION_START_YEAR:
        eff_nre_dist_cg = nre_capital_gain_dist * 0.5
        eff_trust_dist_cg = trust_cgt_gain_dist * 0.5
    else:
        eff_nre_dist_cg = nre_capital_gain_dist
        eff_trust_dist_cg = trust_cgt_gain_dist

    nre_cap_gain = eff_nre_dist_cg + state.nre_gain_total
    trust_cap_gain = eff_trust_dist_cg + state.trust_gain_total + trust_dissolution_gain
    total_taxable = (
        base_taxable_income
        + nre_cap_gain
        + sum(g for g, _ in re_cgt_events)
        + trust_cap_gain
    )

    personal_tax_ordinary = income_tax(base_taxable_income, trust_distribution_income)
    nre_cgt_tax = state.nre_cgt_total
    re_cgt_tax = sum(t for _, t in re_cgt_events)
    trust_sales_tax = max(0.0, state.trust_cgt_total - state.trust_gain_total * 0.30)
    trust_diss_tax = max(0.0, trust_dissolution_tax - trust_dissolution_gain * 0.30)
    trust_dist_cgt_tax = _compute_trust_dist_cgt_tax(
        year, total_taxable, trust_cgt_gain_dist,
        eff_trust_dist_cg,
    )
    div293 = division_293_tax(total_concessional, total_taxable)

    actual_tax = (
        personal_tax_ordinary
        + nre_cgt_tax
        + re_cgt_tax
        + trust_sales_tax
        + trust_diss_tax
        + trust_dist_cgt_tax
        + div293
    )
    return actual_tax, personal_tax_ordinary, div293, total_taxable


# ---------------------------------------------------------------------------
# Iterative solver
# ---------------------------------------------------------------------------

def _run_one_iteration(
    state: _DrawState,
    config,
    is_accessible: bool,
    age: int,
    year: int,
    cpi_now: float,
    expenses_nominal: float,
    base_taxable_income: float,
    trust_distribution_income: float,
    nre_capital_gain_dist: float,
    trust_cgt_gain_dist: float,
    total_concessional: float,
    re_cgt_events: list[tuple[float, float]],
    trust_dissolution_gain: float,
    trust_dissolution_tax: float,
    strategy,
    nre_parcels: list[Parcel],
    trust_parcels: list[Parcel],
) -> tuple[float, float, float, float]:
    """Run one solver pass: compute tax, update funding gap, draw if needed.

    Returns (actual_tax, personal_tax, div293, total_taxable).
    """
    actual_tax, personal_tax, div293, total_taxable = _compute_iteration_tax(
        year, base_taxable_income, trust_distribution_income,
        nre_capital_gain_dist, trust_cgt_gain_dist, total_concessional,
        re_cgt_events, trust_dissolution_gain, trust_dissolution_tax, state,
    )
    state.funding_gap = (expenses_nominal + actual_tax) - state.available_cash

    no_assets = (
        not nre_parcels
        and not trust_parcels
        and not (is_accessible and (state.super_pension_balance + state.super_accumulation_balance) > 0)
    )
    if state.funding_gap <= 1.0 or no_assets:
        return actual_tax, personal_tax, div293, total_taxable

    mode = config.drawdown_policy.mode
    if mode == "waterfall":
        _run_waterfall(state, config, is_accessible, age, year, cpi_now, total_taxable, strategy)
    elif mode == "blended":
        _run_blended(state, config, is_accessible, age, year, cpi_now, total_taxable, strategy)
    elif mode == "rebalanced":
        _run_rebalanced(state, config, is_accessible, age, year, cpi_now, total_taxable, strategy)
    elif mode == "greedy":
        _run_greedy(state, config, is_accessible, age, year, cpi_now, total_taxable)

    return actual_tax, personal_tax, div293, total_taxable


def run_iterative_solver(
    config,
    year: int,
    age: int,
    cpi_now: float,
    base_taxable_income: float,
    trust_distribution_income: float,
    nre_capital_gain_dist: float,
    trust_cgt_gain_dist: float,
    total_concessional: float,
    re_cgt_events: list[tuple[float, float]],
    trust_dissolution_gain: float,
    trust_dissolution_tax: float,
    expenses_nominal: float,
    available_cash_pre_draw: float,
    super_acc_balance: float,
    super_pen_balance: float,
    nre_parcels: list[Parcel],
    trust_parcels: list[Parcel],
    nre_price: dict[str, float],
    trust_price: float,
    strategy,
) -> tuple[_DrawState, float, float, float, float]:
    """Run up to 5 iterations to converge on tax + funding gap.

    Returns (draw_state, actual_tax_paid, personal_tax_ordinary, div293, total_taxable).
    """
    is_accessible = age >= config.super_access_age and (
        age >= config.retirement_age or age >= 65
    )
    state = _DrawState(
        super_pension_balance=super_pen_balance,
        super_accumulation_balance=super_acc_balance,
        nre_parcels=nre_parcels,
        trust_parcels=trust_parcels,
        nre_price=nre_price,
        trust_price=trust_price,
        available_cash=available_cash_pre_draw,
    )
    actual_tax = personal_tax = div293 = total_taxable = 0.0

    for iteration in range(5):
        actual_tax, personal_tax, div293, total_taxable = _run_one_iteration(
            state, config, is_accessible, age, year, cpi_now, expenses_nominal,
            base_taxable_income, trust_distribution_income,
            nre_capital_gain_dist, trust_cgt_gain_dist, total_concessional,
            re_cgt_events, trust_dissolution_gain, trust_dissolution_tax,
            strategy, nre_parcels, trust_parcels,
        )
        if iteration == 0:
            state.initial_funding_gap = state.funding_gap
        if state.funding_gap <= 1.0:
            break

    state.nre_parcels = [p for p in state.nre_parcels if p.units > 1e-6]
    state.trust_parcels = [p for p in state.trust_parcels if p.units > 1e-6]
    return state, actual_tax, personal_tax, div293, total_taxable
