"""
Tests validating field evidence, page citations, confidence ratings, and validation statuses.
"""
import csv
from pathlib import Path
import pytest

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output"

def test_field_evidence_completeness(extracted_records):
    csv_file = OUTPUT_DIR / "field_evidence.csv"
    with open(csv_file, newline="", encoding="utf-8") as f:
        evidence_rows = list(csv.DictReader(f))
    
    # 46 fields x 3 companies = 138 rows (including business_description)
    assert len(evidence_rows) == 138, f"Expected 138 evidence rows, got {len(evidence_rows)}"
    
    valid_statuses = {
        "VALID", "EXPLICIT_ZERO", "MISSING_NOT_REPORTED",
        "CATEGORICAL_UNAVAILABLE", "STANDARDIZED_ASSERTION", "PARSING_FAILED",
        "DERIVED_RECONCILIATION"
    }
    
    for row in evidence_rows:
        assert row["company_name"] in ["Sherwin-Williams", "Reliance (RIL)", "ExxonMobil"]
        assert row["company_id"].startswith("COMP-")
        assert row["field_name"].strip() != ""
        assert row["confidence"] in ["HIGH", "MEDIUM", "LOW"]
        assert row["validation_status"] in valid_statuses
        assert row["is_analyst_assigned"] in ["TRUE", "FALSE"]
        assert row["source_evidence"].strip() != "", f"Empty evidence for {row['company_name']} -> {row['field_name']}"

        if row["validation_status"] in ["VALID", "EXPLICIT_ZERO", "CATEGORICAL_UNAVAILABLE", "STANDARDIZED_ASSERTION"]:
            if row["page_number"] != "":
                p_num = int(row["page_number"])
                assert p_num >= 1, f"Invalid page number: {p_num}"

        if row["validation_status"] in ["MISSING_NOT_REPORTED", "PARSING_FAILED"]:
            if row["field_name"] == "official_records_availability":
                assert row["standardized_value"] in ["NOT_REPORTED", "PARSING_FAILED"]
            else:
                assert row["standardized_value"] == "", (
                    f"Missing/failed field {row['company_name']}.{row['field_name']} must have empty standardized_value, got '{row['standardized_value']}'"
                )


def test_all_populated_evidence_pages_contain_native_or_source_fragment(extracted_records):
    """
    Asserts that every populated evidence page contains the report-native value
    or its captured source fragment. Prevents incorrect page citations.
    """
    import re
    from src.pdf_loader import load_pdf_pages
    input_dir = Path(__file__).resolve().parent.parent / "input"
    
    with open(OUTPUT_DIR / "field_evidence.csv", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    docs = {
        "Sherwin-Williams Pattern Report.pdf": load_pdf_pages(input_dir / "Sherwin-Williams Pattern Report.pdf"),
        "Reliance (RIL) Pattern Report.pdf": load_pdf_pages(input_dir / "Reliance (RIL) Pattern Report.pdf"),
        "ExxonMobil Pattern Report.pdf": load_pdf_pages(input_dir / "ExxonMobil Pattern Report.pdf"),
    }

    failures = []
    for doc_name, pages in docs.items():
        page_texts = {p.page_number: " ".join(p.normalized_text.split()).lower() for p in pages}
        doc_rows = [r for r in rows if r["source_pdf_filename"] == doc_name]
        for r in doc_rows:
            p_str = r["page_number"].strip()
            if not p_str:
                continue
            p_num = int(p_str)
            assert p_num in page_texts, f"{doc_name}: page {p_num} out of range"
            p_txt = page_texts[p_num]
            
            native = " ".join(r["report_native_value"].split()).lower() if r["report_native_value"] else ""
            quotes = re.findall(r"'([^']*)'", r["source_evidence"])
            
            match_found = False
            if native and native in p_txt:
                match_found = True
            else:
                for q in quotes:
                    clean_q = " ".join(q.split()).lower()
                    if clean_q and clean_q in p_txt:
                        match_found = True
                        break
            if not match_found:
                failures.append(f"{doc_name} field '{r['field_name']}' on page {p_num} (native='{native}', quotes={quotes}) not found on page text")

    assert len(failures) == 0, f"Page citation failures:\n" + "\n".join(failures)

