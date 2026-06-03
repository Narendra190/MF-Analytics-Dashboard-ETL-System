# Data Dictionary

## Database: bluestock_mf.db

### Dimension Tables

#### dim_fund
Fund master dimension with scheme details
- fund_id: Primary key
- amfi_code: AMFI scheme code (unique)
- scheme_name: Name of the mutual fund scheme
- fund_house: Fund house/AMC name
- category: Fund category (Equity, Debt, etc.)
- sub_category: Sub-category (Large Cap, Small Cap, etc.)
- plan: Plan type (Regular, Direct)
- launch_date: Scheme launch date
- benchmark: Benchmark index
- risk_category: Risk level (Moderate, High, Very High)
- fund_manager: Fund manager name
- min_sip_amount: Minimum SIP amount
- min_lumpsum_amount: Minimum lumpsum amount
- exit_load_pct: Exit load percentage

#### dim_date
Date dimension for time-based analysis
- date_id: Primary key
- date: Calendar date (unique)
- year, month, day, quarter, week_of_year: Temporal attributes
- day_of_week: Day name
- is_weekend: Boolean flag for weekend

#### dim_investor
Investor dimension with demographic and KYC details
- investor_id: Primary key
- investor_code: Unique investor identifier
- state, city, city_tier: Geographic attributes
- age_group: Age bracket
- gender: Gender
- annual_income_lakh: Annual income in lakhs
- kyc_status: KYC status (Verified, Pending, Rejected)

### Fact Tables

#### fact_nav
Net Asset Value history
- nav_id: Primary key
- fund_id: FK to dim_fund
- date_id: FK to dim_date
- nav: NAV value (must be > 0)

#### fact_transactions
Investor transactions (SIP, Lumpsum, Redemption)
- transaction_id: Primary key
- investor_id: FK to dim_investor
- fund_id: FK to dim_fund
- date_id: FK to dim_date
- transaction_type: Type of transaction (SIP, Lumpsum, Redemption)
- amount_inr: Transaction amount (must be > 0)
- payment_mode: Payment method (UPI, Cheque, Mandate)

#### fact_performance
Fund performance metrics
- performance_id: Primary key
- fund_id: FK to dim_fund
- return_1yr_pct, return_3yr_pct, return_5yr_pct: Returns over periods
- benchmark_3yr_pct: Benchmark return
- alpha, beta: Risk metrics
- sharpe_ratio, sortino_ratio: Risk-adjusted returns
- std_dev_ann_pct: Standard deviation
- max_drawdown_pct: Maximum drawdown
- aum_crore: Assets Under Management
- expense_ratio_pct: Expense ratio (0.1% - 2.5% valid range)
- morningstar_rating: Rating (1-5)
- risk_grade: Risk assessment

#### fact_aum
Assets Under Management by fund house
- aum_id: Primary key
- fund_house: Fund house name
- date_id: FK to dim_date
- aum_crore: Total AUM

### Data Quality Notes
- NAV values > 0: Enforced via CHECK constraint
- Transaction amounts > 0: Enforced via CHECK constraint
- Transaction types: Standardized to 'SIP', 'Lumpsum', 'Redemption'
- KYC status: 'Verified', 'Pending', 'Rejected'
- Expense ratios validated: 0.1% - 2.5% valid range
- Dates parsed to ISO format
- Duplicates removed from nav_history
- Missing NAVs forward-filled
