"""Per-source draw helpers and drawdown mode implementations.

The iterative solver and tax computation live in _solver.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from retirement_calculator.models import Parcel
from retirement_calculator.tax.cgt import cgt_on_parcel

if TYPE_CHECKING:
    from retirement_calculator.simulation._config import CalculatorConfig


# --- Mutable solver state ---

@dataclass
class _DrawState:
    """All mutable state threaded through the iterative drawdown solver."""

    super_pension_balance: float
    super_accumulation_balance: float
    nre_parcels: list[Parcel]
    trust_parcels: list[Parcel]
    nre_price: dict[str, float]
    trust_price: float

    available_cash: float

    super_pension_draw: float = 0.0
    super_accumulation_draw: float = 0.0
    nre_drawdown: float = 0.0
    trust_drawdown: float = 0.0

    nre_gain_total: float = 0.0
    nre_cgt_total: float = 0.0
    trust_gain_total: float = 0.0
    trust_cgt_total: float = 0.0

    initial_funding_gap: float | None = None
    funding_gap: float = 0.0


# --- Per-source draw helpers ---

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
            total_taxable, units_sold=units_sold,
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
            units_sold=units_sold,
        )
        parcel.units -= units_sold
        state.trust_drawdown += val
        state.trust_gain_total += gain
        state.trust_cgt_total += cgt
        state.available_cash += val


# --- Drawdown mode implementations ---

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

    filtered: dict[str, float] = {
        s: w for s, w in target.items()
        if not (s == "super" and not is_accessible)
    }
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

    before = state.available_cash
    if best == "super":
        _draw_super(state, state.funding_gap, is_accessible)
    elif best == "nre":
        _draw_nre(state, state.funding_gap, strategy, age, year, cpi_now, total_taxable, config.drawdown_strategy)
    elif best == "trust":
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
