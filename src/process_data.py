import json
import re
from pathlib import Path
from datetime import datetime, timedelta

import pandas as pd
import numpy as np
import requests
from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
PROCESSED_DIR = ROOT / "data" / "processed"
REPORTS_DIR = ROOT / "reports"
SQL_DIR = ROOT / "sql"

NAV_SCHEMES = {
    "HDFC Top 100 Direct": "125497",
    "SBI Bluechip": "119551",
    "ICICI Bluechip": "120503",
    "Nippon Large Cap": "118632",
    "Axis Bluechip": "119092",
    "Kotak Bluechip": "120841",
}

EXPECTED_FILES = []


def find_csv_files():
    return sorted(RAW_DIR.glob("*.csv"))


def describe_csv_file(path: Path):
    print(f"\n=== {path.name} ===")
    try:
        df = pd.read_csv(path)
    except Exception as exc:
        print(f"Unable to read {path.name}: {exc}")
        return None

    print("shape:", df.shape)
    print("dtypes:")
    print(df.dtypes)
    print("head:")
    print(df.head(5).to_string(index=False))

    issues = []
    if df.empty:
        issues.append("empty dataframe")

    null_counts = df.isna().sum()
    null_cols = null_counts[null_counts > 0]
    if not null_cols.empty:
        issues.append(f"columns with nulls: {dict(null_cols)}")

    duplicates = df.duplicated().sum()
    if duplicates > 0:
        issues.append(f"duplicate rows: {duplicates}")

    numeric_cols = df.select_dtypes(include=["number"]).columns.tolist()
    if numeric_cols:
        inf_counts = (df[numeric_cols].isin([pd.NA, float("inf"), float("-inf")])).sum()
        inf_cols = inf_counts[inf_counts > 0]
        if not inf_cols.empty:
            issues.append(f"infinite values in: {dict(inf_cols)}")

    if issues:
        print("anomalies:")
        for issue in issues:
            print(" -", issue)
    else:
        print("anomalies: none obvious")

    return df


def clean_nav_history(df: pd.DataFrame) -> pd.DataFrame:
    """Clean nav_history.csv with datetime parsing, sorting, deduplication, and validation."""
    print("\n--- Cleaning nav_history ---")
    df = df.copy()
    
    # Parse dates to datetime
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    print(f"Parsed dates; invalid dates: {df['date'].isna().sum()}")
    
    # Remove rows with invalid dates
    df = df.dropna(subset=["date"])
    
    # Convert NAV to numeric
    if df["nav"].dtype == "object":
        df["nav"] = pd.to_numeric(df["nav"].astype(str).str.replace(",", "", regex=False), errors="coerce")
    
    # Forward fill missing NAV values for holidays/weekends
    df = df.sort_values(["amfi_code", "date"]).reset_index(drop=True)
    # Use transform to forward-fill within each amfi_code group (compatible across pandas versions)
    df["nav"] = df.groupby("amfi_code")["nav"].transform(lambda s: s.ffill())
    print(f"Forward-filled missing NAV; remaining NaN: {df['nav'].isna().sum()}")
    
    # Remove duplicates (keep first)
    initial_rows = len(df)
    df = df.drop_duplicates(subset=["amfi_code", "date"], keep="first")
    print(f"Removed {initial_rows - len(df)} duplicates")
    
    # Validate NAV > 0
    invalid_nav = df[df["nav"] <= 0]
    if len(invalid_nav) > 0:
        print(f"Found {len(invalid_nav)} rows with NAV <= 0; removing")
        df = df[df["nav"] > 0]
    
    # Sort by amfi_code and date
    df = df.sort_values(["amfi_code", "date"]).reset_index(drop=True)
    
    print(f"Final nav_history shape: {df.shape}")
    return df


def clean_investor_transactions(df: pd.DataFrame) -> pd.DataFrame:
    """Clean investor_transactions.csv with standardization, validation."""
    print("\n--- Cleaning investor_transactions ---")
    df = df.copy()
    
    # Standardize transaction_type
    valid_types = {"SIP", "Lumpsum", "Redemption"}
    df["transaction_type"] = df["transaction_type"].str.strip().str.title()
    invalid_types = df[~df["transaction_type"].isin(valid_types)]
    if len(invalid_types) > 0:
        print(f"Found {len(invalid_types)} invalid transaction_type values; removing")
        df = df[df["transaction_type"].isin(valid_types)]
    
    # Validate amount > 0
    initial_rows = len(df)
    df = df[df["amount_inr"] > 0]
    print(f"Removed {initial_rows - len(df)} rows with amount <= 0")
    
    # Fix date formats
    df["transaction_date"] = pd.to_datetime(df["transaction_date"], errors="coerce")
    print(f"Parsed transaction_date; invalid dates: {df['transaction_date'].isna().sum()}")
    df = df.dropna(subset=["transaction_date"])
    
    # Check KYC status enum values
    valid_kyc = {"Verified", "Pending", "Rejected"}
    df["kyc_status"] = df["kyc_status"].str.strip()
    invalid_kyc = df[~df["kyc_status"].isin(valid_kyc)]
    if len(invalid_kyc) > 0:
        print(f"Found {len(invalid_kyc)} invalid kyc_status values; setting to 'Pending'")
        df.loc[~df["kyc_status"].isin(valid_kyc), "kyc_status"] = "Pending"
    
    print(f"Final investor_transactions shape: {df.shape}")
    return df


def clean_scheme_performance(df: pd.DataFrame) -> pd.DataFrame:
    """Clean scheme_performance.csv with numeric validation and anomaly flagging."""
    print("\n--- Cleaning scheme_performance ---")
    df = df.copy()
    
    # Validate all return values are numeric
    return_cols = ["return_1yr_pct", "return_3yr_pct", "return_5yr_pct"]
    for col in return_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    
    # Flag anomalies
    anomalies = []
    for col in return_cols:
        if col in df.columns:
            if df[col].isna().any():
                anomalies.append(f"  - {col}: {df[col].isna().sum()} NaN values")
            # Flag extreme returns (> 100% or < -100% as anomalies)
            extreme = df[(df[col] > 100) | (df[col] < -100)]
            if len(extreme) > 0:
                anomalies.append(f"  - {col}: {len(extreme)} extreme values (>100% or <-100%)")
    
    if anomalies:
        print("Anomalies detected:")
        for anom in anomalies:
            print(anom)
    
    # Check expense_ratio range (0.1% – 2.5%)
    if "expense_ratio_pct" in df.columns:
        df["expense_ratio_pct"] = pd.to_numeric(df["expense_ratio_pct"], errors="coerce")
        out_of_range = df[(df["expense_ratio_pct"] < 0.1) | (df["expense_ratio_pct"] > 2.5)]
        if len(out_of_range) > 0:
            print(f"Found {len(out_of_range)} expense ratios outside 0.1%-2.5% range")
            print(f"  - Min: {df['expense_ratio_pct'].min()}, Max: {df['expense_ratio_pct'].max()}")
    
    print(f"Final scheme_performance shape: {df.shape}")
    return df


def get_sqlite_schema() -> str:
    """Return SQLite CREATE TABLE statements for star schema."""
    schema = """
-- Dimension Tables
CREATE TABLE IF NOT EXISTS dim_fund (
    fund_id INTEGER PRIMARY KEY AUTOINCREMENT,
    amfi_code TEXT UNIQUE NOT NULL,
    scheme_name TEXT NOT NULL,
    fund_house TEXT NOT NULL,
    category TEXT,
    sub_category TEXT,
    plan TEXT,
    launch_date DATE,
    benchmark TEXT,
    risk_category TEXT,
    fund_manager TEXT,
    min_sip_amount REAL,
    min_lumpsum_amount REAL,
    exit_load_pct REAL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS dim_date (
    date_id INTEGER PRIMARY KEY AUTOINCREMENT,
    date DATE UNIQUE NOT NULL,
    year INTEGER,
    month INTEGER,
    day INTEGER,
    quarter INTEGER,
    week_of_year INTEGER,
    day_of_week TEXT,
    is_weekend BOOLEAN
);

CREATE TABLE IF NOT EXISTS dim_investor (
    investor_id INTEGER PRIMARY KEY AUTOINCREMENT,
    investor_code TEXT UNIQUE NOT NULL,
    state TEXT,
    city TEXT,
    city_tier TEXT,
    age_group TEXT,
    gender TEXT,
    annual_income_lakh REAL,
    kyc_status TEXT
);

CREATE TABLE IF NOT EXISTS dim_location (
    location_id INTEGER PRIMARY KEY AUTOINCREMENT,
    state TEXT UNIQUE NOT NULL,
    region TEXT
);

-- Fact Tables
CREATE TABLE IF NOT EXISTS fact_nav (
    nav_id INTEGER PRIMARY KEY AUTOINCREMENT,
    fund_id INTEGER NOT NULL,
    date_id INTEGER NOT NULL,
    nav REAL NOT NULL CHECK(nav > 0),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (fund_id) REFERENCES dim_fund(fund_id),
    FOREIGN KEY (date_id) REFERENCES dim_date(date_id)
);

CREATE TABLE IF NOT EXISTS fact_transactions (
    transaction_id INTEGER PRIMARY KEY AUTOINCREMENT,
    investor_id INTEGER NOT NULL,
    fund_id INTEGER NOT NULL,
    date_id INTEGER NOT NULL,
    transaction_type TEXT NOT NULL,
    amount_inr REAL NOT NULL CHECK(amount_inr > 0),
    payment_mode TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (investor_id) REFERENCES dim_investor(investor_id),
    FOREIGN KEY (fund_id) REFERENCES dim_fund(fund_id),
    FOREIGN KEY (date_id) REFERENCES dim_date(date_id)
);

CREATE TABLE IF NOT EXISTS fact_performance (
    performance_id INTEGER PRIMARY KEY AUTOINCREMENT,
    fund_id INTEGER NOT NULL,
    return_1yr_pct REAL,
    return_3yr_pct REAL,
    return_5yr_pct REAL,
    benchmark_3yr_pct REAL,
    alpha REAL,
    beta REAL,
    sharpe_ratio REAL,
    sortino_ratio REAL,
    std_dev_ann_pct REAL,
    max_drawdown_pct REAL,
    aum_crore REAL,
    expense_ratio_pct REAL,
    morningstar_rating INTEGER,
    risk_grade TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (fund_id) REFERENCES dim_fund(fund_id)
);

CREATE TABLE IF NOT EXISTS fact_aum (
    aum_id INTEGER PRIMARY KEY AUTOINCREMENT,
    fund_house TEXT NOT NULL,
    date_id INTEGER NOT NULL,
    aum_crore REAL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (date_id) REFERENCES dim_date(date_id)
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_fact_nav_fund_date ON fact_nav(fund_id, date_id);
CREATE INDEX IF NOT EXISTS idx_fact_transactions_investor ON fact_transactions(investor_id);
CREATE INDEX IF NOT EXISTS idx_fact_transactions_fund_date ON fact_transactions(fund_id, date_id);
CREATE INDEX IF NOT EXISTS idx_dim_date_date ON dim_date(date);
"""
    return schema


def load_to_sqlite(db_path: str, dfs_dict: dict) -> dict:
    """Load cleaned DataFrames into SQLite database with proper mapping."""
    print(f"\n--- Loading data into SQLite: {db_path} ---")
    # If a previous DB exists, remove it to ensure idempotent runs
    db_file = Path(db_path)
    if db_file.exists():
        try:
            db_file.unlink()
            print(f"Removed existing database file: {db_path}")
        except Exception as exc:
            print(f"Warning: unable to remove existing DB file: {exc}")

    engine = create_engine(f"sqlite:///{db_path}")
    
    # Create schema - execute each statement separately
    schema_statements = [
        """CREATE TABLE IF NOT EXISTS dim_fund (
            fund_id INTEGER PRIMARY KEY AUTOINCREMENT,
            amfi_code TEXT UNIQUE NOT NULL,
            scheme_name TEXT NOT NULL,
            fund_house TEXT NOT NULL,
            category TEXT,
            sub_category TEXT,
            plan TEXT,
            launch_date DATE,
            benchmark TEXT,
            risk_category TEXT,
            fund_manager TEXT,
            min_sip_amount REAL,
            min_lumpsum_amount REAL,
            exit_load_pct REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""",
        
        """CREATE TABLE IF NOT EXISTS dim_date (
            date_id INTEGER PRIMARY KEY AUTOINCREMENT,
            date DATE UNIQUE NOT NULL,
            year INTEGER,
            month INTEGER,
            day INTEGER,
            quarter INTEGER,
            week_of_year INTEGER,
            day_of_week TEXT,
            is_weekend BOOLEAN
        )""",
        
        """CREATE TABLE IF NOT EXISTS dim_investor (
            investor_id INTEGER PRIMARY KEY AUTOINCREMENT,
            investor_code TEXT UNIQUE NOT NULL,
            state TEXT,
            city TEXT,
            city_tier TEXT,
            age_group TEXT,
            gender TEXT,
            annual_income_lakh REAL,
            kyc_status TEXT
        )""",
        
        """CREATE TABLE IF NOT EXISTS dim_location (
            location_id INTEGER PRIMARY KEY AUTOINCREMENT,
            state TEXT UNIQUE NOT NULL,
            region TEXT
        )""",
        
        """CREATE TABLE IF NOT EXISTS fact_nav (
            nav_id INTEGER PRIMARY KEY AUTOINCREMENT,
            fund_id INTEGER NOT NULL,
            date_id INTEGER NOT NULL,
            nav REAL NOT NULL CHECK(nav > 0),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (fund_id) REFERENCES dim_fund(fund_id),
            FOREIGN KEY (date_id) REFERENCES dim_date(date_id)
        )""",
        
        """CREATE TABLE IF NOT EXISTS fact_transactions (
            transaction_id INTEGER PRIMARY KEY AUTOINCREMENT,
            investor_id INTEGER NOT NULL,
            fund_id INTEGER NOT NULL,
            date_id INTEGER NOT NULL,
            transaction_type TEXT NOT NULL,
            amount_inr REAL NOT NULL CHECK(amount_inr > 0),
            payment_mode TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (investor_id) REFERENCES dim_investor(investor_id),
            FOREIGN KEY (fund_id) REFERENCES dim_fund(fund_id),
            FOREIGN KEY (date_id) REFERENCES dim_date(date_id)
        )""",
        
        """CREATE TABLE IF NOT EXISTS fact_performance (
            performance_id INTEGER PRIMARY KEY AUTOINCREMENT,
            fund_id INTEGER NOT NULL,
            return_1yr_pct REAL,
            return_3yr_pct REAL,
            return_5yr_pct REAL,
            benchmark_3yr_pct REAL,
            alpha REAL,
            beta REAL,
            sharpe_ratio REAL,
            sortino_ratio REAL,
            std_dev_ann_pct REAL,
            max_drawdown_pct REAL,
            aum_crore REAL,
            expense_ratio_pct REAL,
            morningstar_rating INTEGER,
            risk_grade TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (fund_id) REFERENCES dim_fund(fund_id)
        )""",
        
        """CREATE TABLE IF NOT EXISTS fact_aum (
            aum_id INTEGER PRIMARY KEY AUTOINCREMENT,
            fund_house TEXT NOT NULL,
            date_id INTEGER NOT NULL,
            aum_crore REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (date_id) REFERENCES dim_date(date_id)
        )""",
        
        """CREATE INDEX IF NOT EXISTS idx_fact_nav_fund_date ON fact_nav(fund_id, date_id)""",
        """CREATE INDEX IF NOT EXISTS idx_fact_transactions_investor ON fact_transactions(investor_id)""",
        """CREATE INDEX IF NOT EXISTS idx_fact_transactions_fund_date ON fact_transactions(fund_id, date_id)""",
        """CREATE INDEX IF NOT EXISTS idx_dim_date_date ON dim_date(date)""",
    ]
    
    with engine.begin() as conn:
        for stmt in schema_statements:
            conn.execute(text(stmt))
    
    print("Created database schema")
    
    row_counts = {}
    
    # Load dim_fund from fund_master
    if "fund_master" in dfs_dict and dfs_dict["fund_master"] is not None:
        df_fund = dfs_dict["fund_master"].copy()
        df_fund["amfi_code"] = df_fund["amfi_code"].astype(str)
        df_fund_mapped = pd.DataFrame({
            "amfi_code": df_fund["amfi_code"],
            "scheme_name": df_fund["scheme_name"],
            "fund_house": df_fund["fund_house"],
            "category": df_fund["category"],
            "sub_category": df_fund["sub_category"],
            "plan": df_fund["plan"],
            "launch_date": pd.to_datetime(df_fund["launch_date"], errors="coerce"),
            "benchmark": df_fund["benchmark"],
            "risk_category": df_fund["risk_category"],
            "fund_manager": df_fund["fund_manager"],
            "min_sip_amount": df_fund["min_sip_amount"],
            "min_lumpsum_amount": df_fund["min_lumpsum_amount"],
            "exit_load_pct": df_fund["exit_load_pct"],
        })
        df_fund_mapped.to_sql("dim_fund", engine, if_exists="append", index=False)
        row_counts["dim_fund"] = len(df_fund_mapped)
        print(f"Loaded {len(df_fund_mapped)} rows into dim_fund")
    
    # Load dim_date
    all_dates = set()
    if "nav_history" in dfs_dict and dfs_dict["nav_history"] is not None:
        all_dates.update(dfs_dict["nav_history"]["date"].unique())
    if "investor_transactions" in dfs_dict and dfs_dict["investor_transactions"] is not None:
        all_dates.update(dfs_dict["investor_transactions"]["transaction_date"].unique())
    
    if all_dates:
        dates_list = sorted([pd.Timestamp(d) for d in all_dates])
        dim_date_records = []
        for d in dates_list:
            dim_date_records.append({
                "date": d.date(),
                "year": d.year,
                "month": d.month,
                "day": d.day,
                "quarter": (d.month - 1) // 3 + 1,
                "week_of_year": d.isocalendar()[1],
                "day_of_week": d.day_name(),
                "is_weekend": d.dayofweek >= 5,
            })
        df_dates = pd.DataFrame(dim_date_records)
        df_dates.to_sql("dim_date", engine, if_exists="append", index=False)
        row_counts["dim_date"] = len(df_dates)
        print(f"Loaded {len(df_dates)} rows into dim_date")
    
    # Load fact_nav
    if "nav_history" in dfs_dict and dfs_dict["nav_history"] is not None:
        df_nav = dfs_dict["nav_history"].copy()
        df_nav["amfi_code"] = df_nav["amfi_code"].astype(str)
        # Get fund_id mapping
        df_fund_map = pd.read_sql("SELECT fund_id, amfi_code FROM dim_fund", engine)
        df_fund_map["amfi_code"] = df_fund_map["amfi_code"].astype(str)
        df_nav = df_nav.merge(df_fund_map, left_on="amfi_code", right_on="amfi_code", how="left")
        
        # Get date_id mapping
        df_date_map = pd.read_sql("SELECT date_id, date FROM dim_date", engine)
        df_date_map["date"] = pd.to_datetime(df_date_map["date"]).dt.date
        df_nav["date_only"] = df_nav["date"].dt.date
        df_nav = df_nav.merge(df_date_map, left_on="date_only", right_on="date", how="left")
        
        fact_nav = df_nav[["fund_id", "date_id", "nav"]].dropna(subset=["fund_id", "date_id"])
        fact_nav.to_sql("fact_nav", engine, if_exists="append", index=False)
        row_counts["fact_nav"] = len(fact_nav)
        print(f"Loaded {len(fact_nav)} rows into fact_nav")
    
    # Load dim_investor and fact_transactions
    if "investor_transactions" in dfs_dict and dfs_dict["investor_transactions"] is not None:
        df_trans = dfs_dict["investor_transactions"].copy()
        df_trans["amfi_code"] = df_trans["amfi_code"].astype(str)
        
        # Create dim_investor
        investors = df_trans[["investor_id", "state", "city", "city_tier", "age_group", "gender", "annual_income_lakh", "kyc_status"]].drop_duplicates(subset=["investor_id"])
        investors_mapped = pd.DataFrame({
            "investor_code": investors["investor_id"].astype(str),
            "state": investors["state"],
            "city": investors["city"],
            "city_tier": investors["city_tier"],
            "age_group": investors["age_group"],
            "gender": investors["gender"],
            "annual_income_lakh": investors["annual_income_lakh"],
            "kyc_status": investors["kyc_status"],
        })
        investors_mapped.to_sql("dim_investor", engine, if_exists="append", index=False)
        row_counts["dim_investor"] = len(investors_mapped)
        print(f"Loaded {len(investors_mapped)} rows into dim_investor")
        
        # Map investor_id to investor_id from dim_investor
        df_investor_map = pd.read_sql("SELECT investor_id, investor_code FROM dim_investor", engine)
        df_investor_map["investor_code"] = df_investor_map["investor_code"].astype(str)
        df_trans["investor_code"] = df_trans["investor_id"].astype(str)
        df_trans = df_trans.merge(df_investor_map, left_on="investor_code", right_on="investor_code", how="left", suffixes=("", "_db"))
        
        # Map fund_id
        df_fund_map = pd.read_sql("SELECT fund_id, amfi_code FROM dim_fund", engine)
        df_fund_map["amfi_code"] = df_fund_map["amfi_code"].astype(str)
        df_trans = df_trans.merge(df_fund_map, left_on="amfi_code", right_on="amfi_code", how="left")
        
        # Map date_id
        df_date_map = pd.read_sql("SELECT date_id, date FROM dim_date", engine)
        df_date_map["date"] = pd.to_datetime(df_date_map["date"]).dt.date
        df_trans["transaction_date_only"] = df_trans["transaction_date"].dt.date
        df_trans = df_trans.merge(df_date_map, left_on="transaction_date_only", right_on="date", how="left")
        
        # Select and prepare fact_transactions
        fact_transactions = df_trans[[col for col in ["investor_id_db", "fund_id", "date_id", "transaction_type", "amount_inr", "payment_mode"] if col in df_trans.columns]].copy()
        fact_transactions.columns = ["investor_id" if col == "investor_id_db" else col for col in fact_transactions.columns]
        fact_transactions = fact_transactions.dropna(subset=["investor_id", "fund_id", "date_id"])
        
        # Cast to proper types
        fact_transactions["investor_id"] = fact_transactions["investor_id"].astype(int)
        fact_transactions["fund_id"] = fact_transactions["fund_id"].astype(int)
        fact_transactions["date_id"] = fact_transactions["date_id"].astype(int)
        fact_transactions.to_sql("fact_transactions", engine, if_exists="append", index=False)
        row_counts["fact_transactions"] = len(fact_transactions)
        print(f"Loaded {len(fact_transactions)} rows into fact_transactions")
    
    # Load fact_performance
    if "scheme_performance" in dfs_dict and dfs_dict["scheme_performance"] is not None:
        df_perf = dfs_dict["scheme_performance"].copy()
        df_perf["amfi_code"] = df_perf["amfi_code"].astype(str)
        df_fund_map = pd.read_sql("SELECT fund_id, amfi_code FROM dim_fund", engine)
        df_fund_map["amfi_code"] = df_fund_map["amfi_code"].astype(str)
        df_perf = df_perf.merge(df_fund_map, left_on="amfi_code", right_on="amfi_code", how="left")
        
        fact_performance = pd.DataFrame({
            "fund_id": df_perf["fund_id"].astype(int),
            "return_1yr_pct": pd.to_numeric(df_perf.get("return_1yr_pct", []), errors="coerce"),
            "return_3yr_pct": pd.to_numeric(df_perf.get("return_3yr_pct", []), errors="coerce"),
            "return_5yr_pct": pd.to_numeric(df_perf.get("return_5yr_pct", []), errors="coerce"),
            "benchmark_3yr_pct": pd.to_numeric(df_perf.get("benchmark_3yr_pct", []), errors="coerce"),
            "alpha": pd.to_numeric(df_perf.get("alpha", []), errors="coerce"),
            "beta": pd.to_numeric(df_perf.get("beta", []), errors="coerce"),
            "sharpe_ratio": pd.to_numeric(df_perf.get("sharpe_ratio", []), errors="coerce"),
            "sortino_ratio": pd.to_numeric(df_perf.get("sortino_ratio", []), errors="coerce"),
            "std_dev_ann_pct": pd.to_numeric(df_perf.get("std_dev_ann_pct", []), errors="coerce"),
            "max_drawdown_pct": pd.to_numeric(df_perf.get("max_drawdown_pct", []), errors="coerce"),
            "aum_crore": pd.to_numeric(df_perf.get("aum_crore", []), errors="coerce"),
            "expense_ratio_pct": pd.to_numeric(df_perf.get("expense_ratio_pct", []), errors="coerce"),
            "morningstar_rating": pd.to_numeric(df_perf.get("morningstar_rating", []), errors="coerce"),
            "risk_grade": df_perf.get("risk_grade", []),
        }).dropna(subset=["fund_id"])
        
        fact_performance.to_sql("fact_performance", engine, if_exists="append", index=False)
        row_counts["fact_performance"] = len(fact_performance)
        print(f"Loaded {len(fact_performance)} rows into fact_performance")
    
    print(f"\nLoaded row counts:\n{json.dumps(row_counts, indent=2)}")
    return row_counts


def get_analytical_queries() -> dict:
    """Return 10 analytical SQL queries."""
    queries = {
        "1_top_5_funds_by_aum": """
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
        """,
        
        "2_average_nav_per_month": """
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
        """,
        
        "3_sip_yoy_growth": """
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
        """,
        
        "4_transactions_by_state": """
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
        """,
        
        "5_funds_with_low_expense_ratio": """
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
        """,
        
        "6_lumpsum_vs_sip_analysis": """
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
        """,
        
        "7_investor_kyc_status_breakdown": """
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
        """,
        
        "8_fund_performance_ranking": """
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
        """,
        
        "9_highest_investors_per_fund": """
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
        """,
        
        "10_monthly_nav_trend": """
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
        """
    }
    return queries


def fetch_mfapi_nav(scheme_name: str, scheme_code: str):
    url = f"https://api.mfapi.in/mf/{scheme_code}"
    print(f"Fetching NAV data for {scheme_name} ({scheme_code})...")
    response = requests.get(url, timeout=20)
    response.raise_for_status()
    payload = response.json()

    if "data" not in payload or not isinstance(payload["data"], list):
        raise ValueError("Unexpected response payload from mfapi.in")

    df = pd.DataFrame(payload["data"])
    if "date" in df.columns and "nav" in df.columns:
        df = df.copy()
        df["nav"] = pd.to_numeric(df["nav"].str.replace(",", "", regex=False), errors="coerce")
    out_path = RAW_DIR / f"nav_history_{scheme_code}.csv"
    df.to_csv(out_path, index=False)
    print(f"Saved raw NAV CSV to {out_path}")
    return df


def main():
    print("Project root:", ROOT)
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    SQL_DIR.mkdir(parents=True, exist_ok=True)

    # Read and clean all CSV files
    print("\n=== READING RAW FILES ===")
    cleaned_dfs = {}
    all_nav_data = []
    
    for path in find_csv_files():
        print(f"\nReading {path.name}...")
        df = pd.read_csv(path)
        print(f"  Shape: {df.shape}")
        
        if path.name == "02_nav_history.csv":
            cleaned_dfs["nav_history"] = clean_nav_history(df)
            cleaned_dfs["nav_history"].to_csv(PROCESSED_DIR / "02_nav_history_clean.csv", index=False)
            print(f"  Saved to {PROCESSED_DIR / '02_nav_history_clean.csv'}")
        
        elif path.name.startswith("nav_history_") and path.name.endswith(".csv"):
            # Extract amfi_code from filename
            amfi_code = path.name.replace("nav_history_", "").replace(".csv", "")
            df["amfi_code"] = amfi_code
            all_nav_data.append(df)
            print(f"  Extracted amfi_code: {amfi_code}")
        
        elif path.name == "08_investor_transactions.csv":
            cleaned_dfs["investor_transactions"] = clean_investor_transactions(df)
            cleaned_dfs["investor_transactions"].to_csv(PROCESSED_DIR / "08_investor_transactions_clean.csv", index=False)
            print(f"  Saved to {PROCESSED_DIR / '08_investor_transactions_clean.csv'}")
        
        elif path.name == "07_scheme_performance.csv":
            cleaned_dfs["scheme_performance"] = clean_scheme_performance(df)
            cleaned_dfs["scheme_performance"].to_csv(PROCESSED_DIR / "07_scheme_performance_clean.csv", index=False)
            print(f"  Saved to {PROCESSED_DIR / '07_scheme_performance_clean.csv'}")
        
        elif path.name == "01_fund_master.csv":
            cleaned_dfs["fund_master"] = df
            cleaned_dfs["fund_master"].to_csv(PROCESSED_DIR / "01_fund_master_clean.csv", index=False)
            print(f"  Saved to {PROCESSED_DIR / '01_fund_master_clean.csv'}")
        
        else:
            # Copy other CSVs as-is
            output_path = PROCESSED_DIR / path.name
            df.to_csv(output_path, index=False)
            print(f"  Copied to {output_path}")
    
    # Combine all nav_history data
    if all_nav_data:
        if "nav_history" in cleaned_dfs:
            all_nav_data.append(cleaned_dfs["nav_history"])
        combined_nav = pd.concat(all_nav_data, ignore_index=True)
        cleaned_dfs["nav_history"] = clean_nav_history(combined_nav)
        print(f"\nCombined nav_history shape: {cleaned_dfs['nav_history'].shape}")
        cleaned_dfs["nav_history"].to_csv(PROCESSED_DIR / "02_nav_history_clean.csv", index=False)
        print(f"Saved combined nav_history to {PROCESSED_DIR / '02_nav_history_clean.csv'}")
    
    # Load to SQLite
    print("\n=== CREATING SQLITE DATABASE ===")
    db_path = ROOT / "bluestock_mf.db"
    row_counts = load_to_sqlite(str(db_path), cleaned_dfs)
    print(f"Database created: {db_path}")
    
    # Verify row counts
    print("\n=== VERIFYING ROW COUNTS ===")
    engine = create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        for table in ["dim_fund", "dim_date", "fact_nav", "dim_investor", "fact_transactions", "fact_performance"]:
            result = conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()
            print(f"  {table}: {result} rows")
    
    # Write schema.sql
    schema_path = SQL_DIR / "schema.sql"
    with schema_path.open("w") as f:
        f.write(get_sqlite_schema())
    print(f"\nWrote schema to {schema_path}")
    
    # Write queries.sql
    queries_path = SQL_DIR / "queries.sql"
    with queries_path.open("w") as f:
        queries = get_analytical_queries()
        for name, query in queries.items():
            f.write(f"\n-- Query: {name}\n")
            f.write(f"{query.strip()}\n")
            f.write("\n" + "="*80 + "\n")
    print(f"Wrote queries to {queries_path}")
    
    # Write data_dictionary.md
    data_dict_path = ROOT / "data_dictionary.md"
    with data_dict_path.open("w") as f:
        f.write("# Data Dictionary\n\n")
        f.write("## Database: bluestock_mf.db\n\n")
        
        f.write("### Dimension Tables\n\n")
        
        f.write("#### dim_fund\n")
        f.write("Fund master dimension with scheme details\n")
        f.write("- fund_id: Primary key\n")
        f.write("- amfi_code: AMFI scheme code (unique)\n")
        f.write("- scheme_name: Name of the mutual fund scheme\n")
        f.write("- fund_house: Fund house/AMC name\n")
        f.write("- category: Fund category (Equity, Debt, etc.)\n")
        f.write("- sub_category: Sub-category (Large Cap, Small Cap, etc.)\n")
        f.write("- plan: Plan type (Regular, Direct)\n")
        f.write("- launch_date: Scheme launch date\n")
        f.write("- benchmark: Benchmark index\n")
        f.write("- risk_category: Risk level (Moderate, High, Very High)\n")
        f.write("- fund_manager: Fund manager name\n")
        f.write("- min_sip_amount: Minimum SIP amount\n")
        f.write("- min_lumpsum_amount: Minimum lumpsum amount\n")
        f.write("- exit_load_pct: Exit load percentage\n\n")
        
        f.write("#### dim_date\n")
        f.write("Date dimension for time-based analysis\n")
        f.write("- date_id: Primary key\n")
        f.write("- date: Calendar date (unique)\n")
        f.write("- year, month, day, quarter, week_of_year: Temporal attributes\n")
        f.write("- day_of_week: Day name\n")
        f.write("- is_weekend: Boolean flag for weekend\n\n")
        
        f.write("#### dim_investor\n")
        f.write("Investor dimension with demographic and KYC details\n")
        f.write("- investor_id: Primary key\n")
        f.write("- investor_code: Unique investor identifier\n")
        f.write("- state, city, city_tier: Geographic attributes\n")
        f.write("- age_group: Age bracket\n")
        f.write("- gender: Gender\n")
        f.write("- annual_income_lakh: Annual income in lakhs\n")
        f.write("- kyc_status: KYC status (Verified, Pending, Rejected)\n\n")
        
        f.write("### Fact Tables\n\n")
        
        f.write("#### fact_nav\n")
        f.write("Net Asset Value history\n")
        f.write("- nav_id: Primary key\n")
        f.write("- fund_id: FK to dim_fund\n")
        f.write("- date_id: FK to dim_date\n")
        f.write("- nav: NAV value (must be > 0)\n\n")
        
        f.write("#### fact_transactions\n")
        f.write("Investor transactions (SIP, Lumpsum, Redemption)\n")
        f.write("- transaction_id: Primary key\n")
        f.write("- investor_id: FK to dim_investor\n")
        f.write("- fund_id: FK to dim_fund\n")
        f.write("- date_id: FK to dim_date\n")
        f.write("- transaction_type: Type of transaction (SIP, Lumpsum, Redemption)\n")
        f.write("- amount_inr: Transaction amount (must be > 0)\n")
        f.write("- payment_mode: Payment method (UPI, Cheque, Mandate)\n\n")
        
        f.write("#### fact_performance\n")
        f.write("Fund performance metrics\n")
        f.write("- performance_id: Primary key\n")
        f.write("- fund_id: FK to dim_fund\n")
        f.write("- return_1yr_pct, return_3yr_pct, return_5yr_pct: Returns over periods\n")
        f.write("- benchmark_3yr_pct: Benchmark return\n")
        f.write("- alpha, beta: Risk metrics\n")
        f.write("- sharpe_ratio, sortino_ratio: Risk-adjusted returns\n")
        f.write("- std_dev_ann_pct: Standard deviation\n")
        f.write("- max_drawdown_pct: Maximum drawdown\n")
        f.write("- aum_crore: Assets Under Management\n")
        f.write("- expense_ratio_pct: Expense ratio (0.1% - 2.5% valid range)\n")
        f.write("- morningstar_rating: Rating (1-5)\n")
        f.write("- risk_grade: Risk assessment\n\n")
        
        f.write("#### fact_aum\n")
        f.write("Assets Under Management by fund house\n")
        f.write("- aum_id: Primary key\n")
        f.write("- fund_house: Fund house name\n")
        f.write("- date_id: FK to dim_date\n")
        f.write("- aum_crore: Total AUM\n\n")
        
        f.write("### Data Quality Notes\n")
        f.write("- NAV values > 0: Enforced via CHECK constraint\n")
        f.write("- Transaction amounts > 0: Enforced via CHECK constraint\n")
        f.write("- Transaction types: Standardized to 'SIP', 'Lumpsum', 'Redemption'\n")
        f.write("- KYC status: 'Verified', 'Pending', 'Rejected'\n")
        f.write("- Expense ratios validated: 0.1% - 2.5% valid range\n")
        f.write("- Dates parsed to ISO format\n")
        f.write("- Duplicates removed from nav_history\n")
        f.write("- Missing NAVs forward-filled\n")
    
    print(f"Wrote data dictionary to {data_dict_path}")
    
    print("\n=== PROCESSING COMPLETE ===")
    print(f"Cleaned CSV files saved to: {PROCESSED_DIR}")
    print(f"Database created: {db_path}")
    print(f"Schema saved to: {schema_path}")
    print(f"Queries saved to: {queries_path}")
    print(f"Data dictionary saved to: {data_dict_path}")


if __name__ == "__main__":
    main()
