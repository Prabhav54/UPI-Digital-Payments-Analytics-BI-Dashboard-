"""
transform.py — Build dimension and fact DataFrames from raw extracted data.
Applies FY labelling, bank classification, and P2P/P2M split logic.
"""
import logging
from typing import Optional
import pandas as pd

from config import PAYMENT_TYPES, BANK_TYPE_MAP, LOG_LEVEL

logging.basicConfig(level=LOG_LEVEL,
                    format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

def _fy_label(month: pd.Timestamp) -> tuple[str, int, int]:
    """Return (fy_label, fy_num, fy_month) for a given month.
    Indian FY runs Apr–Mar.  Apr-2024 → 'FY2024-25', fy_num=2025, fy_month=1
    """
    if month.month >= 4:
        fy_start = month.year
    else:
        fy_start = month.year - 1
    label   = f"FY{fy_start}-{str(fy_start + 1)[-2:]}"  # 'FY2024-25'
    fy_num  = fy_start + 1                                 # 2025
    fy_mo   = (month.month - 4) % 12 + 1                  # Apr=1 … Mar=12
    return label, fy_num, fy_mo


# ─────────────────────────────────────────────────────────────
# 1.  dim_date
# ─────────────────────────────────────────────────────────────

def build_dim_date(months: pd.Series) -> pd.DataFrame:
    """
    Build dim_date rows for all unique months in the data.
    months: Series of pd.Timestamp (first day of each month).
    """
    unique_months = months.dropna().dt.to_period("M").drop_duplicates()
    unique_months = sorted(set(m.to_timestamp() for m in unique_months))

    rows = []
    for m in unique_months:
        fy_label, fy_num, fy_mo = _fy_label(m)
        rows.append({
            "month":      m.date(),
            "month_name": m.strftime("%b"),
            "month_num":  m.month,
            "quarter":    (m.month - 1) // 3 + 1,
            "year":       m.year,
            "fy":         fy_label,
            "fy_num":     fy_num,
            "fy_month":   fy_mo,
        })

    df = pd.DataFrame(rows)
    log.info(f"dim_date rows: {len(df)}")
    return df


# ─────────────────────────────────────────────────────────────
# 2.  dim_bank
# ─────────────────────────────────────────────────────────────

def build_dim_bank(bank_names: pd.Series) -> pd.DataFrame:
    """Build dim_bank from unique bank names, classifying each by type."""
    unique = bank_names.dropna().str.strip().unique()
    rows = []
    for name in sorted(unique):
        bank_type = _classify_bank(name)
        rows.append({
            "bank_name": name,
            "bank_type": bank_type,
            "is_active": True,
        })
    df = pd.DataFrame(rows)
    log.info(f"dim_bank rows: {len(df)}")
    return df


def _classify_bank(name: str) -> str:
    """Return bank_type string from BANK_TYPE_MAP or heuristic rules."""
    if name in BANK_TYPE_MAP:
        return BANK_TYPE_MAP[name]

    n = name.lower()
    if any(k in n for k in ["payments bank", "payment bank"]):
        return "Payment Bank"
    if any(k in n for k in ["small finance", "sfb"]):
        return "SFB"
    if any(k in n for k in ["gramin", "rrb", "rural regional"]):
        return "RRB"
    if any(k in n for k in ["co-operative", "cooperative", "co-op"]):
        return "Co-op"
    # PSU bank keywords
    if any(k in n for k in [
            "state bank", "bank of baroda", "bank of india",
            "central bank", "punjab national", "union bank",
            "canara", "uco", "indian bank", "indian overseas",
            "maharashtra", "allahabad", "vijaya", "dena"]):
        return "PSU"
    return "Private"  # default


# ─────────────────────────────────────────────────────────────
# 3.  dim_payment_type  (seeded from config)
# ─────────────────────────────────────────────────────────────

def build_dim_payment_type() -> pd.DataFrame:
    df = pd.DataFrame(PAYMENT_TYPES)
    log.info(f"dim_payment_type rows: {len(df)}")
    return df


# ─────────────────────────────────────────────────────────────
# 4.  fact_transactions
# ─────────────────────────────────────────────────────────────

def build_fact_transactions(
    monthly_df: pd.DataFrame,
    date_id_map: dict,      # month_date → date_id
    ptype_id_map: dict,     # type_name  → ptype_id
) -> pd.DataFrame:
    """
    Expand monthly aggregate rows into fact_transactions.
    Handles both wide format (separate P2P/P2M columns)
    and narrow format (only Total columns).
    """
    rows = []
    total_id = ptype_id_map.get("Total")

    for _, row in monthly_df.iterrows():
        month_key = pd.Timestamp(row["month"]).date() \
                    if not isinstance(row["month"], type(None)) else None
        date_id = date_id_map.get(month_key)
        if not date_id:
            log.warning(f"No date_id for month {month_key}, skipping.")
            continue

        # Total row
        rows.append({
            "date_id":   date_id,
            "ptype_id":  total_id,
            "banks_live": _safe_int(row.get("banks_live")),
            "volume_mn":  _safe_float(row.get("volume_mn")),
            "value_cr":   _safe_float(row.get("value_cr")),
        })

        # P2P row (if available)
        if "p2p_vol_mn" in row and pd.notna(row.get("p2p_vol_mn")):
            rows.append({
                "date_id":   date_id,
                "ptype_id":  ptype_id_map.get("P2P"),
                "banks_live": None,
                "volume_mn":  _safe_float(row.get("p2p_vol_mn")),
                "value_cr":   _safe_float(row.get("p2p_val_cr")),
            })

        # P2M row (if available)
        if "p2m_vol_mn" in row and pd.notna(row.get("p2m_vol_mn")):
            rows.append({
                "date_id":   date_id,
                "ptype_id":  ptype_id_map.get("P2M"),
                "banks_live": None,
                "volume_mn":  _safe_float(row.get("p2m_vol_mn")),
                "value_cr":   _safe_float(row.get("p2m_val_cr")),
            })

    df = pd.DataFrame(rows)
    log.info(f"fact_transactions rows: {len(df)}")
    return df


# ─────────────────────────────────────────────────────────────
# 5.  fact_bank_performance
# ─────────────────────────────────────────────────────────────

def build_fact_bank_performance(
    bank_df: pd.DataFrame,
    date_id_map: dict,
    bank_id_map: dict,      # bank_name → bank_id
) -> pd.DataFrame:
    if bank_df is None or bank_df.empty:
        log.info("No bank performance data to transform.")
        return pd.DataFrame()

    rows = []
    for _, row in bank_df.iterrows():
        month_key = pd.Timestamp(row["month"]).date() \
                    if not isinstance(row["month"], type(None)) else None
        date_id = date_id_map.get(month_key)
        bank_id = bank_id_map.get(str(row.get("bank_name", "")).strip())
        if not date_id or not bank_id:
            log.debug(f"Skipping bank row — missing date/bank id: {row}")
            continue

        rows.append({
            "date_id":        date_id,
            "bank_id":        bank_id,
            "remitter_vol":   _safe_int(row.get("remitter_vol")),
            "beneficiary_vol":_safe_int(row.get("beneficiary_vol")),
            "remitter_val_cr":_safe_float(row.get("remitter_val_cr")),
            "ben_val_cr":     _safe_float(row.get("ben_val_cr")),
        })

    df = pd.DataFrame(rows)
    log.info(f"fact_bank_performance rows: {len(df)}")
    return df


# ─────────────────────────────────────────────────────────────
# Utilities
# ─────────────────────────────────────────────────────────────

def _safe_int(val) -> Optional[int]:
    try:
        return int(float(str(val).replace(",", ""))) if pd.notna(val) else None
    except (ValueError, TypeError):
        return None


def _safe_float(val) -> Optional[float]:
    try:
        return float(str(val).replace(",", "")) if pd.notna(val) else None
    except (ValueError, TypeError):
        return None
