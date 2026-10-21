from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
REFERENCE_DIR = BASE_DIR / "reference"
OUTPUT_DIR = BASE_DIR / "outputs"

DEFAULT_REFERENCE_BUDGET = REFERENCE_DIR / "reference_budget.xlsx"
GOLD_STANDARD_TEMPLATE = REFERENCE_DIR / "gold_standard.xlsx"

ACTUAL_REQUIRED_FIELDS = [
    "MANAGEMENT_CODE",
    "LIB4",
    "ACCOUNT_CODE",
    "DESCRIPTION",
    "PARTNER_CODE",
    "PO_NUMBER",
]

# Deterministic PoC mappings already demonstrated in the gold-standard workbook.
FIXED_MAPPINGS = {
    "631410": ("417100C", "Travel and living", "Approved PoC travel crosswalk"),
    "632210": ("417100C", "Travel and living", "Approved PoC travel crosswalk"),
    "632310": ("417100C", "Travel and living", "Approved PoC travel crosswalk"),
    "632410": ("417100C", "Travel and living", "Approved PoC travel crosswalk"),
    "677120": ("417400A", "Internal telecommunications costs", "Approved PoC telecom crosswalk"),
}

TRAVEL_DESCRIPTION_KEYWORDS = (
    "hotel", "travel", "trip", "itineris", "airfare", "air ticket", "flight",
    "insurance", "accommodation", "lodging", "rail", "train", "taxi", "metro",
    "subway", "underground", "immersion", "departure", "arrival tax", "departure fee",
)
TELECOM_DESCRIPTION_KEYWORDS = (
    "mobile", "telecom", "data pack", "esim", "e-sim", "sim card", "internet",
)
