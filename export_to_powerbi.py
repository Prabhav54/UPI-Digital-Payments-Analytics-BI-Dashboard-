import sqlite3
import pandas as pd
import logging
from pathlib import Path

logging.basicConfig(level="INFO", format="%(asctime)s %(message)s")
log = logging.getLogger(__name__)

def export_views():
    # 1. Connect to your SQLite file
    db_path = "upi_data.db"
    out_dir = Path("powerbi_data")
    out_dir.mkdir(exist_ok=True)
    
    conn = sqlite3.connect(db_path)
    
    # 2. List the views you want in your dashboard
    views = [
        "v_fy_summary",
        "v_growth_momentum",
        "v_bank_market_share",
        "upi_monthly",          # Exporting the raw tables just in case
        "upi_bank_performance" 
    ]
    
    # 3. Export each one to a clean CSV
    for view in views:
        try:
            log.info(f"Exporting {view}...")
            df = pd.read_sql_query(f"SELECT * FROM {view}", conn)
            df.to_csv(out_dir / f"{view}.csv", index=False)
            log.info(f"  -> Saved to powerbi_data/{view}.csv")
        except Exception as e:
            log.error(f"Failed to export {view}: {e}")

    conn.close()
    log.info("All data exported! Ready for Power BI.")

if __name__ == "__main__":
    export_views()