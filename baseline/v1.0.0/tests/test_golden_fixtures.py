"""
Golden-value tests comparing extracted fields against manually approved fixtures
for all three companies: Sherwin-Williams, Reliance (RIL), and ExxonMobil.

Fields covered:
- Company name
- Wingman tier
- Headcount (people_employed)
- Founding year (year_founded)
- Line of work
- Report window
- Public-account count
- Forward-signal count
"""
import csv
from pathlib import Path
import pytest

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output"

GOLDEN_FIXTURES = {
    "Sherwin-Williams": {
        "company_name": "Sherwin-Williams",
        "wingman_tier": "Tier 3",
        "people_employed": "64249",
        "year_founded": "1866",
        "line_of_work": "Paints and coatings",
        "report_window": "2015-2024",
        "public_accounts_count": 7,
        "forward_signals_count": 4,
    },
    "Reliance (RIL)": {
        "company_name": "Reliance (RIL)",
        "wingman_tier": "Tier 2",
        "people_employed": "",  # Unreported in report cards/narrative
        "year_founded": "",     # Unreported in report cards/narrative
        "line_of_work": "Petrochemicals",
        "report_window": "2015-2024",
        "public_accounts_count": 2,
        "forward_signals_count": 4,
    },
    "ExxonMobil": {
        "company_name": "ExxonMobil",
        "wingman_tier": "Tier 1",
        "people_employed": "74900",
        "year_founded": "1882",
        "line_of_work": "Oil and gas",
        "report_window": "2015-2024",
        "public_accounts_count": 12,
        "forward_signals_count": 4,
    },
}


def test_golden_values_against_fixtures(extracted_records):
    """
    Asserts that all three companies exactly match manually approved golden fixtures.
    """
    csv_file = OUTPUT_DIR / "companies_summary.csv"
    with open(csv_file, newline="", encoding="utf-8") as f:
        rows = {r["company_name"]: r for r in csv.DictReader(f)}

    with open(OUTPUT_DIR / "forward_signals.csv", newline="", encoding="utf-8") as f:
        signals = list(csv.DictReader(f))

    with open(OUTPUT_DIR / "public_accounts.csv", newline="", encoding="utf-8") as f:
        accounts = list(csv.DictReader(f))

    for comp_name, fixture in GOLDEN_FIXTURES.items():
        assert comp_name in rows, f"Missing {comp_name} in companies_summary.csv"
        actual = rows[comp_name]

        # 1. Company Name
        assert actual["company_name"] == fixture["company_name"]

        # 2. Tier
        assert actual["wingman_tier"] == fixture["wingman_tier"]

        # 3. Headcount
        assert actual["people_employed"] == fixture["people_employed"], (
            f"{comp_name} headcount mismatch: expected {fixture['people_employed']}, got {actual['people_employed']}"
        )

        # 4. Founding Year
        assert actual["year_founded"] == fixture["year_founded"], (
            f"{comp_name} founding year mismatch: expected {fixture['year_founded']}, got {actual['year_founded']}"
        )

        # 5. Line of Work
        assert actual["line_of_work"] == fixture["line_of_work"], (
            f"{comp_name} line of work mismatch: expected {fixture['line_of_work']}, got {actual['line_of_work']}"
        )

        # 6. Report Window
        assert actual["report_window"] == fixture["report_window"]

        # 7. Forward Signal Count
        comp_signals = [s for s in signals if s["company_name"] == comp_name]
        assert len(comp_signals) == fixture["forward_signals_count"], (
            f"{comp_name} signals count: expected {fixture['forward_signals_count']}, got {len(comp_signals)}"
        )

        # 8. Public Accounts Count
        comp_accounts = [a for a in accounts if a["company_name"] == comp_name]
        assert len(comp_accounts) == fixture["public_accounts_count"], (
            f"{comp_name} accounts count: expected {fixture['public_accounts_count']}, got {len(comp_accounts)}"
        )
