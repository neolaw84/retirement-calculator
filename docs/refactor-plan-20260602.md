# Refactor Plan — 2 June 2026

## Goals

From `docs/philosophy.md` and `docs/decisions_made.md` (D25):

- **Functions**: ≤ 60 lines (exceptions must be documented)
- **Files**: ≤ 300 lines (exceptions must be documented)
- **SOLID** principles; pure functions preferred
- **No dead code**: remove permanently-not-modelled features
- **Bug fixes**: two known issues (D15 NEG_GEARING, D16 RE expenses doc)
- **TDD**: maintain ≥ 80% test coverage throughout

---

## Current State

| File | Lines | Problem |
|---|---|---|
| `simulation/__init__.py` | 1 258 | Single 1 000-line `simulate()` function |
| `tax/__init__.py` | 150 | Dead `_lito()` + 5 dead LITO constants (D03) |
| `tax/cgt.py` | 121 | RE CGT logic duplicated inline in `simulate()` |

---

## Target Architecture

```
simulation/
  __init__.py          (~220 lines)  thin simulate() orchestrator + re-exports
  _config.py           (~125 lines)  CalculatorConfig + 3 helper functions
  _phases.py           (~320 lines)  15 per-year income-phase functions
  _drawdown.py         (~400 lines)  iterative solver + 4 drawdown mode helpers
                                     (exception to 300-line rule: 4 modes are
                                     intrinsically complex; see D25)

tax/
  __init__.py          (~110 lines)  LITO removed; income_tax() simplified
  cgt.py               (~155 lines)  + re_cgt_on_sale() helper
```

**Public API unchanged**: `from retirement_calculator.simulation import simulate, CalculatorConfig`

---

## Phase A — Tax module cleanup (quick wins)

### A1 · Remove LITO dead code from `tax/__init__.py`
- Delete `_LITO_MAX`, `_LITO_PHASE1_*`, `_LITO_PHASE2_*` constants (5 lines)
- Delete `_lito()` function (12 lines)
- Simplify `income_tax()`: remove `lito_offset = _lito(...)` and remove it from the formula
- **Update tests**: `test_income_tax_lito_2026` and `test_income_tax_lito_phaseout` become
  straightforward bracket + medicare tests (LITO is never modelled per D03)

### A2 · Add `re_cgt_on_sale()` to `tax/cgt.py`
- Extract inline RE CGT logic from `simulate()` lines 537–563
- New function signature:
  ```python
  def re_cgt_on_sale(
      re_asset: REAssetConfig,
      sale_year: int,
      sale_value: float,
      cpi: dict[int, float],
      cpi_at_sale: float,
      base_taxable_income: float,
  ) -> tuple[float, float]:   # (assessable_gain, cgt_payable)
  ```

### A3 · Fix `docs/assumptions.md` item 19
- Item 19 claims "10% of gross rent" but code uses `current_re_value * 0.01`
- Update item 19 to match the implementation (per D16)

---

## Phase B — Simulation split

### B1 · Create `simulation/_config.py`
Move from `__init__.py`:
- `CalculatorConfig` dataclass (+ add missing `from typing import Literal` import)
- `_build_cpi_series()`
- `_concessional_cap()`
- `_pension_min_drawdown_rate()`

### B2 · Create `simulation/_phases.py`
Extract these functions (each ≤ 60 lines):

| Function | Lines in simulate() | Description |
|---|---|---|
| `_apply_cgt_stepup_2027(year, nre_parcels, nre_price, trust_parcels, trust_price, re_assets, cpi)` | 302–327 | Mutates parcels in-place |
| `_apply_cash_interest(cash_balance, config, rng)` | 328–335 | Returns new cash_balance |
| `_compute_salary(is_retired, salary_real, config, rng, cpi_now)` | 340–347 | Returns (salary_nominal, salary_real) |
| `_compute_super_contributions(is_retired, salary_nominal, year, total_super_bal, config, unused_concessional)` | 349–375 | Returns (total_concessional, unused_this_year) |
| `_grow_nre(config, rng, nre_parcels, nre_price)` | 377–400 | Mutates nre_price; returns (ordinary_income, cg_dist, total_dist) |
| `_process_trust_year(year, is_retired, config, trust_parcels, trust_price, cpi_now, rng)` | 402–443 | Mutates trust_parcels; returns _TrustYearResult |
| `_process_re_income(year, config, re_values, re_mortgage_balance, rng, cpi_now)` | 452–482 | Mutates re_values; returns _REIncomeResult |
| `_compute_re_assessable(year, net_rent_legacy, net_rent_new)` | 484–492 | Pure; returns float |
| `_handle_trust_dissolution(year, config, trust_parcels, trust_price, cpi_now, base_income)` | 505–517 | Returns (proceeds, gain, tax, new_parcels) |
| `_handle_re_sales(year, config, re_values, re_mortgage_balance, cpi, cpi_now, base_income)` | 519–565 | Mutates re_values; returns _RESalesResult |
| `_compute_re_mortgages(year, config, re_mortgage_balance, rate_by_prop, rng)` | 578–623 | Mutates re_mortgage_balance; returns _MortgageResult |
| `_apply_nre_contributions(config, year, is_retired, nre_parcels, nre_price, cpi_now)` | 640–668 | Mutates nre_parcels; returns contribution_amount |
| `_reinvest_surplus(remaining_savings, year, config, nre_parcels, nre_price, trust_parcels, trust_price, super_acc_bal, cpi_now)` | 1103–1145 | Returns (cash_balance, new_super_acc_bal) |
| `_grow_super(super_acc_bal, super_pen_bal, total_concessional, config, rng)` | 1147–1164 | Returns (new_acc, new_pen, tax_paid) |
| `_build_year_record(...)` | 1185–1255 | Pure; returns dict |

**NamedTuples** used for multi-value returns:
```python
class _TrustYearResult(NamedTuple): ...
class _REIncomeResult(NamedTuple): ...
class _RESalesResult(NamedTuple): ...
class _MortgageResult(NamedTuple): ...
```

### B3 · Create `simulation/_drawdown.py`
Contains the iterative solver and the 4 drawdown mode functions.

**`_DrawState` dataclass** — mutable state for one solver run:
```python
@dataclass
class _DrawState:
    available_cash: float
    super_pension_balance: float
    super_accumulation_balance: float
    nre_parcels: list[Parcel]       # mutated in-place
    trust_parcels: list[Parcel]     # mutated in-place
    super_pension_draw: float = 0.0
    super_accumulation_draw: float = 0.0
    nre_drawdown: float = 0.0
    nre_gain_total: float = 0.0
    nre_cgt_total: float = 0.0
    trust_drawdown: float = 0.0
    trust_gain_total: float = 0.0
    trust_cgt_total: float = 0.0
```

**Functions**:

| Function | Description |
|---|---|
| `_apply_super_transition(age, config, cpi_now, super_acc_bal, super_pen_bal)` | TBC pension transfer; returns (acc, pen) |
| `_apply_mandatory_super_draw(age, super_pen_bal)` | Min drawdown; returns (draw_amount, new_pen) |
| `_draw_super(gap, is_accessible, state)` | Common super-draw helper (deduplicates 4 copies); returns new_gap |
| `_draw_nre(gap, nre_parcels, nre_price, strategy, age, config, year, cpi_now, total_taxable, state)` | Common NRE-draw helper; returns new_gap |
| `_draw_trust(gap, trust_parcels, trust_price, strategy, year, cpi_now, total_taxable, state)` | Common trust-draw helper; returns new_gap |
| `_compute_iteration_tax(state, base_taxable_income, nre_cg_dist, trust_result, diss_gain, diss_tax, re_cgt_events, total_concessional, year)` | Tax for one solver iteration; returns (actual_tax, total_taxable) |
| `_run_waterfall(gap, config, is_accessible, strategy, age, nre_price, trust_price, year, cpi_now, total_taxable, state)` | Waterfall mode; returns new_gap |
| `_run_blended(gap, config, is_accessible, strategy, age, nre_price, trust_price, year, cpi_now, total_taxable, state)` | Blended mode; returns new_gap |
| `_run_rebalanced(gap, config, is_accessible, strategy, age, nre_price, trust_price, year, cpi_now, total_taxable, state)` | Rebalanced mode; returns new_gap |
| `_run_greedy(gap, config, is_accessible, strategy, age, nre_price, trust_price, year, cpi_now, total_taxable, state)` | Greedy mode; returns new_gap |
| `run_drawdown_solver(...)` | Public entrypoint; runs 5-pass loop; returns final _DrawState |

**Note**: `_drawdown.py` is expected to be ~400 lines due to the 4 intrinsically complex mode functions. Documented as an exception to the 300-line rule (see D25).

### B4 · Rewrite `simulation/__init__.py`
- Imports from `._config`, `._phases`, `._drawdown`
- `simulate()` becomes ~90 lines: init state → year loop (each phase is one function call) → return DataFrame
- Re-exports `CalculatorConfig` for public API compatibility

---

## Phase C — Bug fixes

### C1 · Fix NEG_GEARING ring-fence year logic (D15)
**Current (wrong)**:
```python
# Categorisation
if re.year_bought < NEG_GEARING_CUTOFF_YEAR:   # < 2026
    total_net_rent_legacy += ...
else:
    total_net_rent_new += ...

# Assessment
if year >= 2026:   # ring-fencing starts too early
    ...
```

**Correct** (per D15):
```python
# Categorisation
is_ring_fenced = (
    re.year_bought >= 2028
    or (re.year_bought in (2026, 2027) and year >= 2028)
)
if is_ring_fenced:
    total_net_rent_new += ...
else:
    total_net_rent_legacy += ...

# Assessment
if year >= 2028:   # ring-fencing starts from simulation year 2028
    ...
```

### C2 · Run full test suite; fix any regressions

---

## Phase D — Docs + commit

### D1 · Update `docs/directory_structure.md`
- Add `simulation/_config.py`, `simulation/_phases.py`, `simulation/_drawdown.py`

### D2 · Update `docs/decisions_made.md`
- D15: mark NEG_GEARING bug as "fixed in refactor (Phase C1)"
- D16: mark RE expenses discrepancy as "resolved — assumptions.md updated to match code"
- D25: update to reflect refactor completed; note `_drawdown.py` size exception

### D3 · Commit
Message: `refactor: split simulate() into _config/_phases/_drawdown modules`

---

## Constraints

- Do **not** change any public API signatures
- Do **not** change simulation behaviour (all 51 existing tests must remain green)
- Keep ≥ 80% coverage throughout
- Every commit must pass `venv/bin/python -m pytest`
