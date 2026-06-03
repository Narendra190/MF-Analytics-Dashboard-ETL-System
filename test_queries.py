import sqlite3

conn = sqlite3.connect('bluestock_mf.db')
c = conn.cursor()

# Test Query 1: Top 5 funds by AUM
print('=== Top 5 Funds by AUM ===')
c.execute('''
    SELECT 
        df.scheme_name,
        df.fund_house,
        df.category,
        fp.aum_crore,
        fp.expense_ratio_pct
    FROM fact_performance fp
    JOIN dim_fund df ON fp.fund_id = df.fund_id
    ORDER BY fp.aum_crore DESC
    LIMIT 5
''')
for row in c.fetchall():
    print(row)

# Test Query 2: Transactions by state (top 3)
print('\n=== Transactions by State (Top 3) ===')
c.execute('''
    SELECT 
        di.state,
        COUNT(*) as transaction_count,
        SUM(ft.amount_inr) as total_amount_inr
    FROM fact_transactions ft
    JOIN dim_investor di ON ft.investor_id = di.investor_id
    GROUP BY di.state
    ORDER BY total_amount_inr DESC
    LIMIT 3
''')
for row in c.fetchall():
    print(row)

print('\nQueries executed successfully!')
conn.close()
