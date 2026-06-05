from pathlib import Path
import numpy as np
import pandas as pd
from scipy.stats import linregress
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
PROCESSED_DIR = ROOT / 'data' / 'processed'
RAW_DIR = ROOT / 'data' / 'raw'
REPORTS_DIR = ROOT / 'reports'
CHARTS_DIR = REPORTS_DIR / 'charts'
CHARTS_DIR.mkdir(parents=True, exist_ok=True)

RF_ANNUAL = 0.065
TRADING_DAYS = 252


def load_data():
    fund_master = pd.read_csv(PROCESSED_DIR / '01_fund_master_clean.csv')
    nav = pd.read_csv(PROCESSED_DIR / '02_nav_history_clean.csv', parse_dates=['date'])
    benchmark = pd.read_csv(RAW_DIR / '10_benchmark_indices.csv', parse_dates=['date'])
    return fund_master, nav, benchmark


def dedupe_nav(nav: pd.DataFrame) -> pd.DataFrame:
    nav = nav.copy()
    nav = nav.sort_values(['amfi_code', 'date'])
    nav = nav.drop_duplicates(subset=['amfi_code', 'date'], keep='last')
    return nav.reset_index(drop=True)


def compute_daily_returns(nav: pd.DataFrame) -> pd.DataFrame:
    nav = dedupe_nav(nav)
    nav = nav.sort_values(['amfi_code', 'date']).reset_index(drop=True)
    nav['prev_nav'] = nav.groupby('amfi_code')['nav'].shift(1)
    nav['prev_date'] = nav.groupby('amfi_code')['date'].shift(1)
    nav['delta_days'] = (nav['date'] - nav['prev_date']).dt.days
    nav['daily_return'] = np.where(
        nav['delta_days'] > 0,
        (nav['nav'] / nav['prev_nav']) ** (1 / nav['delta_days']) - 1,
        np.nan,
    )
    return nav.drop(columns=['prev_nav', 'prev_date', 'delta_days'])


def _get_anchor_nav(nav: pd.DataFrame, target_date: pd.Timestamp) -> pd.DataFrame:
    mask = nav['date'] <= target_date
    return (
        nav.loc[mask]
        .sort_values(['amfi_code', 'date'])
        .groupby('amfi_code', as_index=False)
        .last()
    )


def compute_cagr(nav: pd.DataFrame, end_date: pd.Timestamp = None) -> pd.DataFrame:
    if end_date is None:
        end_date = nav['date'].max()

    end_nav = _get_anchor_nav(nav, end_date).rename(columns={'nav': 'nav_end', 'date': 'end_date'})

    records = []
    for period in [1, 3, 5]:
        start_date = end_date - pd.DateOffset(years=period)
        start_nav = _get_anchor_nav(nav, start_date).rename(columns={'nav': f'nav_{period}yr_start', 'date': f'start_{period}yr_date'})
        merged = end_nav[['amfi_code', 'nav_end', 'end_date']].merge(start_nav[['amfi_code', f'nav_{period}yr_start', f'start_{period}yr_date']], on='amfi_code', how='left')
        merged[f'cagr_{period}yr'] = np.where(
            merged[f'nav_{period}yr_start'] > 0,
            (merged['nav_end'] / merged[f'nav_{period}yr_start']) ** (1 / period) - 1,
            np.nan,
        )
        if period == 1:
            cagr_df = merged[['amfi_code', f'cagr_{period}yr']].rename(columns={f'cagr_{period}yr': 'cagr_1yr'})
        else:
            cagr_df = cagr_df.merge(merged[['amfi_code', f'cagr_{period}yr']], on='amfi_code', how='left')

    cagr_df = cagr_df.rename(
        columns={
            'cagr_1yr': 'cagr_1yr',
            'cagr_3yr': 'cagr_3yr',
            'cagr_5yr': 'cagr_5yr',
        }
    )
    return cagr_df


def compute_sharpe_sortino(nav_returns: pd.DataFrame) -> pd.DataFrame:
    rf_daily = RF_ANNUAL / TRADING_DAYS
    records = []
    for code, grp in nav_returns.groupby('amfi_code', sort=False):
        daily = grp['daily_return'].dropna()
        mean_r = daily.mean()
        std_r = daily.std(ddof=0)
        downside = daily[daily < 0]
        downside_std = downside.std(ddof=0)

        sharpe = np.nan
        if std_r > 0:
            sharpe = (mean_r - rf_daily) / std_r * np.sqrt(TRADING_DAYS)

        sortino = np.nan
        if downside_std > 0:
            sortino = (mean_r - rf_daily) / downside_std * np.sqrt(TRADING_DAYS)

        records.append(
            {
                'amfi_code': code,
                'mean_daily_return': mean_r,
                'std_daily_return': std_r,
                'sharpe_ratio': sharpe,
                'sortino_ratio': sortino,
                'downside_std': downside_std,
            }
        )

    return pd.DataFrame.from_records(records)


def compute_alpha_beta(nav_returns: pd.DataFrame, benchmark: pd.DataFrame) -> pd.DataFrame:
    bench = (
        benchmark[benchmark['index_name'] == 'NIFTY100']
        .sort_values('date')
        .drop_duplicates(subset=['date'], keep='last')
        .set_index('date')['close_value']
    )
    records = []

    for code, grp in nav_returns.groupby('amfi_code', sort=False):
        fund = grp.sort_values('date')[['date', 'daily_return']].dropna()
        if fund.empty:
            records.append(
                {
                    'amfi_code': code,
                    'alpha_daily': np.nan,
                    'alpha_ann': np.nan,
                    'beta': np.nan,
                    'r_value': np.nan,
                    'p_value': np.nan,
                    'stderr': np.nan,
                    'n_obs': 0,
                }
            )
            continue

        fund_dates = fund['date']
        fund_delta = fund_dates.diff().dt.days
        bench_at_dates = bench.reindex(fund_dates, method='ffill')
        bench_prev = bench_at_dates.shift(1)
        bench_return = np.where(
            fund_delta > 0,
            (bench_at_dates.values / bench_prev.values) ** (1 / fund_delta.values) - 1,
            np.nan,
        )
        merged = pd.DataFrame(
            {
                'fund_return': fund['daily_return'].values,
                'bench_return': bench_return,
            },
            index=fund_dates,
        ).dropna()

        if len(merged) < 2:
            records.append(
                {
                    'amfi_code': code,
                    'alpha_daily': np.nan,
                    'alpha_ann': np.nan,
                    'beta': np.nan,
                    'r_value': np.nan,
                    'p_value': np.nan,
                    'stderr': np.nan,
                    'n_obs': len(merged),
                }
            )
            continue

        lr = linregress(merged['bench_return'], merged['fund_return'])
        records.append(
            {
                'amfi_code': code,
                'alpha_daily': lr.intercept,
                'alpha_ann': lr.intercept * TRADING_DAYS,
                'beta': lr.slope,
                'r_value': lr.rvalue,
                'p_value': lr.pvalue,
                'stderr': lr.stderr,
                'n_obs': len(merged),
            }
        )

    return pd.DataFrame.from_records(records)


def compute_max_drawdown(nav: pd.DataFrame) -> pd.DataFrame:
    records = []
    for code, grp in nav.groupby('amfi_code', sort=False):
        grp = grp.sort_values('date').reset_index(drop=True)
        grp['running_max'] = grp['nav'].cummax()
        grp['drawdown'] = grp['nav'] / grp['running_max'] - 1
        if grp.empty:
            continue
        worst_idx = grp['drawdown'].idxmin()
        trough_date = grp.loc[worst_idx, 'date']
        before_trough = grp.loc[:worst_idx]
        peak_candidates = before_trough[before_trough['nav'] == before_trough['running_max']]
        peak_date = peak_candidates.iloc[-1]['date'] if not peak_candidates.empty else before_trough.iloc[0]['date']
        records.append(
            {
                'amfi_code': code,
                'max_drawdown': grp.loc[worst_idx, 'drawdown'],
                'max_drawdown_pct': grp.loc[worst_idx, 'drawdown'] * 100,
                'drawdown_peak_date': peak_date,
                'drawdown_trough_date': trough_date,
            }
        )

    return pd.DataFrame.from_records(records)


def build_scorecard(performance: pd.DataFrame, fund_master: pd.DataFrame) -> pd.DataFrame:
    perf = performance.copy()
    master = fund_master[['amfi_code', 'scheme_name', 'fund_house', 'expense_ratio_pct']]
    perf = perf.merge(master, on='amfi_code', how='left')

    n = len(perf)
    perf['rank_3yr_return'] = perf['cagr_3yr_pct'].rank(method='min', ascending=False)
    perf['rank_sharpe'] = perf['sharpe_ratio'].rank(method='min', ascending=False)
    perf['rank_alpha'] = perf['alpha_ann'].rank(method='min', ascending=False)
    perf['rank_expense_ratio'] = perf['expense_ratio_pct'].rank(method='min', ascending=True)
    perf['rank_max_drawdown'] = perf['max_drawdown_pct'].rank(method='min', ascending=True)

    perf['score_3yr_return'] = (n - perf['rank_3yr_return']) / (n - 1) * 30
    perf['score_sharpe'] = (n - perf['rank_sharpe']) / (n - 1) * 25
    perf['score_alpha'] = (n - perf['rank_alpha']) / (n - 1) * 20
    perf['score_expense'] = (n - perf['rank_expense_ratio']) / (n - 1) * 15
    perf['score_max_drawdown'] = (n - perf['rank_max_drawdown']) / (n - 1) * 10

    perf['fund_score'] = (
        perf['score_3yr_return']
        + perf['score_sharpe']
        + perf['score_alpha']
        + perf['score_expense']
        + perf['score_max_drawdown']
    )
    perf['fund_score'] = perf['fund_score'].round(2)
    perf['fund_score_rank'] = perf['fund_score'].rank(method='min', ascending=False).astype(int)

    perf = perf.sort_values('fund_score', ascending=False).reset_index(drop=True)
    return perf


def benchmark_tracking_error(nav_returns: pd.DataFrame, benchmark: pd.DataFrame, top_funds: list) -> pd.DataFrame:
    records = []
    for index_name in ['NIFTY50', 'NIFTY100']:
        bench = (
            benchmark[benchmark['index_name'] == index_name]
            .sort_values('date')
            .drop_duplicates(subset=['date'], keep='last')
            .set_index('date')['close_value']
        )
        for code in top_funds:
            fund = nav_returns[nav_returns['amfi_code'] == code][['date', 'daily_return']].dropna().sort_values('date')
            if fund.empty:
                records.append(
                    {
                        'amfi_code': code,
                        'index_name': index_name,
                        'tracking_error': np.nan,
                        'n_obs': 0,
                    }
                )
                continue

            fund_dates = fund['date']
            fund_delta = fund_dates.diff().dt.days
            bench_at_dates = bench.reindex(fund_dates, method='ffill')
            bench_prev = bench_at_dates.shift(1)
            bench_return = np.where(
                fund_delta > 0,
                (bench_at_dates.values / bench_prev.values) ** (1 / fund_delta.values) - 1,
                np.nan,
            )
            merged = pd.DataFrame(
                {
                    'fund_return': fund['daily_return'].values,
                    'bench_return': bench_return,
                },
                index=fund_dates,
            ).dropna()

            tracking_error = np.nan
            if len(merged) > 1:
                tracking_error = merged['fund_return'].sub(merged['bench_return']).std(ddof=0) * np.sqrt(TRADING_DAYS)
            records.append(
                {
                    'amfi_code': code,
                    'index_name': index_name,
                    'tracking_error': tracking_error,
                    'n_obs': len(merged),
                }
            )
    return pd.DataFrame.from_records(records)


def plot_benchmark_comparison(nav_returns: pd.DataFrame, benchmark: pd.DataFrame, top_funds: list, output_path: Path):
    end_date = nav_returns['date'].max()
    start_date = end_date - pd.DateOffset(years=3)
    funds = nav_returns[nav_returns['amfi_code'].isin(top_funds)].copy()
    funds = funds[funds['date'] >= start_date].sort_values(['amfi_code', 'date'])
    funds['cum_return'] = funds.groupby('amfi_code')['daily_return'].transform(lambda x: (1 + x).cumprod() - 1)

    bench = benchmark[benchmark['index_name'].isin(['NIFTY50', 'NIFTY100'])].copy()
    bench = bench[bench['date'] >= start_date].sort_values(['index_name', 'date'])
    bench['daily_return'] = bench.groupby('index_name')['close_value'].pct_change()
    bench['cum_return'] = bench.groupby('index_name')['daily_return'].transform(lambda x: (1 + x).cumprod() - 1)

    plt.figure(figsize=(14, 8))
    for code, grp in funds.groupby('amfi_code', sort=False):
        name = grp['scheme_name'].iloc[0] if 'scheme_name' in grp.columns else code
        plt.plot(grp['date'], grp['cum_return'], label=fund_label(name), linewidth=1.8)

    for index_name, grp in bench.groupby('index_name', sort=False):
        plt.plot(grp['date'], grp['cum_return'], label=index_name, linewidth=2.4, linestyle='--')

    plt.title('Top 5 Funds vs NIFTY50 and NIFTY100 (3-Year Cumulative Return)')
    plt.xlabel('Date')
    plt.ylabel('Cumulative Return')
    plt.legend(loc='upper left', fontsize='small', ncol=2)
    plt.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(output_path, dpi=180)
    plt.close()


def fund_label(name) -> str:
    name = str(name)
    if len(name) > 30:
        return name[:27] + '...'
    return name


def generate_reports():
    fund_master, nav, benchmark = load_data()
    nav = nav.merge(fund_master[['amfi_code', 'scheme_name']], on='amfi_code', how='left')
    nav = dedupe_nav(nav)

    nav_returns = compute_daily_returns(nav)
    cagr_df = compute_cagr(nav)
    risk_df = compute_sharpe_sortino(nav_returns)
    alpha_beta_df = compute_alpha_beta(nav_returns, benchmark)
    max_dd_df = compute_max_drawdown(nav)

    performance = (
        cagr_df
        .merge(risk_df[['amfi_code', 'sharpe_ratio', 'sortino_ratio']], on='amfi_code')
        .merge(alpha_beta_df[['amfi_code', 'alpha_ann', 'beta']], on='amfi_code')
        .merge(max_dd_df[['amfi_code', 'max_drawdown_pct', 'drawdown_peak_date', 'drawdown_trough_date']], on='amfi_code')
    )
    performance = performance.rename(
        columns={
            'cagr_1yr': 'cagr_1yr_pct',
            'cagr_3yr': 'cagr_3yr_pct',
            'cagr_5yr': 'cagr_5yr_pct',
        }
    )
    performance[['cagr_1yr_pct', 'cagr_3yr_pct', 'cagr_5yr_pct']] = performance[['cagr_1yr_pct', 'cagr_3yr_pct', 'cagr_5yr_pct']] * 100

    scorecard = build_scorecard(performance, fund_master)
    scorecard['alpha_annual_pct'] = scorecard['alpha_ann'] * 100
    scorecard = scorecard.drop(columns=['alpha_ann'])

    alpha_beta_out = alpha_beta_df.merge(
        fund_master[['amfi_code', 'scheme_name', 'fund_house']], on='amfi_code', how='left'
    )
    alpha_beta_out = alpha_beta_out[['amfi_code', 'scheme_name', 'fund_house', 'alpha_ann', 'beta', 'r_value', 'p_value', 'stderr', 'n_obs']]
    alpha_beta_out['alpha_annual_pct'] = alpha_beta_out['alpha_ann'] * 100
    alpha_beta_out = alpha_beta_out.drop(columns=['alpha_ann'])

    fund_scorecard_path = ROOT / 'fund_scorecard.csv'
    alpha_beta_path = ROOT / 'alpha_beta.csv'
    benchmark_chart_path = CHARTS_DIR / 'benchmark_comparison_top5.png'

    scorecard.to_csv(fund_scorecard_path, index=False)
    alpha_beta_out.to_csv(alpha_beta_path, index=False)

    top_funds = scorecard.head(5)['amfi_code'].tolist()
    nav_returns = nav_returns.merge(fund_master[['amfi_code', 'scheme_name']], on='amfi_code', how='left')
    plot_benchmark_comparison(nav_returns, benchmark, top_funds, benchmark_chart_path)

    print('Generated:')
    print(' -', fund_scorecard_path)
    print(' -', alpha_beta_path)
    print(' -', benchmark_chart_path)
    return scorecard, alpha_beta_out, benchmark_chart_path


if __name__ == '__main__':
    generate_reports()
