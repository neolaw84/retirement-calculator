import pytest
import pandas as pd
from retirement_calculator.simulation import simulate, CalculatorConfig
from retirement_calculator.rates import ConstantRate

def test_super_pension_phase_transition():
    """
    Test that super moves to pension phase at age 60 (if retired)
    and that earnings in pension phase are tax-free.
    """
    config = CalculatorConfig(
        current_year=2025,
        current_age=58,
        retirement_age=60,
        initial_super_balance=1_000_000.0, # Under TBC
        salary=0.0,
        expenses=0.0,
        super_growth_rate=ConstantRate(0.10), # 10% for easy math
        inflation_rate=ConstantRate(0.0), # No inflation for easy math
        transfer_balance_cap=1_900_000.0
    )
    
    df = simulate(config)
    
    # Age 58 (2025) - Accumulation
    # Earnings = 1,000,000 * 0.10 = 100,000
    # Tax = 100,000 * 0.15 = 15,000
    # EOY Balance = 1,000,000 + 100,000 - 15,000 = 1,085,000
    row_58 = df[df['age'] == 58].iloc[0]
    assert row_58['super_fund_tax'] == 15000.0
    assert row_58['super_balance_eoy'] == 1085000.0
    assert row_58['super_pension_balance_eoy'] == 0.0
    
    # Age 60 (2027) - Retired, should move to pension
    # Start of 2027 balance: we need to calculate 2026 first
    # 2026: 1,085,000 * 1.10 - (108,500 * 0.15) = 1,085,000 + 108,500 - 16,275 = 1,177,225
    # 2027: Moves to pension at start of year.
    # Earnings on 1,177,225 @ 10% = 117,722.50
    # Pension Tax = 0
    row_60 = df[df['age'] == 60].iloc[0]
    assert row_60['super_fund_tax'] == 0.0
    assert row_60['super_pension_balance_eoy'] > 0.0
    assert row_60['super_accumulation_balance_eoy'] == 0.0

def test_transfer_balance_cap_enforcement():
    """
    Test that super moved to pension phase is capped by TBC.
    """
    config = CalculatorConfig(
        current_year=2025,
        current_age=65, # Already accessible
        retirement_age=65,
        initial_super_balance=3_000_000.0, # Well over $1.9m TBC
        salary=0.0,
        expenses=0.0,
        super_growth_rate=ConstantRate(0.10),
        inflation_rate=ConstantRate(0.0),
        transfer_balance_cap=1_900_000.0
    )
    
    df = simulate(config)
    row_65 = df[df['age'] == 65].iloc[0]
    
    # Pension balance should be exactly TBC (since we moved it at start of year) + earnings
    # Initial: 3.0M. 1.9M moves to pension. 1.1M stays in accumulation.
    # Min drawdown (age 65) = 1.9M * 0.05 = 95,000.
    # Pension balance becomes 1,900,000 - 95,000 = 1,805,000.
    # Pension Earnings = 1,805,000 * 0.1 = 180,500. 
    # EOY Pension = 1,805,000 + 180,500 = 1,985,500.
    # Accumulation Earnings = 1,110,000 - 0 = 1.1M * 0.1 = 110,000. 
    # Tax = 110,000 * 0.15 = 16,500. 
    # EOY Accumulation = 1,100,000 + 110,000 - 16,500 = 1,193,500.
    
    assert row_65['super_pension_balance_eoy'] == 1985500.0
    assert row_65['super_accumulation_balance_eoy'] == 1193500.0
    assert row_65['super_fund_tax'] == 16500.0
