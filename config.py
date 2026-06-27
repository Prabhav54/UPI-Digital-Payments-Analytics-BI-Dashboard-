# config.py — centralised settings, loaded once at startup
import os
from pathlib import Path
from dotenv import load_dotenv
import urllib.parse
load_dotenv()

# ── Paths ────────────────────────────────────────────────────
OOT = Path(__file__).parent
DATA_DIR = Path(os.getenv("DATA_DIR", ROOT / "data" / "raw"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

# SQLite file location
DB_PATH = ROOT / "upi_data.db"

def db_url() -> str:
    # This creates/connects to a file named 'upi_data.db' in your project root
    return f"sqlite:///{DB_PATH}"
# ── NPCI Data ─────────────────────────────────────────────────
# Direct download URL pattern for NPCI monthly stats Excel
# NPCI publishes at: https://www.npci.org.in/product/upi/product-statistics
# They also release Excel workbooks — update URL below as needed
NPCI_EXCEL_URL = (
    "https://www.npci.org.in/PDF/npci/upi/Product-Statistics/"
    "UPI-Product-Statistics.xlsx"
)

# Known NPCI bank-performance PDF naming pattern (update yearly)
NPCI_BANK_PDF_PATTERN = (
    "https://www.npci.org.in/PDF/npci/upi/Ecosystem-Statistics/"
    "UPI-Ecosystem-Statistics-{month}-{year}.pdf"
)

# Seed data for dim_payment_type
PAYMENT_TYPES = [
    {"type_name": "P2P",        "category": "retail"},
    {"type_name": "P2M",        "category": "merchant"},
    {"type_name": "UPI Lite",   "category": "merchant"},
    {"type_name": "UPI 123PAY", "category": "retail"},
    {"type_name": "Total",      "category": "others"},
]

# Bank classification map  (add more as NPCI reports list them)
BANK_TYPE_MAP = {
    "State Bank of India":            "PSU",
    "Bank of Baroda":                 "PSU",
    "Punjab National Bank":           "PSU",
    "Union Bank of India":            "PSU",
    "Canara Bank":                    "PSU",
    "HDFC Bank":                      "Private",
    "ICICI Bank":                     "Private",
    "Axis Bank":                      "Private",
    "Kotak Mahindra Bank":            "Private",
    "Yes Bank":                       "Private",
    "IndusInd Bank":                  "Private",
    "IDBI Bank":                      "PSU",
    "Paytm Payments Bank":            "Payment Bank",
    "Airtel Payments Bank":           "Payment Bank",
    "India Post Payments Bank":       "Payment Bank",
    "Jio Payments Bank":              "Payment Bank",
    "AU Small Finance Bank":          "SFB",
    "Equitas Small Finance Bank":     "SFB",
    "ESAF Small Finance Bank":        "SFB",
}

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
