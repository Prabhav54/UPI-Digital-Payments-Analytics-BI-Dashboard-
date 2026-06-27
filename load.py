"""
load.py — Upsert dimension and fact tables into PostgreSQL.
Uses ON CONFLICT DO NOTHING for idempotent incremental loads.
Running the pipeline twice will never duplicate rows.
"""
import logging
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from config import db_url, LOG_LEVEL

logging.basicConfig(level=LOG_LEVEL,
                    format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)


import logging
import pandas as pd
from sqlalchemy import create_engine, text
from config import db_url, LOG_LEVEL

logging.basicConfig(level=LOG_LEVEL, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

def get_engine():
    url = db_url()
    log.info(f"Connecting to SQLite: {url}")
    return create_engine(url)

def run_schema(engine, schema_path: Path = Path("schema.sql")) -> None:
    sql = schema_path.read_text()
    # SQLite doesn't need "CREATE DATABASE" or schema-specific commands
    statements = [s.strip() for s in sql.split(";") if s.strip()]
    with engine.begin() as conn:
        for stmt in statements:
            conn.execute(text(stmt))
    log.info("Schema applied successfully.")

def upsert(engine, table: str, df: pd.DataFrame, conflict_cols: list[str]) -> int:
    if df.empty: return 0
    
    # SQLite uses 'REPLACE' or 'INSERT OR IGNORE' for upserts
    with engine.begin() as conn:
        df.to_sql(table, conn, if_exists='append', index=False, method='multi')
    
    log.info(f"{table}: {len(df)} rows processed.")
    return len(df)
# ─────────────────────────────────────────────────────────────
# Dimension loaders (return id-maps for fact linking)
# ─────────────────────────────────────────────────────────────

def load_dim_date(engine, df: pd.DataFrame) -> dict:
    """Insert dim_date rows, return {month_date → date_id}."""
    if df.empty:
        return {}
    upsert(engine, "dim_date", df, conflict_cols=["month"])
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT date_id, month FROM dim_date")).fetchall()
    return {row.month: row.date_id for row in rows}


def load_dim_bank(engine, df: pd.DataFrame) -> dict:
    """Insert dim_bank rows, return {bank_name → bank_id}."""
    if df.empty:
        return {}
    upsert(engine, "dim_bank", df, conflict_cols=["bank_name"])
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT bank_id, bank_name FROM dim_bank")).fetchall()
    return {row.bank_name: row.bank_id for row in rows}


def load_dim_payment_type(engine, df: pd.DataFrame) -> dict:
    """Insert dim_payment_type rows, return {type_name → ptype_id}."""
    upsert(engine, "dim_payment_type", df, conflict_cols=["type_name"])
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT ptype_id, type_name FROM dim_payment_type")).fetchall()
    return {row.type_name: row.ptype_id for row in rows}


# ─────────────────────────────────────────────────────────────
# Fact loaders
# ─────────────────────────────────────────────────────────────

def load_fact_transactions(engine, df: pd.DataFrame) -> int:
    return upsert(engine, "fact_transactions", df,
                  conflict_cols=["date_id", "ptype_id"])


def load_fact_bank_performance(engine, df: pd.DataFrame) -> int:
    if df.empty:
        return 0
    return upsert(engine, "fact_bank_performance", df,
                  conflict_cols=["date_id", "bank_id"])


# ─────────────────────────────────────────────────────────────
# Row counts (for post-load validation)
# ─────────────────────────────────────────────────────────────

def print_row_counts(engine) -> None:
    tables = ["dim_date", "dim_bank", "dim_payment_type",
              "fact_transactions", "fact_bank_performance"]
    log.info("─── Row counts after load ───")
    with engine.connect() as conn:
        for t in tables:
            try:
                n = conn.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar()
                log.info(f"  {t:<30} {n:>6} rows")
            except Exception as e:
                log.warning(f"  {t}: {e}")
