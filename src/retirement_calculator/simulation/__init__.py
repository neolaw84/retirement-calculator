"""Core retirement simulator.

Runs a year-by-year simulation from current_year to age 99, tracking:
* NRE (Non-Real-Estate) assets with per-parcel CGT tracking
* Real Estate (RE) assets with negative gearing rules
* Superannuation accumulation and drawdown
* Income tax, CGT, super fund tax

Output: pandas DataFrame with one row per simulated year.

See docs/assumptions.md for all modelling assumptions.
"""

from __future__ import annotations

import copy
import warnings
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from retirement_calculator.models import (
    NREAssetConfig,
    REAssetConfig,
    TrustAssetConfig,
    Parcel,
    AssetAllocation,
    DrawdownPolicy,
)
from retirement_calculator.rates import RateFunction, ConstantRate
from retirement_calculator.tax import (
    income_tax,
    marginal_rate,
    division_293_tax,
    super_fund_tax,
    MEDICARE_LEVY_RATE,
)
from retirement_calculator.tax.cgt import (
    cgt_on_parcel,
    INDEXATION_START_YEAR,
    NEG_GEARING_CUTOFF_YEAR,
    MIN_CGT_RATE,
)
from retirement_calculator.strategies import (
    LIFOStrategy,
    FIFOStrategy,
    TaxOptimisedGreedyStrategy,
    RebalancingStrategy,
)


# ---------------------------------------------------------------------------
# Calculator configuration dataclass
# ---------------------------------------------------------------------------

@dataclass
class CalculatorConfig:
    """All inputs to the retirement simulation.

    Attributes
    ----------
    current_year : int
        Simulation start year (e.g. 2026).
    current_age : int
        User's age at the start of current_year.
    retirement_age : int
        Age at which salary/employment income stops.
    super_access_age : int
        Age when superannuation becomes accessible (preservation age; default 60).
    salary : float
        Annual gross salary income in today's dollars (pre-tax).
    salary_growth_rate : RateFunction
        Real growth rate of salary (applied each year before retirement).
        Default: ConstantRate(0.0) – salary is flat in real terms.
    inflation_rate : RateFunction
        Annual CPI inflation rate function. Default: ConstantRate(0.0).
    nre_config : NREAssetConfig
        Non-real-estate asset configuration.
    re_assets : list[REAssetConfig]
        Real estate asset configurations.
    additional_concessional_super : float
        Additional personal concessional super contributions per year (salary sacrifice
        or personal deductible), in today's dollars.
    use_carry_forward_super : bool
        Whether to maximise concessional contributions using carry-forward provisions.
    expenses : float
        Annual living expenses in today's dollars (pre-retirement).
    retirement_expenses : float
        Annual living expenses in today's dollars (post-retirement).
    drawdown_strategy : str
        One of 'fifo', 'lifo', 'tax_optimised', 'rebalancing'.
    super_growth_rate : RateFunction
        Annual growth rate of the super fund balance.
    cash_interest_rate : RateFunction | None
        Annual nominal growth rate applied to the tracked cash balance. If
        set to `None`, the simulator will use `inflation_rate` as the cash
        growth rate.
    initial_super_balance : float
        Super balance at start of simulation, in nominal dollars.
    trust_assets : TrustAssetConfig | None
        Optional discretionary trust configuration.  When not None, the trust's
        contribution, distribution_yield, growth_rate, and dissolution_year fields
        must all be populated.  Distributions attract the 30% non-refundable
        minimum credit (May 2026 budget).  CGT on dissolution uses the
        inflation-indexed real-gain rules.
    surplus_reinvestment_target : str
        Where to invest year-end cash surplus: 'nre', 'trust', 'super', or 'cash'.
        Default is 'nre'. Note that 'cash' effectively means the surplus is
        lost/spent in the current implementation unless specifically handled.
    surplus_reinvestment_pct : float
        The fraction of the annual cash surplus to reinvest (0.0 to 1.0).
    seed : int | None
        Random seed for reproducible stochastic simulations.
    """

    current_year: int
    current_age: int
    retirement_age: int
    super_access_age: int = 60
    salary: float = 0.0
    salary_growth_rate: RateFunction = field(default_factory=lambda: ConstantRate(0.0))
    inflation_rate: RateFunction = field(default_factory=lambda: ConstantRate(0.0))
    nre_config: NREAssetConfig = field(default_factory=NREAssetConfig)
    re_assets: list[REAssetConfig] = field(default_factory=list)
    additional_concessional_super: float = 0.0
    use_carry_forward_super: bool = False
    expenses: float = 0.0
    retirement_expenses: float = 0.0
    drawdown_strategy: str = "fifo"
    drawdown_policy: DrawdownPolicy = field(default_factory=DrawdownPolicy)
    super_growth_rate: RateFunction = field(default_factory=lambda: ConstantRate(0.07))
    loan_interest_rate: RateFunction = field(default_factory=lambda: ConstantRate(0.06))
    cash_interest_rate: RateFunction | None = None
    initial_super_balance: float = 0.0
    transfer_balance_cap: float = 1_900_000.0
    trust_assets: TrustAssetConfig | None = None
    surplus_reinvestment_target: Literal["nre", "trust", "super", "cash"] = "nre"
    surplus_reinvestment_pct: float = 1.0 # Portion of any remaining cash surplus reinvested
    seed: int | None = None


# ---------------------------------------------------------------------------
# Helper: CPI index series
# ---------------------------------------------------------------------------

def _build_cpi_series(
    start_year: int,
    end_year: int,
    inflation_fn: RateFunction,
    rng: np.random.Generator,
) -> dict[int, float]:
    """Return CPI index with start_year = 100.0, growing by inflation each year."""
    cpi: dict[int, float] = {start_year: 100.0}
    for yr in range(start_year + 1, end_year + 1):
        cpi[yr] = cpi[yr - 1] * (1.0 + inflation_fn.sample(rng))
    return cpi


# ---------------------------------------------------------------------------
# Helper: super concessional cap
# ---------------------------------------------------------------------------

def _concessional_cap(year: int) -> float:
    """Return the concessional contributions cap for a given financial year."""
    if year <= 2025:
        return 30_000.0
    elif year == 2026:
        return 30_000.0
    else:
        return 32_500.0  # Assumption: stays at $32,500 post 2026-27


# ---------------------------------------------------------------------------
# Helper: minimum pension withdrawal rates
# ---------------------------------------------------------------------------

def _pension_min_drawdown_rate(age: int) -> float:
    """Return the minimum drawdown percentage for an account-based pension by age."""
    if age < 65:
        return 0.04
    elif age < 75:
        return 0.05
    elif age < 80:
        return 0.06
    elif age < 85:
        return 0.07
    elif age < 90:
        return 0.09
    elif age < 95:
        return 0.11
    else:
        return 0.14


# ---------------------------------------------------------------------------
# Main simulation function
# ---------------------------------------------------------------------------

def simulate(config: CalculatorConfig) -> pd.DataFrame:
    """Run the retirement simulation and return a results DataFrame.

    Returns
    -------
    pd.DataFrame
        One row per year. Columns include income, expenses, tax, and asset values –
        all in both nominal and real (base-year) dollars.
    """
    rng = np.random.default_rng(config.seed)

    end_year = config.current_year + (99 - config.current_age)
    cpi = _build_cpi_series(config.current_year, end_year, config.inflation_rate, rng)

    # --- Select drawdown strategy ---
    _strategies = {
        "fifo": FIFOStrategy(),
        "lifo": LIFOStrategy(),
        "tax_optimised": TaxOptimisedGreedyStrategy(),
        "rebalancing": RebalancingStrategy(),
    }
    drawdown_strategy = _strategies.get(config.drawdown_strategy, FIFOStrategy())

    # --- Initialise Assets ---
    cash_balance = 0.0
    nre_parcels: list[Parcel] = []
    if config.nre_config.initial_value > 0:
        alloc = config.nre_config.allocation
        stock_value = config.nre_config.initial_value * alloc.stock
        bond_value = config.nre_config.initial_value * alloc.bond
        base_cpi = cpi[config.current_year]
        if stock_value > 0:
            nre_parcels.append(Parcel(
                asset_type="stock",
                year_acquired=config.current_year,
                cost_base=stock_value,
                cpi_at_acquisition=base_cpi,
                units=stock_value,  # price per unit = $1 initially
            ))
        if bond_value > 0:
            nre_parcels.append(Parcel(
                asset_type="bond",
                year_acquired=config.current_year,
                cost_base=bond_value,
                cpi_at_acquisition=base_cpi,
                units=bond_value,
            ))

    # --- NRE price per unit (tracks growth; start at $1.00) ---
    nre_price = {"stock": 1.0, "bond": 1.0}

    # --- RE asset state ---
    re_values: dict[int, float] = {}  # property_id -> current nominal value
    for re in config.re_assets:
        # Use valuation_at_base_date as starting estimate (adjust for years to base)
        years_to_base = max(0, 2027 - config.current_year)
        approx_current = re.valuation_at_base_date / (
            (1.0 + re.growth_rate.sample(rng)) ** years_to_base
        )
        re_values[re.property_id] = approx_current

    # Track outstanding mortgage balances per property (amortising over 30 years from purchase)
    re_mortgage_balance: dict[int, float] = {}
    for re in config.re_assets:
        re_mortgage_balance[re.property_id] = float(re.loan_balance)

    # --- Trust state ---
    trust_parcels: list[Parcel] = []
    trust_price = 1.0
    if config.trust_assets is not None:
        val = config.trust_assets.initial_value
        trust_parcels.append(Parcel(
            asset_type="stock",
            year_acquired=config.current_year,
            cost_base=val,
            cpi_at_acquisition=cpi[config.current_year],
            units=val
        ))

    # --- Super state ---
    super_accumulation_balance = config.initial_super_balance
    super_pension_balance = 0.0
    # Carry-forward tracking: accumulate unused caps over 5 years
    unused_concessional: list[float] = []  # rolling window, oldest first

    records = []

    salary_real = config.salary  # in today's dollars (real)
    cash_balance = 0.0

    for year in range(config.current_year, end_year + 1):
        age = config.current_age + (year - config.current_year)
        is_retired = age >= config.retirement_age
        super_accessible = age >= config.super_access_age
        cpi_now = cpi[year]
        deflator = 100.0 / cpi_now  # to convert nominal → base-year real

        # Initialize available cash for the year
        available_cash_pre_draw = 0.0

        # ---- Budget 2026: Cost-base step-up on 2027-07-01 ----
        # Per user requirement: Gains up to 2027-06-30 get the 50% discount.
        # Real gains (inflation-indexed) from 2027-07-01 onwards have no discount.
        if year == 2027:
            for p in nre_parcels:
                if p.year_acquired < 2027:
                    # Capture the discounted gain up to the step-up point
                    nominal_gain_to_2027 = max(0.0, (p.units * nre_price[p.asset_type]) - p.cost_base)
                    p.discounted_gain_at_2027 = nominal_gain_to_2027 * 0.5
                    
                    # Reset cost base for post-2027 real gain calculation
                    p.cost_base = p.units * nre_price[p.asset_type]
                    p.cpi_at_acquisition = cpi[2027]
                    
            for p in trust_parcels:
                if p.year_acquired < 2027:
                    nominal_gain_to_2027 = max(0.0, (p.units * trust_price) - p.cost_base)
                    p.discounted_gain_at_2027 = nominal_gain_to_2027 * 0.5
                    
                    p.cost_base = p.units * trust_price
                    p.cpi_at_acquisition = cpi[2027]

            for re in config.re_assets:
                if re.year_bought < 2027:
                    # Capture the discounted gain up to the step-up point
                    nominal_gain_to_2027 = max(0.0, re.valuation_at_base_date - re.purchase_price)
                    re.discounted_gain_at_2027 = nominal_gain_to_2027 * 0.5

        # Apply interest to cash_balance (defaults to inflation if not provided)
        if cash_balance > 0.0:
            cash_rate = (
                config.cash_interest_rate.sample(rng)
                if config.cash_interest_rate is not None
                else config.inflation_rate.sample(rng)
            )
            cash_balance *= (1.0 + cash_rate)

        # available_cash_pre_draw is what we actually have to spend
        available_cash_pre_draw += cash_balance

        # ---- 1. Salary income (nominal) ----
        if not is_retired:
            salary_real *= (1.0 + config.salary_growth_rate.sample(rng))
            salary_nominal = salary_real * (cpi_now / 100.0)
        else:
            salary_nominal = 0.0
        
        available_cash_pre_draw += salary_nominal

        # ---- 2. Super Guarantee contribution ----
        sg_rate = 0.12  # from FY2025-26 onwards
        sg_contribution = salary_nominal * sg_rate if not is_retired else 0.0

        # ---- 3. Additional concessional super contributions ----
        # Convert today's dollar amount to nominal
        addl_concessional_nominal = (
            config.additional_concessional_super * (cpi_now / 100.0)
            if not is_retired
            else 0.0
        )

        # Cap total concessional contributions
        base_cap = _concessional_cap(year)
        if config.use_carry_forward_super and (super_accumulation_balance + super_pension_balance) < 500_000:
            # Add unused caps from up to 5 prior years
            carry_fwd = sum(unused_concessional[-5:])
            effective_cap = base_cap + carry_fwd
        else:
            effective_cap = base_cap

        total_concessional = min(sg_contribution + addl_concessional_nominal, effective_cap)
        # Record unused for carry-forward
        unused_this_year = max(0.0, base_cap - total_concessional)
        unused_concessional.append(unused_this_year)
        if len(unused_concessional) > 5:
            unused_concessional.pop(0)

        # ---- 4. NRE asset growth ----
        stock_growth = config.nre_config.stock_growth_rate.sample(rng)
        bond_growth = config.nre_config.bond_growth_rate.sample(rng)
        nre_price["stock"] *= (1.0 + stock_growth)
        nre_price["bond"] *= (1.0 + bond_growth)

        # ---- 5. NRE distributions ----
        # 1. Total distribution calculation (per-asset yield)
        nre_stock_value = sum(p.units * nre_price[p.asset_type] for p in nre_parcels if p.asset_type == "stock")
        nre_bond_value = sum(p.units * nre_price[p.asset_type] for p in nre_parcels if p.asset_type == "bond")
        
        nre_distribution = (
            nre_stock_value * config.nre_config.stock_yield
            + nre_bond_value * config.nre_config.bond_yield
        )
        
        # 2. Treat ordinary income and capital gain component (input-driven)
        cg_pct = config.nre_config.capital_gain_component_pct
        nre_ordinary_income = nre_distribution * (1.0 - cg_pct)
        nre_capital_gain_dist = nre_distribution * cg_pct
        
        # Distributions are cash. In Australia, the CG component of a distribution
        # is a realized taxable event, not an unrealized "lump up" of the unit value.
        available_cash_pre_draw += nre_distribution

        # ---- 5b. Trust asset: growth, distribution, contribution, dissolution ----
        trust_distribution_income = 0.0
        trust_cgt_gain_dist = 0.0  # Character retention (CGT component of distribution)
        trust_dissolution_gain = 0.0
        trust_dissolution_tax = 0.0
        trust_contribution_this_year = 0.0
        trust_tax_paid = 0.0
        trust_distribution_net_cash = 0.0

        if config.trust_assets is not None:
            ta = config.trust_assets
            # Growth
            trust_price *= (1.0 + ta.growth_rate.sample(rng))
            trust_val_start = sum(p.units * trust_price for p in trust_parcels)

            # Distribution
            raw_dist = trust_val_start * ta.distribution_yield
            # Use defined annual CG dist (nominal)
            # In Budget 2026, 30% non-refundable credit applies to ordinary income.
            # CGT component has 30% floor.
            trust_cgt_gain_dist = ta.annual_capital_gain_dist
            trust_distribution_income = raw_dist
            
            # Trust pays 30% at source
            trust_tax_paid = raw_dist * 0.30
            trust_distribution_net_cash = raw_dist - trust_tax_paid
            
            # Add ordinary distribution (net of trust tax) and the capital component cash to available cash
            available_cash_pre_draw += (trust_distribution_net_cash + trust_cgt_gain_dist)

            # Contribution (adds to parcels)
            contrib_nominal = (ta.annual_post_retirement_contribution if is_retired
                               else ta.annual_contribution) * (cpi_now / 100.0)
            if contrib_nominal > 0:
                trust_parcels.append(Parcel(
                    asset_type="stock",
                    year_acquired=year,
                    cost_base=contrib_nominal,
                    cpi_at_acquisition=cpi_now,
                    units=contrib_nominal / trust_price
                ))
                trust_contribution_this_year = contrib_nominal

        # ---- 6. RE assets: growth, rent income, negative gearing ----
        total_net_rent_legacy = 0.0
        total_net_rent_new = 0.0
        re_price_per_prop: dict[int, float] = {}
        # Sampled loan rates for each property this year (used for interest calculations)
        re_rate_by_prop: dict[int, float] = {}

        for re in config.re_assets:
            # Check if active
            if year < re.year_bought:
                continue
            if re.sale_year is not None and year > re.sale_year:
                continue

            prop_growth = re.growth_rate.sample(rng)
            re_values[re.property_id] *= (1.0 + prop_growth)
            current_re_value = re_values[re.property_id]

            gross_rent = re.gross_annual_rent * (cpi_now / 100.0)
            re_expenses = current_re_value * 0.01

            # Outstanding principal for tax/interest calculation
            outstanding = re_mortgage_balance.get(re.property_id, float(re.loan_balance))
            rate_this_year = config.loan_interest_rate.sample(rng)
            re_rate_by_prop[re.property_id] = rate_this_year
            re_interest = outstanding * rate_this_year

            # Taxable/net rent includes interest as a deductible cost
            net_rent_for_tax = gross_rent - re_expenses - re_interest
            if re.year_bought < NEG_GEARING_CUTOFF_YEAR:
                total_net_rent_legacy += net_rent_for_tax
            else:
                total_net_rent_new += net_rent_for_tax

            # Cash flow before mortgage payments: owner receives rent less operating expenses.
            cash_rent_before_mortgage = gross_rent - re_expenses
            available_cash_pre_draw += cash_rent_before_mortgage
            re_price_per_prop[re.property_id] = current_re_value

        # ---- 7. Calculate Base Taxable Income (before liquidation CGT) ----
        re_pool_total = total_net_rent_legacy + total_net_rent_new
        if year >= 2026:
            deductible_legacy_loss = min(0.0, total_net_rent_legacy)
            leg_profit = max(0.0, total_net_rent_legacy)
            effective_new_net = max(total_net_rent_new, -leg_profit)
            re_assessable = deductible_legacy_loss + leg_profit + effective_new_net
        else:
            re_assessable = re_pool_total

        base_taxable_income = (
            salary_nominal
            + nre_ordinary_income
            + re_assessable
            + trust_distribution_income
        )

        # ---- 8. Liquidation Events (Trust Dissolution & RE Sales) ----
        re_cgt_events: list[tuple[float, float]] = []  # (assessable_gain, cgt)
        
        # Trust Dissolution
        if config.trust_assets is not None:
            ta = config.trust_assets
            if ta.dissolution_year is not None and year == ta.dissolution_year:
                # Proceeds flow to beneficiary
                diss_proceeds = sum(p.units * trust_price for p in trust_parcels)
                available_cash_pre_draw += diss_proceeds
                
                for p in trust_parcels:
                    # Use base_taxable_income for marginal rate
                    g, t = cgt_on_parcel(p, trust_price, year, cpi_now, base_taxable_income)
                    trust_dissolution_gain += g
                    trust_dissolution_tax += t
                trust_parcels = []

        # RE Sales
        re_sale_proceeds_this_year = 0.0
        re_investment_target_this_year = "nre"
        for re in config.re_assets:
            if year < re.year_bought:
                continue
            if re.sale_year is not None and year == re.sale_year:
                current_re_value = re_values[re.property_id]
                
                # Pay off mortgage and sale costs using current outstanding balance
                sale_costs = current_re_value * re.sale_costs_pct
                outstanding = re_mortgage_balance.get(re.property_id, float(re.loan_balance))
                net_proceeds = current_re_value - outstanding - sale_costs
                available_cash_pre_draw += net_proceeds
                re_sale_proceeds_this_year += net_proceeds
                re_investment_target_this_year = re.sale_reinvestment_target

                # CGT on RE
                if year >= INDEXATION_START_YEAR:
                    # 1. Real gain (post-2027 component)
                    if re.year_bought < INDEXATION_START_YEAR:
                        cost_base = re.valuation_at_base_date
                        c_acq = cpi[INDEXATION_START_YEAR]
                    else:
                        cost_base = re.purchase_price
                        c_acq = cpi.get(re.year_bought, cpi_now)
                    
                    indexed_cost_base = cost_base * (cpi_now / c_acq)
                    real_gain_post_2027 = max(0.0, current_re_value - indexed_cost_base)
                    
                    # 2. Total assessable gain includes pre-2027 discounted component
                    assessable_gain = real_gain_post_2027 + re.discounted_gain_at_2027
                    
                    # 3. CGT calculation with 30% floor
                    # Use base_taxable_income for marginal rate
                    income_with_gain = base_taxable_income + assessable_gain
                    effective_rate = max(marginal_rate(income_with_gain), MIN_CGT_RATE)
                    cgt_re = assessable_gain * effective_rate
                else:
                    # Pre-2027 sale: 50% discount on nominal gain
                    nominal_gain = max(0.0, current_re_value - re.purchase_price)
                    assessable_gain = nominal_gain * 0.5
                    cgt_re = assessable_gain * marginal_rate(base_taxable_income + assessable_gain)
                
                re_cgt_events.append((assessable_gain, cgt_re))
                # Remove from portfolio
                re_values.pop(re.property_id)

        # ---- 9. Determine funding gap & Drawdown ----
        nre_drawdown = 0.0
        nre_cgt_total = 0.0
        nre_gain_total = 0.0
        drawdown_parcels: list[tuple[Parcel, float]] = []

        expenses_nominal = (
            (config.retirement_expenses if is_retired else config.expenses)
            * (cpi_now / 100.0)
        )

        # RE mortgage P+I contributions (annual payment amortised over 30 years
        # from purchase). Compute per-property payments using the outstanding
        # principal and this year's sampled loan rate (sampled earlier).
        # Total annual P+I (payment), and breakdown of interest vs principal
        re_contribution_nominal = 0.0
        re_mortgage_interest_nominal = 0.0
        re_mortgage_principal_nominal = 0.0
        for re in config.re_assets:
            if year < re.year_bought:
                continue
            if re.sale_year is not None and year > re.sale_year:
                continue
            pid = re.property_id
            principal = re_mortgage_balance.get(pid, float(re.loan_balance))
            years_elapsed = year - re.year_bought
            remaining_years = max(0, 30 - years_elapsed)
            if principal <= 0.0 or remaining_years <= 0:
                continue
            rate = re_rate_by_prop.get(pid, config.loan_interest_rate.sample(rng))
            if rate <= 0.0:
                payment = principal / remaining_years
            else:
                r = rate
                n = remaining_years
                try:
                    payment = principal * (r * (1.0 + r) ** n) / (((1.0 + r) ** n) - 1.0)
                except OverflowError:
                    payment = principal / n

            interest_component = principal * rate
            principal_reduction = payment - interest_component
            if principal_reduction < 0.0:
                principal_reduction = 0.0
                payment = interest_component
            if principal_reduction > principal:
                principal_reduction = principal
                payment = interest_component + principal_reduction

            re_mortgage_balance[pid] = max(0.0, principal - principal_reduction)
            re_contribution_nominal += payment
            # Accumulate interest and principal components for reporting
            re_mortgage_interest_nominal += interest_component
            re_mortgage_principal_nominal += principal_reduction

        # Expose variable name expected downstream
        re_contributions = re_contribution_nominal

        # Deduct annual mortgage payments from available cash pre-draw
        if re_contribution_nominal > 0.0:
            available_cash_pre_draw -= re_contribution_nominal

        # Available cash BEFORE tax and BEFORE portfolio drawdowns
        base_available_cash = (
            salary_nominal 
            + nre_ordinary_income 
            + (total_net_rent_legacy + total_net_rent_new) # actually available cash (losses are costs)
            + (trust_distribution_net_cash if config.trust_assets is not None else 0.0)
            # Reinvested capital gain component is not available cash to spend
        )
        # Note: trust dissolution proceeds were already added to available_cash_pre_draw
        available_cash_current = base_available_cash

        nre_contribution_nominal = 0.0
        if not is_retired:
            nre_contribution_nominal = config.nre_config.annual_contribution

        # Apply NRE contribution: create parcels and deduct from available cash
        nre_contribution_this_year = 0.0
        if nre_contribution_nominal > 0:
            alloc = config.nre_config.allocation
            stock_contrib = nre_contribution_nominal * alloc.stock
            bond_contrib = nre_contribution_nominal * alloc.bond
            if stock_contrib > 0:
                nre_parcels.append(Parcel(
                    asset_type="stock",
                    year_acquired=year,
                    cost_base=stock_contrib,
                    cpi_at_acquisition=cpi_now,
                    units=stock_contrib / nre_price["stock"],
                ))
            if bond_contrib > 0:
                nre_parcels.append(Parcel(
                    asset_type="bond",
                    year_acquired=year,
                    cost_base=bond_contrib,
                    cpi_at_acquisition=cpi_now,
                    units=bond_contrib / nre_price["bond"],
                ))
            # Deduct contribution from available cash (pre-draw)
            available_cash_pre_draw -= nre_contribution_nominal
            nre_contribution_this_year = nre_contribution_nominal

        # We already calculated base_taxable_income above.

        nre_drawdown = 0.0
        nre_cgt_total = 0.0
        nre_gain_total = 0.0
        
        trust_drawdown = 0.0
        trust_cgt_total = 0.0
        trust_gain_total = 0.0
        
        # Iterative Solver for Tax and Drawdown (Phase 2, Step 5)
        # We need to find `total_drawdown` such that:
        # cash_in = available_cash_pre_draw + total_drawdown
        # cash_out = expenses_nominal + re_contributions + nre_contribution_nominal + tax(base_taxable_income + gain(total_drawdown))
        # cash_in >= cash_out
        
        # --- Super Pension Phase Transition ---
        # Transfer from accumulation to pension up to TBC when accessible and retired (or 65)
        # Note: We re-check every year to move any new accumulations (e.g. from earnings)
        # into the tax-free pension phase if there is TBC cap room.
        
        tbc_nominal = config.transfer_balance_cap * (cpi_now / 100.0)
        in_pension_mode = super_accessible and (is_retired or age >= 65)
        
        if in_pension_mode:
            room = max(0.0, tbc_nominal - super_pension_balance)
            if room > 0 and super_accumulation_balance > 0:
                transfer = min(room, super_accumulation_balance)
                super_pension_balance += transfer
                super_accumulation_balance -= transfer

        # Pension minimum drawdown
        super_min_pension_draw = 0.0
        if super_pension_balance > 0:
            super_min_pension_draw = super_pension_balance * _pension_min_drawdown_rate(age)
            # Minimum drawdown is mandatory, adds to available cash
            super_pension_balance -= super_min_pension_draw
            available_cash_pre_draw += super_min_pension_draw

        # Track drawdowns within the iterative loop
        super_pension_draw = 0.0
        super_accumulation_draw = 0.0
        
        # NRE/Trust variables for the final result
        nre_drawdown_final = 0.0
        trust_drawdown_final = 0.0
        
        # NRE & Trust portion - iterative because sales generate MORE tax (CGT)
        initial_funding_gap = None
        for _ in range(5):
            # Calculate total taxable income (separating ordinary/non-CGT from CGT gains)
            # Character retention: Include trust distribution CGT component, trust manual sales, and trust dissolution
            
            # Pre-2027: Capital gains from distributions are discounted before assessment.
            if year < INDEXATION_START_YEAR:
                effective_nre_dist_cg = nre_capital_gain_dist * 0.5
                effective_trust_dist_cg = trust_cgt_gain_dist * 0.5
            else:
                effective_nre_dist_cg = nre_capital_gain_dist
                effective_trust_dist_cg = trust_cgt_gain_dist
            
            nre_active_cap_gain = effective_nre_dist_cg + nre_gain_total
            trust_active_cap_gain = effective_trust_dist_cg + trust_gain_total + trust_dissolution_gain
            total_taxable = (base_taxable_income 
                             + nre_active_cap_gain 
                             + sum(g for g, _ in re_cgt_events)
                             + trust_active_cap_gain)
            
            # 1. Tax on ordinary income
            # Trust distribution ordinary component is taxed at marginal rate but with 30% credit
            # income_tax() already applies the non-refundable credit internally.
            personal_tax_ordinary = income_tax(base_taxable_income, trust_distribution_income)
            
            # 2. CGT results from parcels, RE sales, and Trust sales
            nre_cgt_tax = nre_cgt_total
            re_cgt_tax = sum(t for _, t in re_cgt_events)
            
            # Trust sales and dissolution attract the 30% credit as they are distributions
            trust_sales_tax = max(0.0, trust_cgt_total - (trust_gain_total * 0.30))
            trust_diss_tax_final = max(0.0, trust_dissolution_tax - (trust_dissolution_gain * 0.30))
            
            # Tax on trust distribution CGT component (character retention)
            # Pre-2027: 50% discount. Post-2027: 30% floor.
            # Both attract the 30% non-refundable credit (May 2026 budget).
            if year < INDEXATION_START_YEAR:
                assessable_trust_dist_cg = trust_cgt_gain_dist * 0.5
                # Simple marginal tax without floor before 2027
                base_cgt_tax = (income_tax(total_taxable) - income_tax(total_taxable - assessable_trust_dist_cg))
            else:
                assessable_trust_dist_cg = trust_cgt_gain_dist
                tcgd_eff_rate = max(marginal_rate(total_taxable), 0.30)
                base_cgt_tax = assessable_trust_dist_cg * tcgd_eff_rate
            
            # Non-refundable credit on trust CGT component
            trust_dist_cgt_tax = max(0.0, base_cgt_tax - (trust_cgt_gain_dist * 0.30))
            
            # 3. Div 293
            div293_personal = division_293_tax(total_concessional, total_taxable)
            
            actual_tax_paid = (personal_tax_ordinary 
                               + nre_cgt_tax 
                               + re_cgt_tax 
                               + trust_sales_tax 
                               + trust_diss_tax_final
                               + trust_dist_cgt_tax
                               + div293_personal)
            
            # Contributions (NRE / RE mortgage P+I) have already been deducted
            # from `available_cash_pre_draw` earlier. Do NOT add them again on
            # the RHS — otherwise they are double-counted and force premature
            # drawdowns. Funding gap = required outflows (expenses + tax)
            # minus available cash.
            funding_gap = (expenses_nominal + actual_tax_paid) - available_cash_pre_draw
            if _ == 0:
                initial_funding_gap = funding_gap
            
            # DEBUG: Uncomment to trace gap issues
            # print(f"DEBUG: year={year} age={age} iter={_} gap={funding_gap} exp={expenses_nominal} tax={actual_tax_paid} avail={available_cash_pre_draw}")
            
            if funding_gap <= 1.0 or (not nre_parcels and not trust_parcels and not (in_pension_mode and (super_pension_balance > 0 or super_accumulation_balance > 0))):
                break 

            # Handle the gap according to the DrawdownPolicy
            is_accessible = in_pension_mode
            
            if config.drawdown_policy.mode == "waterfall":
                for source in config.drawdown_policy.sequence:
                    if funding_gap <= 1.0:
                        break
                    
                    if source == "super" and is_accessible:
                        # Draw from super (pension then accumulation)
                        if super_pension_balance > 0:
                            draw = min(funding_gap, super_pension_balance)
                            super_pension_balance -= draw
                            super_pension_draw += draw
                            available_cash_pre_draw += draw
                            funding_gap -= draw
                        if funding_gap > 1.0 and super_accumulation_balance > 0:
                            draw = min(funding_gap, super_accumulation_balance)
                            super_accumulation_balance -= draw
                            super_accumulation_draw += draw
                            available_cash_pre_draw += draw
                            funding_gap -= draw
                    
                    elif source == "nre" and nre_parcels:
                        target_allocation = None
                        if config.drawdown_strategy == "rebalancing":
                            bond_pct = min(max((age - 10) / 100.0, 0.0), 1.0)
                            target_allocation = {"bond": bond_pct, "stock": 1.0 - bond_pct}

                        iter_nre = drawdown_strategy.select_parcels(
                            parcels=nre_parcels,
                            target_proceeds=funding_gap,
                            price_per_unit=nre_price,
                            sale_year=year,
                            cpi_at_sale=cpi_now,
                            other_income=total_taxable,
                            target_allocation=target_allocation,
                        )
                        for parcel, units_sold in iter_nre:
                            val = units_sold * nre_price[parcel.asset_type]
                            nre_drawdown_final += val
                            gain, cgt = cgt_on_parcel(
                                parcel, 
                                nre_price[parcel.asset_type], 
                                year, 
                                cpi_now, 
                                total_taxable,
                                units_sold=units_sold
                            )
                            nre_gain_total += gain
                            nre_cgt_total += cgt
                            parcel.units -= units_sold
                            available_cash_pre_draw += val
                            funding_gap -= val
                            
                    elif source == "trust" and trust_parcels:
                        iter_trust = drawdown_strategy.select_parcels(
                            parcels=trust_parcels,
                            target_proceeds=funding_gap,
                            price_per_unit={"stock": trust_price},
                            sale_year=year,
                            cpi_at_sale=cpi_now,
                            other_income=total_taxable,
                            target_allocation=None,
                        )
                        for parcel, units_sold in iter_trust:
                            val = units_sold * trust_price
                            trust_drawdown_final += val
                            gain, cgt = cgt_on_parcel(
                                parcel, 
                                trust_price, 
                                year, 
                                cpi_now, 
                                total_taxable,
                                units_sold=units_sold
                            )
                            trust_gain_total += gain
                            trust_cgt_total += cgt
                            parcel.units -= units_sold
                            available_cash_pre_draw += val
                            funding_gap -= val

            elif config.drawdown_policy.mode == "blended":
                # Use target ratios from config, or default to equal split if empty
                ratios = config.drawdown_policy.ratios
                if not ratios:
                    # Default: equal split among active sources
                    active_sources = []
                    for source in config.drawdown_policy.sequence:
                        if source == "super" and is_accessible:
                            if (super_pension_balance + super_accumulation_balance) > 0: active_sources.append(source)
                        elif source == "nre" and nre_parcels: active_sources.append(source)
                        elif source == "trust" and trust_parcels: active_sources.append(source)
                    if active_sources:
                        ratios = {s: 1.0/len(active_sources) for s in active_sources}
                    else:
                        ratios = {}
                
                # Apply ratios to funding gap
                for source, pct in ratios.items():
                    share = funding_gap * pct
                    if share <= 0: continue

                    if source == "super" and is_accessible:
                        if super_pension_balance > 0:
                            draw = min(share, super_pension_balance)
                            super_pension_balance -= draw
                            super_pension_draw += draw
                            available_cash_pre_draw += draw
                            share -= draw
                        if share > 1.0 and super_accumulation_balance > 0:
                            draw2 = min(share, super_accumulation_balance)
                            super_accumulation_balance -= draw2
                            super_accumulation_draw += draw2
                            available_cash_pre_draw += draw2
                    elif source == "nre":
                        target_allocation = None
                        if config.drawdown_strategy == "rebalancing":
                            bond_pct = min(max((age - 10) / 100.0, 0.0), 1.0)
                            target_allocation = {"bond": bond_pct, "stock": 1.0 - bond_pct}

                        iter_nre = drawdown_strategy.select_parcels(
                            parcels=nre_parcels,
                            target_proceeds=share,
                            price_per_unit=nre_price,
                            sale_year=year,
                            cpi_at_sale=cpi_now,
                            other_income=total_taxable,
                            target_allocation=target_allocation,
                        )
                        for parcel, units_sold in iter_nre:
                            val = units_sold * nre_price[parcel.asset_type]
                            nre_drawdown_final += val
                            gain, cgt = cgt_on_parcel(parcel, nre_price[parcel.asset_type], year, cpi_now, total_taxable, units_sold=units_sold)
                            nre_gain_total += gain
                            nre_cgt_total += cgt
                            parcel.units -= units_sold
                            available_cash_pre_draw += val
                    elif source == "trust":
                        iter_trust = drawdown_strategy.select_parcels(
                            parcels=trust_parcels,
                            target_proceeds=share,
                            price_per_unit={"stock": trust_price},
                            sale_year=year,
                            cpi_at_sale=cpi_now,
                            other_income=total_taxable,
                        )
                        for parcel, units_sold in iter_trust:
                            val = units_sold * trust_price
                            trust_drawdown_final += val
                            gain, cgt = cgt_on_parcel(parcel, trust_price, year, cpi_now, total_taxable, units_sold=units_sold)
                            trust_gain_total += gain
                            trust_cgt_total += cgt
                            parcel.units -= units_sold
                            available_cash_pre_draw += val
            
            elif config.drawdown_policy.mode == "rebalanced":
                # Rebalanced mode: Draw from the source that is currently above its target ratio
                # Default target ratios if empty: Super (if accessible) gets more weight as we age
                target_ratios = config.drawdown_policy.ratios
                if not target_ratios:
                    if age < 60:
                        target_ratios = {"nre": 0.7, "trust": 0.3, "super": 0.0}
                    elif age < 75:
                        target_ratios = {"nre": 0.3, "trust": 0.2, "super": 0.5}
                    else:
                        target_ratios = {"nre": 0.1, "trust": 0.1, "super": 0.8}
                
                # Filter to accessible/active sources only and re-normalise
                filtered_ratios = {}
                total_w = 0.0
                for s, w in target_ratios.items():
                    if s == "super" and not is_accessible: continue
                    filtered_ratios[s] = w
                    total_w += w
                if total_w > 0:
                    filtered_ratios = {s: w/total_w for s, w in filtered_ratios.items()}
                else:
                    # Fallback to waterfall if no target sources are active
                    is_accessible_cached = is_accessible # temp
                    # (we'll just use waterfall logic below)
                    config.drawdown_policy.mode = "waterfall" 
                    continue # Re-run loop with waterfall
                
                # Calculate current balances
                nre_val = sum(p.units * nre_price[p.asset_type] for p in nre_parcels)
                trust_val = sum(p.units * trust_price for p in trust_parcels)
                super_val = super_pension_balance + super_accumulation_balance
                total_val = nre_val + trust_val + super_val
                
                if total_val > 0:
                    current_ratios = {
                        "nre": nre_val / total_val,
                        "trust": trust_val / total_val,
                        "super": super_val / total_val if is_accessible else 0.0
                    }
                    # Pick the source furthest above its target
                    diffs = {s: current_ratios.get(s, 0.0) - filtered_ratios.get(s, 0.0) for s in filtered_ratios}
                    best_source = max(diffs, key=diffs.get)
                    
                    # Draw small chunks (10% of funding gap) to allow rebalancing across iterations
                    # OR just draw the whole gap from the "best" source this iteration
                    source = best_source
                    share = funding_gap
                    # (rest of logic same as waterfall source)
                    if source == "super" and is_accessible:
                        if super_pension_balance > 0:
                            draw = min(share, super_pension_balance)
                            super_pension_balance -= draw
                            super_pension_draw += draw
                            available_cash_pre_draw += draw
                            funding_gap -= draw
                        if funding_gap > 1.0 and super_accumulation_balance > 0:
                            draw = min(funding_gap, super_accumulation_balance)
                            super_accumulation_balance -= draw
                            super_accumulation_draw += draw
                            available_cash_pre_draw += draw
                            funding_gap -= draw
                    elif source == "nre":
                        # ... nre logic ...
                        target_allocation = None
                        if config.drawdown_strategy == "rebalancing":
                            bond_pct = min(max((age - 10) / 100.0, 0.0), 1.0)
                            target_allocation = {"bond": bond_pct, "stock": 1.0 - bond_pct}
                        iter_nre = drawdown_strategy.select_parcels(parcels=nre_parcels, target_proceeds=share, price_per_unit=nre_price, sale_year=year, cpi_at_sale=cpi_now, other_income=total_taxable, target_allocation=target_allocation)
                        for parcel, units_sold in iter_nre:
                            val = units_sold * nre_price[parcel.asset_type]
                            nre_drawdown_final += val
                            gain, cgt = cgt_on_parcel(parcel, nre_price[parcel.asset_type], year, cpi_now, total_taxable, units_sold=units_sold)
                            nre_gain_total += gain
                            nre_cgt_total += cgt
                            parcel.units -= units_sold
                            available_cash_pre_draw += val
                            funding_gap -= val
                    elif source == "trust":
                        iter_trust = drawdown_strategy.select_parcels(parcels=trust_parcels, target_proceeds=share, price_per_unit={"stock": trust_price}, sale_year=year, cpi_at_sale=cpi_now, other_income=total_taxable)
                        for parcel, units_sold in iter_trust:
                            val = units_sold * trust_price
                            trust_drawdown_final += val
                            gain, cgt = cgt_on_parcel(parcel, trust_price, year, cpi_now, total_taxable, units_sold=units_sold)
                            trust_gain_total += gain
                            trust_cgt_total += cgt
                            parcel.units -= units_sold
                            available_cash_pre_draw += val
                            funding_gap -= val
                else:
                    break # No assets left

                
            elif config.drawdown_policy.mode == "greedy":
                # Global Year-Agnostic Greedy (Bucket-agnostic)
                # 1. Super is always first (0 friction)
                if is_accessible:
                    if super_pension_balance > 0:
                        draw = min(funding_gap, super_pension_balance)
                        super_pension_balance -= draw
                        super_pension_draw += draw
                        available_cash_pre_draw += draw
                        funding_gap -= draw
                    if funding_gap > 1.0 and super_accumulation_balance > 0:
                        draw = min(funding_gap, super_accumulation_balance)
                        super_accumulation_balance -= draw
                        super_accumulation_draw += draw
                        available_cash_pre_draw += draw
                        funding_gap -= draw
                
                if funding_gap > 1.0:
                    # Compare NRE and Trust parcels
                    all_parcels = []
                    for p in nre_parcels:
                        all_parcels.append(('nre', p, nre_price[p.asset_type]))
                    for p in trust_parcels:
                        all_parcels.append(('trust', p, trust_price))
                    
                    def friction_sort(item):
                        source, p, price = item
                        _, cgt = cgt_on_parcel(p, price, year, cpi_now, total_taxable)
                        val = p.units * price
                        return cgt / val if val > 0 else 0
                    
                    all_parcels.sort(key=friction_sort)
                    
                    for source, p, price in all_parcels:
                        if funding_gap <= 1.0:
                            break
                        available = p.units
                        val_available = available * price
                        units_to_sell = min(available, funding_gap / price)
                        sold_val = units_to_sell * price
                        
                        gain, cgt = cgt_on_parcel(p, price, year, cpi_now, total_taxable, units_sold=units_to_sell)
                        
                        if source == 'nre':
                            nre_drawdown_final += sold_val
                            nre_gain_total += gain
                            nre_cgt_total += cgt
                        else:
                            trust_drawdown_final += sold_val
                            trust_gain_total += gain
                            trust_cgt_total += cgt
                            
                        p.units -= units_to_sell
                        available_cash_pre_draw += sold_val
                        funding_gap -= sold_val

        # Final cleanup of empty parcels
        nre_parcels = [p for p in nre_parcels if p.units > 1e-6]
        trust_parcels = [p for p in trust_parcels if p.units > 1e-6]

        super_draw = super_min_pension_draw + super_pension_draw + super_accumulation_draw

        # ---- 9. Surplus Reinvestment (Salary or RE Sales) ----
        total_personal_tax = actual_tax_paid
        # Contributions have already been subtracted from `available_cash_pre_draw`.
        # Remaining savings should therefore be available cash minus expenses and tax.
        remaining_savings = available_cash_pre_draw - (expenses_nominal + actual_tax_paid)
        
        # If we have a surplus, decide where it goes
        if remaining_savings > 1.0:
            investible_surplus = remaining_savings * config.surplus_reinvestment_pct

            target = config.surplus_reinvestment_target
            if re_sale_proceeds_this_year > 1.0:
                target = re_investment_target_this_year

            # Allocate investible_surplus according to target
            if target == "nre":
                alloc = config.nre_config.allocation
                stock_inv = investible_surplus * alloc.stock
                bond_inv = investible_surplus * alloc.bond
                if stock_inv > 0:
                    nre_parcels.append(Parcel("stock", year, stock_inv, cpi_now, stock_inv / nre_price["stock"]))
                if bond_inv > 0:
                    nre_parcels.append(Parcel("bond", year, bond_inv, cpi_now, bond_inv / nre_price["bond"]))
            elif target == "trust" and config.trust_assets is not None:
                # Add to trust as a single stock parcel
                trust_parcels.append(Parcel("stock", year, investible_surplus, cpi_now, investible_surplus / trust_price))
            elif target == "super":
                super_accumulation_balance += investible_surplus
            elif target == "cash":
                # investible_surplus remains in cash
                pass

            # Cash held at year-end is remaining_savings minus any investible_surplus
            # that was moved to non-cash assets. If the investible_surplus targets
            # cash, the full remaining_savings stays in cash_balance.
            non_invested_surplus = remaining_savings - investible_surplus
            if target == "cash":
                cash_balance = remaining_savings
            else:
                cash_balance = non_invested_surplus
        else:
            # No surplus: cash balance is whatever small remainder exists (or zero)
            cash_balance = max(0.0, remaining_savings)

        # ---- 10. Super growth and tax ----
        super_earn_rate = config.super_growth_rate.sample(rng)
        
        # 1. Accumulation earnings and tax
        acc_earnings = super_accumulation_balance * super_earn_rate
        acc_tax_paid = super_fund_tax(
            concessional_contributions=total_concessional,
            investment_earnings=acc_earnings,
            in_pension_phase=False, # Accumulation is always taxed
        )
        super_accumulation_balance += (total_concessional + acc_earnings - acc_tax_paid)
        
        # 2. Pension earnings (tax free)
        pension_earnings = super_pension_balance * super_earn_rate
        super_pension_balance += pension_earnings
        
        super_balance = super_accumulation_balance + super_pension_balance
        super_tax_paid = acc_tax_paid

        # ---- 11. Net position & Recording ----
        nre_end_value = sum(p.units * nre_price[p.asset_type] for p in nre_parcels)
        re_end_value = sum(re_values.values())
        trust_end_value = sum(p.units * trust_price for p in trust_parcels)
        total_assets = nre_end_value + re_end_value + super_balance + trust_end_value + cash_balance

        # Use the latest total_taxable from the iterative solver loop
        final_taxable = total_taxable

        # Liabilities: outstanding mortgage balances across RE properties
        try:
            total_liabilities = sum(re_mortgage_balance.values()) if re_mortgage_balance else 0.0
        except Exception:
            # defensive: ensure a numeric total if structure is unexpected
            total_liabilities = 0.0

        net_worth_nominal = total_assets - total_liabilities
        net_worth_real = net_worth_nominal * deflator

        records.append({
            "year": year,
            "age": age,
            # Income (nominal)
            "salary_nominal": salary_nominal,
            "nre_ordinary_income_nominal": nre_ordinary_income,
            "net_rent_nominal": total_net_rent_legacy + total_net_rent_new,
            "nre_capital_gain_nominal": nre_gain_total + nre_capital_gain_dist,
            "re_cgt_gain_nominal": sum(g for g, _ in re_cgt_events),
            "total_taxable_income_nominal": final_taxable,
            # Income (real = base-year dollars)
            "salary_real": salary_nominal * deflator,
            "nre_ordinary_income_real": nre_ordinary_income * deflator,
            "net_rent_real": (total_net_rent_legacy + total_net_rent_new) * deflator,
            # Expenses (nominal and real)
            "expenses_nominal": expenses_nominal,
            "expenses_real": expenses_nominal * deflator,
            # Tax
            "personal_income_tax": personal_tax_ordinary,
            "super_fund_tax": super_tax_paid,
            "div293_tax": div293_personal,
            "cgt_total": nre_cgt_total + sum(t for _, t in re_cgt_events) + trust_cgt_total + trust_diss_tax_final + trust_dist_cgt_tax,
            "total_tax": actual_tax_paid + super_tax_paid,
            # Drawdown
            "nre_drawdown": nre_drawdown_final,
            "super_drawdown": super_draw,
            "trust_drawdown": trust_drawdown_final,
            # Super
            "super_contribution_concessional": total_concessional,
            "super_balance_eoy": super_balance,
            "super_accumulation_balance_eoy": super_accumulation_balance,
            "super_pension_balance_eoy": super_pension_balance,
            # Assets (nominal end-of-year)
            "nre_portfolio_value": nre_end_value,
            "re_portfolio_value": re_end_value,
            "cash_balance": cash_balance,
            "total_assets_nominal": total_assets,
            # Assets (real)
            "nre_portfolio_value_real": nre_end_value * deflator,
            "re_portfolio_value_real": re_end_value * deflator,
            "cash_balance_real": cash_balance * deflator,
            "super_balance_eoy_real": super_balance * deflator,
            "total_assets_real": total_assets * deflator,
            # Liabilities and net worth
            "total_liabilities_nominal": total_liabilities,
            "total_liabilities_real": total_liabilities * deflator,
            "net_worth_nominal": net_worth_nominal,
            "net_worth_real": net_worth_real,
            # Trust
            "trust_distribution_income_nominal": trust_distribution_income,
            "trust_distribution_income_real": trust_distribution_income * deflator,
            "trust_tax_paid_nominal": trust_tax_paid,
            "trust_tax_paid_real": trust_tax_paid * deflator,
            "trust_contribution_nominal": trust_contribution_this_year,
            "nre_contribution_nominal": nre_contribution_this_year,
            "re_contribution_nominal": re_contribution_nominal,
            "re_mortgage_payment_nominal": re_contribution_nominal,
            "re_mortgage_interest_nominal": re_mortgage_interest_nominal,
            "re_mortgage_principal_nominal": re_mortgage_principal_nominal,
            "trust_cgt_gain_nominal": trust_active_cap_gain,
            "trust_cgt_tax": trust_cgt_total + trust_diss_tax_final + trust_dist_cgt_tax,
            "trust_value_eoy": trust_end_value,
            "trust_value_eoy_real": trust_end_value * deflator,
            # CPI
            "cpi_index": cpi_now,
            # Debug fields
            "available_cash_pre_draw_debug": available_cash_pre_draw,
            "remaining_savings_debug": remaining_savings,
            "funding_gap_debug": funding_gap,
            "initial_funding_gap_debug": initial_funding_gap,
        })

    return pd.DataFrame(records)
