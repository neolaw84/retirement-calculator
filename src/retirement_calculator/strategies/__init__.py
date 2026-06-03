"""Drawdown strategies for NRE (Non-Real-Estate) assets.

Strategies determine the ORDER in which parcels are sold when a drawdown is
needed from the NRE portfolio.

All strategies return a list of (Parcel, units_to_sell) tuples.
The caller must update the parcel list and compute CGT from these.
"""

from __future__ import annotations

import copy
from typing import Protocol

import numpy as np

from retirement_calculator.models import Parcel
from retirement_calculator.tax.cgt import cgt_on_parcel


class DrawdownStrategy(Protocol):
    """Protocol that all drawdown strategies must satisfy."""

    def select_parcels(
        self,
        parcels: list[Parcel],
        target_proceeds: float,
        price_per_unit: dict[str, float],
        sale_year: int,
        cpi_at_sale: float,
        other_income: float,
        target_allocation: dict[str, float] | None,
    ) -> list[tuple[Parcel, float]]:
        """Return a list of (parcel, units_to_sell) pairs.

        Parameters
        ----------
        parcels : list[Parcel]
            Current holding parcels (not mutated).
        target_proceeds : float
            Nominal dollars to raise via sales.
        price_per_unit : dict[str, float]
            Current market price per unit, keyed by asset_type ('stock', 'bond').
        sale_year : int
            Calendar year of the sale.
        cpi_at_sale : float
            CPI index at sale date.
        other_income : float
            Non-CGT taxable income for marginal rate purposes.
        target_allocation : dict[str, float] | None
            Desired allocation by asset_type (e.g. {'stock': 0.6, 'bond': 0.4}).
            Used by the rebalancing strategy.

        Returns
        -------
        list of (parcel, units_to_sell) pairs.
        """
        ...


def _total_portfolio_value(
    parcels: list[Parcel],
    price_per_unit: dict[str, float],
) -> float:
    return sum(p.units * price_per_unit[p.asset_type] for p in parcels)


def _fill_proceeds(
    ordered_parcels: list[Parcel],
    target_proceeds: float,
    price_per_unit: dict[str, float],
) -> list[tuple[Parcel, float]]:
    """Sell parcels in order until target_proceeds is met."""
    result: list[tuple[Parcel, float]] = []
    remaining = target_proceeds
    for parcel in ordered_parcels:
        if remaining <= 0:
            break
        unit_price = price_per_unit[parcel.asset_type]
        units_available = parcel.units
        max_proceeds = units_available * unit_price
        if max_proceeds <= remaining:
            result.append((parcel, units_available))
            remaining -= max_proceeds
        else:
            units_to_sell = remaining / unit_price
            result.append((parcel, units_to_sell))
            remaining = 0
    return result


class LIFOStrategy:
    """Last In, First Out – sell newest parcels first."""

    def select_parcels(
        self,
        parcels: list[Parcel],
        target_proceeds: float,
        price_per_unit: dict[str, float],
        sale_year: int,
        cpi_at_sale: float,
        other_income: float,
        target_allocation: dict[str, float] | None = None,
    ) -> list[tuple[Parcel, float]]:
        ordered = sorted(parcels, key=lambda p: p.year_acquired, reverse=True)
        return _fill_proceeds(ordered, target_proceeds, price_per_unit)


class FIFOStrategy:
    """First In, First Out – sell oldest parcels first."""

    def select_parcels(
        self,
        parcels: list[Parcel],
        target_proceeds: float,
        price_per_unit: dict[str, float],
        sale_year: int,
        cpi_at_sale: float,
        other_income: float,
        target_allocation: dict[str, float] | None = None,
    ) -> list[tuple[Parcel, float]]:
        ordered = sorted(parcels, key=lambda p: p.year_acquired)
        return _fill_proceeds(ordered, target_proceeds, price_per_unit)


class TaxOptimisedGreedyStrategy:
    """Sell the parcel that produces the minimum CGT liability first (greedy)."""

    def select_parcels(
        self,
        parcels: list[Parcel],
        target_proceeds: float,
        price_per_unit: dict[str, float],
        sale_year: int,
        cpi_at_sale: float,
        other_income: float,
        target_allocation: dict[str, float] | None = None,
    ) -> list[tuple[Parcel, float]]:
        # Score each parcel by CGT per dollar of proceeds, then sort ascending
        def cgt_rate(parcel: Parcel) -> float:
            unit_price = price_per_unit[parcel.asset_type]
            if unit_price <= 0 or parcel.units <= 0:
                return 0.0
            # Score assuming the whole parcel is sold
            _, cgt = cgt_on_parcel(
                parcel, unit_price, sale_year, cpi_at_sale, other_income
            )
            proceeds = parcel.units * unit_price
            return cgt / proceeds if proceeds > 0 else 0.0

        ordered = sorted(parcels, key=cgt_rate)
        return _fill_proceeds(ordered, target_proceeds, price_per_unit)


def _sell_overweight_parcels(
    parcels: list[Parcel],
    remaining: float,
    price_per_unit: dict[str, float],
    type_values: dict[str, float],
    total: float,
    target_allocation: dict[str, float],
) -> tuple[list[tuple[Parcel, float]], float]:
    """Sell most-overweight asset types down to their target values.

    Returns (sold_pairs, remaining_proceeds_needed).
    """
    result: list[tuple[Parcel, float]] = []
    overweight = {
        at: (type_values[at] / total) - target_allocation.get(at, 0.0)
        for at in type_values
    }
    for asset_type in sorted(overweight, key=lambda x: -overweight[x]):
        if remaining <= 0:
            break
        current_val = type_values[asset_type]
        target_val = total * target_allocation.get(asset_type, 0.0)
        surplus = max(0.0, current_val - target_val)
        if surplus <= 0:
            continue
        sell_amount = min(remaining, surplus)
        type_parcels = sorted(
            [p for p in parcels if p.asset_type == asset_type],
            key=lambda p: p.year_acquired,
        )
        sold = _fill_proceeds(type_parcels, sell_amount, price_per_unit)
        result.extend(sold)
        actual_sold_val = sum(u * price_per_unit[p.asset_type] for p, u in sold)
        remaining -= actual_sold_val
        type_values[asset_type] -= actual_sold_val
        total -= actual_sold_val
    return result, remaining


def _fill_from_remaining(
    parcels: list[Parcel],
    already_sold: list[tuple[Parcel, float]],
    remaining: float,
    price_per_unit: dict[str, float],
) -> list[tuple[Parcel, float]]:
    """FIFO fallback: sell from parcels not already in already_sold."""
    result: list[tuple[Parcel, float]] = []
    sold_units = {id(r[0]): r[1] for r in already_sold}
    candidates = sorted(
        [p for p in parcels if p not in [r[0] for r in already_sold]],
        key=lambda p: p.year_acquired,
    )
    for p in candidates:
        if remaining <= 0:
            break
        available = p.units - sold_units.get(id(p), 0.0)
        if available <= 1e-6:
            continue
        unit_price = price_per_unit[p.asset_type]
        max_proceeds = available * unit_price
        if max_proceeds <= remaining:
            result.append((p, available))
            remaining -= max_proceeds
        else:
            result.append((p, remaining / unit_price))
            remaining = 0
    return result


class RebalancingStrategy:
    """Maintain (age - 10)% in bonds, rest in stocks while drawing down.

    Sells whichever asset is most overweight relative to target allocation.
    """

    def select_parcels(
        self,
        parcels: list[Parcel],
        target_proceeds: float,
        price_per_unit: dict[str, float],
        sale_year: int,
        cpi_at_sale: float,
        other_income: float,
        target_allocation: dict[str, float] | None = None,
    ) -> list[tuple[Parcel, float]]:
        if target_allocation is None:
            return FIFOStrategy().select_parcels(
                parcels, target_proceeds, price_per_unit,
                sale_year, cpi_at_sale, other_income
            )

        type_values: dict[str, float] = {
            asset_type: sum(
                p.units * price_per_unit[p.asset_type]
                for p in parcels if p.asset_type == asset_type
            )
            for asset_type in price_per_unit
        }
        total = sum(type_values.values())
        if total == 0:
            return []

        result, remaining = _sell_overweight_parcels(
            parcels, target_proceeds, price_per_unit,
            type_values, total, target_allocation,
        )
        if remaining > 0.01:
            result.extend(_fill_from_remaining(parcels, result, remaining, price_per_unit))
        return result
