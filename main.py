"""
main.py — UPI ETL Pipeline Orchestrator
========================================
Run modes:
  python main.py                    # Excel (primary source)
  python main.py --source pdf       # PDF (fallback)
  python main.py --file data/raw/custom.xlsx  # specific file
  python main.py --force-download   # re-download even if cached
  python main.py --schema-only      # create tables then exit

Usage after install:
  pip install -r requirements.txt
  cp .env.example .env              # fill in your DB creds
  python main.py
"""
import argparse
import logging
import sys
from pathlib import Path

import pandas as pd
from tqdm import tqdm

import extract as E
import transform as T
import load as L
from config import DATA_DIR, LOG_LEVEL

logging.basicConfig(level=LOG_LEVEL,
                    format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)


def parse_args():
    p = argparse.ArgumentParser(description="UPI ETL Pipeline")
    p.add_argument("--source", choices=["excel", "pdf"], default="excel")
    p.add_argument("--file", type=Path, default=None,
                   help="Path to a specific local file to process")
    p.add_argument("--force-download", action="store_true",
                   help="Re-download even if file is cached")
    p.add_argument("--schema-only", action="store_true",
                   help="Apply schema.sql and exit")
    return p.parse_args()


def run(args) -> None:
    # ── 1. Database setup ─────────────────────────────────────
    log.info("=" * 55)
    log.info("  UPI Digital Payments ETL Pipeline")
    log.info("=" * 55)

    engine = L.get_engine()
    schema_path = Path(__file__).parent / "schema.sql"
    L.run_schema(engine, schema_path)

    if args.schema_only:
        log.info("--schema-only flag set. Tables created. Exiting.")
        return

    # ── 2. Extract ────────────────────────────────────────────
    steps = ["Extract", "Transform", "Load dims", "Load facts", "Validate"]
    pbar = tqdm(steps, desc="Pipeline", unit="step")

    pbar.set_description("Extract")
    raw = {}

    if args.file:
        # User supplied a specific local file
        path = args.file
        if path.suffix.lower() in (".xlsx", ".xls"):
            raw = E.extract_from_excel(path)
        elif path.suffix.lower() == ".pdf":
            raw = E.extract_from_pdf(path)
        else:
            log.error(f"Unsupported file type: {path.suffix}")
            sys.exit(1)

    elif args.source == "excel":
        try:
            path = E.fetch_npci_excel(force=args.force_download)
            raw = E.extract_from_excel(path)
        except Exception as exc:
            log.error(f"Excel download/parse failed: {exc}")
            log.info("Hint: Download manually from npci.org.in and "
                     "re-run with --file path/to/file.xlsx")
            sys.exit(1)

    else:  # pdf
        pdf_files = sorted(DATA_DIR.glob("*.pdf"))
        if not pdf_files:
            log.error(
                "No PDFs found in data/raw/\n"
                "Download NPCI UPI PDFs from:\n"
                "  npci.org.in → Products → UPI → Product Statistics\n"
                "Place them in data/raw/ and re-run."
            )
            sys.exit(1)
        all_monthly = []
        all_bank    = []
        for pdf_path in pdf_files:
            result = E.extract_from_pdf(pdf_path)
            if "monthly" in result:
                all_monthly.append(result["monthly"])
            if "bank_performance" in result:
                all_bank.append(result["bank_performance"])

        if all_monthly:
            combined = pd.concat(all_monthly, ignore_index=True)
            raw["monthly"] = (combined
                              .drop_duplicates(subset=["month"])
                              .sort_values("month")
                              .reset_index(drop=True))
        if all_bank:
            raw["bank_performance"] = (pd.concat(all_bank, ignore_index=True)
                                       .reset_index(drop=True))

    pbar.update(1)

    if "monthly" not in raw or raw["monthly"].empty:
        log.error("No monthly data extracted. Check your source files.")
        sys.exit(1)

    monthly_df = raw["monthly"]
    bank_df    = raw.get("bank_performance", pd.DataFrame())

    log.info(f"Monthly data: {len(monthly_df)} rows, "
             f"range {monthly_df['month'].min()} → {monthly_df['month'].max()}")

    # ── 3. Transform dims ─────────────────────────────────────
    pbar.set_description("Transform")

    dim_date_df    = T.build_dim_date(monthly_df["month"])
    dim_ptype_df   = T.build_dim_payment_type()
    dim_bank_df    = (T.build_dim_bank(bank_df["bank_name"])
                      if not bank_df.empty else pd.DataFrame())

    pbar.update(1)

    # ── 4. Load dims (return id maps) ─────────────────────────
    pbar.set_description("Load dims")

    date_id_map  = L.load_dim_date(engine, dim_date_df)
    ptype_id_map = L.load_dim_payment_type(engine, dim_ptype_df)
    bank_id_map  = L.load_dim_bank(engine, dim_bank_df) if not dim_bank_df.empty else {}

    pbar.update(1)

    # ── 5. Transform + load facts ─────────────────────────────
    pbar.set_description("Load facts")

    fact_txn_df = T.build_fact_transactions(
        monthly_df, date_id_map, ptype_id_map)
    L.load_fact_transactions(engine, fact_txn_df)

    if not bank_df.empty:
        fact_bank_df = T.build_fact_bank_performance(
            bank_df, date_id_map, bank_id_map)
        L.load_fact_bank_performance(engine, fact_bank_df)

    pbar.update(1)

    # ── 6. Validate ───────────────────────────────────────────
    pbar.set_description("Validate")
    L.print_row_counts(engine)
    pbar.update(1)
    pbar.close()

    log.info("=" * 55)
    log.info("  Pipeline complete.")
    log.info("  Connect Power BI via PostgreSQL connector")
    log.info(f"  Tables: dim_date, dim_bank, dim_payment_type,")
    log.info(f"          fact_transactions, fact_bank_performance")
    log.info(f"  Views:  v_monthly_overview, v_bank_market_share,")
    log.info(f"          v_payment_type_split")
    log.info("=" * 55)


if __name__ == "__main__":
    run(parse_args())
