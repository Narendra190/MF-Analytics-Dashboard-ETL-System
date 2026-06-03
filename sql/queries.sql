
-- Query: 1_top_5_funds_by_aum
SELECT 
                df.scheme_name,
                df.fund_house,
                df.category,
                fp.aum_crore,
                fp.expense_ratio_pct
            FROM fact_performance fp
            JOIN dim_fund df ON fp.fund_id = df.fund_id
            ORDER BY fp.aum_crore DESC
            LIMIT 5;

================================================================================

-- Query: 2_average_nav_per_month
SELECT 
                strftime('%Y-%m', dd.date) as month,
                df.scheme_name,
                ROUND(AVG(fn.nav), 4) as avg_nav,
                MIN(fn.nav) as min_nav,
                MAX(fn.nav) as max_nav
            FROM fact_nav fn
            JOIN dim_fund df ON fn.fund_id = df.fund_id
            JOIN dim_date dd ON fn.date_id = dd.date_id
            GROUP BY strftime('%Y-%m', dd.date), df.fund_id, df.scheme_name
            ORDER BY month DESC, df.scheme_name;

================================================================================

-- Query: 3_sip_yoy_growth
SELECT 
                dd.year,
                SUM(CASE WHEN ft.transaction_type = 'SIP' THEN ft.amount_inr ELSE 0 END) as total_sip,
                LAG(SUM(CASE WHEN ft.transaction_type = 'SIP' THEN ft.amount_inr ELSE 0 END)) 
                    OVER (ORDER BY dd.year) as prev_year_sip,
                ROUND(
                    (SUM(CASE WHEN ft.transaction_type = 'SIP' THEN ft.amount_inr ELSE 0 END) -
                     LAG(SUM(CASE WHEN ft.transaction_type = 'SIP' THEN ft.amount_inr ELSE 0 END)) 
                        OVER (ORDER BY dd.year)) / 
                    LAG(SUM(CASE WHEN ft.transaction_type = 'SIP' THEN ft.amount_inr ELSE 0 END)) 
                        OVER (ORDER BY dd.year) * 100, 2
                ) as yoy_growth_pct
            FROM fact_transactions ft
            JOIN dim_date dd ON ft.date_id = dd.date_id
            GROUP BY dd.year
            ORDER BY dd.year;

================================================================================

-- Query: 4_transactions_by_state
SELECT 
                di.state,
                COUNT(*) as transaction_count,
                SUM(ft.amount_inr) as total_amount_inr,
                ROUND(AVG(ft.amount_inr), 2) as avg_transaction_amount,
                COUNT(DISTINCT ft.investor_id) as unique_investors
            FROM fact_transactions ft
            JOIN dim_investor di ON ft.investor_id = di.investor_id
            GROUP BY di.state
            ORDER BY total_amount_inr DESC;

================================================================================

-- Query: 5_funds_with_low_expense_ratio
SELECT 
                df.scheme_name,
                df.fund_house,
                df.category,
                fp.expense_ratio_pct,
                fp.return_3yr_pct,
                fp.aum_crore
            FROM fact_performance fp
            JOIN dim_fund df ON fp.fund_id = df.fund_id
            WHERE fp.expense_ratio_pct IS NOT NULL 
                AND fp.expense_ratio_pct BETWEEN 0.1 AND 2.5
            ORDER BY fp.expense_ratio_pct
            LIMIT 10;

================================================================================

-- Query: 6_lumpsum_vs_sip_analysis
SELECT 
                df.scheme_name,
                ft.transaction_type,
                COUNT(*) as count,
                SUM(ft.amount_inr) as total_amount_inr,
                ROUND(AVG(ft.amount_inr), 2) as avg_amount_inr,
                COUNT(DISTINCT ft.investor_id) as unique_investors
            FROM fact_transactions ft
            JOIN dim_fund df ON ft.fund_id = df.fund_id
            WHERE ft.transaction_type IN ('SIP', 'Lumpsum')
            GROUP BY df.scheme_name, ft.transaction_type
            ORDER BY df.scheme_name, total_amount_inr DESC;

================================================================================

-- Query: 7_investor_kyc_status_breakdown
SELECT 
                di.kyc_status,
                COUNT(DISTINCT di.investor_id) as investor_count,
                COUNT(DISTINCT ft.transaction_id) as transaction_count,
                SUM(ft.amount_inr) as total_transacted_inr,
                ROUND(AVG(ft.amount_inr), 2) as avg_transaction_amount
            FROM dim_investor di
            LEFT JOIN fact_transactions ft ON di.investor_id = ft.investor_id
            GROUP BY di.kyc_status
            ORDER BY investor_count DESC;

================================================================================

-- Query: 8_fund_performance_ranking
SELECT 
                df.scheme_name,
                df.fund_house,
                fp.return_1yr_pct,
                fp.return_3yr_pct,
                fp.return_5yr_pct,
                fp.sharpe_ratio,
                fp.aum_crore,
                ROW_NUMBER() OVER (ORDER BY fp.return_3yr_pct DESC) as rank_by_3yr_return
            FROM fact_performance fp
            JOIN dim_fund df ON fp.fund_id = df.fund_id
            WHERE fp.return_3yr_pct IS NOT NULL
            ORDER BY fp.return_3yr_pct DESC;

================================================================================

-- Query: 9_highest_investors_per_fund
SELECT 
                df.scheme_name,
                df.fund_house,
                COUNT(DISTINCT ft.investor_id) as investor_count,
                COUNT(*) as transaction_count,
                SUM(ft.amount_inr) as total_aum_inr
            FROM fact_transactions ft
            JOIN dim_fund df ON ft.fund_id = df.fund_id
            GROUP BY df.fund_id, df.scheme_name, df.fund_house
            ORDER BY investor_count DESC
            LIMIT 10;

================================================================================

-- Query: 10_monthly_nav_trend
SELECT 
                df.scheme_name,
                strftime('%Y-%m', dd.date) as month,
                FIRST_VALUE(fn.nav) OVER (
                    PARTITION BY df.fund_id, strftime('%Y-%m', dd.date)
                    ORDER BY dd.date
                ) as opening_nav,
                LAST_VALUE(fn.nav) OVER (
                    PARTITION BY df.fund_id, strftime('%Y-%m', dd.date)
                    ORDER BY dd.date
                    ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
                ) as closing_nav,
                MIN(fn.nav) as min_nav,
                MAX(fn.nav) as max_nav
            FROM fact_nav fn
            JOIN dim_fund df ON fn.fund_id = df.fund_id
            JOIN dim_date dd ON fn.date_id = dd.date_id
            ORDER BY df.fund_id, month DESC;

================================================================================
