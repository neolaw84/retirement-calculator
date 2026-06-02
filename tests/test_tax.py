import pytest
from retirement_calculator.tax import income_tax, marginal_rate, division_293_tax, super_fund_tax
from retirement_calculator.tax.cgt import cgt_on_parcel
from retirement_calculator.models import Parcel

def test_marginal_rate():
    assert marginal_rate(18000) == 0.0
    assert marginal_rate(40000) == 0.16
    assert marginal_rate(100000) == 0.30
    assert marginal_rate(150000) == 0.37
    assert marginal_rate(200000) == 0.45

def test_income_tax_no_lito_30k():
    # $30,000 income (LITO permanently not modelled per D03):
    # Tax = (30000 - 18201) * 0.16 = 1887.84
    # Medicare = 30000 * 0.02 = 600
    # Net tax = 1887.84 + 600 = 2487.84
    assert pytest.approx(income_tax(30000), 0.01) == 2487.84

def test_income_tax_no_lito_40k():
    # $40,000 income (LITO permanently not modelled per D03):
    # Tax = (40000 - 18201) * 0.16 = 3487.84
    # Medicare = 40000 * 0.02 = 800
    # Net tax = 3487.84 + 800 = 4287.84
    assert pytest.approx(income_tax(40000), 0.01) == 4287.84

def test_div293_tax():
    # salary 200k, super 30k -> 230k < 250k: 0
    assert division_293_tax(30000, 200000) == 0.0
    # salary 240k, super 30k -> 270k. Taxable contrib = 270 - 250 = 20k
    # Tax = 20000 * 0.15 = 3000
    assert division_293_tax(30000, 240000) == 3000.0

def test_cgt_new_regime_indexed():
    # Sale in 2027, held > 1 year
    p = Parcel(asset_type="stock", year_acquired=2026, cost_base=1000, cpi_at_acquisition=100, units=100)
    # Sale price $15/unit = 1500 proceeds. CPI = 110.
    # Indexed cost base = 1000 * (110/100) = 1100
    # Real gain = 400
    # Marginal rate at 100k income is 0.30. Plus 0.02 Medicare = 0.32.
    # CGT = 400 * 0.32 = 128
    gain, tax = cgt_on_parcel(p, 15.0, 2027, 110.0, 100000)
    assert gain == 400.0
    assert tax == 128.0

def test_cgt_30_percent_floor():
    # Low income (e.g. 20k) but real gain exists.
    p = Parcel(asset_type="stock", year_acquired=2026, cost_base=1000, cpi_at_acquisition=100, units=100)
    # Real gain 400.
    # Marginal rate at 20k is 0.16. Floor is 0.30.
    # CGT = 400 * 0.30 = 120
    gain, tax = cgt_on_parcel(p, 15.0, 2027, 110.0, 20000)
    assert tax == 120.0
