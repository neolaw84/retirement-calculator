import pytest
import pandas as pd
from retirement_calculator.simulation import CalculatorConfig, simulate
from retirement_calculator.models import DrawdownPolicy, NREAssetConfig, AssetAllocation
from retirement_calculator.rates import ConstantRate

def test_bridge_phase_waterfall():
    # Scenario: Retire at 45, super at 60.
    # Waterfall: NRE -> Super.
    # Should empty NRE before touching Super (once accessible).
    
    config = CalculatorConfig(
        current_year=2026,
        current_age=45,
        retirement_age=45, # Retire immediately
        super_access_age=60,
        salary=0.0,
        expenses=100000.0,
        retirement_expenses=100000.0,
        initial_super_balance=1000000.0,
        nre_config=NREAssetConfig(
            initial_value=500000.0, # Enough for 5 years
            allocation=AssetAllocation(1.0, 0.0) # all stock
        ),
        drawdown_policy=DrawdownPolicy(
            mode="waterfall",
            sequence=["nre", "super"]
        ),
        seed=42
    )
    
    df = simulate(config)
    
    # Year 2026 (Age 45): Super not accessible. Should draw from NRE.
    row_45 = df[df["age"] == 45].iloc[0]
    assert row_45["nre_drawdown"] > 75000
    assert row_45["super_drawdown"] == 0
    
    # Year 2041 (Age 60): Super accessible. If NRE still has money, should draw from NRE.
    # (By age 60, 15 years * 100k = 1.5M, so NRE 500k will be empty).
    # Let's find the year NRE empty.
    nre_empty_year = df[df["nre_portfolio_value"] < 1000].iloc[0]["year"]
    assert nre_empty_year < 2041
    
    # Year 2041: Should draw from Super.
    row_60 = df[df["age"] == 60].iloc[0]
    assert row_60["super_drawdown"] > 90000
    assert row_60["nre_drawdown"] < 1000

if __name__ == "__main__":
    pytest.main([__file__])
