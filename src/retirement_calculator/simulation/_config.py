"""Configuration dataclass and pure helper functions for the simulation.

This module contains only the static inputs to the simulation (CalculatorConfig)
and small stateless helper functions.  No simulation logic lives here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import numpy as np

from retirement_calculator.models import (
    NREAssetConfig,
    REAssetConfig,
    TrustAssetConfig,
    DrawdownPolicy,
)
from retirement_calculator.rates import RateFunction, ConstantRate


# ---------------------------------------------------------------------------
# Calculator configuration dataclass
# ---------------------------------------------------------------------------

@dataclass
class CalculatorConfig:
    """All inputs to the retirement simulation.

    Attributes
    ----------
    current_year : int
        Simulation start year (e.g. 2026).
    current_age : int
        User's age at the start of current_year.
    retirement_age : int
        Age at which salary/employment income stops.
    super_access_age : int
        Age when superannuation becomes accessible (preservation age; default 60).
    salary : float
        Annual gross salary income in today's dollars (pre-tax).
    salary_growth_rate : RateFunction
        Real growth rate of salary (applied each year before retirement).
    inflation_rate : RateFunction
        Annual CPI inflation rate function.
    nre_config : NREAssetConfig
        Non-real-estate asset configuration.
    re_assets : list[REAssetConfig]
        Real estate asset configurations.
    additional_concessional_super : float
        Additional personal concessional super contributions per year (today's dollars).
    use_carry_forward_super : bool
        Whether to maximise concessional contributions using carry-forward provisions.
    expenses : float
        Annual living expenses in today's dollars (pre-retirement).
    retirement_expenses : float
        Annual living expenses in today's dollars (post-retirement).
    drawdown_strategy : str
        One of 'fifo', 'lifo', 'tax_optimised', 'rebalancing'.
    super_growth_rate : RateFunction
        Annual growth rate of the super fund balance.
    cash_interest_rate : RateFunction | None
        Annual nominal growth rate applied to cash balance.
        If None, uses inflation_rate.
    initial_super_balance : float
        Super balance at start of simulation, in nominal dollars.
    trust_assets : TrustAssetConfig | None
        Optional discretionary trust configuration.
    surplus_reinvestment_target : str
        Where to invest year-end cash surplus: 'nre', 'trust', 'super', or 'cash'.
    surplus_reinvestment_pct : float
        Fraction of annual cash surplus to reinvest (0.0 to 1.0).
    seed : int | None
        Random seed for reproducible stochastic simulations.
    """

    current_year: int
    current_age: int
    retirement_age: int
    super_access_age: int = 60
    salary: float = 0.0
    salary_growth_rate: RateFunction = field(default_factory=lambda: ConstantRate(0.0))
    inflation_rate: RateFunction = field(default_factory=lambda: ConstantRate(0.0))
    nre_config: NREAssetConfig = field(default_factory=NREAssetConfig)
    re_assets: list[REAssetConfig] = field(default_factory=list)
    additional_concessional_super: float = 0.0
    use_carry_forward_super: bool = False
    expenses: float = 0.0
    retirement_expenses: float = 0.0
    drawdown_strategy: str = "fifo"
    drawdown_policy: DrawdownPolicy = field(default_factory=DrawdownPolicy)
    super_growth_rate: RateFunction = field(default_factory=lambda: ConstantRate(0.07))
    loan_interest_rate: RateFunction = field(default_factory=lambda: ConstantRate(0.06))
    cash_interest_rate: RateFunction | None = None
    initial_super_balance: float = 0.0
    transfer_balance_cap: float = 1_900_000.0
    trust_assets: TrustAssetConfig | None = None
    surplus_reinvestment_target: Literal["nre", "trust", "super", "cash"] = "nre"
    surplus_reinvestment_pct: float = 1.0
    seed: int | None = None


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

def _build_cpi_series(
    start_year: int,
    end_year: int,
    inflation_fn: RateFunction,
    rng: np.random.Generator,
) -> dict[int, float]:
    """Return a CPI index dict with start_year = 100.0, growing by inflation."""
    cpi: dict[int, float] = {start_year: 100.0}
    for yr in range(start_year + 1, end_year + 1):
        cpi[yr] = cpi[yr - 1] * (1.0 + inflation_fn.sample(rng))
    return cpi


def _concessional_cap(year: int) -> float:
    """Return the concessional contributions cap for a given financial year."""
    if year <= 2026:
        return 30_000.0
    return 32_500.0  # Assumed constant post 2026-27


def _pension_min_drawdown_rate(age: int) -> float:
    """Return the ATO minimum drawdown % for an account-based super pension."""
    if age < 65:
        return 0.04
    elif age < 75:
        return 0.05
    elif age < 80:
        return 0.06
    elif age < 85:
        return 0.07
    elif age < 90:
        return 0.09
    elif age < 95:
        return 0.11
    return 0.14
