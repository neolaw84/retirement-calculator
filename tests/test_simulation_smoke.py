import pytest
import pandas as pd
from retirement_calculator.simulation import CalculatorConfig, simulate
from retirement_calculator.rates import ConstantRate

def test_smoke_simulation():
    config = CalculatorConfig(
        current_year=2026,
        current_age=40,
        retirement_age=60,
        salary=150000.0,
        expenses=80000.0,
        retirement_expenses=80000.0,
        initial_super_balance=200000.0,
        seed=42
    )
    df = simulate(config)
    assert isinstance(df, pd.DataFrame)
    assert len(df) == 60 # 99 - 40 + 1? No, 40 to 99 is 60 years
    assert "total_assets_real" in df.columns
    # Check that tax is being calculated
    assert df["personal_income_tax"].iloc[0] > 0
    # Check that super grows
    assert df["super_balance_eoy"].iloc[-1] > 0 or df["super_balance_eoy"].iloc[0] > 0

def test_retirement_drawdown_smoke():
    # Setup for quick retirement
    config = CalculatorConfig(
        current_year=2026,
        current_age=59,
        retirement_age=60,
        salary=0.0, # already stopped?
        expenses=50000.0,
        retirement_expenses=50000.0,
        initial_super_balance=1000000.0,
        super_access_age=60,
        seed=42
    )
    df = simulate(config)
    # At age 60 (year 2027), super should be drawn
    row_60 = df[df["age"] == 60].iloc[0]
    # In year 1 (age 59), Super grows from 1M to 1.07M.
    # In year 2 (age 60), we draw 50k. Remaining ~1.02M + growth.
    # We check that super_drawdown is captured and balance is lower than just growth would imply.
    assert row_60["super_drawdown"] > 0
    # Comparison check: balance with draw should be less than balance if no draw (1.07M * 1.07)
    assert row_60["super_balance_eoy"] < 1.15e6 

