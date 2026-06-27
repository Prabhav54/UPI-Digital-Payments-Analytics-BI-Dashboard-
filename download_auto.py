"""
download_auto.py — Fully automatic UPI data download
=====================================================
Uses India Data Portal direct CSV (no Selenium, no browser needed).
Covers FY2017 → present. Run this ONCE before main.py.

Sources (all direct links, no JavaScript):
  1. India Data Portal  → UPI monthly stats CSV  (primary)
  2. Kaggle API         → nilesh2042/monthly-metrics (backup)
  3. NPCI manual steps  → printed if both fail
"""

import logging
import time
from pathlib import Path

import pandas as pd
import requests

logging.basicConfig(level="INFO",
                    format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

DATA_DIR = Path("data/raw")
DATA_DIR.mkdir(parents=True, exist_ok=True)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 Chrome/124.0 Safari/537.36"
}

# ── Direct CSV URL — India Data Portal (NPCI official dataset) ──
# This is a plain HTTP link — no JS rendering required
INDIA_DATA_PORTAL_CSV = (
    "https://ckandev.indiadataportal.com/dataset/"
    "150fe363-f61f-41f2-9215-15f61358f427/resource/"
    "8b176063-658a-41d7-9401-7461808d87a2/download/"
    "upi-product-statistics.csv"
)

# ── Kaggle dataset backup (requires kaggle API key) ──
KAGGLE_DATASET = "nilesh2042/monthly-metrics"

# ─────────────────────────────────────────────────────────────
# Source 1 — India Data Portal (primary, no auth needed)
# ─────────────────────────────────────────────────────────────

def download_india_data_portal() -> Path | None:
    """
    Download UPI Product Statistics CSV from India Data Portal.
    Direct link — works with plain requests, no browser needed.
    """
    dest = DATA_DIR / "upi_product_statistics_idp.csv"
    log.info("Trying India Data Portal direct CSV...")
    log.info(f"URL: {INDIA_DATA_PORTAL_CSV}")

    try:
        resp = requests.get(INDIA_DATA_PORTAL_CSV,
                            headers=HEADERS, timeout=30)
        resp.raise_for_status()

        dest.write_bytes(resp.content)
        log.info(f"Downloaded: {dest} ({len(resp.content)/1024:.1f} KB)")

        # Quick validation — check it's actually a CSV with data
        df = pd.read_csv(dest)
        log.info(f"Rows: {len(df)} | Columns: {list(df.columns)}")

        if len(df) < 10:
            log.warning("Too few rows — file may be incomplete.")
            return None

        return dest

    except Exception as e:
        log.warning(f"India Data Portal failed: {e}")
        return None


# ─────────────────────────────────────────────────────────────
# Source 2 — Kaggle API (backup)
# ─────────────────────────────────────────────────────────────

def download_kaggle() -> Path | None:
    """
    Download UPI CSV from Kaggle using the kaggle CLI.
    Requires: pip install kaggle + ~/.kaggle/kaggle.json API key
    Get API key: kaggle.com → Account → Create New Token
    """
    import subprocess, shutil

    if not shutil.which("kaggle"):
        log.warning("kaggle CLI not found. Install: pip install kaggle")
        return None

    kaggle_dir = DATA_DIR / "kaggle_upi"
    kaggle_dir.mkdir(exist_ok=True)

    log.info(f"Downloading Kaggle dataset: {KAGGLE_DATASET}")
    result = subprocess.run(
        ["kaggle", "datasets", "download", "-d", KAGGLE_DATASET,
         "--unzip", "-p", str(kaggle_dir)],
        capture_output=True, text=True
    )

    if result.returncode != 0:
        log.warning(f"Kaggle download failed: {result.stderr}")
        return None

    # Find the UPI CSV inside the downloaded files
    upi_files = list(kaggle_dir.glob("*upi*")) + list(kaggle_dir.glob("*UPI*"))
    if not upi_files:
        upi_files = list(kaggle_dir.glob("*.csv"))

    if not upi_files:
        log.warning("No CSV files found in Kaggle download.")
        return None

    dest = DATA_DIR / "upi_kaggle.csv"
    import shutil as sh
    sh.copy(upi_files[0], dest)
    log.info(f"Kaggle file saved: {dest}")
    return dest


# ─────────────────────────────────────────────────────────────
# Source 3 — Manual instructions (last resort)
# ─────────────────────────────────────────────────────────────

def print_manual_steps():
    print("""
╔══════════════════════════════════════════════════════════════╗
║          MANUAL DOWNLOAD — 3 options, pick any one          ║
╠══════════════════════════════════════════════════════════════╣
║                                                              ║
║  OPTION A — India Data Portal (easiest, CSV, direct link)   ║
║  ─────────────────────────────────────────────────────────  ║
║  1. Open this URL in browser:                                ║
║     https://data.gov.in/resource/                            ║
║     unified-payments-interface-upi-product-statistics        ║
║  2. Click "Download CSV"                                     ║
║  3. Save file to:  data/raw/                                 ║
║  4. Run:  python main.py --source csv                        ║
║                                                              ║
║  OPTION B — NPCI Website (Excel, all data FY17→now)         ║
║  ─────────────────────────────────────────────────────────  ║
║  1. Open: https://www.npci.org.in/product/upi/               ║
║            product-statistics                                ║
║  2. Scroll down — you'll see a table with monthly data       ║
║  3. Click the DOWNLOAD / Excel icon (top right of table)     ║
║  4. Save file to:  data/raw/                                 ║
║  5. Run:  python main.py --file data/raw/<filename>.xlsx     ║
║                                                              ║
║  OPTION C — Kaggle (CSV, cleaned, community maintained)     ║
║  ─────────────────────────────────────────────────────────  ║
║  1. Open: https://www.kaggle.com/datasets/                   ║
║            nilesh2042/monthly-metrics                        ║
║  2. Click Download (top right)                               ║
║  3. Unzip → find upi.csv or similar                          ║
║  4. Save to:  data/raw/                                      ║
║  5. Run:  python main.py --source csv                        ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
""")


# ─────────────────────────────────────────────────────────────
# Normalise CSV → standard format for main.py
# ─────────────────────────────────────────────────────────────

def normalise_csv(src: Path) -> Path:
    """
    Standardise any downloaded CSV to the column names
    that extract.py and transform.py expect:
      month, banks_live, volume_mn, value_cr
    """
    df = pd.read_csv(src)
    log.info(f"Raw columns: {list(df.columns)}")

    col_map = {}
    for col in df.columns:
        c = col.lower().strip()
        if "month" in c or "date" in c:
            col_map[col] = "month_str"
        elif "bank" in c and ("live" in c or "count" in c or "number" in c):
            col_map[col] = "banks_live"
        elif ("volume" in c or "no." in c or "count" in c) \
              and "value" not in c and "bank" not in c:
            col_map[col] = "volume_mn"
        elif "value" in c or "amount" in c or "crore" in c:
            col_map[col] = "value_cr"

    df = df.rename(columns=col_map)
    keep = [c for c in ["month_str","banks_live","volume_mn","value_cr"]
            if c in df.columns]
    df = df[keep].copy()

    # Parse month
    for fmt in ["%b-%y", "%B %Y", "%Y-%m", "%m/%Y", "%b %Y", "%d-%m-%Y"]:
        try:
            df["month"] = pd.to_datetime(df["month_str"], format=fmt)
            if not df["month"].isna().all():
                break
        except Exception:
            continue

    df = df.dropna(subset=["month"]).drop(columns=["month_str"],
                                           errors="ignore")

    # Coerce numerics
    for col in ["banks_live", "volume_mn", "value_cr"]:
        if col in df.columns:
            df[col] = pd.to_numeric(
                df[col].astype(str)
                       .str.replace(",", "")
                       .str.replace("₹", "")
                       .str.strip(),
                errors="coerce")

    df = df.sort_values("month").reset_index(drop=True)
    dest = src.parent / "upi_normalised.csv"
    df.to_csv(dest, index=False)

    log.info(f"Normalised CSV saved: {dest}")
    log.info(f"Date range: {df['month'].min()} → {df['month'].max()}")
    log.info(f"Total rows: {len(df)}")
    return dest


# ─────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\n UPI Data Auto-Downloader")
    print("=" * 45)

    result = None

    # Try Source 1 — India Data Portal
    result = download_india_data_portal()

    # Try Source 2 — Kaggle (if Source 1 failed)
    if not result:
        log.info("Trying Kaggle as backup...")
        result = download_kaggle()

    # All auto sources failed — print manual steps
    if not result:
        log.error("Auto-download failed from all sources.")
        print_manual_steps()
    else:
        # Normalise the CSV to standard format
        normalised = normalise_csv(result)
        print(f"""
╔══════════════════════════════════════════════════════╗
║  Download complete!                                  ║
║                                                      ║
║  File: {str(normalised):<44}║
║                                                      ║
║  Next step — run the ETL pipeline:                   ║
║                                                      ║
║    python main.py --source csv                       ║
║                                                      ║
╚══════════════════════════════════════════════════════╝
""")