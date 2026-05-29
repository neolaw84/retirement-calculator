from retirement_calculator.rates import ConstantRate
from retirement_calculator.simulation import CalculatorConfig, simulate
from retirement_calculator.models import DrawdownPolicy, NREAssetConfig, AssetAllocation

config = CalculatorConfig(
    current_year=2026,
    current_age=45,
    retirement_age=45, # Retire immediately
    super_access_age=60,
    salary=0.0,
    expenses=100000.0,
    retirement_expenses=100000.0, # Must set this too!
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
row = df[df["year"] == 2026].iloc[0]
print(f"Year: {row['year']}")
print(f"Expenses: {row['expenses_nominal']}")
print(f"Salary: {row['salary_nominal']}")
print(f"NRE Ordinary Inc: {row['nre_ordinary_income_nominal']}")
print(f"NRE Drawdown: {row['nre_drawdown']}")
print(f"Total Tax: {row['total_tax']}")
print(f"NRE Gain: {row['nre_capital_gain_nominal']}")
print(f"Total Cash In: {row['nre_ordinary_income_nominal'] + row['nre_drawdown']}")
print(f"Total Cash Out: {row['expenses_nominal'] + row['total_tax']}")
