"""Pydantic data models for the retirement calculator."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from retirement_calculator.rates import RateFunction, ConstantRate


# ---------------------------------------------------------------------------
# Asset parcel (transaction) – used for CGT tracking
# ---------------------------------------------------------------------------

@dataclass
class Parcel:
    """A single lot/parcel of an ETF holding acquired at a point in time.

    Attributes
    ----------
    asset_type : str
        Either 'stock' or 'bond'.
    year_acquired : int
        Calendar year in which this parcel was acquired.
    cost_base : float
        Total cost base of this parcel in nominal dollars at acquisition.
    cpi_at_acquisition : float
        CPI index value at the time of acquisition (used for inflation-indexed CGT).
    units : float
        Number of units (can be fractional).
    discounted_gain_at_2027 : float
        The 50% discounted nominal gain accrued up to 2027-06-30.
        Only populated for parcels acquired before 2027.
    """

    asset_type: Literal["stock", "bond"]
    year_acquired: int
    cost_base: float  # nominal cost at acquisition
    cpi_at_acquisition: float
    units: float
    discounted_gain_at_2027: float = 0.0


# ---------------------------------------------------------------------------
# NRE Asset configuration
# ---------------------------------------------------------------------------

@dataclass
class AssetAllocation:
    """Target allocation for NRE assets.

    Attributes
    ----------
    stock : float
        Proportion allocated to stock ETF (0.0 – 1.0).
    bond : float
        Proportion allocated to bond ETF (0.0 – 1.0).
    """

    stock: float = 0.7
    bond: float = 0.3

    def __post_init__(self) -> None:
        total = self.stock + self.bond
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"stock + bond must sum to 1.0, got {total}")


@dataclass
class NREAssetConfig:
    """Configuration for Non-Real-Estate assets outside super.

    Attributes
    ----------
    allocation : AssetAllocation
        Target stock/bond split.
    stock_growth_rate : RateFunction
        Annual expected growth rate for stock ETF component.
    bond_growth_rate : RateFunction
        Annual expected growth rate for bond ETF component.
    stock_yield : float
        Annual distribution yield for stock ETF as a fraction of value (e.g. 0.04).
    bond_yield : float
        Annual distribution yield for bond ETF as a fraction of value (e.g. 0.03).
    capital_gain_component_pct : float
        The portion of distribution treated as capital return/gain reinvested (e.g. 0.30).
    annual_contribution : float
        Annual amount added to NRE assets (before retirement), in nominal dollars.
    initial_value : float
        Current market value of existing NRE portfolio, in today's nominal dollars.
    """

    allocation: AssetAllocation = field(default_factory=AssetAllocation)
    stock_growth_rate: RateFunction = field(default_factory=lambda: ConstantRate(0.06))
    bond_growth_rate: RateFunction = field(default_factory=lambda: ConstantRate(0.01))
    stock_yield: float = 0.02
    bond_yield: float = 0.03
    capital_gain_component_pct: float = 0.30
    annual_contribution: float = 0.0
    initial_value: float = 0.0


# ---------------------------------------------------------------------------
# Trust Asset configuration
# ---------------------------------------------------------------------------

@dataclass
class TrustAssetConfig:
    """Configuration for a Discretionary Trust holding.

    Income distributions from this trust attract the minimum 30% non-refundable
    credit introduced in the May 12, 2026 budget.  Character of income (ordinary
    vs capital gains) is retained at the beneficiary level.

    Attributes
    ----------
    initial_value : float
        Current market value of trust assets in today's nominal dollars.
    annual_contribution : float
        Annual injection into the trust (before retirement), in today's dollars.
    annual_post_retirement_contribution : float
        Annual injection into the trust (after retirement), in today's dollars.
    distribution_yield : float
        Annual ordinary income distribution as a fraction of corpus (e.g. 0.04 = 4%).
    growth_rate : RateFunction
        Annual expected capital growth rate of the trust corpus.
    capital_gain_component_pct : float
        Portion of the annual distribution treated as a capital gain (e.g. 0.10).
    dissolution_year : int | None
        Year the trust is wound up / corpus distributed.  None = held indefinitely.
    """

    initial_value: float
    annual_contribution: float = 0.0
    annual_post_retirement_contribution: float = 0.0
    distribution_yield: float = 0.04
    annual_capital_gain_dist: float = 0.0 # Nominal capital gain distributed annually
    growth_rate: RateFunction = field(default_factory=lambda: ConstantRate(0.07))
    capital_gain_component_pct: float = 0.0
    dissolution_year: int | None = None


# ---------------------------------------------------------------------------
# Real Estate Asset configuration
# ---------------------------------------------------------------------------

@dataclass
class REAssetConfig:
    """Configuration for a single Real Estate asset.

    Attributes
    ----------
    property_id : int
        Auto-assigned identifier (1-based).
    year_bought : int
        Year of purchase; determines negative gearing eligibility.
    valuation_at_base_date : float
        Valuation of the property on 2027-07-01, used as CGT cost base reference
        (or at acquisition if purchased after base date).
    gross_annual_rent : float
        Annual gross rent income in today's dollars.
    growth_rate : RateFunction
        Annual expected capital growth rate.
    sale_year : int | None
        Year the property is expected to be sold. None = never sold within horizon.
    annual_pre_retirement_contribution : float
        Annual cash top-up from salary for mortgage/maintenance (before retirement), today's $.
    annual_post_retirement_contribution : float
        Annual cash top-up after retirement (e.g. from drawdowns), today's $.
    sale_reinvestment_target : str
        Where to invest net proceeds from property sale: 'nre', 'trust', 'super', or 'cash'.
        Default is 'nre'.
    sale_costs_pct : float
        Transaction costs as a percentage of sale price (e.g. 0.02 for 2%).
    """

    property_id: int
    year_bought: int
    purchase_price: float
    valuation_at_base_date: float
    gross_annual_rent: float
    loan_balance: float = 0.0
    growth_rate: RateFunction = field(default_factory=lambda: ConstantRate(0.05))
    sale_year: int | None = None
    annual_pre_retirement_contribution: float = 0.0
    annual_post_retirement_contribution: float = 0.0
    sale_reinvestment_target: Literal["nre", "trust", "super", "cash"] = "nre"
    sale_costs_pct: float = 0.02  # Agent/Legal fees
    discounted_gain_at_2027: float = 0.0

# ---------------------------------------------------------------------------
# Drawdown Orchestration models
# ---------------------------------------------------------------------------

@dataclass
class DrawdownPolicy:
    """Configures the high-level drawdown preferences.

    Attributes
    ----------
    mode : str
        Either 'waterfall', 'blended', 'greedy', or 'rebalanced'.
    sequence : list[str]
        Priority order for 'waterfall' (e.g. ['trust', 'nre', 'super']).
    ratios : dict[str, float]
        Target mix for 'blended' (e.g. {'trust': 0.4, 'nre': 0.6}).
    """

    mode: Literal["waterfall", "blended", "greedy", "rebalanced"] = "waterfall"
    sequence: list[str] = field(default_factory=lambda: ["super", "nre", "trust"])
    ratios: dict[str, float] = field(default_factory=dict)
