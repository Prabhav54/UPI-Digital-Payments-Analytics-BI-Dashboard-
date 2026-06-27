# UPI Digital Payments Intelligence — ETL Pipeline

Python ETL that extracts NPCI UPI statistics, loads them into a
PostgreSQL star schema, and powers a Power BI DirectQuery dashboard.

## Project structure
```
upi_etl/
├── main.py          # orchestrator — run this
├── extract.py       # NPCI PDF + Excel parsers
├── transform.py     # build dim/fact DataFrames
├── load.py          # PostgreSQL upsert logic
├── config.py        # DB settings, bank type map
├── schema.sql       # CREATE TABLE + VIEWs
├── requirements.txt
├── .env.example     # copy to .env and fill credentials
└── data/raw/        # place downloaded NPCI files here
```

## Quick start

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Set up PostgreSQL
```bash
psql -U postgres -c "CREATE DATABASE upi_db;"
```

### 3. Configure credentials
```bash
cp .env.example .env
# Edit .env with your DB host, port, user, password
```

### 4. Get NPCI data
- Go to https://npci.org.in/product/upi/product-statistics
- Download the latest Excel workbook → save to `data/raw/`
- Optionally download monthly PDFs for older data

### 5. Run the pipeline
```bash
# Primary (Excel — cleanest format)
python main.py

# PDF fallback (place PDFs in data/raw/ first)
python main.py --source pdf

# Specific file
python main.py --file data/raw/UPI-Product-Statistics.xlsx

# Force re-download
python main.py --force-download

# Schema only (create tables, no data)
python main.py --schema-only
```

### 6. Connect Power BI
1. Open Power BI Desktop
2. Get Data → PostgreSQL
3. Host: localhost  Port: 5432  Database: upi_db
4. Select **DirectQuery** for fact tables
5. Select **Import** for dim tables (small, rarely change)
6. Load these views:
   - `v_monthly_overview`
   - `v_bank_market_share`
   - `v_payment_type_split`

## Data sources
| Source | URL | Format |
|--------|-----|--------|
| NPCI Monthly Stats | npci.org.in/product/upi/product-statistics | Excel / PDF |
| NPCI Bank Performance | npci.org.in (Ecosystem Statistics) | PDF |
| RBI Payment Systems | rbi.org.in → DBIE → Payment Systems | Excel |

## Schema
```
dim_date          → date_id, month, fy, fy_num, quarter …
dim_bank          → bank_id, bank_name, bank_type …
dim_payment_type  → ptype_id, type_name, category
fact_transactions → date_id, ptype_id, volume_mn, value_cr …
fact_bank_perf    → date_id, bank_id, remitter_vol, beneficiary_vol …
```
