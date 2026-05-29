## Code Review Findings (Senior Architect Review)

We conducted a thorough review of the codebase and identified several critical logic, tax, and architectural bugs that must be resolved to ensure the retirement calculator is accurate and compliant with the specifications.

### 1. Syntax Error in Tests
* **File**: [test_sample.py](file:///home/neolaw/projects/retirement-calculator/tests/test_sample.py) (Line 3)
* **Issue**: The test file imports the package as `import retirement-calculator`. In Python, hyphens are invalid syntax in import statements.
* **Fix**: Change to `import retirement_calculator`.

### 2. Personal Income Tax is Never Paid/Deducted
* **File**: [simulation/__init__.py](file:///home/neolaw/projects/retirement-calculator/src/retirement_calculator/simulation/__init__.py)
* **Issue**: Personal income tax (`personal_tax`) and Division 293 tax (`div293`) are calculated each year, but they are never deducted from the user's NRE assets or superannuation. The simulation projects asset growth as if the user pays $0 in personal taxes.
* **Fix**: Update the `funding_gap` calculation and drawdown loop to include personal income tax and Division 293 tax as outflows. Since tax depends on NRE sales (which generate CGT, increasing the tax), we will implement an iterative solver that converges on the correct drawdown amount and tax paid for the year.

### 3. Incorrect Superannuation Drawdown Column
* **File**: [simulation/__init__.py](file:///home/neolaw/projects/retirement-calculator/src/retirement_calculator/simulation/__init__.py) (Line 568)
* **Issue**: The `"super_drawdown"` column in the results DataFrame is recorded as `super_balance` instead of the actual amount drawn (`super_draw`).
* **Fix**: Track the actual `super_draw` amount and record it in the `"super_drawdown"` column.

### 4. NRE Capital Return is Discarded
* **File**: [simulation/__init__.py](file:///home/neolaw/projects/retirement-calculator/src/retirement_calculator/simulation/__init__.py) (Lines 285-288)
* **Issue**: The 30% capital return portion of NRE distributions (`nre_capital_return`) is calculated but never reinvested, added to cash flow, or used to reduce the cost base of existing parcels. It is completely discarded.
* **Fix**: As per `docs/assumptions.md` (item 16), the capital return should be reinvested back into the NRE assets. We will create new parcels for the reinvested amount in the current year, split according to the target allocation.

### 5. Negative Gearing Ring-Fencing Logic Bug
* **File**: [simulation/__init__.py](file:///home/neolaw/projects/retirement-calculator/src/retirement_calculator/simulation/__init__.py) (Lines 510-516)
* **Issue**: The condition `re.year_bought <= BUDGET_2026_YEAR and year < BUDGET_2026_YEAR` prevents properties purchased before the 2026 budget from offsetting general income in any year from 2026 onwards. This violates the grandfathering rule.
* **Fix**: Partition real estate net rents into pre-budget and post-budget properties. Pre-budget property net losses can offset general income in any simulation year, whereas post-budget property net losses can only offset aggregate real estate income.

### 6. Division 293 Tax Base Income Bug
* **File**: [simulation/__init__.py](file:///home/neolaw/projects/retirement-calculator/src/retirement_calculator/simulation/__init__.py) (Line 506)
* **Issue**: Division 293 tax is calculated using only `salary_nominal` as the income base, ignoring NRE ordinary income, net rental income, trust distributions, and capital gains.
* **Fix**: Pass the total taxable income (`total_taxable`) to `division_293_tax`.

### 7. Low Income Tax Offset (LITO) Rate Bug
* **File**: [tax/__init__.py](file:///home/neolaw/projects/retirement-calculator/src/retirement_calculator/tax/__init__.py) (Line 38)
* **Issue**: `_LITO_PHASE1_RATE` is defined as `0.015` (1.5c per $1) instead of `0.05` (5c per $1), resulting in incorrect LITO reductions for taxable incomes between $37,500 and $45,000.
* **Fix**: Correct the phase 1 rate to `0.05`.

### 8. CGT Floor Not Applied in Personal Income Tax
* **File**: [simulation/__init__.py](file:///home/neolaw/projects/retirement-calculator/src/retirement_calculator/simulation/__init__.py)
* **Issue**: The 30% CGT floor is calculated for NRE, RE, and Trust capital gains, but the actual tax paid by the individual is calculated via `income_tax(total_taxable)`. Since `income_tax` does not apply the 30% floor on CGT components, the minimum tax rate of 30% on capital gains is never actually enforced on the taxpayer's final bill.
* **Fix**: Separate CGT tax calculation from ordinary income tax:
  `personal_tax = tax_on_other_income + total_cgt`
  where `tax_on_other_income` is calculated on the non-CGT taxable income, and `total_cgt` is the sum of CGT on NRE, RE, and Trust gains (which have the 30% floor applied).

### 9. Future Real Estate Assets Active Too Early
* **File**: [simulation/__init__.py](file:///home/neolaw/projects/retirement-calculator/src/retirement_calculator/simulation/__init__.py)
* **Issue**: Real estate properties are grown and rent is collected starting from the simulation start year (2026), even if the property's `year_bought` is in the future.
* **Fix**: Only include properties in the active portfolio, collect rent, and apply contributions if `year >= re.year_bought`.

### 10. Rebalancing Strategy Overshooting
* **File**: [strategies/__init__.py](file:///home/neolaw/projects/retirement-calculator/src/retirement_calculator/strategies/__init__.py)
* **Issue**: `RebalancingStrategy` sells up to the entire target proceeds from the most overweight asset class without checking if this makes it underweight.
* **Fix**: Calculate the target values after drawdown and only sell from the overweight class down to its target value, then sell proportionally from both classes.

---

## Proposed Changes

We will modify the source code to resolve the bugs identified above and write a comprehensive suite of unit tests in the `tests` directory.

### 1. Fix Bug in LITO Rate
#### [MODIFY] [tax/\_\_init\_\_.py](file:///home/neolaw/projects/retirement-calculator/src/retirement_calculator/tax/__init__.py)
* Change `_LITO_PHASE1_RATE` to `0.05`.

### 2. Fix Rebalancing Strategy
#### [MODIFY] [strategies/\_\_init\_\_.py](file:///home/neolaw/projects/retirement-calculator/src/retirement_calculator/strategies/__init__.py)
* Update `RebalancingStrategy` to accurately determine and execute rebalancing sales without overshooting.

### 3. Fix Simulation Logic
#### [MODIFY] [simulation/\_\_init\_\_.py](file:///home/neolaw/projects/retirement-calculator/src/retirement_calculator/simulation/__init__.py)
* Implement the NRE capital return reinvestment.
* Add properties to the active portfolio only when `year >= re.year_bought`.
* Correct the negative gearing ring-fencing logic.
* Implement the iterative solver to incorporate personal income tax and Div 293 tax into the yearly funding gap and drawdown.
* Use `total_taxable` in Division 293 tax calculation.
* Calculate `personal_tax` using the separate CGT tax method.
* Correct the `"super_drawdown"` column.

### 4. Update and Write Tests
#### [MODIFY] [tests/test_sample.py](file:///home/neolaw/projects/retirement-calculator/tests/test_sample.py)
* Fix the package import syntax.

#### [NEW] [tests/test_rates.py](file:///home/neolaw/projects/retirement-calculator/tests/test_rates.py)
* Test `ConstantRate` and `NormalRate`.

#### [NEW] [tests/test_tax.py](file:///home/neolaw/projects/retirement-calculator/tests/test_tax.py)
* Test LITO, Medicare levy, Division 293 tax, super fund tax, and CGT calculations (indexed vs nominal).

#### [NEW] [tests/test_strategies.py](file:///home/neolaw/projects/retirement-calculator/tests/test_strategies.py)
* Test FIFO, LIFO, TaxOptimisedGreedy, and Rebalancing strategies.

#### [NEW] [tests/test_simulation.py](file:///home/neolaw/projects/retirement-calculator/tests/test_simulation.py)
* Test full simulation runs under various configurations (with/without real estate, discretionary trust, concessional super caps, carry-forward, and different drawdown strategies).

---

## Verification Plan

### Automated Tests
* Run `venv/bin/pytest --cov=src` to execute all tests and verify 100% correctness and high coverage.
* Confirm that no errors occur during execution.
