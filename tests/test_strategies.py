import pytest
from retirement_calculator.models import Parcel
from retirement_calculator.strategies import FIFOStrategy, LIFOStrategy, TaxOptimisedGreedyStrategy, RebalancingStrategy

@pytest.fixture
def price_data():
    return {"stock": 10.0, "bond": 5.0}

@pytest.fixture
def sample_parcels():
    return [
        Parcel("stock", 2020, 100, 100, 10), # val 100, index 0
        Parcel("stock", 2021, 100, 100, 10), # val 100, index 1
        Parcel("bond", 2022, 50, 100, 10),   # val 50, index 2
    ]

def test_fifo_strategy(sample_parcels, price_data):
    strat = FIFOStrategy()
    # Sell 150 worth. Should take all of first stock (100) and 5 worth of second stock (5 units).
    result = strat.select_parcels(sample_parcels, 150.0, price_data, 2026, 100, 100000)
    assert len(result) == 2
    assert result[0] == (sample_parcels[0], 10.0)
    assert result[1] == (sample_parcels[1], 5.0)

def test_lifo_strategy(sample_parcels, price_data):
    strat = LIFOStrategy()
    # Sell 75 worth. Should take newer bond (val 50) then 2.5 units of 2021 stock.
    result = strat.select_parcels(sample_parcels, 75.0, price_data, 2026, 100, 100000)
    assert len(result) == 2
    assert result[0] == (sample_parcels[2], 10.0) # all of 2022 bond
    assert result[1] == (sample_parcels[1], 2.5)  # $25 / $10 = 2.5 units

def test_rebalancing_strategy_overshoot_fix(price_data):
    strat = RebalancingStrategy()
    # 80/20 target
    target = {"stock": 0.8, "bond": 0.2}
    # Current: stock=900, bond=100. Total=1000. 
    # Target values: stock=800, bond=200.
    # Stock is overweight by 100.
    parcels = [
        Parcel("stock", 2020, 900, 100, 90),
        Parcel("bond", 2020, 100, 100, 20),
    ]
    
    # CASE 1: Need 50. Should take only from stock (surplus is 100).
    res1 = strat.select_parcels(parcels, 50.0, price_data, 2026, 100, 100000, target)
    assert len(res1) == 1
    assert res1[0][0].asset_type == "stock"
    assert res1[0][1] == 5.0 # $50 / $10
    
    # CASE 2: Need 150. Should take 100 from stock (bringing it to target 800),
    # then total is 850. New targets? 
    # Actually my implementation sells surplus (100) then fills remainder (50) from others.
    res2 = strat.select_parcels(parcels, 150.0, price_data, 2026, 100, 100000, target)
    # 1. Sell surplus stock: 10 units ($100).
    # 2. Remaining 50: Proportional from remaining stock (800) and bond (100).
    # Total remaining = 900.
    # Stock share = 800/900 * 50 = 44.44. units = 4.44.
    # Bond share = 100/900 * 50 = 5.55. units = 1.11.
    assert any(p.asset_type == "stock" for p, u in res2)
    assert any(p.asset_type == "bond" for p, u in res2)
    total_val = sum(u * price_data[p.asset_type] for p, u in res2)
    assert pytest.approx(total_val) == 150.0
