"""Build the per-year result record for the simulation DataFrame.

Extracted from simulate() to keep the main orchestrator function short.
"""

from __future__ import annotations

from retirement_calculator.models import Parcel
from retirement_calculator.tax.cgt import INDEXATION_START_YEAR
from retirement_calculator.simulation._phases_capital import _RESalesResult
from retirement_calculator.simulation._phase_types import (
    _NREGrowthResult,
    _TrustIncomeResult,
    _REIncomeResult,
    _REMortgageResult,
    _SuperGrowthResult,
)


def _build_year_record(
    year: int,
    age: int,
    deflator: float,
    cpi_now: float,
    salary_nominal: float,
    nre_result: _NREGrowthResult,
    re_result: _REIncomeResult,
    trust_result: _TrustIncomeResult,
    expenses_nominal: float,
    actual_tax: float,
    personal_tax: float,
    div293: float,
    super_tax: float,
    super_balance: float,
    super_acc: float,
    super_pen: float,
    super_min_draw: float,
    super_draw: float,
    total_taxable: float,
    nre_end_value: float,
    re_end_value: float,
    trust_end_value: float,
    total_assets: float,
    total_liabilities: float,
    net_worth_nominal: float,
    cash_balance: float,
    nre_contrib: float,
    mortgage: _REMortgageResult,
    re_sales: _RESalesResult,
    trust_diss_gain: float,
    trust_diss_tax: float,
    trust_active_cap_gain: float,
    trust_sales_tax: float,
    trust_diss_tax_final: float,
    draw_nre_drawdown: float,
    draw_nre_gain_total: float,
    draw_nre_cgt_total: float,
    draw_trust_drawdown: float,
    draw_trust_cgt_total: float,
    draw_funding_gap: float,
    draw_initial_funding_gap: float,
    available_cash: float,
    remaining_savings: float,
) -> dict:
    """Assemble the full per-year record dict for the results DataFrame."""
    return {
        "year": year,
        "age": age,
        "salary_nominal": salary_nominal,
        "nre_ordinary_income_nominal": nre_result.nre_ordinary_income,
        "net_rent_nominal": re_result.net_rent_legacy + re_result.net_rent_new,
        "nre_capital_gain_nominal": draw_nre_gain_total + nre_result.nre_capital_gain_dist,
        "re_cgt_gain_nominal": sum(g for g, _ in re_sales.re_cgt_events),
        "total_taxable_income_nominal": total_taxable,
        "salary_real": salary_nominal * deflator,
        "nre_ordinary_income_real": nre_result.nre_ordinary_income * deflator,
        "net_rent_real": (re_result.net_rent_legacy + re_result.net_rent_new) * deflator,
        "expenses_nominal": expenses_nominal,
        "expenses_real": expenses_nominal * deflator,
        "personal_income_tax": personal_tax,
        "super_fund_tax": super_tax,
        "div293_tax": div293,
        "cgt_total": (
            draw_nre_cgt_total
            + sum(t for _, t in re_sales.re_cgt_events)
            + trust_sales_tax
            + trust_diss_tax_final
        ),
        "total_tax": actual_tax + super_tax,
        "nre_drawdown": draw_nre_drawdown,
        "super_drawdown": super_draw,
        "trust_drawdown": draw_trust_drawdown,
        "super_contribution_concessional": 0.0,  # filled by caller
        "super_balance_eoy": super_balance,
        "super_accumulation_balance_eoy": super_acc,
        "super_pension_balance_eoy": super_pen,
        "nre_portfolio_value": nre_end_value,
        "re_portfolio_value": re_end_value,
        "cash_balance": cash_balance,
        "total_assets_nominal": total_assets,
        "nre_portfolio_value_real": nre_end_value * deflator,
        "re_portfolio_value_real": re_end_value * deflator,
        "cash_balance_real": cash_balance * deflator,
        "super_balance_eoy_real": super_balance * deflator,
        "total_assets_real": total_assets * deflator,
        "total_liabilities_nominal": total_liabilities,
        "total_liabilities_real": total_liabilities * deflator,
        "net_worth_nominal": net_worth_nominal,
        "net_worth_real": net_worth_nominal * deflator,
        "trust_distribution_income_nominal": trust_result.distribution_income,
        "trust_distribution_income_real": trust_result.distribution_income * deflator,
        "trust_tax_paid_nominal": trust_result.tax_paid,
        "trust_tax_paid_real": trust_result.tax_paid * deflator,
        "trust_contribution_nominal": trust_result.contribution_this_year,
        "nre_contribution_nominal": nre_contrib,
        "re_contribution_nominal": mortgage.contribution_nominal,
        "re_mortgage_payment_nominal": mortgage.contribution_nominal,
        "re_mortgage_interest_nominal": mortgage.interest_nominal,
        "re_mortgage_principal_nominal": mortgage.principal_nominal,
        "trust_cgt_gain_nominal": trust_active_cap_gain,
        "trust_cgt_tax": trust_sales_tax + trust_diss_tax_final,
        "trust_value_eoy": trust_end_value,
        "trust_value_eoy_real": trust_end_value * deflator,
        "cpi_index": cpi_now,
        "available_cash_pre_draw_debug": available_cash,
        "remaining_savings_debug": remaining_savings,
        "funding_gap_debug": draw_funding_gap,
        "initial_funding_gap_debug": draw_initial_funding_gap,
    }
