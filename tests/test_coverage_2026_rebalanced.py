import pytest
import numpy as np
import pandas as pd
from retirement_calculator.simulation import CalculatorConfig, simulate
from retirement_calculator.models import (
    DrawdownPolicy, NREAssetConfig, AssetAllocation, 
    REAssetConfig, TrustAssetConfig, Parcel
)
from retirement_calculator.rates import ConstantRate

def test_rebalanced_drawdown_glide_path():
    """Test the rebalanced strategy age-based glide paths."""
    # Age 50 (Under 60): Target NRE 0.7, Trust 0.3
    config = CalculatorConfig(
        current_year=2034,
        current_age=50,
        retirement_age=50,
        expenses=0.0,
        retirement_expenses=100000.0,
        nre_config=NREAssetConfig(initial_value=1200000.0), # More NRE to make it overweight
        trust_assets=TrustAssetConfig(initial_value=300000.0),
        drawdown_policy=DrawdownPolicy(mode="rebalanced"),
        seed=42
    )
    df = simulate(config)
    row = df[df["age"] == 50].iloc[0]
    # Total = 1.5M. NRE=1.2M (0.8), Trust=0.3M (0.2).
    # Target NRE=0.7, Trust=0.3.
    # NRE is overweight (0.8 > 0.7).
    assert row["nre_drawdown"] > 0
    
    # Age 61: (60-75): Target NRE 0.3, Trust 0.2, Super 0.5
    config.current_age = 61
    config.retirement_age = 60
    config.retirement_expenses = 100000.0
    config.nre_config.initial_value = 1000.0
    config.trust_assets.initial_value = 1000.0
    config.initial_super_balance = 1000000.0
    config.super_access_age = 60
    df = simulate(config)
    row = df[df["age"] == 61].iloc[0]
    assert row["super_drawdown"] > 0

def test_blended_with_ratios():
    """Test blended mode with explicit ratios."""
    config = CalculatorConfig(
        current_year=2030,
        current_age=55,
        retirement_age=55,
        retirement_expenses=100000.0,
        nre_config=NREAssetConfig(initial_value=500000.0),
        trust_assets=TrustAssetConfig(initial_value=500000.0),
        drawdown_policy=DrawdownPolicy(
            mode="blended", 
            ratios={"nre": 0.8, "trust": 0.2}
        ),
        seed=42
    )
    df = simulate(config)
    row = df[df["age"] == 55].iloc[0]
    # Ratios applied to gap.
    assert row["nre_drawdown"] > 0
    assert row["trust_drawdown"] > 0
    assert row["nre_drawdown"] > row["trust_drawdown"] * 2

def test_re_sale_reinvestment_super():
    """Test RE sale proceeds going to super."""
    re = REAssetConfig(
        property_id=1,
        year_bought=2024,
        purchase_price=500000,
        valuation_at_base_date=500000,
        gross_annual_rent=0,
        loan_balance=200000,
        sale_year=2028,
        sale_reinvestment_target="super",
        sale_costs_pct=0.05
    )
    config = CalculatorConfig(
        current_year=2026,
        current_age=45,
        retirement_age=65,
        expenses=50000.0,
        initial_super_balance=100000.0,
        re_assets=[re],
        seed=42
    )
    df = simulate(config)
    row_2028 = df[df["year"] == 2028].iloc[0]
    row_2027 = df[df["year"] == 2027].iloc[0]
    
    # Super should jump significantly in 2028
    assert row_2028["super_balance_eoy"] > row_2027["super_balance_eoy"] + 100000

def test_greedy_trust_drawdown():
    """Force greedy strategy to draw from trust."""
    config = CalculatorConfig(
        current_year=2030,
        current_age=65,
        retirement_age=60,
        retirement_expenses=200000.0,
        nre_config=NREAssetConfig(initial_value=1000.0), # small NRE
        trust_assets=TrustAssetConfig(initial_value=1000000.0),
        initial_super_balance=10.0, # minimal super
        drawdown_policy=DrawdownPolicy(mode="greedy", sequence=["super", "nre", "trust"]),
        seed=42
    )
    df = simulate(config)
    row = df.iloc[0]
    assert row["trust_drawdown"] > 100000

def test_trust_contribution_retired():
    """Test trust contributions in retirement."""
    config = CalculatorConfig(
        current_year=2026,
        current_age=65,
        retirement_age=60,
        retirement_expenses=0.0, # No expenses to avoid drawdown
        trust_assets=TrustAssetConfig(
            initial_value=100000.0,
            annual_post_retirement_contribution=10000.0
        ),
        seed=42
    )
    df = simulate(config)
    row = df.iloc[0]
    assert row["trust_contribution_nominal"] > 9900
    assert row["trust_value_eoy"] > 110000

def test_waterfall_super_accumulation_drawdown():
    """Test drawing from accumulation after pension is exhausted."""
    config = CalculatorConfig(
        current_year=2030,
        current_age=65,
        retirement_age=60,
        retirement_expenses=500000.0,
        initial_super_balance=200000.0,
        transfer_balance_cap=100000.0, # force 100k into accumulation
        drawdown_policy=DrawdownPolicy(mode="waterfall", sequence=["super"]),
        seed=42
    )
    df = simulate(config)
    row = df.iloc[0]
    # At age 65, min draw is 5% of 100k = 5k.
    # Gap is 500k. 
    # It should draw the remaining 95k from pension and 100k from accumulation.
    assert row["super_drawdown"] >= 195000
