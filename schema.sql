-- ============================================================
-- UPI Digital Payments Intelligence — SQLite Star Schema
-- ============================================================

-- ── Dimension: Date ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS dim_date (
    date_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    month       DATE        NOT NULL UNIQUE,
    month_name  VARCHAR(10) NOT NULL,
    month_num   INTEGER     NOT NULL,
    quarter     INTEGER     NOT NULL,
    year        INTEGER     NOT NULL,
    fy          VARCHAR(12) NOT NULL,
    fy_num      INTEGER     NOT NULL,
    fy_month    INTEGER     NOT NULL
);

-- ── Dimension: Bank ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS dim_bank (
    bank_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    bank_name   VARCHAR(120) NOT NULL UNIQUE,
    bank_type   VARCHAR(30)  NOT NULL,
    is_active   BOOLEAN      NOT NULL DEFAULT 1
);

-- ── Dimension: Payment Type ──────────────────────────────────
CREATE TABLE IF NOT EXISTS dim_payment_type (
    ptype_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    type_name   VARCHAR(30) NOT NULL UNIQUE,
    category    VARCHAR(20) NOT NULL
);

-- ── Fact: Monthly Aggregate Transactions ────────────────────
CREATE TABLE IF NOT EXISTS fact_transactions (
    txn_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    date_id         INTEGER NOT NULL,
    ptype_id        INTEGER NOT NULL,
    banks_live      INTEGER,
    volume_mn       REAL,
    value_cr        REAL,
    UNIQUE (date_id, ptype_id),
    FOREIGN KEY (date_id) REFERENCES dim_date(date_id),
    FOREIGN KEY (ptype_id) REFERENCES dim_payment_type(ptype_id)
);

-- ── Fact: Bank-wise Performance ──────────────────────────────
CREATE TABLE IF NOT EXISTS fact_bank_performance (
    perf_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    date_id         INTEGER NOT NULL,
    bank_id         INTEGER NOT NULL,
    remitter_vol    BIGINT,
    beneficiary_vol BIGINT,
    remitter_val_cr REAL,
    ben_val_cr      REAL,
    UNIQUE (date_id, bank_id),
    FOREIGN KEY (date_id) REFERENCES dim_date(date_id),
    FOREIGN KEY (bank_id) REFERENCES dim_bank(bank_id)
);

-- ── Views (Power BI reads these) ─────────────────────────────

-- 1. Monthly overview
DROP VIEW IF EXISTS v_monthly_overview;
CREATE VIEW v_monthly_overview AS
SELECT
    d.month,
    d.month_name,
    d.fy,
    d.fy_num,
    d.fy_month,
    SUM(f.volume_mn) AS total_vol_mn,
    SUM(f.value_cr) AS total_val_cr,
    MAX(f.banks_live) AS banks_live
FROM fact_transactions f
JOIN dim_date d ON f.date_id = d.date_id
GROUP BY d.month, d.month_name, d.fy, d.fy_num, d.fy_month;

-- 2. Bank market share 
DROP VIEW IF EXISTS v_bank_market_share;
CREATE VIEW v_bank_market_share AS
SELECT
    b.bank_name,
    b.bank_type,
    SUM(bp.remitter_vol) AS remitter_total,
    SUM(bp.beneficiary_vol) AS beneficiary_total
FROM fact_bank_performance bp
JOIN dim_bank b ON bp.bank_id = b.bank_id
GROUP BY b.bank_name, b.bank_type;

-- 3. P2P vs P2M split
DROP VIEW IF EXISTS v_payment_type_split;
CREATE VIEW v_payment_type_split AS
SELECT
    d.month,
    pt.type_name,
    f.volume_mn,
    f.value_cr
FROM fact_transactions f
JOIN dim_date d ON f.date_id = d.date_id
JOIN dim_payment_type pt ON f.ptype_id = pt.ptype_id;