import json
import re
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
PROCESSED_DIR = ROOT / "data" / "processed"
REPORTS_DIR = ROOT / "reports"

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


def explore_fund_master(fund_master: pd.DataFrame, nav_history: pd.DataFrame | None = None):
    print("\n=== Fund Master Exploration ===")
    print("columns:", list(fund_master.columns))

    for field in ["Fund House", "AMC", "Scheme Category", "Category", "Sub Category", "Sub-Category", "Risk Grade", "Risk"]:
        if field in fund_master.columns:
            if fund_master[field].nunique() < 1000:
                print(f"unique {field}:", sorted(fund_master[field].dropna().unique())[:20])
            else:
                print(f"unique {field} count:", fund_master[field].nunique())

    code_columns = [c for c in fund_master.columns if re.search(r"amfi|scheme|code", c, re.I)]
    print("AMFI-related columns:", code_columns)

    if code_columns:
        amfi_col = code_columns[0]
        codes = fund_master[amfi_col].astype(str).str.strip()
        print("AMFI code sample:", codes.head(10).tolist())
        print("code lengths:", sorted(codes.str.len().value_counts().to_dict().items()))
        print("digits only:", codes.str.match(r"^\d+$").all())

        if nav_history is not None and not nav_history.empty:
            nav_codes = set(nav_history.columns) if "scheme_code" in nav_history.columns else set()
            if "scheme_code" not in nav_history.columns:
                nav_codes = set(nav_history[amfi_col].astype(str).str.strip()) if amfi_col in nav_history.columns else set()
            missing = set(codes.unique()) - nav_codes
            print(f"AMFI codes present in fund_master: {len(codes.unique())}")
            print(f"AMFI codes present in nav_history: {len(nav_codes)}")
            print(f"missing AMFI codes in nav_history: {len(missing)}")
            if missing:
                print("example missing codes:", list(missing)[:20])

    return amfi_col if code_columns else None


def validate_amfi_codes(fund_master: pd.DataFrame, nav_history: pd.DataFrame):
    code_columns = [c for c in fund_master.columns if re.search(r"amfi|scheme|code", c, re.I)]
    if not code_columns:
        print("No AMFI code column found in fund_master")
        return

    amfi_col = code_columns[0]
    fm_codes = set(fund_master[amfi_col].astype(str).str.strip())

    possible_nav_code_cols = [c for c in nav_history.columns if re.search(r"amfi|scheme|code", c, re.I)]
    if possible_nav_code_cols:
        nav_col = possible_nav_code_cols[0]
        nh_codes = set(nav_history[nav_col].astype(str).str.strip())
    elif "scheme_code" in nav_history.columns:
        nav_col = "scheme_code"
        nh_codes = set(nav_history[nav_col].astype(str).str.strip())
    else:
        print("Unable to find AMFI code column inside nav_history")
        return

    missing = sorted(fm_codes - nh_codes)
    print(f"Validated AMFI codes: {len(fm_codes)} codes in fund_master, {len(nh_codes)} codes in nav_history")
    if missing:
        print(f"Missing codes in nav_history: {len(missing)}; first examples: {missing[:20]}")
    else:
        print("All AMFI codes in fund_master exist in nav_history.")

    return missing


def main():
    print("Project root:", ROOT)
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    csv_files = find_csv_files()
    if not csv_files:
        print("No CSV files found in data/raw. Place your CSV datasets under data/raw/ and rerun.")
    else:
        dataframes = {}
        for path in csv_files:
            df = describe_csv_file(path)
            if df is not None:
                dataframes[path.stem] = df

        if "fund_master" in dataframes and "nav_history" in dataframes:
            validate_amfi_codes(dataframes["fund_master"], dataframes["nav_history"])
        elif "fund_master" in dataframes:
            print("fund_master found, but nav_history not found for AMFI validation.")

    print("\n=== Fetching live NAVs and saving raw CSV output ===")
    for scheme_name, scheme_code in NAV_SCHEMES.items():
        try:
            df_nav = fetch_mfapi_nav(scheme_name, scheme_code)
            print(f"Latest record for {scheme_name}: {df_nav.iloc[0].to_dict() if not df_nav.empty else 'empty'}")
        except Exception as exc:
            print(f"Failed to fetch {scheme_name} ({scheme_code}): {exc}")

    summary_path = REPORTS_DIR / "data_quality_summary.txt"
    with summary_path.open("w", encoding="utf-8") as report:
        report.write("Data quality summary\n")
        report.write("====================\n")
        report.write("If fund_master or nav_history are present in data/raw, the script validates AMFI code consistency.\n")
        report.write("If CSV files are missing, copy them into data/raw before rerunning.\n")
    print(f"Wrote summary placeholder to {summary_path}")


if __name__ == "__main__":
    main()
