"""
Fund Risk-Based Recommender System

A simple recommender that filters mutual funds by risk appetite and ranks them by Sharpe ratio.
Use this module to recommend funds based on investor risk profile.

Usage:
------
from recommender import fund_recommender
import pandas as pd

# Get recommendations for Moderate risk appetite
recommendations = fund_recommender('Moderate', num_recommendations=3)
print(recommendations)

# Available risk appetites: 'Low', 'Moderate', 'High'
"""

import pandas as pd
import os


def load_performance_data(data_dir='data/processed'):
    """
    Load fund performance data from CSV.
    
    Parameters:
    -----------
    data_dir : str
        Path to data directory containing performance CSV
    
    Returns:
    --------
    DataFrame with fund performance metrics
    """
    perf_file = os.path.join(data_dir, '07_scheme_performance_clean.csv')
    return pd.read_csv(perf_file)


def fund_recommender(risk_appetite, num_recommendations=3, performance_data=None):
    """
    Recommend mutual funds based on risk appetite.
    
    Filters funds by matching risk_grade and ranks by Sharpe ratio (highest first).
    
    Parameters:
    -----------
    risk_appetite : str
        Investor risk tolerance. One of:
        - 'Low': Conservative, lower volatility funds
        - 'Moderate': Balanced risk-return profile
        - 'High': Aggressive, higher volatility funds
    
    num_recommendations : int
        Number of funds to recommend (default: 3)
    
    performance_data : DataFrame, optional
        Pre-loaded performance data. If None, will load from CSV.
    
    Returns:
    --------
    DataFrame with recommended funds containing:
    - rank: Recommendation rank (1 = best)
    - amfi_code: AMFI scheme code
    - scheme_name: Fund name
    - fund_house: Asset Management Company
    - category: Fund category (Equity, Debt, etc.)
    - risk_grade: Risk classification
    - sharpe_ratio: Risk-adjusted return metric (higher is better)
    - return_1yr_pct: 1-year return percentage
    - std_dev_ann_pct: Annual volatility percentage
    - expense_ratio_pct: Management fee as percentage
    - aum_crore: Assets Under Management in crores
    
    Raises:
    -------
    ValueError: If risk_appetite is invalid
    FileNotFoundError: If performance data file cannot be found
    
    Examples:
    ---------
    >>> # Get top 3 Low risk funds
    >>> low_risk = fund_recommender('Low', num_recommendations=3)
    >>> print(low_risk)
    
    >>> # Get top 5 Moderate risk funds
    >>> moderate_risk = fund_recommender('Moderate', num_recommendations=5)
    >>> print(moderate_risk[['rank', 'scheme_name', 'sharpe_ratio']])
    
    >>> # Get High risk recommendations
    >>> high_risk = fund_recommender('High')
    >>> print(high_risk.to_string())
    """
    
    # Validate risk appetite
    valid_appetites = ['Low', 'Moderate', 'High']
    if risk_appetite not in valid_appetites:
        raise ValueError(
            f"Invalid risk_appetite '{risk_appetite}'. "
            f"Must be one of: {', '.join(valid_appetites)}"
        )
    
    # Load performance data if not provided
    if performance_data is None:
        try:
            performance_data = load_performance_data()
        except FileNotFoundError as e:
            raise FileNotFoundError(
                "Cannot find performance data. Ensure you're in the project directory "
                "with 'data/processed/07_scheme_performance_clean.csv' available."
            ) from e
    
    # Map risk appetite to risk grades
    risk_mapping = {
        'Low': ['Moderate', 'Conservative'],
        'Moderate': ['Moderate'],
        'High': ['High', 'Very High']
    }
    
    # Filter funds by risk grade
    target_risk_grades = risk_mapping[risk_appetite]
    filtered_funds = performance_data[
        performance_data['risk_grade'].isin(target_risk_grades)
    ].copy()
    
    # Sort by Sharpe ratio (descending - highest returns per unit risk first)
    filtered_funds = filtered_funds.sort_values('sharpe_ratio', ascending=False)
    
    # Handle case where sharpe_ratio might contain NaN
    filtered_funds = filtered_funds.dropna(subset=['sharpe_ratio'])
    
    if len(filtered_funds) == 0:
        raise ValueError(
            f"No funds found with risk_grade in {target_risk_grades}. "
            f"Available risk grades: {performance_data['risk_grade'].unique()}"
        )
    
    # Select top N recommendations
    recommended = filtered_funds.head(num_recommendations)[[
        'amfi_code',
        'scheme_name',
        'fund_house',
        'category',
        'risk_grade',
        'sharpe_ratio',
        'return_1yr_pct',
        'std_dev_ann_pct',
        'expense_ratio_pct',
        'aum_crore'
    ]].copy()
    
    # Reset index and add rank column
    recommended = recommended.reset_index(drop=True)
    recommended.insert(0, 'rank', range(1, len(recommended) + 1))
    
    return recommended


def print_recommendations(risk_appetite, num_recommendations=3):
    """
    Print formatted fund recommendations for a given risk appetite.
    
    Parameters:
    -----------
    risk_appetite : str
        One of 'Low', 'Moderate', 'High'
    num_recommendations : int
        Number of funds to recommend
    
    Returns:
    --------
    None (prints to console)
    """
    try:
        recommendations = fund_recommender(risk_appetite, num_recommendations)
        
        print(f"\n{'='*120}")
        print(f"FUND RECOMMENDATIONS - Risk Appetite: {risk_appetite.upper()}")
        print(f"{'='*120}\n")
        
        for idx, row in recommendations.iterrows():
            print(f"Rank #{row['rank']}: {row['scheme_name']}")
            print(f"  Fund House: {row['fund_house']} | Category: {row['category']}")
            print(f"  Sharpe Ratio: {row['sharpe_ratio']:.2f} | 1Y Return: {row['return_1yr_pct']:.2f}%")
            print(f"  Annual Volatility: {row['std_dev_ann_pct']:.2f}% | Expense Ratio: {row['expense_ratio_pct']:.2f}%")
            print(f"  AUM: ₹{row['aum_crore']:,.0f} Cr | Risk Grade: {row['risk_grade']}")
            print()
        
        print(f"{'='*120}\n")
        
    except (FileNotFoundError, ValueError) as e:
        print(f"Error: {e}")


if __name__ == '__main__':
    """
    Example usage - run this file directly to see recommendations for all risk appetites
    """
    print("\n📊 MUTUAL FUND RECOMMENDER SYSTEM\n")
    
    for risk in ['Low', 'Moderate', 'High']:
        try:
            print_recommendations(risk, num_recommendations=3)
        except Exception as e:
            print(f"Error for {risk} risk appetite: {e}\n")
