"""
Tests validating the structural schemas and integrity of the 6 generated CSV outputs.
"""
import csv
from pathlib import Path
import pytest

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output"

def test_all_six_csv_files_exist(extracted_records):
    expected_files = [
        "companies_summary.csv",
        "field_evidence.csv",
        "forward_signals.csv",
        "public_accounts.csv",
        "seven_patterns.csv",
        "validation_issues.csv",
    ]
    for filename in expected_files:
        csv_file = OUTPUT_DIR / filename
        assert csv_file.exists(), f"Missing CSV output: {filename}"
        assert csv_file.stat().st_size > 0, f"CSV file is empty: {filename}"

def test_companies_summary_schema(extracted_records):
    csv_file = OUTPUT_DIR / "companies_summary.csv"
    with open(csv_file, newline="", encoding="utf-8") as f:
        reader = list(csv.DictReader(f))
        assert len(reader) == 3, f"Expected 3 company rows, got {len(reader)}"
        
        required_headers = [
            "parser_version", "extraction_timestamp", "source_pdf_filename", "company_id",
            "company_name", "extraction_review_required", "source_verification_required",
            "analyst_normalization_review_required", "manual_review_required", "manual_review_notes", "wingman_tier",
            "wingman_source", "headquarters_city", "headquarters_country", "report_geography",
            "operating_countries", "year_founded", "people_employed", "line_of_work",
            "headcount_source_type", "headcount_source_date", "headcount_value_context", "headcount_profile_card_present",
            "report_window", "header_basis_of_report", "official_records_availability",
            "header_publicly_written_accounts", "public_sources_cited", "records_proven",
            "answered_by_record", "open_information_count", "press_reported_account_count",
            "forward_looking_press_count", "osha_inspections_found", "csb_mentions_found",
            "citations_count", "penalties_amount", "penalties_currency_symbol",
            "penalties_currency_iso", "penalties_display_text", "investigated_accidents_count",
            "deaths_count", "sec_annual_report_status", "sec_filing_date",
            "the_seven_answered_count", "the_seven_overall_status", "regulatory_record_status",
            "safety_performance_inference", "report_audit_status"
        ]
        for header in required_headers:
            assert header in reader[0], f"Missing expected column header in companies_summary: {header}"

def test_metadata_in_all_six_csvs(extracted_records):
    expected_files = [
        "companies_summary.csv",
        "field_evidence.csv",
        "forward_signals.csv",
        "public_accounts.csv",
        "seven_patterns.csv",
        "validation_issues.csv",
    ]
    for filename in expected_files:
        csv_file = OUTPUT_DIR / filename
        with open(csv_file, newline="", encoding="utf-8") as f:
            reader = list(csv.DictReader(f))
            assert len(reader) > 0, f"{filename} is empty"
            assert "parser_version" in reader[0], f"parser_version missing from {filename}"
            assert "extraction_timestamp" in reader[0], f"extraction_timestamp missing from {filename}"
            assert "source_pdf_filename" in reader[0], f"source_pdf_filename missing from {filename}"
            assert "company_id" in reader[0], f"company_id missing from {filename}"

def test_stable_identifiers_present(extracted_records):
    # Signals
    with open(OUTPUT_DIR / "forward_signals.csv", newline="", encoding="utf-8") as f:
        signals = list(csv.DictReader(f))
        for s in signals:
            assert s["signal_id"].startswith("SIG-")
            assert s["company_id"].startswith("COMP-")

    # Accounts
    with open(OUTPUT_DIR / "public_accounts.csv", newline="", encoding="utf-8") as f:
        accounts = list(csv.DictReader(f))
        for a in accounts:
            assert a["account_id"].startswith("ACC-")
            assert a["company_id"].startswith("COMP-")

    # Patterns
    with open(OUTPUT_DIR / "seven_patterns.csv", newline="", encoding="utf-8") as f:
        patterns = list(csv.DictReader(f))
        for p in patterns:
            assert p["pattern_id"].startswith("PAT-")
            assert p["company_id"].startswith("COMP-")

    # Issues
    with open(OUTPUT_DIR / "validation_issues.csv", newline="", encoding="utf-8") as f:
        issues = list(csv.DictReader(f))
        for i in issues:
            assert i["issue_id"].startswith("ISS-")
            assert i["company_id"].startswith("COMP-")
