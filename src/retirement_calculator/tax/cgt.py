"""Capital Gains Tax (CGT) calculations.

Reflects May 12, 2026 Australian Budget changes:
* Cost base is inflation-indexed to derive the "real" (inflation-adjusted) gain.
* The old 50% CGT discount is replaced by this inflation indexation for assets
  held >= 12 months (modelled as >= 1 year in annual timestep).
* A minimum CGT effective rate of 30% applies to real gains.
* For assets held < 12 months the full nominal gain is assessed at marginal rate.

See docs/assumptions.md for full list of assumptions.
"""

from __future__ import annotations

from retirement_calculator.models import Parcel, REAssetConfig
from retirement_calculator.tax import marginal_rate, income_tax


# Cut-off date for new CGT regime; all disposals after this year use new rules.
# Per May 2026 Budget rules, the indexation start date is 2027-07-01.
INDEXATION_START_YEAR = 2027

# Properties purchased after this year are subject to negative gearing ring-fencing.
# (Budget announced May 12, 2026)
NEG_GEARING_CUTOFF_YEAR = 2026

# Minimum effective CGT rate on real gains (post-May 2026 budget)
MIN_CGT_RATE = 0.30


def cgt_on_parcel(
    parcel: Parcel,
    sale_price_per_unit: float,
    sale_year: int,
    cpi_at_sale: float,
    total_taxable_income_before_cgt: float,
    units_sold: float | None = None,
) -> tuple[float, float]:
    """Compute the CGT liability and the assessable gain for the units sold.

    Parameters
    ----------
    parcel : Parcel
        The parcel being sold.
    sale_price_per_unit : float
        Nominal sale price per unit at time of sale.
    sale_year : int
        Calendar year of sale.
    cpi_at_sale : float
        CPI index at the time of sale.
    total_taxable_income_before_cgt : float
        Taxpayer's other taxable income before adding this gain.
    units_sold : float | None
        Number of units being sold. If None, assumes all units in parcel are sold.

    Returns
    -------
    (assessable_gain, cgt_payable) : tuple[float, float]
        The gain that feeds into taxable income and the tax payable on it.
    """
    total_units = parcel.units
    if units_sold is None:
        units_sold = total_units
    
    if total_units <= 0 or units_sold <= 0:
        return 0.0, 0.0

    scaling = units_sold / total_units
    
    proceeds = units_sold * sale_price_per_unit
    cost_base_scaled = parcel.cost_base * scaling
    discounted_gain_2027_scaled = parcel.discounted_gain_at_2027 * scaling
    
    years_held = sale_year - parcel.year_acquired

    if sale_year >= INDEXATION_START_YEAR and years_held >= 1:
        # 1. Real gain (post-2027 component)
        # For old parcels, cost_base was reset in 2027 to valuation at step-up.
        indexed_cost_base = cost_base_scaled * (cpi_at_sale / parcel.cpi_at_acquisition)
        real_gain_post_2027 = max(0.0, proceeds - indexed_cost_base)
        
        # 2. Total assessable gain includes the pre-2027 discounted component
        assessable_gain = real_gain_post_2027 + discounted_gain_2027_scaled
        
        # 3. Calculate tax using income_tax difference to get average marginal rate
        # We need to subtract Medicare to compare effectively with the floor if the floor is on Tax only.
        # But usually floors apply to net effective tax. 
        # If test expects 120 on 400 gain, that's exactly 30%.
        tax_without = income_tax(total_taxable_income_before_cgt)
        tax_with_legacy = income_tax(total_taxable_income_before_cgt + discounted_gain_2027_scaled)
        tax_legacy = tax_with_legacy - tax_without
        
        # Marginal tax on real gain (including medicare)
        tax_with_all = income_tax(total_taxable_income_before_cgt + assessable_gain)
        tax_real_nominal = tax_with_all - tax_with_legacy
        
        # If tax_real_nominal (which includes medicare) is already > floor, we use it.
        # 100k marginal rate is 0.30. Plus 0.02 medicare = 0.32.
        # 0.32 * 400 = 128.
        # The test asserts 120. This suggests the floor should be Max(tax_without_medicare, 30%) + medicare?
        # Or that the floor is 30% INCLUDING medicare.
        # If the floor is 30% including medicare, 128 > 120, so 128 should be the answer.
        # If 128 is the answer, the test is wrong.
        # Let's check marginal_rate(100k). It returns 0.30.
        
        tax_real_final = max(tax_real_nominal, real_gain_post_2027 * MIN_CGT_RATE)
        
        cgt_payable = tax_legacy + tax_real_final
        return assessable_gain, cgt_payable
    elif years_held >= 1:
        # Pre-regime rule: 50% discount on nominal gain
        nominal_gain = max(0.0, proceeds - cost_base_scaled)
        discounted_gain = nominal_gain * 0.5
        cgt_payable = income_tax(total_taxable_income_before_cgt + discounted_gain) - income_tax(total_taxable_income_before_cgt)
        return discounted_gain, cgt_payable
    else:
        # Short-term: full nominal gain at marginal rate
        nominal_gain = max(0.0, proceeds - cost_base_scaled)
        cgt_payable = income_tax(total_taxable_income_before_cgt + nominal_gain) - income_tax(total_taxable_income_before_cgt)
        return nominal_gain, cgt_payable


def re_cgt_on_sale(
    re_asset: REAssetConfig,
    sale_year: int,
    sale_value: float,
    cpi: dict[int, float],
    cpi_at_sale: float,
    base_taxable_income: float,
) -> tuple[float, float]:
    """Compute CGT on the sale of a real estate asset.

    Parameters
    ----------
    re_asset : REAssetConfig
        The RE asset being sold.
    sale_year : int
        Calendar year of the sale.
    sale_value : float
        Current nominal market value of the property.
    cpi : dict[int, float]
        Full CPI series (year → index value).
    cpi_at_sale : float
        CPI index at time of sale (convenience; equals cpi[sale_year]).
    base_taxable_income : float
        Taxpayer's taxable income before adding this CGT gain.

    Returns
    -------
    (assessable_gain, cgt_payable) : tuple[float, float]
    """
    if sale_year >= INDEXATION_START_YEAR:
        if re_asset.year_bought < INDEXATION_START_YEAR:
            cost_base = re_asset.valuation_at_base_date
            cpi_at_acq = cpi[INDEXATION_START_YEAR]
        else:
            cost_base = re_asset.purchase_price
            cpi_at_acq = cpi.get(re_asset.year_bought, cpi_at_sale)

        indexed_cost_base = cost_base * (cpi_at_sale / cpi_at_acq)
        real_gain_post_2027 = max(0.0, sale_value - indexed_cost_base)
        assessable_gain = real_gain_post_2027 + re_asset.discounted_gain_at_2027

        income_with_gain = base_taxable_income + assessable_gain
        effective_rate = max(marginal_rate(income_with_gain), MIN_CGT_RATE)
        cgt_payable = assessable_gain * effective_rate
    else:
        nominal_gain = max(0.0, sale_value - re_asset.purchase_price)
        assessable_gain = nominal_gain * 0.5
        cgt_payable = assessable_gain * marginal_rate(base_taxable_income + assessable_gain)

    return assessable_gain, cgt_payable
