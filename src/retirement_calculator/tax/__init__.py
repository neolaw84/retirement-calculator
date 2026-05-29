"""Australian income tax and related offset calculations.

All rates reflect 2025-26 ATO published brackets with the Stage 3 tax cuts.
These are assumed to remain unchanged for the projection horizon (no bracket
indexation).  See docs/assumptions.md for details.

Post-May 12 2026 budget changes modelled here:
* CGT on inflation-adjusted real gains (see cgt.py)
* Minimum CGT rate of 30% (see cgt.py)
* Discretionary Trust minimum 30% non-refundable credit (applied here)
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Tax brackets (2025-26, Stage 3 cuts applied)
# ---------------------------------------------------------------------------

# Each entry: (lower_bound, base_tax, marginal_rate_above_lower)
_BRACKETS_2025 = [
    (190_001, 51_638, 0.45),
    (135_001, 31_288, 0.37),
    (45_001,   4_288, 0.30),
    (18_201,       0, 0.16),
    (0,            0, 0.00),
]

# Medicare levy rate
MEDICARE_LEVY_RATE = 0.02

# Division 293 threshold and additional super tax rate
DIV293_THRESHOLD = 250_000
DIV293_RATE = 0.15

# Low Income Tax Offset (LITO) – 2025-26
_LITO_MAX = 700.0
_LITO_PHASE1_START = 37_500
_LITO_PHASE1_RATE = 0.05   # 5c per $1 from $37,500 to $45,000
_LITO_PHASE2_START = 45_001
_LITO_PHASE2_RATE = 0.015   # 1.5c per $1 from $45,001 to $66,667

# Trust minimum non-refundable credit rate (May 2026 budget)
TRUST_MIN_CREDIT_RATE = 0.30


def _gross_income_tax(taxable_income: float) -> float:
    """Return raw income tax before any offsets (based on 2025-26 brackets)."""
    for lower, base, rate in _BRACKETS_2025:
        if taxable_income > lower:
            return base + (taxable_income - lower) * rate
    return 0.0


def _lito(taxable_income: float) -> float:
    """Low Income Tax Offset (non-refundable)."""
    if taxable_income <= _LITO_PHASE1_START:
        return _LITO_MAX
    elif taxable_income <= 45_000:
        reduction = (taxable_income - _LITO_PHASE1_START) * _LITO_PHASE1_RATE
        return max(0.0, _LITO_MAX - reduction)
    else:
        # Phase 1 already fully phased out, apply phase 2
        phase1_reduction = (45_000 - _LITO_PHASE1_START) * _LITO_PHASE1_RATE
        phase2_reduction = (taxable_income - 45_000) * _LITO_PHASE2_RATE
        return max(0.0, _LITO_MAX - phase1_reduction - phase2_reduction)


def income_tax(
    taxable_income: float,
    trust_distribution: float = 0.0,
) -> float:
    """Calculate total personal income tax including Medicare levy.

    Parameters
    ----------
    taxable_income : float
        Total taxable income (including any CGT gains and trust distributions).
    trust_distribution : float
        Portion of taxable_income that comes from discretionary trust distributions.
        A 30% non-refundable credit applies to this amount (May 2026 budget change).

    Returns
    -------
    float
        Net tax payable (after offsets and trust credits), floored at 0.
    """
    gross = _gross_income_tax(taxable_income)
    lito_offset = _lito(taxable_income)
    medicare = taxable_income * MEDICARE_LEVY_RATE

    # Trust credit is non-refundable (capped at gross tax before Medicare)
    trust_credit = min(trust_distribution * TRUST_MIN_CREDIT_RATE, gross)

    net_tax = max(0.0, gross - lito_offset - trust_credit) + medicare
    return net_tax


def marginal_rate(taxable_income: float) -> float:
    """Return the marginal income tax rate at a given income level (excl. Medicare)."""
    for lower, _base, rate in _BRACKETS_2025:
        if taxable_income > lower:
            return rate
    return 0.0


def division_293_tax(
    concessional_contributions: float,
    income: float,
) -> float:
    """Additional 15% tax on concessional super contributions for high earners.

    Division 293 applies when income + concessional contributions > $250,000.
    Only the contributions that push the total over the threshold are taxed.
    """
    total = income + concessional_contributions
    if total <= DIV293_THRESHOLD:
        return 0.0
    taxable_contrib = min(concessional_contributions, total - DIV293_THRESHOLD)
    return taxable_contrib * DIV293_RATE


def super_fund_tax(
    concessional_contributions: float,
    investment_earnings: float,
    in_pension_phase: bool = False,
) -> float:
    """Tax within the super fund.

    * Accumulation phase: 15% on concessional contributions + 15% on earnings.
    * Pension phase: 0% on all earnings and withdrawals from a taxed fund.

    Parameters
    ----------
    concessional_contributions : float
        Concessional contributions in this year.
    investment_earnings : float
        Gross investment earnings within the super fund this year.
    in_pension_phase : bool
        True once the member has started a pension (post preservation age).

    Returns
    -------
    float
        Tax payable by the super fund.
    """
    if in_pension_phase:
        return 0.0
    tax = (concessional_contributions + investment_earnings) * 0.15
    return max(0.0, tax)
