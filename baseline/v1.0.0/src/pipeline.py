"""
Orchestration pipeline for EON Pattern Report extraction.
"""
from pathlib import Path
from typing import List, Optional

from src.pdf_loader import load_pdf_pages
from src.extractor import PatternReportExtractor
from src.validator import validate_all_policies
from src.csv_writer import CsvWriter
from src.models import CompanyRecord

TARGET_PDFS = [
    "Sherwin-Williams Pattern Report.pdf",
    "Reliance (RIL) Pattern Report.pdf",
    "ExxonMobil Pattern Report.pdf",
]


def run_pipeline(input_dir: str | Path, output_dir: str | Path) -> List[CompanyRecord]:
    input_path = Path(input_dir)
    output_path = Path(output_dir)

    print(f"[Pipeline] Scanning input directory: {input_path}")
    records: List[CompanyRecord] = []

    for pdf_name in TARGET_PDFS:
        pdf_file = input_path / pdf_name
        if not pdf_file.exists():
            print(f"[Warning] Target PDF not found: {pdf_file}")
            continue

        print(f"[Pipeline] Processing: {pdf_name}")
        pages = load_pdf_pages(pdf_file)
        extractor = PatternReportExtractor(filename=pdf_name, pages=pages)
        record = extractor.extract_all()
        records.append(record)
        print(f"  -> Extracted '{record.company_name}': {len(record.fields)} fields, "
              f"{len(record.forward_signals)} signals, {len(record.public_accounts)} accounts, "
              f"{len(record.seven_patterns)} patterns.")

    # Validation
    print("[Pipeline] Running policy validation...")
    valid, violations = validate_all_policies(records)
    if not valid:
        print("[Pipeline] Validation violations detected:")
        for v in violations:
            print(f"  - {v}")
    else:
        print("[Pipeline] All policy checks passed successfully!")

    # Write CSVs
    print(f"[Pipeline] Writing 6 CSV files to {output_path}...")
    writer = CsvWriter(output_dir=output_path)
    paths = writer.write_all(records)
    for name, path in paths.items():
        print(f"  - {name}: {path.name} ({path.stat().st_size} bytes)")

    return records
