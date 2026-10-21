"""
Integrity and relational consistency tests:
- Unique primary keys across all 6 tables
- Valid company foreign keys
- Count reconciliation (including Sherwin & Exxon forward signal discrepancy)
- Seven distinct pattern numbers & PDF-derived pattern text
- Audit-status mutation test
- Duplicate signals & accounts verification
"""
import copy
import csv
from pathlib import Path
import pytest

from src.pdf_loader import load_pdf_pages
from src.extractor import PatternReportExtractor

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output"
INPUT_DIR = Path(__file__).resolve().parent.parent / "input"


def test_unique_primary_keys(extracted_records):
    # 1. companies_summary: company_id unique
    with open(OUTPUT_DIR / "companies_summary.csv", newline="", encoding="utf-8") as f:
        comp_ids = [r["company_id"] for r in csv.DictReader(f)]
        assert len(comp_ids) == len(set(comp_ids)) == 3

    # 2. forward_signals: signal_id unique
    with open(OUTPUT_DIR / "forward_signals.csv", newline="", encoding="utf-8") as f:
        sig_ids = [r["signal_id"] for r in csv.DictReader(f)]
        assert len(sig_ids) == len(set(sig_ids)) == 12

    # 3. public_accounts: account_id unique
    with open(OUTPUT_DIR / "public_accounts.csv", newline="", encoding="utf-8") as f:
        acc_ids = [r["account_id"] for r in csv.DictReader(f)]
        assert len(acc_ids) == len(set(acc_ids)) == 21

    # 4. seven_patterns: pattern_id unique
    with open(OUTPUT_DIR / "seven_patterns.csv", newline="", encoding="utf-8") as f:
        pat_ids = [r["pattern_id"] for r in csv.DictReader(f)]
        assert len(pat_ids) == len(set(pat_ids)) == 21

    # 5. validation_issues: issue_id unique
    with open(OUTPUT_DIR / "validation_issues.csv", newline="", encoding="utf-8") as f:
        iss_ids = [r["issue_id"] for r in csv.DictReader(f)]
        assert len(iss_ids) == len(set(iss_ids))


def test_valid_company_foreign_keys(extracted_records):
    with open(OUTPUT_DIR / "companies_summary.csv", newline="", encoding="utf-8") as f:
        valid_comp_ids = {r["company_id"] for r in csv.DictReader(f)}

    child_files = [
        "field_evidence.csv",
        "forward_signals.csv",
        "public_accounts.csv",
        "seven_patterns.csv",
        "validation_issues.csv",
    ]
    for child in child_files:
        with open(OUTPUT_DIR / child, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                cid = row["company_id"]
                assert cid in valid_comp_ids, f"{child} contains invalid foreign key company_id: {cid}"


def test_count_reconciliation(extracted_records):
    with open(OUTPUT_DIR / "companies_summary.csv", newline="", encoding="utf-8") as f:
        rows = {r["company_id"]: r for r in csv.DictReader(f)}

    # Sherwin-Williams: 6 reported vs 4 extracted -> FALSE
    shw = rows["COMP-SHW"]
    assert shw["forward_signals_reported_count"] == "6"
    assert shw["forward_signals_extracted_count"] == "4"
    assert shw["forward_signals_count_matches"] == "FALSE"
    assert shw["public_accounts_count_matches"] == "TRUE"
    assert shw["seven_patterns_count_matches"] == "TRUE"

    # ExxonMobil: 6 reported vs 4 extracted -> FALSE
    xom = rows["COMP-XOM"]
    assert xom["forward_signals_reported_count"] == "6"
    assert xom["forward_signals_extracted_count"] == "4"
    assert xom["forward_signals_count_matches"] == "FALSE"
    assert xom["public_accounts_count_matches"] == "TRUE"
    assert xom["seven_patterns_count_matches"] == "TRUE"

    # Reliance: 4 reported vs 4 extracted -> TRUE
    rel = rows["COMP-REL"]
    assert rel["forward_signals_reported_count"] == "4"
    assert rel["forward_signals_extracted_count"] == "4"
    assert rel["forward_signals_count_matches"] == "TRUE"

    # Verify discrepancies logged in validation_issues.csv
    with open(OUTPUT_DIR / "validation_issues.csv", newline="", encoding="utf-8") as f:
        issues = list(csv.DictReader(f))
    discrepancy_fields = {(i["company_id"], i["field_name"]) for i in issues if i["issue_type"] == "DISCREPANCY"}
    assert ("COMP-SHW", "forward_signals_count") in discrepancy_fields
    assert ("COMP-XOM", "forward_signals_count") in discrepancy_fields


def test_seven_distinct_pattern_numbers(extracted_records):
    with open(OUTPUT_DIR / "seven_patterns.csv", newline="", encoding="utf-8") as f:
        patterns = list(csv.DictReader(f))

    expected_set = {"01", "02", "03", "04", "05", "06", "07"}
    by_comp = {}
    for p in patterns:
        by_comp.setdefault(p["company_id"], set()).add(p["pattern_number"])

    for cid, num_set in by_comp.items():
        assert num_set == expected_set, f"{cid} does not have exactly 7 distinct pattern numbers: {num_set}"


def test_pdf_derived_pattern_text(extracted_records):
    """
    Confirms that pattern text in seven_patterns.csv comes directly from the PDF text,
    not from static dictionaries.
    """
    for doc in ["Sherwin-Williams Pattern Report.pdf", "Reliance (RIL) Pattern Report.pdf", "ExxonMobil Pattern Report.pdf"]:
        pages = load_pdf_pages(INPUT_DIR / doc)
        full_pdf_text = " ".join(" ".join(p.normalized_text.split()) for p in pages).lower()
        
        cid = "COMP-SHW" if "Sherwin" in doc else ("COMP-REL" if "Reliance" in doc else "COMP-XOM")
        
        with open(OUTPUT_DIR / "seven_patterns.csv", newline="", encoding="utf-8") as f:
            company_patterns = [p for p in csv.DictReader(f) if p["company_id"] == cid]

        for pat in company_patterns:
            # Pattern quote must appear in full PDF text
            # Some quotes have line breaks in PDF; check normalized token sequence
            quote_tokens = pat["quote"].split()
            quote_sub = " ".join(quote_tokens[:5]).lower()
            assert quote_sub in full_pdf_text, (
                f"Pattern quote '{quote_sub}' not found in {doc} text"
            )


def test_audit_status_mutation():
    """
    Confirms that when the 'Status of this copy:' footer is removed/unparsed,
    report_audit_status produces a missing value, PARSING_FAILED status,
    and logs a validation issue.
    """
    pages = load_pdf_pages(INPUT_DIR / "Sherwin-Williams Pattern Report.pdf")
    mutated = copy.deepcopy(pages)
    last_page = mutated[-1]
    last_page.normalized_text = last_page.normalized_text.replace("Status of this copy:", "")

    ext = PatternReportExtractor("Sherwin-Williams Pattern Report.pdf", mutated)
    rec = ext.extract_all()

    audit_fe = rec.fields.get("report_audit_status")
    assert audit_fe is not None
    assert audit_fe.report_native_value is None
    assert audit_fe.standardized_value is None
    assert audit_fe.validation_status == "PARSING_FAILED"
    assert rec.metadata["manual_review_required"] == "TRUE"

    issue_fields = [iss.field_name for iss in rec.validation_issues if iss.issue_type == "PARSING_FAILED"]
    assert "report_audit_status" in issue_fields


def test_no_duplicate_signals_or_accounts(extracted_records):
    # Check signals
    with open(OUTPUT_DIR / "forward_signals.csv", newline="", encoding="utf-8") as f:
        signals = list(csv.DictReader(f))
    sig_seen = set()
    for s in signals:
        key = (s["company_id"], s["headline"].strip().lower())
        assert key not in sig_seen, f"Duplicate signal found: {key}"
        sig_seen.add(key)

    # Check accounts
    with open(OUTPUT_DIR / "public_accounts.csv", newline="", encoding="utf-8") as f:
        accounts = list(csv.DictReader(f))
    acc_seen = set()
    for a in accounts:
        key = (a["company_id"], a["headline"].strip().lower())
        assert key not in acc_seen, f"Duplicate public account found: {key}"
        acc_seen.add(key)
