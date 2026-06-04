from pathlib import Path
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
import plotly.express as px


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / 'data' / 'processed'
CHARTS_DIR = ROOT / 'reports' / 'charts'
CHARTS_DIR.mkdir(parents=True, exist_ok=True)


def save_plotly(fig, name):
    out = CHARTS_DIR / name
    try:
        fig.write_image(str(out))
        print('Saved', out)
    except Exception as exc:
        print('Plotly image export failed, saving HTML fallback:', exc)
        fig.write_html(str(out.with_suffix('.html')))
        print('Saved HTML fallback', out.with_suffix('.html'))


def save_matplotlib(fig, name):
    out = CHARTS_DIR / name
    fig.savefig(out, bbox_inches='tight', dpi=180)
    print('Saved', out)
    plt.close(fig)


def main():
    sns.set(style='whitegrid')
    fm = pd.read_csv(DATA_DIR / '01_fund_master_clean.csv')
    nav = pd.read_csv(DATA_DIR / '02_nav_history_clean.csv', parse_dates=['date'])
    aum = pd.read_csv(DATA_DIR / '03_aum_by_fund_house.csv')
    sip_monthly = pd.read_csv(DATA_DIR / '04_monthly_sip_inflows.csv', parse_dates=['month'])
    category_inflows = pd.read_csv(DATA_DIR / '05_category_inflows.csv', parse_dates=['month'])
    folio = pd.read_csv(DATA_DIR / '06_industry_folio_count.csv', parse_dates=['month'])
    perf = pd.read_csv(DATA_DIR / '07_scheme_performance_clean.csv')
    inv_tx = pd.read_csv(DATA_DIR / '08_investor_transactions_clean.csv', parse_dates=['transaction_date'])
    holdings = pd.read_csv(DATA_DIR / '09_portfolio_holdings.csv')

    # 1. NAV trends (matplotlib or plotly)
    nav = nav[(nav['date'] >= '2022-01-01') & (nav['date'] <= '2026-12-31')].copy()
    if 'scheme_name' not in nav.columns and 'amfi_code' in nav.columns:
        nav = nav.merge(fm[['amfi_code', 'scheme_name']], on='amfi_code', how='left')
    schemes = nav['scheme_name'].dropna().unique()[:40]
    nav_small = nav[nav['scheme_name'].isin(schemes)]
    fig = px.line(nav_small, x='date', y='nav', color='scheme_name', title='Daily NAV (2022-2026) - top 40 schemes')
    fig.update_layout(shapes=[
        dict(type='rect', xref='x', yref='paper', x0='2023-01-01', x1='2023-12-31', y0=0, y1=1, fillcolor='green', opacity=0.08, layer='below', line_width=0),
        dict(type='rect', xref='x', yref='paper', x0='2024-04-01', x1='2024-12-31', y0=0, y1=1, fillcolor='red', opacity=0.08, layer='below', line_width=0)
    ])
    save_plotly(fig, 'nav_trends_2022_2026.png')

    # 2. AUM grouped bar
    if 'year' not in aum.columns and 'date' in aum.columns:
        aum['date'] = pd.to_datetime(aum['date'])
        aum['year'] = aum['date'].dt.year
    aum_filt = aum[aum['year'].between(2022, 2025)].copy()
    pivot = aum_filt.pivot_table(index='fund_house', columns='year', values='aum_crore', aggfunc='sum').fillna(0)
    fig2, ax = plt.subplots(figsize=(12,6))
    pivot_sorted = pivot.sort_values(2022, ascending=False).head(30)
    pivot_sorted.plot(kind='bar', ax=ax)
    ax.set_ylabel('AUM (Crore)')
    ax.set_title('AUM by Fund House (2022-2025)')
    if 'SBI' in ' '.join(pivot_sorted.index):
        ax.text(0.02, 0.95, 'SBI ~ ₹12.5L Cr (dominant)', transform=ax.transAxes, fontsize=10, bbox=dict(facecolor='yellow', alpha=0.2))
    save_matplotlib(fig2, 'aum_by_fund_house_2022_2025.png')

    # 3. SIP time-series
    sip = sip_monthly.copy()
    sip = sip[(sip['month'] >= '2022-01-01') & (sip['month'] <= '2025-12-31')]
    sip['month'] = pd.to_datetime(sip['month'])
    # column in processed CSV is 'sip_inflow_crore'
    ycol = 'sip_inflow_crore' if 'sip_inflow_crore' in sip.columns else 'sip_inflow_cr'
    fig3 = px.line(sip, x='month', y=ycol, title='Monthly SIP Inflows (Jan 2022 - Dec 2025)')
    if not sip.empty and ycol in sip.columns:
        max_row = sip.loc[sip[ycol].idxmax()]
        fig3.add_annotation(x=max_row['month'], y=max_row[ycol], text=f"ALL-TIME HIGH: ₹{int(max_row[ycol]):,} Cr", showarrow=True, arrowhead=2)
    save_plotly(fig3, 'sip_monthly_2022_2025.png')

    # 4. Category inflow heatmap
    cat = category_inflows.copy()
    cat['month'] = pd.to_datetime(cat['month'])
    cat['month_str'] = cat['month'].dt.strftime('%Y-%m')
    # processed CSV uses 'net_inflow_crore'
    valcol = 'net_inflow_crore' if 'net_inflow_crore' in cat.columns else 'net_inflow_cr'
    pivot_cat = cat.pivot_table(index='category', columns='month_str', values=valcol, aggfunc='sum').fillna(0)
    fig4, ax4 = plt.subplots(figsize=(14,8))
    sns.heatmap(pivot_cat, cmap='rocket_r', ax=ax4, linewidths=0.2)
    ax4.set_title('Category Net Inflow (months x categories)')
    save_matplotlib(fig4, 'category_inflow_heatmap.png')

    # 5. Investor demographics
    inv = inv_tx.copy()
    if 'age_group' in inv.columns:
        age_counts = inv['age_group'].value_counts().sort_index()
        fig5, ax5 = plt.subplots(figsize=(6,6))
        ax5.pie(age_counts, labels=age_counts.index, autopct='%1.1f%%', startangle=90)
        ax5.set_title('Investor Age Group Distribution')
        save_matplotlib(fig5, 'age_group_pie.png')

    if 'transaction_type' in inv.columns:
        sip_tx = inv[inv['transaction_type'].str.lower()=='sip']
    else:
        sip_tx = inv
    if 'age_group' in sip_tx.columns and 'amount_inr' in sip_tx.columns:
        fig6, ax6 = plt.subplots(figsize=(10,6))
        sns.boxplot(data=sip_tx, x='age_group', y='amount_inr', ax=ax6)
        ax6.set_yscale('log')
        ax6.set_title('SIP Amount by Age Group (log scale)')
        save_matplotlib(fig6, 'sip_amount_by_age_boxplot.png')

    if 'gender' in inv.columns:
        gender_counts = inv['gender'].fillna('Unknown').value_counts()
        fig7, ax7 = plt.subplots(figsize=(5,5))
        ax7.pie(gender_counts, labels=gender_counts.index, autopct='%1.1f%%', startangle=90)
        ax7.set_title('Gender Split')
        save_matplotlib(fig7, 'gender_split_pie.png')

    # 6. Geographic distribution
    if 'transaction_type' in inv.columns and 'state' in inv.columns:
        state_sip = inv[inv['transaction_type'].str.lower()=='sip'].groupby('state')['amount_inr'].sum().sort_values(ascending=True).tail(30)
        if not state_sip.empty:
            fig8, ax8 = plt.subplots(figsize=(10,8))
            state_sip.plot(kind='barh', ax=ax8, color='teal')
            ax8.set_xlabel('Total SIP Amount (INR)')
            ax8.set_title('Top 30 States by SIP Amount')
            save_matplotlib(fig8, 'sip_by_state_top30.png')
        else:
            print('No SIP transactions found for state-level chart; skipping sip_by_state_top30.png')

    if 'city_tier' in inv.columns:
        tiers = inv['city_tier'].fillna('Unknown').value_counts()
        fig9, ax9 = plt.subplots(figsize=(5,5))
        ax9.pie(tiers, labels=tiers.index, autopct='%1.1f%%')
        ax9.set_title('City Tier Distribution (T30 vs B30)')
        save_matplotlib(fig9, 'city_tier_pie.png')

    # 7. Folio count growth
    if 'month' in folio.columns and 'folio_count_cr' in folio.columns:
        folio2 = folio.copy()
        folio2['month'] = pd.to_datetime(folio2['month'])
        folio2 = folio2[(folio2['month'] >= '2022-01-01') & (folio2['month'] <= '2025-12-31')]
        fig10, ax10 = plt.subplots(figsize=(10,5))
        ax10.plot(folio2['month'], folio2['folio_count_cr'], marker='o')
        ax10.set_title('Folio Count Growth (Cr)')
        ax10.set_ylabel('Folio Count (Cr)')
        milestones = {'Jan 2022':13.26, 'Dec 2025':26.12}
        if not folio2.empty:
            ax10.annotate('Jan 2022: 13.26 Cr', xy=(folio2['month'].iloc[0], milestones['Jan 2022']), xytext=(10,10), textcoords='offset points')
            ax10.annotate('Dec 2025: 26.12 Cr', xy=(folio2['month'].iloc[-1], milestones['Dec 2025']), xytext=(-80,-20), textcoords='offset points')
        save_matplotlib(fig10, 'folio_count_growth.png')

    # 8. NAV return correlation matrix (10 funds)
    if 'scheme_name' in nav.columns:
        selected = nav['scheme_name'].dropna().unique()[:10]
        nav_sel = nav[nav['scheme_name'].isin(selected)].copy()
        # remove duplicate date+scheme rows by keeping the last entry
        nav_sel = nav_sel.sort_values(['scheme_name', 'date']).drop_duplicates(subset=['date', 'scheme_name'], keep='last')
        nav_wide = nav_sel.pivot(index='date', columns='scheme_name', values='nav')
        returns = nav_wide.pct_change().dropna()
        corr = returns.corr()
        fig11, ax11 = plt.subplots(figsize=(10,8))
        sns.heatmap(corr, annot=True, fmt='.2f', cmap='vlag', center=0, ax=ax11)
        ax11.set_title('Correlation Matrix - Daily Returns (10 funds)')
        save_matplotlib(fig11, 'nav_return_correlation_10funds.png')

    # 9. Sector allocation donut
    if 'sector' in holdings.columns and 'weight_pct' in holdings.columns:
        agg = holdings.groupby('sector')['weight_pct'].sum().sort_values(ascending=False)
        fig12, ax12 = plt.subplots(figsize=(7,7))
        wedges, texts = ax12.pie(agg, labels=agg.index, startangle=90, wedgeprops=dict(width=0.3))
        ax12.set_title('Aggregate Sector Allocation (donut)')
        save_matplotlib(fig12, 'sector_allocation_donut.png')

        # --- Supplemental charts to reach 15+ visuals ---
        # NAV rolling 30-day avg for top 5 schemes
        try:
            top5 = list(schemes[:5])
            nav_top5 = nav[nav['scheme_name'].isin(top5)].pivot(index='date', columns='scheme_name', values='nav')
            nav_roll = nav_top5.rolling(30).mean()
            fig13 = px.line(nav_roll, x=nav_roll.index, y=nav_roll.columns, title='30-day Rolling Avg NAV - Top 5 Schemes')
            save_plotly(fig13, 'nav_30d_roll_top5.html')
        except Exception as e:
            print('Skipping top5 rolling NAV chart:', e)

        # SIP-related trends: active accounts, new accounts, SIP AUM
        try:
            if 'active_sip_accounts_crore' in sip.columns:
                fig14, ax14 = plt.subplots(figsize=(10,5))
                ax14.plot(sip['month'], sip['active_sip_accounts_crore'], marker='o')
                ax14.set_title('Active SIP Accounts (Crore)')
                save_matplotlib(fig14, 'active_sip_accounts_trend.png')
            if 'new_sip_accounts_lakh' in sip.columns:
                fig15, ax15 = plt.subplots(figsize=(10,5))
                ax15.plot(sip['month'], sip['new_sip_accounts_lakh'], marker='o', color='orange')
                ax15.set_title('New SIP Accounts (Lakh)')
                save_matplotlib(fig15, 'new_sip_accounts_trend.png')
            if 'sip_aum_lakh_crore' in sip.columns:
                fig16, ax16 = plt.subplots(figsize=(10,5))
                ax16.plot(sip['month'], sip['sip_aum_lakh_crore'], marker='o', color='green')
                ax16.set_title('SIP AUM (Lakh Crore)')
                save_matplotlib(fig16, 'sip_aum_trend.png')
        except Exception as e:
            print('Skipping some SIP supplemental charts:', e)

        # Top fund houses pie (from pivot_sorted used earlier)
        try:
            top_houses = pivot_sorted.sum(axis=1).sort_values(ascending=False).head(10)
            fig17, ax17 = plt.subplots(figsize=(7,7))
            ax17.pie(top_houses, labels=top_houses.index, autopct='%1.1f%%', startangle=90)
            ax17.set_title('Top 10 Fund Houses by AUM (2022 baseline)')
            save_matplotlib(fig17, 'top10_fund_houses_pie.png')
        except Exception as e:
            print('Skipping top fund houses pie:', e)

    print('Chart generation complete. Files saved to:', CHARTS_DIR)


if __name__ == '__main__':
    main()
