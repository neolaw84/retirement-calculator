"""NamedTuple return types shared by income and capital phase functions."""

from __future__ import annotations

from typing import NamedTuple


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
