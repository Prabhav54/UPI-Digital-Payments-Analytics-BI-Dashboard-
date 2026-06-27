"""
extract.py — Download and parse NPCI UPI data
Supports:
  1. NPCI Excel workbook  (primary — cleanest format)
  2. NPCI monthly aggregate PDF  (fallback)
  3. NPCI bank-performance PDF   (ecosystem statistics)
"""
import logging
import re
from pathlib import Path
from typing import Optional

import pandas as pd
import pdfplumber
import requests
from tenacity import retry, stop_after_attempt, wait_exponential

from config import DATA_DIR, NPCI_EXCEL_URL, LOG_LEVEL

logging.basicConfig(level=LOG_LEVEL,
                    format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

HEADERS = {"User-Agent": "Mozilla/5.0 (UPI Research Project)"}

# ─────────────────────────────────────────────────────────────
# 1.  Download helpers
# ─────────────────────────────────────────────────────────────

@retry(stop=stop_after_attempt(3),
       wait=wait_exponential(multiplier=1, min=2, max=10))
def download_file(url: str, dest: Path) -> Path:
    """Download url → dest with retry. Returns dest path."""
    log.info(f"Downloading {url}")
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    dest.write_bytes(resp.content)
    log.info(f"Saved to {dest} ({len(resp.content)/1024:.1f} KB)")
    return dest


def fetch_npci_excel(force: bool = False) -> Path:
    """Download the NPCI UPI monthly stats Excel workbook."""
    dest = DATA_DIR / "upi_product_statistics.xlsx"
    if dest.exists() and not force:
        log.info(f"Excel already exists at {dest}, skipping download.")
        return dest
    return download_file(NPCI_EXCEL_URL, dest)


def fetch_npci_pdf(local_path: Path) -> Path:
    """
    For manually downloaded NPCI PDFs.
    Place them in data/raw/ and pass the path here.
    NPCI PDFs are not directly linkable (JS-rendered page),
    so manual download is required for PDFs.
    """
    if not local_path.exists():
        raise FileNotFoundError(
            f"PDF not found: {local_path}\n"
            "Download manually from:\n"
            "npci.org.in → Products → UPI → Product Statistics"
        )
    return local_path


# ─────────────────────────────────────────────────────────────
# 2.  Excel extractor  (primary source — cleanest)
# ─────────────────────────────────────────────────────────────

def extract_from_excel(path: Path) -> dict[str, pd.DataFrame]:
    """
    Parse NPCI UPI Excel workbook.
    Returns dict with keys: 'monthly', 'bank_performance' (if sheet exists).

    NPCI Excel typically has sheets:
      - 'Monthly' or 'UPI-Monthly'   : aggregate monthly stats
      - 'Bank Performance'            : bank-wise remitter/beneficiary
    """
    log.info(f"Reading Excel: {path}")
    xl = pd.ExcelFile(path, engine="openpyxl")
    log.info(f"Sheets found: {xl.sheet_names}")

    result = {}

    # ── Monthly aggregate sheet ──────────────────────────────
    monthly_sheet = _find_sheet(xl.sheet_names,
                                ["Monthly", "UPI-Monthly", "month", "statistics"])
    if monthly_sheet:
        df = xl.parse(monthly_sheet, header=None)
        result["monthly"] = _clean_monthly_excel(df)
        log.info(f"Monthly rows extracted: {len(result['monthly'])}")

    # ── Bank performance sheet ───────────────────────────────
    bank_sheet = _find_sheet(xl.sheet_names,
                             ["Bank", "Performance", "Remitter", "Beneficiary"])
    if bank_sheet:
        df = xl.parse(bank_sheet, header=None)
        result["bank_performance"] = _clean_bank_excel(df)
        log.info(f"Bank rows extracted: {len(result['bank_performance'])}")

    return result


def _find_sheet(sheets: list, keywords: list) -> Optional[str]:
    for sheet in sheets:
        for kw in keywords:
            if kw.lower() in sheet.lower():
                return sheet
    return None


def _clean_monthly_excel(df: pd.DataFrame) -> pd.DataFrame:
    """
    Locate the data table within the Excel sheet and standardise columns.
    NPCI Excels often have title rows before the actual table.
    """
    # Find the header row (contains 'Month' or 'Volume' or 'Value')
    header_row = None
    for i, row in df.iterrows():
        row_str = " ".join(str(v).lower() for v in row.values if pd.notna(v))
        if any(kw in row_str for kw in ["month", "volume", "transaction", "value"]):
            header_row = i
            break

    if header_row is None:
        raise ValueError("Could not locate header row in monthly sheet.")

    # Re-read with correct header
    data = df.iloc[header_row + 1:].copy()
    data.columns = df.iloc[header_row].values
    data = data.dropna(how="all").reset_index(drop=True)

    # Normalise column names
    col_map = {}
    for col in data.columns:
        c = str(col).lower().strip()
        if "month" in c:
            col_map[col] = "month_str"
        elif "bank" in c and "live" in c:
            col_map[col] = "banks_live"
        elif "volume" in c or ("transaction" in c and "value" not in c):
            col_map[col] = "volume_mn"
        elif "value" in c or "amount" in c:
            col_map[col] = "value_cr"
        elif "p2p" in c and "volume" in c:
            col_map[col] = "p2p_vol_mn"
        elif "p2p" in c and "value" in c:
            col_map[col] = "p2p_val_cr"
        elif "p2m" in c and "volume" in c:
            col_map[col] = "p2m_vol_mn"
        elif "p2m" in c and "value" in c:
            col_map[col] = "p2m_val_cr"

    data = data.rename(columns=col_map)

    # Keep only mapped columns
    keep = [c for c in col_map.values() if c in data.columns]
    data = data[keep].copy()

    # Parse month strings → datetime
    if "month_str" in data.columns:
        data["month"] = pd.to_datetime(data["month_str"],
                                       format="%b-%y", errors="coerce")
        # Try alternate format if above fails
        mask = data["month"].isna()
        if mask.any():
            data.loc[mask, "month"] = pd.to_datetime(
                data.loc[mask, "month_str"],
                format="%B %Y", errors="coerce")
        data = data.dropna(subset=["month"])
        data = data.drop(columns=["month_str"])

    # Coerce numerics
    for col in ["banks_live", "volume_mn", "value_cr",
                "p2p_vol_mn", "p2p_val_cr", "p2m_vol_mn", "p2m_val_cr"]:
        if col in data.columns:
            data[col] = pd.to_numeric(
                data[col].astype(str).str.replace(",", "").str.strip(),
                errors="coerce")

    return data.sort_values("month").reset_index(drop=True)


def _clean_bank_excel(df: pd.DataFrame) -> pd.DataFrame:
    """Parse bank-wise performance sheet."""
    header_row = None
    for i, row in df.iterrows():
        row_str = " ".join(str(v).lower() for v in row.values if pd.notna(v))
        if "bank" in row_str and ("remitter" in row_str or "beneficiary" in row_str):
            header_row = i
            break

    if header_row is None:
        log.warning("Could not find header in bank performance sheet.")
        return pd.DataFrame()

    data = df.iloc[header_row + 1:].copy()
    data.columns = df.iloc[header_row].values
    data = data.dropna(how="all").reset_index(drop=True)

    col_map = {}
    for col in data.columns:
        c = str(col).lower().strip()
        if "bank" in c and "name" in c or c == "bank":
            col_map[col] = "bank_name"
        elif "month" in c:
            col_map[col] = "month_str"
        elif "remitter" in c and "vol" in c:
            col_map[col] = "remitter_vol"
        elif "remitter" in c and "val" in c:
            col_map[col] = "remitter_val_cr"
        elif "beneficiary" in c and "vol" in c:
            col_map[col] = "beneficiary_vol"
        elif "beneficiary" in c and "val" in c:
            col_map[col] = "ben_val_cr"

    data = data.rename(columns=col_map)
    keep = [c for c in col_map.values() if c in data.columns]
    data = data[keep].copy()

    if "month_str" in data.columns:
        data["month"] = pd.to_datetime(data["month_str"],
                                       format="%b-%y", errors="coerce")
        data = data.dropna(subset=["month"]).drop(columns=["month_str"])

    for col in ["remitter_vol", "beneficiary_vol"]:
        if col in data.columns:
            data[col] = pd.to_numeric(
                data[col].astype(str).str.replace(",", "").str.strip(),
                errors="coerce")

    for col in ["remitter_val_cr", "ben_val_cr"]:
        if col in data.columns:
            data[col] = pd.to_numeric(
                data[col].astype(str).str.replace(",", "").str.strip(),
                errors="coerce")

    data = data.dropna(subset=["bank_name"])
    data["bank_name"] = data["bank_name"].str.strip()
    return data.reset_index(drop=True)


# ─────────────────────────────────────────────────────────────
# 3.  PDF extractor  (fallback for older NPCI reports)
# ─────────────────────────────────────────────────────────────

def extract_from_pdf(path: Path) -> dict[str, pd.DataFrame]:
    """
    Extract tables from NPCI UPI monthly statistics PDF.
    pdfplumber table detection works well on NPCI's bordered tables.
    """
    log.info(f"Reading PDF: {path}")
    result = {}
    all_rows = []

    with pdfplumber.open(path) as pdf:
        log.info(f"PDF pages: {len(pdf.pages)}")
        for page_num, page in enumerate(pdf.pages, 1):
            tables = page.extract_tables(
                table_settings={
                    "vertical_strategy":   "lines",
                    "horizontal_strategy": "lines",
                    "snap_tolerance":      5,
                })

            if not tables:
                # Fallback: try text-based parsing
                log.debug(f"Page {page_num}: no bordered tables, trying text parse")
                text_rows = _parse_pdf_text(page.extract_text() or "")
                all_rows.extend(text_rows)
                continue

            for table in tables:
                if not table or len(table) < 2:
                    continue
                df = pd.DataFrame(table)
                df = df.dropna(how="all").reset_index(drop=True)
                log.debug(f"Page {page_num}: table {df.shape}")

                # Detect if this is the monthly stats table
                header = " ".join(str(v).lower() for v in df.iloc[0]
                                  if v is not None)
                if any(kw in header for kw in
                       ["month", "volume", "transaction", "value", "bank"]):
                    parsed = _parse_pdf_table(df)
                    if parsed is not None and len(parsed):
                        all_rows.append(parsed)

    if all_rows:
        combined = pd.concat(all_rows, ignore_index=True)
        combined = combined.drop_duplicates(subset=["month"]).sort_values("month")
        result["monthly"] = combined
        log.info(f"PDF monthly rows: {len(combined)}")

    return result


def _parse_pdf_table(df: pd.DataFrame) -> Optional[pd.DataFrame]:
    """Map a raw pdfplumber table → standardised monthly DataFrame."""
    # First row = header
    df.columns = [str(v).lower().strip() if v else f"col_{i}"
                  for i, v in enumerate(df.iloc[0])]
    df = df.iloc[1:].copy()

    col_map = {}
    for col in df.columns:
        if "month" in col:
            col_map[col] = "month_str"
        elif "bank" in col and "live" in col:
            col_map[col] = "banks_live"
        elif "volume" in col or "no. of" in col:
            col_map[col] = "volume_mn"
        elif "value" in col or "amount" in col:
            col_map[col] = "value_cr"

    if "month_str" not in col_map.values():
        return None

    df = df.rename(columns=col_map)
    keep = list(col_map.values())
    df = df[[c for c in keep if c in df.columns]].copy()

    df["month"] = pd.to_datetime(df.get("month_str", ""),
                                 format="%b-%y", errors="coerce")
    if df["month"].isna().all():
        df["month"] = pd.to_datetime(df.get("month_str", ""),
                                     format="%B %Y", errors="coerce")

    df = df.dropna(subset=["month"])
    for col in ["banks_live", "volume_mn", "value_cr"]:
        if col in df.columns:
            df[col] = pd.to_numeric(
                df[col].astype(str).str.replace(",", "").str.strip(),
                errors="coerce")

    return df.drop(columns=["month_str"], errors="ignore")


def _parse_pdf_text(text: str) -> list:
    """
    Last-resort text parser for NPCI PDFs that use text layout instead
    of bordered tables. Looks for month-value patterns.
    """
    rows = []
    # Pattern: "Apr-23   703   8,886.17   14,07,676.12"
    pattern = re.compile(
        r"((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
        r"[-–]\d{2,4})"           # month like Apr-23
        r"\s+([\d,]+)"            # banks live
        r"\s+([\d,]+\.?\d*)"     # volume
        r"\s+([\d,]+\.?\d*)"     # value
    )
    for match in pattern.finditer(text):
        month_str, banks, vol, val = match.groups()
        try:
            month = pd.to_datetime(month_str, format="%b-%y")
        except ValueError:
            continue
        rows.append(pd.DataFrame([{
            "month":      month,
            "banks_live": int(banks.replace(",", "")),
            "volume_mn":  float(vol.replace(",", "")),
            "value_cr":   float(val.replace(",", "")),
        }]))
    return rows
