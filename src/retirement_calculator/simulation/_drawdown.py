"""Iterative drawdown solver and drawdown mode helpers.

This module contains the _DrawState dataclass (mutable solver state) and
the per-mode drawdown functions. The 5-pass iterative solver resolves the
equilibrium between taxable income (including CGT) and the annual funding gap.

Exception to 300-line rule: the four drawdown modes are intrinsically
complex and cannot be split further without losing clarity (D25).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np

from retirement_calculator.models import Parcel
from retirement_calculator.tax import income_tax, marginal_rate, division_293_tax
from retirement_calculator.tax.cgt import cgt_on_parcel, INDEXATION_START_YEAR

if TYPE_CHECKING:
    from retirement_calculator.simulation._config import CalculatorConfig
    from retirement_calculator.strategies import (
        LIFOStrategy,
        FIFOStrategy,
        TaxOptimisedGreedyStrategy,
        RebalancingStrategy,
    )


# ---------------------------------------------------------------------------
# Mutable solver state
# ---------------------------------------------------------------------------

@dataclass
class _DrawState:
    """All mutable state threaded through the iterative drawdown solver."""

    # Portfolio balances (mutated by draw helpers)
    super_pension_balance: float
    super_accumulation_balance: float
    nre_parcels: list[Parcel]
    trust_parcels: list[Parcel]
    nre_price: dict[str, float]
    trust_price: float

    # Available cash (grows as draws are made)
    available_cash: float

    # Accumulated draw amounts (not reset between iterations)
    super_pension_draw: float = 0.0
    super_accumulation_draw: float = 0.0
    nre_drawdown: float = 0.0
    trust_drawdown: float = 0.0

    # Accumulated CGT (not reset between iterations – D26)
    nre_gain_total: float = 0.0
    nre_cgt_total: float = 0.0
    trust_gain_total: float = 0.0
    trust_cgt_total: float = 0.0

    # Solver diagnostics
    initial_funding_gap: float | None = None
    funding_gap: float = 0.0


# ---------------------------------------------------------------------------
# Per-source draw helpers
# ---------------------------------------------------------------------------

def _draw_super(state: _DrawState, amount: float, is_accessible: bool) -> None:
    """Draw `amount` from super (pension then accumulation). Mutates state."""
    if not is_accessible or amount <= 0.0:
        return
    if state.super_pension_balance > 0.0:
        draw = min(amount, state.super_pension_balance)
        state.super_pension_balance -= draw
        state.super_pension_draw += draw
        state.available_cash += draw
        amount -= draw
    if amount > 1.0 and state.super_accumulation_balance > 0.0:
        draw = min(amount, state.super_accumulation_balance)
        state.super_accumulation_balance -= draw
        state.super_accumulation_draw += draw
        state.available_cash += draw


def _draw_nre(
    state: _DrawState,
    amount: float,
    strategy,
    age: int,
    year: int,
    cpi_now: float,
    total_taxable: float,
    drawdown_strategy_name: str,
) -> None:
    """Draw `amount` from NRE parcels. Mutates state (parcels + cash)."""
    if amount <= 0.0 or not state.nre_parcels:
        return
    target_allocation = None
    if drawdown_strategy_name == "rebalancing":
        bond_pct = min(max((age - 10) / 100.0, 0.0), 1.0)
        target_allocation = {"bond": bond_pct, "stock": 1.0 - bond_pct}

    for parcel, units_sold in strategy.select_parcels(
        parcels=state.nre_parcels,
        target_proceeds=amount,
        price_per_unit=state.nre_price,
        sale_year=year,
        cpi_at_sale=cpi_now,
        other_income=total_taxable,
        target_allocation=target_allocation,
    ):
        val = units_sold * state.nre_price[parcel.asset_type]
        gain, cgt = cgt_on_parcel(
            parcel, state.nre_price[parcel.asset_type], year, cpi_now,
            total_taxable, units_sold=units_sold
        )
        parcel.units -= units_sold
        state.nre_drawdown += val
        state.nre_gain_total += gain
        state.nre_cgt_total += cgt
        state.available_cash += val


def _draw_trust(
    state: _DrawState,
    amount: float,
    strategy,
    year: int,
    cpi_now: float,
    total_taxable: float,
) -> None:
    """Draw `amount` from trust parcels. Mutates state (parcels + cash)."""
    if amount <= 0.0 or not state.trust_parcels:
        return
    for parcel, units_sold in strategy.select_parcels(
        parcels=state.trust_parcels,
        target_proceeds=amount,
        price_per_unit={"stock": state.trust_price},
        sale_year=year,
        cpi_at_sale=cpi_now,
        other_income=total_taxable,
        target_allocation=None,
    ):
        val = units_sold * state.trust_price
        gain, cgt = cgt_on_parcel(
            parcel, state.trust_price, year, cpi_now, total_taxable,
            units_sold=units_sold
        )
        parcel.units -= units_sold
        state.trust_drawdown += val
        state.trust_gain_total += gain
        state.trust_cgt_total += cgt
        state.available_cash += val


# ---------------------------------------------------------------------------
# Tax computation
# ---------------------------------------------------------------------------

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
    # Effective CG from distributions (pre/post 2027 discount)
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

    # Ordinary income tax (trust 30% non-refundable credit handled by income_tax)
    personal_tax_ordinary = income_tax(base_taxable_income, trust_distribution_income)

    # CGT taxes
    nre_cgt_tax = state.nre_cgt_total
    re_cgt_tax = sum(t for _, t in re_cgt_events)
    trust_sales_tax = max(0.0, state.trust_cgt_total - state.trust_gain_total * 0.30)
    trust_diss_tax = max(0.0, trust_dissolution_tax - trust_dissolution_gain * 0.30)

    if year < INDEXATION_START_YEAR:
        assessable_trust_dist_cg = trust_cgt_gain_dist * 0.5
        base_cgt_tax = income_tax(total_taxable) - income_tax(
            total_taxable - assessable_trust_dist_cg
        )
    else:
        assessable_trust_dist_cg = trust_cgt_gain_dist
        tcgd_rate = max(marginal_rate(total_taxable), 0.30)
        base_cgt_tax = assessable_trust_dist_cg * tcgd_rate
    trust_dist_cgt_tax = max(0.0, base_cgt_tax - trust_cgt_gain_dist * 0.30)

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
# Drawdown mode implementations
# ---------------------------------------------------------------------------

def _run_waterfall(
    state: _DrawState,
    config,
    is_accessible: bool,
    age: int,
    year: int,
    cpi_now: float,
    total_taxable: float,
    strategy,
) -> None:
    """Waterfall drawdown: exhaust each source in config.drawdown_policy.sequence."""
    for source in config.drawdown_policy.sequence:
        if state.funding_gap <= 1.0:
            break
        before = state.available_cash
        if source == "super":
            _draw_super(state, state.funding_gap, is_accessible)
        elif source == "nre":
            _draw_nre(state, state.funding_gap, strategy, age, year, cpi_now, total_taxable, config.drawdown_strategy)
        elif source == "trust":
            _draw_trust(state, state.funding_gap, strategy, year, cpi_now, total_taxable)
        state.funding_gap -= state.available_cash - before


def _run_blended(
    state: _DrawState,
    config,
    is_accessible: bool,
    age: int,
    year: int,
    cpi_now: float,
    total_taxable: float,
    strategy,
) -> None:
    """Blended drawdown: split gap proportionally across sources per ratios."""
    ratios = config.drawdown_policy.ratios
    if not ratios:
        active = []
        for src in config.drawdown_policy.sequence:
            if src == "super" and is_accessible and (
                state.super_pension_balance + state.super_accumulation_balance
            ) > 0:
                active.append(src)
            elif src == "nre" and state.nre_parcels:
                active.append(src)
            elif src == "trust" and state.trust_parcels:
                active.append(src)
        ratios = {s: 1.0 / len(active) for s in active} if active else {}

    for source, pct in ratios.items():
        share = state.funding_gap * pct
        if share <= 0:
            continue
        if source == "super":
            _draw_super(state, share, is_accessible)
        elif source == "nre":
            _draw_nre(state, share, strategy, age, year, cpi_now, total_taxable, config.drawdown_strategy)
        elif source == "trust":
            _draw_trust(state, share, strategy, year, cpi_now, total_taxable)


def _run_rebalanced(
    state: _DrawState,
    config,
    is_accessible: bool,
    age: int,
    year: int,
    cpi_now: float,
    total_taxable: float,
    strategy,
) -> None:
    """Rebalanced drawdown: draw from the source furthest above its target ratio."""
    target = config.drawdown_policy.ratios
    if not target:
        if age < 60:
            target = {"nre": 0.7, "trust": 0.3, "super": 0.0}
        elif age < 75:
            target = {"nre": 0.3, "trust": 0.2, "super": 0.5}
        else:
            target = {"nre": 0.1, "trust": 0.1, "super": 0.8}

    filtered: dict[str, float] = {}
    for s, w in target.items():
        if s == "super" and not is_accessible:
            continue
        filtered[s] = w
    total_w = sum(filtered.values())
    if total_w <= 0:
        config.drawdown_policy.mode = "waterfall"
        return
    filtered = {s: w / total_w for s, w in filtered.items()}

    nre_val = sum(p.units * state.nre_price[p.asset_type] for p in state.nre_parcels)
    trust_val = sum(p.units * state.trust_price for p in state.trust_parcels)
    super_val = state.super_pension_balance + state.super_accumulation_balance
    total_val = nre_val + trust_val + super_val
    if total_val <= 0:
        return

    cur = {
        "nre": nre_val / total_val,
        "trust": trust_val / total_val,
        "super": super_val / total_val if is_accessible else 0.0,
    }
    diffs = {s: cur.get(s, 0.0) - filtered.get(s, 0.0) for s in filtered}
    best = max(diffs, key=diffs.get)

    if best == "super":
        before = state.available_cash
        _draw_super(state, state.funding_gap, is_accessible)
        state.funding_gap -= state.available_cash - before
    elif best == "nre":
        before = state.available_cash
        _draw_nre(state, state.funding_gap, strategy, age, year, cpi_now, total_taxable, config.drawdown_strategy)
        state.funding_gap -= state.available_cash - before
    elif best == "trust":
        before = state.available_cash
        _draw_trust(state, state.funding_gap, strategy, year, cpi_now, total_taxable)
        state.funding_gap -= state.available_cash - before


def _run_greedy(
    state: _DrawState,
    config,
    is_accessible: bool,
    age: int,
    year: int,
    cpi_now: float,
    total_taxable: float,
) -> None:
    """Greedy drawdown: super first (zero friction), then lowest-CGT-rate parcel."""
    before = state.available_cash
    _draw_super(state, state.funding_gap, is_accessible)
    state.funding_gap -= state.available_cash - before

    if state.funding_gap <= 1.0:
        return

    all_parcels = (
        [("nre", p, state.nre_price[p.asset_type]) for p in state.nre_parcels]
        + [("trust", p, state.trust_price) for p in state.trust_parcels]
    )

    def _friction(item: tuple) -> float:
        _, p, price = item
        _, cgt = cgt_on_parcel(p, price, year, cpi_now, total_taxable)
        val = p.units * price
        return cgt / val if val > 0 else 0.0

    all_parcels.sort(key=_friction)

    for source, p, price in all_parcels:
        if state.funding_gap <= 1.0:
            break
        units_to_sell = min(p.units, state.funding_gap / price)
        sold_val = units_to_sell * price
        gain, cgt = cgt_on_parcel(p, price, year, cpi_now, total_taxable, units_sold=units_to_sell)
        p.units -= units_to_sell
        state.available_cash += sold_val
        state.funding_gap -= sold_val
        if source == "nre":
            state.nre_drawdown += sold_val
            state.nre_gain_total += gain
            state.nre_cgt_total += cgt
        else:
            state.trust_drawdown += sold_val
            state.trust_gain_total += gain
            state.trust_cgt_total += cgt


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
    from retirement_calculator.simulation._config import _pension_min_drawdown_rate
    if super_pen_balance <= 0.0:
        return 0.0, super_pen_balance
    min_draw = super_pen_balance * _pension_min_drawdown_rate(age)
    return min_draw, super_pen_balance - min_draw


# ---------------------------------------------------------------------------
# Main iterative solver
# ---------------------------------------------------------------------------

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
        actual_tax, personal_tax, div293, total_taxable = _compute_iteration_tax(
            year, base_taxable_income, trust_distribution_income,
            nre_capital_gain_dist, trust_cgt_gain_dist, total_concessional,
            re_cgt_events, trust_dissolution_gain, trust_dissolution_tax, state
        )

        state.funding_gap = (expenses_nominal + actual_tax) - state.available_cash
        if iteration == 0:
            state.initial_funding_gap = state.funding_gap

        no_assets = (
            not nre_parcels
            and not trust_parcels
            and not (is_accessible and (state.super_pension_balance + state.super_accumulation_balance) > 0)
        )
        if state.funding_gap <= 1.0 or no_assets:
            break

        mode = config.drawdown_policy.mode
        if mode == "waterfall":
            _run_waterfall(state, config, is_accessible, age, year, cpi_now, total_taxable, strategy)
        elif mode == "blended":
            _run_blended(state, config, is_accessible, age, year, cpi_now, total_taxable, strategy)
        elif mode == "rebalanced":
            _run_rebalanced(state, config, is_accessible, age, year, cpi_now, total_taxable, strategy)
        elif mode == "greedy":
            _run_greedy(state, config, is_accessible, age, year, cpi_now, total_taxable)

    # Clean up zero-unit parcels
    state.nre_parcels = [p for p in state.nre_parcels if p.units > 1e-6]
    state.trust_parcels = [p for p in state.trust_parcels if p.units > 1e-6]

    return state, actual_tax, personal_tax, div293, total_taxable
