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


KINDER_MORGAN_SHA256 = "cb186794999e108e62dfe28485c28fa97879008d3935c75158c8455903689a97"
KINDER_MORGAN_FIXTURE = {
    "company_name": "Kinder Morgan",
    "wingman_tier": "UNASSIGNED",
    "people_employed": "11075",
    "year_founded": "1997",
    "line_of_work": "Energy infrastructure",
    "business_description": "It specializes in owning and controlling oil and gas pipelines and terminals.",
    "report_window": "2015-2024",
    "public_accounts_count": 11,
    "forward_signals_count": 4,
}


def test_kinder_morgan_holdout_golden_fixture():
    """
    Asserts Kinder Morgan holdout extraction matches verified golden values
    and confirms the input PDF SHA-256 checksum.
    """
    import hashlib
    pdf_path = Path(__file__).resolve().parent.parent / "input" / "holdout" / "Kinder-Morgan-Pattern-Report-4.pdf"
    assert pdf_path.exists(), f"Missing holdout PDF: {pdf_path}"
    with open(pdf_path, "rb") as f:
        file_hash = hashlib.sha256(f.read()).hexdigest()
    assert file_hash == KINDER_MORGAN_SHA256, f"Checksum mismatch: expected {KINDER_MORGAN_SHA256}, got {file_hash}"

    holdout_dir = Path(__file__).resolve().parent.parent / "output" / "holdout_v1_1"
    summary_csv = holdout_dir / "companies_summary.csv"
    assert summary_csv.exists(), f"Missing holdout companies_summary.csv at {summary_csv}"
    with open(summary_csv, newline="", encoding="utf-8") as f:
        rows = {r["company_name"]: r for r in csv.DictReader(f)}

    assert "Kinder Morgan" in rows
    km = rows["Kinder Morgan"]
    assert km["company_name"] == KINDER_MORGAN_FIXTURE["company_name"]
    assert km["wingman_tier"] == KINDER_MORGAN_FIXTURE["wingman_tier"]
    assert km["people_employed"] == KINDER_MORGAN_FIXTURE["people_employed"]
    assert km["year_founded"] == KINDER_MORGAN_FIXTURE["year_founded"]
    assert km["line_of_work"] == KINDER_MORGAN_FIXTURE["line_of_work"]
    assert km["business_description"] == KINDER_MORGAN_FIXTURE["business_description"]
    assert km["report_window"] == KINDER_MORGAN_FIXTURE["report_window"]

    with open(holdout_dir / "forward_signals.csv", newline="", encoding="utf-8") as f:
        signals = list(csv.DictReader(f))
    assert len(signals) == KINDER_MORGAN_FIXTURE["forward_signals_count"]

    with open(holdout_dir / "public_accounts.csv", newline="", encoding="utf-8") as f:
        accounts = list(csv.DictReader(f))
    assert len(accounts) == KINDER_MORGAN_FIXTURE["public_accounts_count"]
