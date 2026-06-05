# Architecture

This document describes the top-down architecture of the `retirement-calculator` Python library.

## Purpose

A year-by-year retirement simulation engine for **Australian tax residents** pursuing FIRE (Financial Independence, Retire Early). It incorporates the May 12, 2026 Federal Budget tax reforms. The end goal is a Gradio/Streamlit web app hosted on HuggingFace.

---

## Top-Level Structure

```
retirement-calculator (library)
│
├── rates         – stochastic / deterministic rate function primitives
├── models        – pure data models (dataclasses, no business logic)
├── tax           – tax calculation functions (income tax, CGT, super tax)
│   └── cgt       – Capital Gains Tax rules (pre/post 2027 budget transition)
├── strategies    – NRE / Trust parcel-selection strategies for drawdown
└── simulation    – main simulation engine (CalculatorConfig + simulate())
```

All public API flows through `simulation.simulate(config: CalculatorConfig) -> pd.DataFrame`.

---

## Layer Responsibilities

### `rates` — `src/retirement_calculator/rates/__init__.py`
Provides the `RateFunction` abstract base class and three concrete implementations:
- `ConstantRate` – fixed scalar
- `NormalRate` – normally distributed annual return (with optional floor)
- `HistoricalRate` – bootstrap sampling from a user-supplied list

Rate functions are called once per simulation year via `.sample(rng)`. They are the *only* source of randomness in the simulator.

### `models` — `src/retirement_calculator/models/__init__.py`
Pure dataclasses. No business logic. No imports from other library subpackages except `rates`.

| Class | Purpose |
|---|---|
| `Parcel` | A single lot of an ETF or trust holding (tracks cost base, CPI at acquisition, units, pre-2027 discounted gain) |
| `AssetAllocation` | Stock/Bond split target (must sum to 1.0) |
| `NREAssetConfig` | Non-Real-Estate asset settings (allocation, yields, growth rates, annual contribution, initial value) |
| `TrustAssetConfig` | Discretionary trust settings (corpus, yield, dissolution year, etc.) |
| `REAssetConfig` | Single real estate property (purchase year, valuation, rent, mortgage, sale details) |
| `DrawdownPolicy` | Drawdown orchestration mode and sequence/ratios |

### `tax` — `src/retirement_calculator/tax/__init__.py`
Stateless pure functions. No side effects.

| Function | Purpose |
|---|---|
| `income_tax(taxable_income, trust_distribution)` | Personal income tax + Medicare levy + 30% trust credit (Budget 2026) |
| `marginal_rate(taxable_income)` | Marginal income tax rate at a given income level |
| `division_293_tax(concessional, income)` | Extra 15% on super contributions for high earners (threshold $250k) |
| `super_fund_tax(concessional, earnings, in_pension_phase)` | Tax inside the super fund (15% accumulation; 0% pension) |

### `tax/cgt` — `src/retirement_calculator/tax/cgt.py`
CGT logic split from general tax because of size and the complexity of the 2027 transition:

| Constant | Value |
|---|---|
| `INDEXATION_START_YEAR` | 2027 |
| `NEG_GEARING_CUTOFF_YEAR` | 2026 |
| `MIN_CGT_RATE` | 0.30 |

Key function: `cgt_on_parcel(parcel, sale_price_per_unit, sale_year, cpi_at_sale, total_income_before_cgt, units_sold)` → `(assessable_gain, cgt_payable)`.

**Pre-2027 rule**: 50% discount on nominal gain (for assets held ≥ 1 year).  
**Post-2027 rule**: CPI-indexed real gain, 30% minimum effective rate.  
**Transition**: In year 2027, the simulator performs a cost-base step-up on all existing parcels, capturing the pre-2027 discounted gain in `parcel.discounted_gain_at_2027`.

### `strategies` — `src/retirement_calculator/strategies/__init__.py`
Implements the `DrawdownStrategy` Protocol and four concrete strategies:

| Strategy | Behaviour |
|---|---|
| `FIFOStrategy` | Sell oldest parcels first |
| `LIFOStrategy` | Sell newest parcels first |
| `TaxOptimisedGreedyStrategy` | Sell parcels with lowest CGT-per-dollar-of-proceeds first |
| `RebalancingStrategy` | Sell overweight asset class down to target allocation; fallback to FIFO |

`DrawdownOrchestrator` is a stub for a future higher-level orchestration class (not yet used by `simulate()`).

### `simulation` — `src/retirement_calculator/simulation/__init__.py`
The main simulation loop.

**Entry point**: `simulate(config: CalculatorConfig) -> pd.DataFrame`

**Inputs**: A single `CalculatorConfig` dataclass instance.  
**Output**: A `pd.DataFrame` with one row per simulation year, from `current_year` to the year the user turns 99.

#### Per-Year Calculation Sequence

1. Build CPI series once (base year = 100.0).
2. Salary income (nominal), after real growth.
3. Super Guarantee (12%) + additional concessional contributions, capped.
4. NRE asset price growth (per asset type).
5. NRE distributions → ordinary income + capital gain component (reinvested as new parcels).
6. Trust corpus growth, distribution, contribution, and dissolution (CGT event if `dissolution_year`).
7. RE assets: growth, rent, mortgage interest, net rent per negative gearing rules.
8. Cost-base step-up on all parcels in year 2027.
9. Base taxable income (before drawdown CGT).
10. RE sale CGT events.
11. **Iterative solver** (5 passes): resolves funding gap → triggers drawdown → generates CGT → increases tax → re-calculates gap. Converges on the equilibrium drawdown amount and tax payable.
12. Drawdown orchestration (waterfall / blended / rebalanced / greedy policy modes), calling the selected `DrawdownStrategy` for NRE/Trust parcel selection.
13. Surplus reinvestment (to NRE, trust, super, or cash).
14. Super fund tax + earnings (accumulation and pension phases).
15. Record all columns to the results DataFrame row.

---

## Data Flow Diagram

```
CalculatorConfig
      │
      ▼
 simulate()
      │
      ├─ rates.*          ← stochastic sampling per year
      ├─ models.*         ← parcel state mutated in-place each year
      ├─ tax.income_tax   ← called in iterative solver loop
      ├─ tax.cgt.*        ← called per parcel per sale
      └─ strategies.*     ← called to select parcels for drawdown
      │
      ▼
pd.DataFrame  (one row per year, ~40 columns, nominal + real)
```

---

## Planned Future Layers (Not Yet Implemented)

- **UI layer**: Gradio or Streamlit interface on HuggingFace Spaces. Will wrap `simulate()` and render the output DataFrame as charts.
- **Scenario comparison**: Run multiple `CalculatorConfig` variants and compare results.
- **Monte Carlo aggregation**: Run N simulations with stochastic rates and report percentile outcomes.
