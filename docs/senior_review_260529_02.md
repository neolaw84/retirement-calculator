## Senior Architect Review Findings (Round 2)

During our review of the newly introduced code paths, we found three bugs/omissions in the implementation:

### 1. RE Sale CGT Marginal Tax Rate Bug
* **File**: [simulation/__init__.py](file:///home/neolaw/projects/retirement-calculator/src/retirement_calculator/simulation/__init__.py) (Lines 486 & 493)
* **Issue**: The marginal rate for RE sale CGT is calculated based only on `salary_nominal` (e.g. `salary_nominal + assessable_gain`), completely ignoring other taxable income (dividends, rent from other properties, trust distribution income). This under-calculates the CGT rate, especially during retirement when salary is 0 but other investment incomes exist.
* **Fix**: Change `salary_nominal` to `base_taxable_income` in RE CGT calculations.

### 2. Trust Dissolution CGT Marginal Tax Rate Bug
* **File**: [simulation/__init__.py](file:///home/neolaw/projects/retirement-calculator/src/retirement_calculator/simulation/__init__.py) (Line 434)
* **Issue**: Similar to RE sales, trust dissolution CGT uses `salary_nominal` to determine the marginal tax rate, ignoring other ordinary incomes of that year.
* **Fix**: Change `salary_nominal` to `base_taxable_income` in trust dissolution CGT calculation.

### 3. Missing `target_allocation` in Blended Drawdown mode for NRE
* **File**: [simulation/__init__.py](file:///home/neolaw/projects/retirement-calculator/src/retirement_calculator/simulation/__init__.py) (Line 794)
* **Issue**: When drawing down NRE assets in `blended` policy mode, the code calls `drawdown_strategy.select_parcels` without passing `target_allocation`. If `drawdown_strategy="rebalancing"`, it will fail to rebalance and fallback to FIFO.
* **Fix**: Calculate and pass `target_allocation` in blended NRE drawdown, matching the waterfall mode logic.

---

## Strict Test Coverage Requirement

> [!IMPORTANT]
> **Strict PR Acceptance Criteria**: The PR will be rejected if the total test coverage is lower than **80%**.
> To enforce this, we will add `--cov-fail-under=80` to the pytest configuration in `pyproject.toml`.

---

## Proposed Changes

### 1. Configure Pytest Coverage Failure Threshold
#### [MODIFY] [pyproject.toml](file:///home/neolaw/projects/retirement-calculator/pyproject.toml)
* Update `addopts` under `[tool.pytest.ini_options]` to include `--cov-fail-under=80`.

### 2. Fix Simulator Bugs
#### [MODIFY] [simulation/\_\_init\_\_.py](file:///home/neolaw/projects/retirement-calculator/src/retirement_calculator/simulation/__init__.py)
* Fix RE sale CGT marginal rate calculation to use `base_taxable_income` instead of `salary_nominal`.
* Fix trust dissolution CGT marginal rate calculation to use `base_taxable_income` instead of `salary_nominal`.
* Calculate and pass `target_allocation` to `select_parcels` in the blended NRE drawdown block.

### 3. Add Test Cases for 100% Feature Coverage
We will add new tests to [test_simulation.py](file:///home/neolaw/projects/retirement-calculator/tests/test_simulation.py) or create new test files:
* **Concessional Super Carry-Forward**: Verify that unused caps from previous years are accumulated and correctly utilized in a year where contribution exceeds the base cap.
* **Trust Contributions & Dissolution**: Verify trust corpus growth, post-retirement contributions, and dissolution year liquidation.
* **Real Estate Sale & CGT**: Verify that selling a property correctly computes CGT (pre-2027 discounted gain and post-2027 indexed gains with 30% floor) and terminates future rents.
* **Blended Policy Mode**: Verify drawdowns are split between NRE, Trust, and Super.
* **Greedy Policy Mode**: Verify drawdowns are ordered by minimum tax friction.

---

## Verification Plan

### Automated Tests
* Run `./venv/bin/pytest` which will now automatically fail if test coverage is below 90%.
