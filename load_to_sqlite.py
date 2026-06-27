"""
load_to_postgres_v2.py  —  NPCI Excel files → PostgreSQL
=========================================================
Handles:
  1. Multiple yearly NPCI Product Statistics Excels  (main monthly data)
  2. NPCI Ecosystem Statistics bank-wise downloads   (bank performance)

Folder structure expected:
  data/raw/
    ├── Product-Statistics-UPI-...-2017-18-Monthly.xlsx
    ├── Product-Statistics-UPI-...-2018-19-Monthly.xlsx
    ├── ...  (all yearly files)
    └── bank/
        ├── ecosystem_stats_jan_2026.xlsx  (optional)
        └── ...

Run:
    python load_to_postgres_v2.py
"""

import logging
import re
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text

# ── CONFIG — edit DB_PASSWORD ─────────────────────────────────
DB_HOST     = "localhost"
DB_PORT     = 5432
DB_NAME     = "upi_db"
DB_USER     = "postgres"
DB_PASSWORD = "admin%402128"      # ← change this
RAW_DIR     = Path("data/raw")
BANK_DIR    = RAW_DIR / "bank"
# ─────────────────────────────────────────────────────────────

logging.basicConfig(level="INFO",
                    format="%(asctime)s  %(message)s")
log = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════
# PART 1 — Read & combine all yearly NPCI Product Excel files
# ════════════════════════════════════════════════════════════

def read_one_yearly_excel(path: Path) -> pd.DataFrame:
    """
    Read one NPCI yearly Excel (e.g. FY2020-21).
    Each file has ~12 rows: Month | Banks Live | Volume | Value
    """
    try:
        df = pd.read_excel(path, sheet_name=0, engine="openpyxl")
        
        # Standardise column names
        rename = {}
        for col in df.columns:
            c = str(col).lower().strip()
            if "month" in c:                       rename[col] = "month_str"
            elif "bank" in c:                      rename[col] = "banks_live"
            elif "volume" in c:                    rename[col] = "volume_mn"
            elif "value" in c:                     rename[col] = "value_cr"
        
        df = df.rename(columns=rename)
        keep = [c for c in ["month_str","banks_live","volume_mn","value_cr"]
                if c in df.columns]
        df = df[keep].dropna(subset=["month_str"]).copy()
        
        log.info(f"  {path.name}: {len(df)} rows")
        return df

    except Exception as e:
        log.warning(f"  Skipped {path.name}: {e}")
        return pd.DataFrame()


def parse_month(series: pd.Series) -> pd.Series:
    """Try multiple date formats used across NPCI yearly files."""
    for fmt in ["%B-%Y", "%b-%Y", "%B %Y", "%b %Y",
                "%B-%y", "%b-%y", "%m/%Y", "%Y-%m"]:
        parsed = pd.to_datetime(series, format=fmt, errors="coerce")
        if parsed.notna().sum() > len(series) * 0.7:
            return parsed
    # Last resort: let pandas infer
    return pd.to_datetime(series, infer_datetime_format=True, errors="coerce")


def load_all_yearly_excels() -> pd.DataFrame:
    """Find and combine all NPCI Product Statistics Excel files."""
    # Match any .xlsx in data/raw/ (excluding bank/ subfolder)
    files = [f for f in RAW_DIR.glob("*.xlsx")
             if "ecosystem" not in f.name.lower()
             and "bank" not in f.name.lower()]

    if not files:
        raise FileNotFoundError(
            f"No Excel files found in {RAW_DIR}\n"
            "Place your yearly NPCI Excel files there and retry."
        )

    log.info(f"Found {len(files)} yearly Excel file(s):")
    frames = [read_one_yearly_excel(f) for f in sorted(files)]
    frames = [df for df in frames if not df.empty]

    if not frames:
        raise ValueError("All Excel files were empty or unparseable.")

    combined = pd.concat(frames, ignore_index=True)

    # Parse month string → datetime
    combined["month"] = parse_month(combined["month_str"])
    combined = combined.dropna(subset=["month"]).copy()

    # Clean numeric columns (remove commas, spaces)
    for col in ["banks_live", "volume_mn", "value_cr"]:
        if col in combined.columns:
            combined[col] = pd.to_numeric(
                combined[col].astype(str)
                             .str.replace(",", "")
                             .str.strip(),
                errors="coerce")

    # Remove duplicates, sort
    combined = (combined
                .drop_duplicates(subset=["month"])
                .sort_values("month")
                .reset_index(drop=True))

    # Derive FY columns
    months_ts = pd.to_datetime(combined["month"])

    def fy_label(m):
        s = m.year if m.month >= 4 else m.year - 1
        return f"FY{s}-{str(s+1)[-2:]}"

    combined["month_dt"]   = months_ts.dt.date
    combined["month_name"] = months_ts.dt.strftime("%b")
    combined["quarter"]    = months_ts.dt.quarter
    combined["year"]       = months_ts.dt.year
    combined["fy"]         = months_ts.apply(fy_label)
    combined["fy_num"]     = months_ts.apply(
        lambda m: m.year + 1 if m.month >= 4 else m.year)
    combined["fy_month"]   = months_ts.apply(
        lambda m: (m.month - 4) % 12 + 1)

    final_cols = ["month_dt","month_name","quarter","year",
                  "fy","fy_num","fy_month",
                  "banks_live","volume_mn","value_cr"]
    combined = combined[[c for c in final_cols if c in combined.columns]]
    combined = combined.rename(columns={"month_dt": "month"})

    log.info(f"Combined: {len(combined)} rows | "
             f"{combined['month'].min()} → {combined['month'].max()}")
    return combined


# ════════════════════════════════════════════════════════════
# PART 2 — Bank-wise Ecosystem Statistics (optional)
# ════════════════════════════════════════════════════════════

def read_bank_excel(path: Path) -> pd.DataFrame:
    """
    Parse NPCI Ecosystem Statistics Excel (bank-wise performance).
    Columns from NPCI: Bank Name, Total Volume (In Mn.), Approved %,
                       BD%, TD%, Total Debit Reversal Count, 
                       Debit Reversal Success %
    """
    try:
        # Try each sheet for the bank performance table
        xl = pd.ExcelFile(path, engine="openpyxl")
        target_sheet = None
        for sheet in xl.sheet_names:
            if any(kw in sheet.lower() for kw in
                   ["member","bank","remitter","beneficiary","performance"]):
                target_sheet = sheet
                break
        
        df = xl.parse(target_sheet or 0, header=None)

        # Find header row (contains "Bank" and "Volume")
        header_row = None
        for i, row in df.iterrows():
            row_str = " ".join(str(v).lower() for v in row if pd.notna(v))
            if "bank" in row_str and "volume" in row_str:
                header_row = i
                break

        if header_row is None:
            log.warning(f"No bank table header found in {path.name}")
            return pd.DataFrame()

        data = df.iloc[header_row + 1:].copy()
        data.columns = df.iloc[header_row].values
        data = data.dropna(how="all").reset_index(drop=True)

        # Standardise columns
        rename = {}
        for col in data.columns:
            c = str(col).lower().strip()
            if "bank" in c and ("name" in c or "upi" in c or c == "bank"):
                rename[col] = "bank_name"
            elif "volume" in c:           rename[col] = "volume_mn"
            elif "approved" in c:         rename[col] = "approved_pct"
            elif "bd" in c or "business decline" in c: rename[col] = "bd_pct"
            elif "td" in c or "technical decline" in c: rename[col] = "td_pct"
            elif "reversal" in c and "count" in c:  rename[col] = "reversal_count_mn"
            elif "reversal" in c and "success" in c: rename[col] = "reversal_success_pct"

        data = data.rename(columns=rename)

        # Extract month/year from filename (e.g. ecosystem_jan_2026.xlsx)
        # Extract month/year from filename (e.g. ecosystem_jan_2026.xlsx)
        month_match = re.search(r"_([a-z]{3}|\d{2})_(\d{4})", path.name.lower())
        if month_match:
            m_str, y_str = month_match.groups()
            if m_str.isdigit():
                # If it's a number like '01', format it as YYYY-MM-01
                data["report_month"] = pd.to_datetime(f"{y_str}-{m_str}-01")
            else:
                # If it's letters like 'jan', use the %b format
                data["report_month"] = pd.to_datetime(f"{m_str}-{y_str}", format="%b-%Y")
        else:
            data["report_month"] = None

        keep = [c for c in ["bank_name","volume_mn","approved_pct",
                            "bd_pct","td_pct","reversal_count_mn",
                            "reversal_success_pct","report_month"]
                if c in data.columns]
        data = data[keep].dropna(subset=["bank_name"]).copy()
        data["bank_name"] = data["bank_name"].astype(str).str.strip()
        data = data[data["bank_name"].str.len() > 2]

        for col in ["volume_mn","approved_pct","bd_pct","td_pct",
                    "reversal_count_mn","reversal_success_pct"]:
            if col in data.columns:
                data[col] = pd.to_numeric(
                    data[col].astype(str)
                             .str.replace("%","")
                             .str.replace(",","")
                             .str.strip(),
                    errors="coerce")

        log.info(f"  Bank file {path.name}: {len(data)} banks")
        return data

    except Exception as e:
        log.warning(f"  Skipped bank file {path.name}: {e}")
        return pd.DataFrame()


def load_all_bank_excels() -> pd.DataFrame:
    """Load all bank Excel files from data/raw/bank/"""
    if not BANK_DIR.exists():
        log.info("No data/raw/bank/ folder — skipping bank data.")
        return pd.DataFrame()

    files = list(BANK_DIR.glob("*.xlsx")) + list(BANK_DIR.glob("*.xls"))
    if not files:
        log.info("No bank Excel files in data/raw/bank/ — skipping.")
        return pd.DataFrame()

    log.info(f"Found {len(files)} bank Excel file(s):")
    frames = [read_bank_excel(f) for f in sorted(files)]
    frames = [df for df in frames if not df.empty]
    if not frames:
        return pd.DataFrame()

    combined = pd.concat(frames, ignore_index=True)
    log.info(f"Bank data: {len(combined)} total rows")
    return combined


# ════════════════════════════════════════════════════════════
# PART 3 — PostgreSQL schema
# ════════════════════════════════════════════════════════════

SCHEMA_SQL = """
-- ── Main monthly table ───────────────────────────────────────
CREATE TABLE IF NOT EXISTS upi_monthly (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    month           DATE UNIQUE NOT NULL,
    month_name      VARCHAR(5),
    quarter         INTEGER,
    year            INTEGER,
    fy              VARCHAR(12),
    fy_num          INTEGER,
    fy_month        INTEGER,
    banks_live      INTEGER,
    volume_mn       REAL,
    value_cr        REAL
);

-- ── Bank performance table (optional) ────────────────────────
CREATE TABLE IF NOT EXISTS upi_bank_performance (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    report_month          DATE,
    bank_name             VARCHAR(120),
    volume_mn             REAL,
    approved_pct          REAL,
    bd_pct                REAL,
    td_pct                REAL,
    reversal_count_mn     REAL,
    reversal_success_pct  REAL,
    UNIQUE(report_month, bank_name)
);

-- ── Indexes ──────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_upi_month  ON upi_monthly(month);
CREATE INDEX IF NOT EXISTS idx_upi_fy     ON upi_monthly(fy_num);
CREATE INDEX IF NOT EXISTS idx_bank_month ON upi_bank_performance(report_month);

-- ── View 1: FY summary ───────────────────────────────────────
DROP VIEW IF EXISTS v_fy_summary;
CREATE VIEW v_fy_summary AS
SELECT fy, fy_num,
    ROUND(SUM(volume_mn), 1)     AS total_vol_mn,
    ROUND(SUM(value_cr), 2)      AS total_val_cr,
    ROUND(SUM(value_cr)*1e7/NULLIF(SUM(volume_mn)*1e6,0), 0) AS avg_ticket_inr,
    MAX(banks_live)              AS peak_banks_live
FROM upi_monthly
GROUP BY fy, fy_num ORDER BY fy_num;

-- ── View 2: Growth momentum ───────────────────────────────────
DROP VIEW IF EXISTS v_growth_momentum;
CREATE VIEW v_growth_momentum AS
SELECT month, month_name, fy, fy_month,
    volume_mn, value_cr,
    ROUND((volume_mn / NULLIF(LAG(volume_mn,1) OVER (ORDER BY month),0) - 1)*100,1)
        AS mom_growth_pct,
    ROUND((volume_mn / NULLIF(LAG(volume_mn,12) OVER (ORDER BY month),0) - 1)*100,1)
        AS yoy_growth_pct,
    ROUND(AVG(volume_mn) OVER (ORDER BY month ROWS 2 PRECEDING),2)
        AS vol_3m_avg
FROM upi_monthly ORDER BY month;

-- ── View 3: Bank market share (latest month) ─────────────────
DROP VIEW IF EXISTS v_bank_market_share;
CREATE VIEW v_bank_market_share AS
SELECT bank_name, volume_mn, approved_pct, bd_pct, td_pct,
    reversal_success_pct,
    ROUND(volume_mn*100.0/NULLIF(SUM(volume_mn) OVER(),0),2) AS vol_share_pct,
    RANK() OVER (ORDER BY volume_mn DESC) AS rank
FROM upi_bank_performance
WHERE report_month = (SELECT MAX(report_month) FROM upi_bank_performance);
"""

def apply_schema(engine):
    with engine.begin() as conn:
        for stmt in SCHEMA_SQL.split(";"):
            s = stmt.strip()
            if s:
                conn.execute(text(s))
    log.info("Schema applied.")


# ════════════════════════════════════════════════════════════
# PART 4 — Load & validate
# ════════════════════════════════════════════════════════════

def upsert(engine, table: str, df: pd.DataFrame, conflict_col: str):
    if df.empty:
        return 0
        
    # --- NEW FIX: Convert Pandas Timestamps to standard strings ---
    for col in df.select_dtypes(include=['datetime64[ns]', '<M8[ns]']).columns:
        df[col] = df[col].dt.strftime('%Y-%m-%d')
    # --------------------------------------------------------------
    
    records = df.where(df.notna(), None).to_dict(orient="records")
    cols    = list(records[0].keys())
    sql = text(
        f"INSERT INTO {table} ({','.join(cols)}) "
        f"VALUES ({','.join(':'+c for c in cols)}) "
        f"ON CONFLICT ({conflict_col}) DO NOTHING"
    )
    with engine.begin() as conn:
        result = conn.execute(sql, records)
    log.info(f"{table}: {result.rowcount}/{len(records)} rows inserted")
    return result.rowcount


def validate(engine):
    checks = {
        "upi_monthly rows":       "SELECT COUNT(*) FROM upi_monthly",
        "Date range":             "SELECT CONCAT(MIN(month),' → ',MAX(month)) FROM upi_monthly",
        "FY years":               "SELECT COUNT(DISTINCT fy) FROM upi_monthly",
        "Bank rows":              "SELECT COUNT(*) FROM upi_bank_performance",
        "Banks (latest month)":   "SELECT COUNT(*) FROM v_bank_market_share",
    }
    log.info("─── Validation ───────────────────────────────")
    with engine.connect() as conn:
        for label, sql in checks.items():
            try:
                val = conn.execute(text(sql)).scalar()
                log.info(f"  {label:<28} {val}")
            except Exception as e:
                log.info(f"  {label:<28} (skipped: {e})")
    log.info("──────────────────────────────────────────────")


# ════════════════════════════════════════════════════════════
# Main
# ════════════════════════════════════════════════════════════

def main():
    url = "sqlite:///upi_data.db"
    engine = create_engine(url)
    log.info("Connected to SQLite database.")
    
    # Remove Postgres-specific schema triggers if present
    apply_schema(engine)

    # Monthly data
    monthly_df = load_all_yearly_excels()
    upsert(engine, "upi_monthly", monthly_df, "month")

    # Bank data (optional)
    bank_df = load_all_bank_excels()
    if not bank_df.empty:
        upsert(engine, "upi_bank_performance", bank_df,
               "report_month, bank_name")

    validate(engine)
    log.info("\nDone! Load into Power BI:")
    log.info("  Tables: upi_monthly, upi_bank_performance")
    log.info("  Views:  v_fy_summary, v_growth_momentum, v_bank_market_share")


if __name__ == "__main__":
    main()