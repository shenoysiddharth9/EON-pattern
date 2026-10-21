"""
Comprehensive test suite for Parser Version 1.1.0 features:
- Dynamic company-name candidate hierarchy and consensus
- Ambiguity resolution (conflicting candidates produce AMBIGUOUS, missing std_val, review required)
- Filename fallback semantics (source_type=FILENAME_FALLBACK, confidence=LOW, extraction_review_required=TRUE)
- Generic narrative line-of-work and business-description extraction
- Dynamic country evidence isolation (no cross-company contamination)
- Multiline disclaimer stripping without deleting legitimate text containing 'organisation'
- Multiline benchmark reconstruction and qualifier segregation
- The Seven macro status: ALL_PATTERNS_SILENT when all 7 individual patterns are silent
- Derived public-account totals (DERIVED_RECONCILIATION, COMPONENT_SUM)
- Negative synthetic text mutations ensuring 0 is never assigned on regex/parsing failure
"""
import pytest
from pathlib import Path
import re
from unittest.mock import MagicMock

from src.models import PARSER_VERSION, FieldEvidence, PublicAccount, SevenPattern
from src.pdf_loader import PageData
from src.extractor import PatternReportExtractor


def test_candidate_company_name_consensus():
    p1_text = (
        "E O N  A I  V E N T U R E S    ·    T H E  P A T T E R N  R E P O R T\n"
        "Acme Global\n"
        "Your own safety record, assembled in one place\n"
        "About Acme Global\n"
        "Acme Global is an American technology enterprise.\n"
    )
    pages = [PageData(page_number=1, raw_text=p1_text, normalized_text=p1_text)]
    extractor = PatternReportExtractor("Acme-Report.pdf", pages)
    name, evid, conf, status, src_type = extractor._detect_company_name_candidates()

    assert name == "Acme Global"
    assert status == "VALID"
    assert conf == "HIGH"
    assert src_type in ["REPORT_HEADER", "CONSENSUS"]
    assert "Candidate consensus" in evid


def test_conflicting_candidates_produce_ambiguous():
    p1_text = (
        "E O N  A I  V E N T U R E S    ·    T H E  P A T T E R N  R E P O R T\n"
        "First Entity Name\n"
        "Your own safety record, assembled in one place\n"
        "About Second Entity Name\n"
        "Second Entity Name is an American enterprise.\n"
    )
    pages = [PageData(page_number=1, raw_text=p1_text, normalized_text=p1_text)]
    extractor = PatternReportExtractor("Report.pdf", pages)
    extractor.extract_all()

    fe = extractor.fields["company_name"]
    assert fe.validation_status == "AMBIGUOUS"
    assert fe.standardized_value is None
    assert extractor.extraction_review_required == "TRUE"
    assert any(iss.issue_type == "AMBIGUOUS" for iss in extractor.validation_issues)


def test_filename_fallback_when_report_candidates_absent():
    p1_text = "E O N  A I  V E N T U R E S\nGeneric document without headers or about section."
    pages = [PageData(page_number=1, raw_text=p1_text, normalized_text=p1_text)]
    extractor = PatternReportExtractor("Delta-Pacific-Holdings-Pattern-Report-2.pdf", pages)
    name, evid, conf, status, src_type = extractor._detect_company_name_candidates()

    assert name == "Delta Pacific Holdings"
    assert src_type == "FILENAME_FALLBACK"
    assert conf == "LOW"
    assert status == "VALID"

    extractor.extract_all()
    assert extractor.extraction_review_required == "TRUE"
    assert any("FILENAME_FALLBACK" in r for r in extractor.manual_review_reasons)


def test_generic_line_of_work_and_business_description():
    p1_text = (
        "E O N  A I  V E N T U R E S    ·    T H E  P A T T E R N  R E P O R T\n"
        "Solaris Tech\n"
        "Your own safety record, assembled in one place\n"
        "About Solaris Tech\n"
        "Solaris Tech, Corp. is an American renewable energy provider. "
        "It specializes in owning and controlling solar power facilities across the southwest.\n"
        "5,000\npeople employed\nAustin\nhead office\n2010\nfounded\n"
    )
    pages = [PageData(page_number=1, raw_text=p1_text, normalized_text=p1_text)]
    extractor = PatternReportExtractor("Solaris-Report.pdf", pages)
    extractor.extract_all()

    low_fe = extractor.fields["line_of_work"]
    assert low_fe.report_native_value == "renewable energy"
    assert low_fe.standardized_value == "Renewable energy"
    assert low_fe.is_analyst_assigned is True

    desc_fe = extractor.fields["business_description"]
    assert desc_fe.standardized_value == "It specializes in owning and controlling solar power facilities across the southwest."
    assert desc_fe.is_analyst_assigned is False


def test_no_cross_company_contamination_for_country():
    p1_text = (
        "E O N  A I  V E N T U R E S    ·    T H E  P A T T E R N  R E P O R T\n"
        "Northern Pacific\n"
        "Your own safety record, assembled in one place\n"
        "About Northern Pacific\n"
        "Northern Pacific is an American logistics corporation.\n"
        "1,000\npeople employed\nSeattle\nhead office\n"
    )
    pages = [PageData(page_number=1, raw_text=p1_text, normalized_text=p1_text)]
    extractor = PatternReportExtractor("NP-Report.pdf", pages)
    extractor.extract_all()

    hq = extractor.fields["headquarters_country"]
    assert hq.standardized_value == "United States"
    assert "Northern Pacific" in hq.source_evidence
    assert "Sherwin-Williams" not in hq.source_evidence
    assert "ExxonMobil" not in hq.source_evidence


def test_multiline_disclaimer_stripping_and_outlet_preservation():
    block = [
        "2024 Fire",
        "Pipeline rupture sparks warehouse fire in regional terminal",
        "The organisation's logistics team worked with county responders to contain the incident.",
        "Reported by pgjonline.com. Not verified, and not treated as a fact about your",
        "organisation.",
        "Read the source →",
    ]
    extractor = PatternReportExtractor("Test-Report.pdf", [])
    acc = extractor._parse_public_account_block(block, idx=1, page_num=7)

    assert acc is not None
    assert acc.source_outlet == "pgjonline.com"
    assert acc.year == "2024"
    assert acc.tag == "Fire"
    assert "The organisation's logistics team worked with county responders to contain the incident." in acc.description_snippet
    assert "Not verified" not in acc.description_snippet
    assert "Reported by" not in acc.description_snippet
    assert acc.raw_evidence == "\n".join(block)


def test_the_seven_all_patterns_silent_and_qualifier():
    from src.pdf_loader import load_pdf_pages
    pdf_path = Path(__file__).resolve().parent.parent / "input" / "holdout" / "Kinder-Morgan-Pattern-Report-4.pdf"
    pages = load_pdf_pages(pdf_path)
    extractor = PatternReportExtractor("Kinder-Morgan-Pattern-Report-4.pdf", pages)
    extractor._extract_the_seven_patterns()

    overall = extractor.fields["the_seven_overall_status"]
    assert overall.standardized_value == "ALL_PATTERNS_SILENT"

    p3 = extractor.seven_patterns[2]
    assert p3.sector_benchmark_qualifier == "Presence rate, not a share of causes."

    p7 = extractor.seven_patterns[6]
    assert p7.sector_benchmark_qualifier == "Offshore benchmark. Do not present as an onshore figure."


def test_derived_public_accounts_reconciliation():
    pages = [PageData(page_number=1, raw_text="", normalized_text="")]
    extractor = PatternReportExtractor("Test-Report.pdf", pages)
    extractor._add_field("open_information_count", "5", "5", "Build stats", 8, "HIGH", "VALID")
    extractor._add_field("press_reported_account_count", "6", "6", "Build stats", 8, "HIGH", "VALID")
    extractor.public_accounts = [MagicMock() for _ in range(11)]

    extractor._reconcile_counts()

    rep_fe = extractor.fields["public_accounts_reported_count"]
    assert rep_fe.report_native_value is None
    assert rep_fe.standardized_value == "11"
    assert rep_fe.validation_status == "DERIVED_RECONCILIATION"
    assert rep_fe.derivation_method == "COMPONENT_SUM"
    assert rep_fe.derivation_components == "open_information_count=5;press_reported_account_count=6"
    assert extractor.fields["public_accounts_count_matches"].standardized_value == "TRUE"


def test_strict_zero_fallback_never_assigns_zero_on_missing_metric():
    p3_text = "The shape of the record\nReport text with missing metrics cards."
    pages = [PageData(page_number=3, raw_text=p3_text, normalized_text=p3_text)]
    extractor = PatternReportExtractor("Test-Report.pdf", pages)
    extractor._extract_regulatory_outcomes()

    assert extractor.fields["citations_count"].standardized_value is None
    assert extractor.fields["citations_count"].validation_status == "PARSING_FAILED"

    assert extractor.fields["penalties_amount"].standardized_value is None
    assert extractor.fields["penalties_amount"].validation_status == "PARSING_FAILED"

    assert extractor.fields["investigated_accidents_count"].standardized_value is None
    assert extractor.fields["investigated_accidents_count"].validation_status == "PARSING_FAILED"

    assert extractor.fields["deaths_count"].standardized_value is None
    assert extractor.fields["deaths_count"].validation_status == "PARSING_FAILED"
