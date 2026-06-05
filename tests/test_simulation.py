import pytest
import pandas as pd
from retirement_calculator.simulation import CalculatorConfig, simulate
from retirement_calculator.models import REAssetConfig, TrustAssetConfig, NREAssetConfig, AssetAllocation
from retirement_calculator.rates import ConstantRate

def test_full_scenario_re_ringfencing():
    # Scenario: High salary, but RE losses.
    # RE bought pre-budget (2025) should offset salary.
    # RE bought post-budget (2026+) should be ring-fenced.
    
    config = CalculatorConfig(
        current_year=2026,
        current_age=45,
        retirement_age=65,
        salary=200000.0,
        salary_growth_rate=ConstantRate(0.0),
        expenses=50000.0,
        re_assets=[
            REAssetConfig(
                property_id=1,
                year_bought=2025, # Grandfathered
                purchase_price=1000000,
                valuation_at_base_date=1000000,
                gross_annual_rent=0, # Force loss
                loan_balance=1000000,
                growth_rate=ConstantRate(0.0)
            ),
            REAssetConfig(
                property_id=2,
                year_bought=2027, # Ring-fenced
                purchase_price=1000000,
                valuation_at_base_date=1000000,
                gross_annual_rent=0, # Force loss
                loan_balance=1000000,
                growth_rate=ConstantRate(0.0)
            )
        ],
        loan_interest_rate=ConstantRate(0.05), # 50k interest per property
        seed=42
    )
    df = simulate(config)
    
    # Per D15: year_bought=2027 → ring-fenced from simulation year 2028 onwards.
    # In 2027: both props go to the legacy bucket (ring-fence not yet active).
    # In 2028:
    #   Prop 1 (legacy) Loss = 50k (interest) + 10k (1% of 1M) = 60k loss → deductible.
    #   Prop 2 (ring-fenced from 2028) Loss = 60k → ring-fenced.
    #   Assessable RE income = -60k (legacy only).
    #   Total Taxable = 200k - 60k = 140k.
    
    row_2028 = df[df["year"] == 2028].iloc[0]
    assert abs(row_2028["total_taxable_income_nominal"] - 140000.0) < 5000.0

def test_trust_min_credit_v2():
    # Scenario: 100k salary, 50k trust distribution.
    # Trust distribution should get 30% credit (15k).
    # Total taxable = 150k.
    
    config = CalculatorConfig(
        current_year=2026,
        current_age=45,
        retirement_age=65,
        salary=100000.0,
        salary_growth_rate=ConstantRate(0.0), # Stabilize
        inflation_rate=ConstantRate(0.0), # Stabilize
        trust_assets=TrustAssetConfig(
            initial_value=1000000.0,
            distribution_yield=0.05, # 50k
            growth_rate=ConstantRate(0.0)
        ),
        seed=42
    )
    df = simulate(config)
    row_2026 = df[df["year"] == 2026].iloc[0]
    # Without credit, tax on 150k is ~39.8k (including medicare).
    # With 15k credit, it should be ~24.8k.
    assert row_2026["personal_income_tax"] < 30000
    df = simulate(config)
    row_2026 = df[df["year"] == 2026].iloc[0]
    # Tax should be significantly lower than standard tax on 150k.
    # Without credit, tax on 150k is ~39.8k.
    # With credit, ~24.8k.
    assert row_2026["personal_income_tax"] < 30000

if __name__ == "__main__":
    pytest.main([__file__])
