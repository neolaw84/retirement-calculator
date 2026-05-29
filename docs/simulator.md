**Simulator: Usage & Calculation Reference**

This document explains how to use the retirement simulator and precisely what it calculates each year. It documents the input API, the per-year calculation sequence, conditional branches (to cover all input-driven paths), and math formulas used for tax, CGT, drawdown and super behaviour.

**Quick Start**
- **Install (editable)**: `pip install -e .` from the repo root.
- **Run unit tests**: set `PYTHONPATH` to `src` then run `pytest`.

Example: run the simulator from Python

```python
from retirement_calculator.simulation import CalculatorConfig, simulate

cfg = CalculatorConfig(
    current_year=2026,
    current_age=35,
    retirement_age=60,
    salary=120000.0,
    expenses=60000.0,
    initial_super_balance=200000.0,
    seed=42,
)

df = simulate(cfg)
print(df.head())
```

**Full Customization Example**

Below is an example showing how to explicitly configure every parameter of the simulation, including nested asset configurations and stochastic rate functions.

```python
import numpy as np
from retirement_calculator.simulation import CalculatorConfig, simulate
from retirement_calculator.models import (
    NREAssetConfig, 
    AssetAllocation, 
    REAssetConfig, 
    TrustAssetConfig
)
from retirement_calculator.rates import ConstantRate, NormalRate

# 1. Configure Non-Real-Estate (NRE) Assets
nre_cfg = NREAssetConfig(
    allocation=AssetAllocation(stock=0.6, bond=0.4),
    stock_growth_rate=NormalRate(mean=0.08, std=0.15),
    bond_growth_rate=ConstantRate(0.04),
    stock_yield=0.04,
    bond_yield=0.02,
    capital_gain_component_pct=0.30,
    annual_contribution=10000.0,
    initial_value=150000.0
)

# 2. Configure Real Estate (RE) Assets
properties = [
    REAssetConfig(
        property_id=1,
        year_bought=2020, # Grandfathered negative gearing
        valuation_at_base_date=850000.0,
        gross_annual_rent=35000.0,
        growth_rate=ConstantRate(0.05),
        sale_year=2040,
        annual_pre_retirement_contribution=5000.0,
        annual_post_retirement_contribution=2000.0
    ),
    REAssetConfig(
        property_id=2,
        year_bought=2027, # Post-2026 Budget: ring-fenced losses
        valuation_at_base_date=600000.0,
        gross_annual_rent=24000.0,
        growth_rate=NormalRate(mean=0.04, std=0.05),
        sale_year=None, # Held indefinitely
        annual_pre_retirement_contribution=0.0,
        annual_post_retirement_contribution=0.0
    )
]

# 3. Configure Trust Assets
trust_cfg = TrustAssetConfig(
    initial_value=100000.0,
    annual_contribution=5000.0,
    annual_post_retirement_contribution=0.0,
    distribution_yield=0.05,
    growth_rate=ConstantRate(0.06),
    dissolution_year=2050
)

# 4. Final Simulator Configuration
cfg = CalculatorConfig(
    current_year=2026,
    current_age=40,
    retirement_age=65,
    super_access_age=60,
    salary=180000.0,
    salary_growth_rate=ConstantRate(0.01), # 1% real growth
    inflation_rate=NormalRate(mean=0.025, std=0.01),
    nre_config=nre_cfg,
    re_assets=properties,
    additional_concessional_super=15000.0,
    use_carry_forward_super=True,
    expenses=80000.0,
    retirement_expenses=65000.0,
    drawdown_strategy="rebalancing", # rebalances to (age-10)% bonds
    super_growth_rate=NormalRate(mean=0.07, std=0.10),
    initial_super_balance=250000.0,
    trust_assets=trust_cfg,
    seed=123 # Deterministic results
)

# Run simulation
results_df = simulate(cfg)
```

**Where to look in the code**
- Simulator main loop: [src/retirement_calculator/simulation/__init__.py](src/retirement_calculator/simulation/__init__.py)
- Config dataclass: `CalculatorConfig` in the same module.
- Asset & input models: [src/retirement_calculator/models/__init__.py](src/retirement_calculator/models/__init__.py)
- Tax primitives (income tax, LITO, Div293, medicare): [src/retirement_calculator/tax/__init__.py](src/retirement_calculator/tax/__init__.py)
- CGT rules and `cgt_on_parcel`: [src/retirement_calculator/tax/cgt.py](src/retirement_calculator/tax/cgt.py)
- Drawdown strategies: [src/retirement_calculator/strategies/__init__.py](src/retirement_calculator/strategies/__init__.py)

**Top-level inputs (CalculatorConfig)**
- `current_year` (int): simulation start year.
- `current_age`, `retirement_age`, `super_access_age` (int).
- `salary` (float): today's real salary.
- `salary_growth_rate` (RateFunction): real salary growth per year.
- `inflation_rate` (RateFunction): CPI sampling function.
- `nre_config` (`NREAssetConfig`): non-real-estate asset settings (allocation, yields, growth rates, initial value, annual contributions).
- `re_assets` (list of `REAssetConfig`): real-estate holdings; each has `year_bought`, `valuation_at_base_date`, `gross_annual_rent`, `sale_year`, etc.
- `additional_concessional_super` (float), `use_carry_forward_super` (bool).
- `expenses`, `retirement_expenses` (float).
- `drawdown_strategy` (str): `'fifo'|'lifo'|'tax_optimised'|'rebalancing'`.
- `super_growth_rate`, `initial_super_balance`, `trust_assets` (optional `TrustAssetConfig`), `seed`.

**Per-year calculation sequence (detailed)**
The simulator repeats the following steps for each `year` from `current_year` to age 99.

1. **CPI**: CPI index series is built once; `cpi[start_year]=100.0` and evolves via `inflation_rate.sample(rng)`.

2. **Salary (nominal)**
- If not retired: `salary_real *= (1 + salary_growth.sample(rng))` then `salary_nominal = salary_real * (cpi_now/100)`.
- Else `salary_nominal = 0`.

3. **Super Guarantee & Concessional Contributions**
- SG: `sg_contribution = salary_nominal * 0.12` (before retirement).
- Additional concessional contributions converted to nominal: `addl_nominal = additional_concessional_super * (cpi_now/100)`.
- Effective concessional cap computed by `_concessional_cap(year)` and carry-forward (if `use_carry_forward_super` and `super_balance < 500k`).
- `total_concessional = min(sg_contribution + addl_nominal, effective_cap)`.

4. **NRE asset growth**
- Update per-unit prices: `nre_price[asset] *= (1 + growth_sample)`.

5. **NRE distributions**
- `nre_total_value = sum(parcel.units * nre_price[parcel.asset_type])`
- `nre_distribution = nre_total_value * distribution_yield`
- `nre_ordinary_income = nre_distribution * 0.70` (taxable income)
- `nre_capital_return = nre_distribution * 0.30` (cash not taxed as ordinary income)
- **Reinvestment**: simulator reinvests `nre_capital_return` proportionally into new `Parcel`s using `nre_config.allocation`:
  - `stock_reinvest = nre_capital_return * alloc.stock` and create a `Parcel` with `cost_base=stock_reinvest` and `units=stock_reinvest/nre_price['stock']` (same for bonds).

6. **Trust corpus (if present)**
- Growth: `trust_value *= (1 + ta.growth_rate.sample(rng))`.
- Distribution income: `trust_distribution_income = trust_value * ta.distribution_yield` (treated specially in tax calculation — a 30% non-refundable credit applies; see `income_tax`).
- Contribution: contribution nominal added to `trust_cost_base`.
- Dissolution (CGT event): if `year == ta.dissolution_year` and `years_held >= 1`:
  - Post-2026 budget: `indexed_cost_base = trust_cost_base * (cpi_now / trust_cpi_at_acquisition)`
    - `trust_cgt_gain = max(0, trust_value - indexed_cost_base)`
    - `trust_cgt_tax = trust_cgt_gain * eff_rate` where `eff_rate = max(marginal_rate(salary_nominal + trust_cgt_gain), 0.30)`.
  - Pre-2026 / old rules: 50% discount or nominal gain applies per the code path.

7. **Real Estate (RE) assets**
- Skip any `REAssetConfig` where `year < year_bought` (no activity before purchase).
- Update property value: `value *= (1 + growth_sample)`.
- `gross_rent = re.gross_annual_rent * (cpi_now / 100)`; `net_rent = gross_rent * 0.90` (after agent/maintenance).
- Negative gearing:
  - If `net_rent < 0` and `re.year_bought >= BUDGET_2026_YEAR`: the loss is **ring-fenced** and cannot offset general income (post-Budget rule).
  - Otherwise (grandfathered / pre-2026 assets) negative net rent reduces taxable income under old rules.
- Sale CGT event (if `sale_year == year`):
  - For post-2026 holdings with at least 1 year: compute indexed cost base using `valuation_at_base_date` and `base_date_cpi` (base CPI 2027 or fallback); `real_gain = max(0, sale_value - indexed_cost_base)`.
  - `effective_rate = max(marginal_rate(salary_nominal + real_gain), 0.30)` (floor 30% under the May 2026 Budget).
  - `cgt_re = real_gain * effective_rate` (post-Budget); pre-budget uses 50% discount logic.

8. **Available cash & taxable income before drawdown**
- `base_taxable_income = salary_nominal + nre_ordinary_income + (total_net_rent + total_re_loss) + trust_distribution_income`.
  - Adding back `total_re_loss` ensures that post-2026 negative gearing losses do not reduce other taxable income.
- `available_cash_pre_draw = salary_nominal + nre_ordinary_income + total_net_rent + trust_distribution_income + nre_capital_return`.
  - Here, `total_net_rent` includes negative amounts as they are real cash outflows.

9. **Iterative funding / drawdown solver (super + NRE)**
The simulator resolves the funding gap as follows:

- **Pension Phase & TBC**: If accessible and retired (or age 65+), the fund moves up to the Transfer Balance Cap (TBC) into the tax-free pension phase.
- **Min Drawdown**: Mandatory minimum withdrawals are calculated and deducted from the pension balance, increasing `available_cash_pre_draw`.
- **Super Drawdown**: If a gap still exists, additional funds are drawn from Super (Pension first, then Accumulation).

- Then the iterative loop (up to 5 iterations) handles NRE sales and tax feedback:
  1. `total_taxable = base_taxable_income + nre_gain_total + sum(g for g,t in re_cgt_events)`
  2. `personal_tax_ordinary = income_tax(base_taxable_income, trust_distribution_income)`
  3. `nre_cgt_tax = nre_cgt_total` (enforced 30% floor)
  4. `re_cgt_tax = sum(t for g,t in re_cgt_events)` (enforced 30% floor)
  5. `div293_personal = division_293_tax(total_concessional, total_taxable)`
  6. `actual_tax_paid = personal_tax_ordinary + nre_cgt_tax + re_cgt_tax + div293_personal`
  7. `funding_gap = (expenses_nominal + re_contributions + actual_tax_paid) - available_cash_pre_draw`
  7. If `funding_gap <= 1.0` or `nre_parcels` empty, loop exits (converged).
  8. Otherwise request sales from NRE via `drawdown_strategy.select_parcels(...)` to raise `funding_gap` proceeds.
  9. For each `(parcel, units_sold)` returned: compute sale proceeds and call `cgt_on_parcel(parcel, price, year, cpi_now, total_taxable)` → `(gain, cgt)`; accumulate `nre_gain_total` and `nre_cgt_total`, decrement `parcel.units`.
 10. Add sale proceeds to `available_cash_pre_draw` and repeat so that the extra tax from sales is included in the next iteration.

The loop converges because each iteration adds realized gains / CGT and the `funding_gap` reduces when enough proceeds are raised.

10. **Post-drawdown contributions & super**
- If not retired, remaining savings after `expenses + re_contributions + actual_tax_paid` are invested into new NRE `Parcel`s by allocation split.

- Super growth & internal tax:
  - Account split: `super_accumulation_balance` and `super_pension_balance`.
  - Monthly transfer: If `super_accessible` and (`is_retired` or age >= 65), transfer from accumulation to pension up to the `transfer_balance_cap` (nominal).
  - Minimum drawdown: If in pension phase, a mandatory `super_min_pension_draw` is taken (4% to 14% based on age).
  - Internal growth:
    - Accumulation: `acc_earnings = accumulation_balance * super_growth_rate`. Taxed at 15%.
    - Pension: `pension_earnings = pension_balance * super_growth_rate`. Taxed at 0%.
  - `super_balance = super_accumulation_balance + super_pension_balance`.

- `div293` is recorded via `division_293_tax(total_concessional, total_taxable)` in the iterative solver paths.

11. **Final taxable & totals**
- `total_taxable` compiles salary, `nre_ordinary_income`, `nre_gain_total`, ring-fenced/offsettable RE items, trust distributions, and trust CGT gains.
- `personal_tax_ordinary = income_tax(non_cgt_taxable_income, trust_distribution_income)`
- `total_cgt = nre_cgt_total + sum(cgt from RE events) + trust_cgt_tax` (each step enforces 30% floor on real gains)
- `total_tax = personal_tax_ordinary + total_cgt + super_tax_paid + div293`
- `funding_gap` is confirmed solved.

12. **Record row & repeat**
- The simulator writes a row with nominal and real columns, taxes, drawdowns, asset values and proceeds to the next `year`.

**Tax & CGT formula reference**

- `income_tax(taxable_income, trust_distribution)`:
  - `gross = _gross_income_tax(taxable_income)` (bracket lookup)
  - `lito = _lito(taxable_income)`
  - `medicare = taxable_income * MEDICARE_LEVY_RATE` (2%)
  - `trust_credit = min(trust_distribution * TRUST_MIN_CREDIT_RATE, gross)` (30% credit capped at gross tax)
  - `net_tax = max(0, gross - lito - trust_credit) + medicare`

- `division_293_tax(concessional_contributions, income)`:
  - `total = income + concessional_contributions`
  - if `total <= DIV293_THRESHOLD`: 0
  - else `taxable_contrib = min(concessional_contributions, total - DIV293_THRESHOLD)`
  - `tax = taxable_contrib * DIV293_RATE` (15%)

- `super_fund_tax(concessional_contributions, investment_earnings, in_pension_phase)`:
  - accumulation: 15% on concessional contributions and 15% on earnings
  - pension phase: 0% on earnings for a taxed (complying) fund

- `cgt_on_parcel(parcel, sale_price_per_unit, sale_year, cpi_now, other_income)`:
  - `sale_proceeds = sale_price_per_unit * units_sold`
  - if `sale_year >= BUDGET_2026_YEAR` and `years_held >= 1`:
    - `indexed_cost_base = parcel.cost_base * (cpi_now / parcel.cpi_at_acquisition)`
    - `real_gain = max(0, sale_proceeds - indexed_cost_base)`
    - `effective_rate = max(marginal_rate(other_income + real_gain), 0.30)`
    - `cgt = real_gain * effective_rate`
  - elif `years_held >= 1` (pre-budget discount path):
    - `nominal_gain = max(0, sale_proceeds - parcel.cost_base)`
    - `discounted_gain = nominal_gain * 0.5`
    - `cgt = discounted_gain * marginal_rate(other_income + discounted_gain)`
  - else:
    - `gain = max(0, sale_proceeds - parcel.cost_base)`
    - `cgt = gain * marginal_rate(other_income + gain)`

**Drawdown strategies (behaviour)**

- `fifo`: sells oldest `Parcel`s first.
- `lifo`: sells newest `Parcel`s first.
- `tax_optimised`: greedily picks lots to minimise immediate tax impact.
- `rebalancing`: sells from asset classes that are overweight relative to a target allocation (age-based target possible); sells surplus first then proportionally to restore balance.

**Examples & quick numbers**

- Example CGT (post-2026) from tests:
  - Parcel: `cost_base=1000`, `cpi_at_acquisition=100`, `units=100`; sold at `15/unit` in 2027 with `cpi_now=110`:
  - `indexed_cost_base = 1000 * (110/100) = 1100`
  - `sale_proceeds = 15 * 100 = 1500`
  - `real_gain = 1500 - 1100 = 400`
  - if marginal rate (income+gain) 30% → `CGT = 400 * 0.30 = 120`

**Decision tree coverage (conditional branches)**

- `is_retired` toggles salary, SG and pre/post contribution flows.
- `super_accessible` controls whether super can be used to fill funding gaps and whether pension-phase taxation applies.
- `re.year_bought` vs `BUDGET_2026_YEAR` toggles negative gearing ring-fencing.
- `parcel.year_acquired` and `sale_year` vs `BUDGET_2026_YEAR` toggle indexed-CGT vs 50% discount.
- `trust_assets is None` disables trust paths.
- Empty `nre_parcels` means no NRE drawdown possible; simulator will rely on super or report shortfalls via the funding gap logic.

**Reading simulator output (DataFrame columns)**

- `year`, `age` — timeline.
- Income columns: `salary_nominal`, `nre_ordinary_income_nominal`, `net_rent_nominal`, `trust_distribution_income_nominal`.
- CGT: `nre_cgt_gain_nominal`, `re_cgt_gain_nominal`, `trust_cgt_gain_nominal`, `cgt_total`.
- Taxes: `personal_income_tax`, `super_fund_tax`, `div293_tax`, `total_tax`.
- Drawdown: `nre_drawdown`, `super_drawdown`.
- Asset values: `nre_portfolio_value`, `re_portfolio_value`, `super_balance_eoy`, plus real equivalents.

**Troubleshooting & notes**

- Set `seed` for deterministic sampling when debugging.
- Inspect a single `year` row in the DataFrame to trace exact numeric flows for that year.
- The tax/CMT implementations follow the logic in [src/retirement_calculator/tax](src/retirement_calculator/tax); update there if policy assumptions change.

**Next steps / extensions**
- Add a small CLI runner that dumps the simulation trace and per-lot sale details to CSV.
- Add unit tests for edge cases (fractional lots, zero-price, extreme inflation scenarios).
