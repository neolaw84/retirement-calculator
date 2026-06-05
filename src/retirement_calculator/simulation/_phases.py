"""Re-export shim for backward compatibility.

All phase functions now live in _phases_income and _phases_capital.
All return types live in _phase_types.
"""

from retirement_calculator.simulation._phase_types import (
    _NREGrowthResult,
    _TrustIncomeResult,
    _REIncomeResult,
    _TrustDissolutionResult,
    _RESalesResult,
    _REMortgageResult,
    _SuperGrowthResult,
)

from retirement_calculator.simulation._phases_income import (
    _apply_cash_interest,
    _compute_salary,
    _compute_super_contributions,
    _grow_nre,
    _process_trust_income,
    _process_re_income,
    _compute_re_assessable,
)

from retirement_calculator.simulation._phases_capital import (
    _apply_cgt_stepup_2027,
    _handle_trust_dissolution,
    _handle_re_sales,
    _compute_re_mortgages,
    _apply_nre_contributions,
    _grow_super,
    _reinvest_surplus,
)

__all__ = [
    "_NREGrowthResult",
    "_TrustIncomeResult",
    "_REIncomeResult",
    "_TrustDissolutionResult",
    "_RESalesResult",
    "_REMortgageResult",
    "_SuperGrowthResult",
    "_apply_cash_interest",
    "_compute_salary",
    "_compute_super_contributions",
    "_grow_nre",
    "_process_trust_income",
    "_process_re_income",
    "_compute_re_assessable",
    "_apply_cgt_stepup_2027",
    "_handle_trust_dissolution",
    "_handle_re_sales",
    "_compute_re_mortgages",
    "_apply_nre_contributions",
    "_grow_super",
    "_reinvest_surplus",
]
