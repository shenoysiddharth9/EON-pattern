#!/usr/bin/env python3
"""
Generic CLI entry point for extracting standardized data from any EON Pattern Report PDF.
Passes the supplied PDF into the unchanged PatternReportExtractor v1.0.0.
Assigns deterministic temporary company_id and unassigned Wingman info for holdout evaluations.
"""
import argparse
import hashlib
from pathlib import Path
import sys

# Ensure project root is in sys.path
project_root = Path(__file__).resolve().parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.pdf_loader import load_pdf_pages
from src.extractor import PatternReportExtractor
from src.validator import validate_all_policies
from src.csv_writer import CsvWriter
from src.models import WingmanInfo


def run_single_pdf(pdf_path: Path, output_dir: Path):
    if not pdf_path.exists():
        raise FileNotFoundError(f"Target PDF does not exist: {pdf_path}")

    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"[Holdout Runner] Loading PDF: {pdf_path}")
    pages = load_pdf_pages(pdf_path)
    print(f"[Holdout Runner] Loaded {len(pages)} pages.")

    # Instantiate unchanged extractor
    extractor = PatternReportExtractor(filename=pdf_path.name, pages=pages)

    # If company is not pre-mapped in v1.0.0 baseline, assign deterministic temporary ID & unassigned Wingman
    if extractor.company_id == "COMP-UNKNOWN":
        comp_hash = hashlib.sha256(pdf_path.stem.encode("utf-8")).hexdigest()[:6].upper()
        temp_company_id = f"COMP-TMP-{comp_hash}"
        temp_slug = f"TMP{comp_hash[:4]}"
        extractor.company_id = temp_company_id
        extractor.slug = temp_slug
        extractor.wingman = WingmanInfo(tier="UNASSIGNED", source="NOT_PROVIDED")
        print(f"[Holdout Runner] Unmapped company detected. Assigned deterministic temporary ID: {temp_company_id}")

    print(f"[Holdout Runner] Executing extraction with unchanged parser v1.0.0...")
    record = extractor.extract_all()

    print(f"[Holdout Runner] Extracted company: '{record.company_name}' (ID: {record.company_id})")
    print(f"  - Fields: {len(record.fields)}")
    print(f"  - Forward Signals: {len(record.forward_signals)}")
    print(f"  - Public Accounts: {len(record.public_accounts)}")
    print(f"  - Seven Patterns: {len(record.seven_patterns)}")
    print(f"  - Validation Issues: {len(record.validation_issues)}")
    print(f"  - Extraction Review Required: {record.metadata.get('extraction_review_required')}")
    print(f"  - Source Verification Required: {record.metadata.get('source_verification_required')}")
    print(f"  - Analyst Normalization Review Required: {record.metadata.get('analyst_normalization_review_required')}")
    print(f"  - Manual Review Required: {record.metadata.get('manual_review_required')}")
    print(f"  - Manual Review Notes: {record.metadata.get('manual_review_notes')}")

    # Validate policies
    print("[Holdout Runner] Validating policies...")
    valid, violations = validate_all_policies([record])
    if not valid:
        print(f"[Holdout Runner] {len(violations)} policy violations identified:")
        for v in violations:
            print(f"  ! {v}")
    else:
        print("[Holdout Runner] All policy checks passed.")

    # Write CSVs and Review Workbook
    print(f"[Holdout Runner] Writing holdout artifacts to: {output_dir}")
    writer = CsvWriter(output_dir=output_dir)
    paths = writer.write_all([record])
    for name, path in paths.items():
        print(f"  * {name}: {path.name} ({path.stat().st_size} bytes)")

    return record


def main():
    parser = argparse.ArgumentParser(description="Generic EON Pattern Report Holdout Runner v1.1.0")
    parser.add_argument("--pdf", type=Path, required=True, help="Path to EON Pattern Report PDF")
    parser.add_argument("--output", type=Path, default=project_root / "output" / "holdout_v1_1", help="Output directory")
    args = parser.parse_args()

    run_single_pdf(pdf_path=args.pdf, output_dir=args.output)


if __name__ == "__main__":
    main()
