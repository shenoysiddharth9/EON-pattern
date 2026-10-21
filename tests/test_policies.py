"""
Tests enforcing the user's business rules and integrity policies:
- Zero vs Missing preservation
- No safety performance inference
- Controlled categorical records availability (NO_RECORD_REACHABLE, RECORD_REACHABLE)
- Manual Wingman label segregation
- Disaggregated metrics distinction
"""
import csv
from pathlib import Path
import pytest

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output"

def test_missing_values_preserved_as_missing(extracted_records):
    csv_file = OUTPUT_DIR / "companies_summary.csv"
    with open(csv_file, newline="", encoding="utf-8") as f:
        rows = {r["company_name"]: r for r in csv.DictReader(f)}
    
    reliance = rows["Reliance (RIL)"]
    # Missing founded must be empty, not 0
    assert reliance["year_founded"] == "", "Reliance year_founded must be empty, not '0'"
    # Missing employees must be empty, not 0
    assert reliance["people_employed"] == "", "Reliance people_employed must be empty, not '0'"
    # Missing 10-K date must be empty
    assert reliance["sec_filing_date"] == "", "Reliance sec_filing_date must be empty"

def test_explicit_zeros_preserved_as_zero(extracted_records):
    csv_file = OUTPUT_DIR / "companies_summary.csv"
    with open(csv_file, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    
    for r in rows:
        assert r["citations_count"] == "0", f"{r['company_name']} citations_count must be '0'"
        assert r["penalties_amount"] == "0", f"{r['company_name']} penalties_amount must be '0'"
        assert r["penalties_display_text"] == "$0", f"{r['company_name']} penalties_display_text must be '$0'"
        assert r["investigated_accidents_count"] == "0", f"{r['company_name']} accidents must be '0'"
        assert r["deaths_count"] == "0", f"{r['company_name']} deaths_count must be '0'"

def test_categorical_availability_controlled_values(extracted_records):
    csv_file = OUTPUT_DIR / "companies_summary.csv"
    with open(csv_file, newline="", encoding="utf-8") as f:
        rows = {r["company_name"]: r for r in csv.DictReader(f)}
    
    for comp in ["Reliance (RIL)", "ExxonMobil"]:
        avail = rows[comp]["official_records_availability"]
        assert avail != "0", f"{comp} official_records_availability must NOT be numeric '0'"
        assert avail == "NO_RECORD_REACHABLE", f"{comp} expected 'NO_RECORD_REACHABLE', got '{avail}'"

    sherwin_avail = rows["Sherwin-Williams"]["official_records_availability"]
    assert sherwin_avail == "NOT_REPORTED", f"Sherwin-Williams expected 'NOT_REPORTED', got '{sherwin_avail}'"
    assert rows["Sherwin-Williams"]["registry_search_status"] == "SEARCH_EXECUTED"
    assert rows["Sherwin-Williams"]["official_company_record_found"] == "FALSE"

def test_safety_non_inference_policy(extracted_records):
    csv_file = OUTPUT_DIR / "companies_summary.csv"
    with open(csv_file, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    
    for r in rows:
        inference_val = r["safety_performance_inference"]
        assert "CANNOT_INFER_SAFE" in inference_val, (
            f"{r['company_name']} must explicitly declare CANNOT_INFER_SAFE"
        )
        assert r["regulatory_record_status"] == "Thin Case — No official safety records found"

def test_manual_wingman_labels_and_segregation(extracted_records):
    csv_file = OUTPUT_DIR / "companies_summary.csv"
    with open(csv_file, newline="", encoding="utf-8") as f:
        rows = {r["company_name"]: r for r in csv.DictReader(f)}
    
    assert rows["ExxonMobil"]["wingman_tier"] == "Tier 1"
    assert rows["Reliance (RIL)"]["wingman_tier"] == "Tier 2"
    assert rows["Sherwin-Williams"]["wingman_tier"] == "Tier 3"

    for r in rows.values():
        assert r["wingman_source"] == "manual_from_trigger_board"

def test_disaggregated_metrics_distinction(extracted_records):
    csv_file = OUTPUT_DIR / "companies_summary.csv"
    with open(csv_file, newline="", encoding="utf-8") as f:
        rows = {r["company_name"]: r for r in csv.DictReader(f)}
    
    shw = rows["Sherwin-Williams"]
    assert shw["public_sources_cited"] == "1"
    assert shw["records_proven"] == "0"
    assert shw["open_information_count"] == "1"
    assert shw["press_reported_account_count"] == "6"
    assert shw["forward_looking_press_count"] == "6"
    assert shw["header_publicly_written_accounts"] == ""

    rel = rows["Reliance (RIL)"]
    assert rel["header_publicly_written_accounts"] == "2"
    assert rel["open_information_count"] == "1"
    assert rel["press_reported_account_count"] == "1"
    assert rel["forward_looking_press_count"] == "4"
    assert rel["public_sources_cited"] == ""
    assert rel["records_proven"] == ""

    xom = rows["ExxonMobil"]
    assert xom["header_publicly_written_accounts"] == "12"
    assert xom["open_information_count"] == "6"
    assert xom["press_reported_account_count"] == "6"
    assert xom["forward_looking_press_count"] == "6"
    assert xom["public_sources_cited"] == ""
    assert xom["records_proven"] == ""


def test_split_review_flags(extracted_records):
    csv_file = OUTPUT_DIR / "companies_summary.csv"
    with open(csv_file, newline="", encoding="utf-8") as f:
        rows = {r["company_name"]: r for r in csv.DictReader(f)}

    for comp in ["Sherwin-Williams", "Reliance (RIL)", "ExxonMobil"]:
        # "Do not mark extraction review as required merely because unverified public accounts exist."
        assert rows[comp]["extraction_review_required"] == "FALSE"
        # All three have unverified public accounts
        assert rows[comp]["source_verification_required"] == "TRUE"

    # Sherwin-Williams has line_of_work normalized from narrative text
    assert rows["Sherwin-Williams"]["analyst_normalization_review_required"] == "TRUE"
    # Reliance and Exxon have native cards
    assert rows["Reliance (RIL)"]["analyst_normalization_review_required"] == "FALSE"
    assert rows["ExxonMobil"]["analyst_normalization_review_required"] == "FALSE"


def test_headcount_source_and_card_metadata(extracted_records):
    csv_file = OUTPUT_DIR / "field_evidence.csv"
    with open(csv_file, newline="", encoding="utf-8") as f:
        emp_evidence = {r["company_name"]: r for r in csv.DictReader(f) if r["field_name"] == "people_employed"}

    # Sherwin-Williams: 64,249 extracted from annual-report quote
    shw = emp_evidence["Sherwin-Williams"]
    assert shw["report_native_value"] == "64,249"
    assert shw["standardized_value"] == "64249"
    assert shw["page_number"] == "7"
    assert shw["is_analyst_assigned"] == "FALSE"
    assert shw["source_type"] == "ANNUAL_REPORT_QUOTE"
    assert shw["source_date"] == "2025-12-31"
    assert shw["value_context"] == "worldwide employees"
    assert shw["profile_card_present"] == "FALSE"
    assert shw["validation_status"] == "VALID"

    # ExxonMobil: 74,900 from page 1 profile card
    xom = emp_evidence["ExxonMobil"]
    assert xom["report_native_value"] == "74,900"
    assert xom["standardized_value"] == "74900"
    assert xom["page_number"] == "1"
    assert xom["is_analyst_assigned"] == "FALSE"
    assert xom["source_type"] == "PROFILE_CARD"
    assert xom["profile_card_present"] == "TRUE"
    assert xom["validation_status"] == "VALID"

    # Reliance: missing/not reported
    rel = emp_evidence["Reliance (RIL)"]
    assert rel["report_native_value"] == ""
    assert rel["standardized_value"] == ""
    assert rel["profile_card_present"] == "FALSE"
    assert rel["validation_status"] == "MISSING_NOT_REPORTED"


def test_outcome_cards_evidence_page_three(extracted_records):
    """
    Asserts that citations, penalties, investigated accidents, and deaths
    cite Page 3 as their primary evidence page across all three reports.
    """
    csv_file = OUTPUT_DIR / "field_evidence.csv"
    with open(csv_file, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    target_fields = {
        "citations_count", "penalties_amount", "penalties_display_text",
        "investigated_accidents_count", "deaths_count"
    }

    for r in rows:
        if r["field_name"] in target_fields:
            assert r["page_number"] == "3", (
                f"{r['company_name']}.{r['field_name']} primary evidence page must be 3, got '{r['page_number']}'"
            )

