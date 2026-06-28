# UPI Digital Payments Analytics & BI Dashboard

An end-to-end analytics project on India's UPI (Unified Payments Interface) ecosystem — from raw NPCI/RBI statistics to a 4-page interactive Power BI dashboard covering national growth, bank-wise market share, P2P vs P2M transaction behavior, and UPI's global expansion.

## Overview

UPI processes tens of billions of transactions a month across 40+ banks in India. NPCI publishes this data publicly, but spread across multiple report formats with no single combined dataset. This project builds a Python ETL pipeline to pull that data together, stores it in SQLite, and presents it through a Power BI dashboard.

## Project structure

```
upi_project/
├── data/                     Raw and cleaned data files
├── powerbi_data/             CSV exports feeding the Power BI model
├── p2p_p2m_raw/              Monthly NPCI P2P/P2M source files
├── extract.py                Pulls and parses NPCI source data
├── transform.py               Cleans and reshapes extracted data
├── load.py                    Loads cleaned data into SQLite
├── load_to_sqlite.py          SQLite schema and load logic
├── config.py                  Project configuration
├── download_auto.py           Automated source file handling
├── export_to_powerbi.py       Exports SQLite tables to CSV for Power BI
├── main.py                     Pipeline entry point
├── schema.sql                  Database schema definition
├── requirements.txt
└── upi_data.db                SQLite database
```

## Pipeline

**1. Extract** — `extract.py` reads NPCI's monthly statistics (national volume/value, bank-wise performance, P2P/P2M split) from downloaded Excel/PDF source files.

**2. Transform** — `transform.py` cleans the extracted data: normalizes bank names, parses Indian-formatted numbers, derives fiscal-year and month fields.

**3. Load to SQLite** — `load_to_sqlite.py` writes the cleaned data into `upi_data.db` using the schema in `schema.sql`. Tables: monthly national stats, bank-level performance, and derived summary views.

**4. Export to Power BI** — `export_to_powerbi.py` exports the SQLite tables to CSV files in `powerbi_data/`, which Power BI imports directly.

**5. Model and visualize** — Power BI imports the CSVs, builds relationships between tables, and computes additional measures in DAX (YoY growth, average ticket size, top-N bank share) on top of the SQLite data.

## Data sources

- NPCI UPI Product Statistics (monthly national figures)
- NPCI UPI Ecosystem Statistics (bank-wise performance, P2P/P2M split)
- Manually compiled UPI international go-live dates

## Dashboard pages

**Page 1 — National Command Center**
Total transaction volume/value over time, active banks, year-over-year growth, fiscal-year breakdown.
![Page 1](screenshots/page1_national_overview.png)

**Page 2 — Bank Market Share War**
Top 10 banks by volume, PSU/Private/Payment Bank split, approval rate vs business decline rate by bank.
![Page 2](screenshots/page2_bank_market_share.png)

**Page 3 — P2P vs P2M Behavior**
Person-to-person vs person-to-merchant split over time, average ticket size comparison.
![Page 3](screenshots/page3_p2p_p2m_behavior.png)

**Page 4 — Global Expansion Tracker**
Countries where UPI is live internationally, go-live timeline, adoption status.
![Page 4](screenshots/page4_global_expansion.png)

## Tech stack

Python (pandas, openpyxl) · SQLite · Power Query · Power BI · DAX

## Running this yourself

1. Clone the repo
2. Run `python main.py` to extract, transform, and load NPCI data into SQLite
3. Run `python export_to_powerbi.py` to generate the CSVs in `powerbi_data/`
4. Open the `.pbix` file in Power BI Desktop and refresh

## Author

Prabhav Khare — [GitHub](https://github.com/Prabhav54)

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
