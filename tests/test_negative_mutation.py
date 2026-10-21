"""
Negative and mutation tests confirming that parser failure produces MISSING values,
NOT numeric zero, in strict compliance with policy.
"""
import copy
import pytest
from src.pdf_loader import PageData
from src.extractor import PatternReportExtractor
from src.csv_writer import CsvWriter

@pytest.fixture
def base_pages(extracted_records):
    # Use ExxonMobil pages as base
    from src.pdf_loader import load_pdf_pages
    from pathlib import Path
    pdf_path = Path(__file__).resolve().parent.parent / "input" / "ExxonMobil Pattern Report.pdf"
    return load_pdf_pages(pdf_path)

def test_missing_citations_produces_missing_not_zero(base_pages):
    """
    Deliberately strip out 'citations' metric text.
    Must produce missing (None / empty string), NOT zero.
    Must flag PARSING_FAILED and manual_review_required = TRUE.
    """
    mutated_pages = copy.deepcopy(base_pages)
    # Page 3 has citations card
    p3 = mutated_pages[2]
    # Remove citations line
    p3.normalized_text = p3.normalized_text.replace("0\ncitations", "").replace("citations", "")

    extractor = PatternReportExtractor("ExxonMobil Pattern Report.pdf", mutated_pages)
    rec = extractor.extract_all()

    cit_fe = rec.fields.get("citations_count")
    assert cit_fe is not None
    assert cit_fe.report_native_value is None, f"Expected None, got {cit_fe.report_native_value}"
    assert cit_fe.standardized_value is None, f"Expected None, got {cit_fe.standardized_value}"
    assert cit_fe.validation_status == "PARSING_FAILED"
    assert rec.metadata["manual_review_required"] == "TRUE"

    # Confirm it is logged in validation issues
    issue_fields = [iss.field_name for iss in rec.validation_issues if iss.issue_type == "PARSING_FAILED"]
    assert "citations_count" in issue_fields

def test_missing_penalties_produces_missing_not_zero(base_pages):
    """
    Deliberately strip out '$0 in penalties' metric text.
    Must produce missing (None / empty string), NOT zero.
    """
    mutated_pages = copy.deepcopy(base_pages)
    p3 = mutated_pages[2]
    p3.normalized_text = p3.normalized_text.replace("$0\nin penalties", "").replace("penalties", "")

    extractor = PatternReportExtractor("ExxonMobil Pattern Report.pdf", mutated_pages)
    rec = extractor.extract_all()

    pen_fe = rec.fields.get("penalties_amount")
    assert pen_fe is not None
    assert pen_fe.report_native_value is None, f"Expected None, got {pen_fe.report_native_value}"
    assert pen_fe.standardized_value is None, f"Expected None, got {pen_fe.standardized_value}"
    assert pen_fe.validation_status == "PARSING_FAILED"

    disp_fe = rec.fields.get("penalties_display_text")
    assert disp_fe.standardized_value is None
    assert disp_fe.validation_status == "PARSING_FAILED"

def test_missing_accidents_and_deaths_produces_missing_not_zero(base_pages):
    """
    Deliberately strip out investigated accidents and deaths.
    Must produce missing (None), NOT zero.
    """
    mutated_pages = copy.deepcopy(base_pages)
    p3 = mutated_pages[2]
    p3.normalized_text = (
        p3.normalized_text
        .replace("0\ninvestigated accidents", "")
        .replace("investigated accidents", "")
        .replace("0\ndeaths", "")
        .replace("deaths", "")
    )

    extractor = PatternReportExtractor("ExxonMobil Pattern Report.pdf", mutated_pages)
    rec = extractor.extract_all()

    acc_fe = rec.fields.get("investigated_accidents_count")
    assert acc_fe.standardized_value is None
    assert acc_fe.validation_status == "PARSING_FAILED"

    death_fe = rec.fields.get("deaths_count")
    assert death_fe.standardized_value is None
    assert death_fe.validation_status == "PARSING_FAILED"

def test_missing_osha_csb_produces_missing_not_zero(base_pages):
    """
    Deliberately strip out OSHA and CSB build statistics lines.
    Must produce missing (None), NOT zero.
    """
    mutated_pages = copy.deepcopy(base_pages)
    # Page 8 has HOW IT WAS BUILT
    p8 = mutated_pages[7]
    p8.normalized_text = p8.normalized_text.replace("OSHA: 0 inspection(s)", "").replace("CSB: 0 published items", "")

    extractor = PatternReportExtractor("ExxonMobil Pattern Report.pdf", mutated_pages)
    rec = extractor.extract_all()

    osha_fe = rec.fields.get("osha_inspections_found")
    assert osha_fe.standardized_value is None
    assert osha_fe.validation_status == "PARSING_FAILED"

    csb_fe = rec.fields.get("csb_mentions_found")
    assert csb_fe.standardized_value is None
    assert csb_fe.validation_status == "PARSING_FAILED"
