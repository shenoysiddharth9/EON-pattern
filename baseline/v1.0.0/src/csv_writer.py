"""
CSV and Review Workbook Exporters for EON Pattern Report extraction.
Produces:
1. companies_summary.csv
2. field_evidence.csv
3. forward_signals.csv
4. public_accounts.csv
5. seven_patterns.csv
6. validation_issues.csv
7. manual_review_workbook.md (Comprehensive audit table for human reviewers)
"""
import csv
from pathlib import Path
from typing import List, Dict, Any

from src.models import CompanyRecord

COMPANIES_SUMMARY_HEADERS = [
    # Uniform Metadata & Tracking
    "parser_version",
    "extraction_timestamp",
    "source_pdf_filename",
    "company_id",
    "company_name",
    "extraction_review_required",
    "source_verification_required",
    "analyst_normalization_review_required",
    "manual_review_required",
    "manual_review_notes",
    # Manual Wingman (strictly segregated)
    "wingman_tier",
    "wingman_source",
    # Company Profile
    "headquarters_city",
    "headquarters_country",
    "report_geography",
    "operating_countries",
    "year_founded",
    "people_employed",
    "line_of_work",
    "headcount_source_type",
    "headcount_source_date",
    "headcount_value_context",
    "headcount_profile_card_present",
    # Top Header Metrics
    "report_window",
    "header_basis_of_report",
    "official_records_availability",
    "registry_search_status",
    "official_company_record_found",
    "header_publicly_written_accounts",
    "public_sources_cited",
    "records_proven",
    "answered_by_record",
    # Build Stats ("HOW IT WAS BUILT")
    "open_information_count",
    "press_reported_account_count",
    "forward_looking_press_count",
    "osha_inspections_found",
    "csb_mentions_found",
    # Count Reconciliations
    "forward_signals_reported_count",
    "forward_signals_extracted_count",
    "forward_signals_count_matches",
    "public_accounts_reported_count",
    "public_accounts_extracted_count",
    "public_accounts_count_matches",
    "seven_patterns_reported_count",
    "seven_patterns_extracted_count",
    "seven_patterns_count_matches",
    # Official Regulatory Totals (Explicit Outcome Counts)
    "citations_count",
    "penalties_amount",
    "penalties_currency_symbol",
    "penalties_currency_iso",
    "penalties_display_text",
    "investigated_accidents_count",
    "deaths_count",
    # SEC / Annual Report
    "sec_annual_report_status",
    "sec_filing_date",
    # The Seven & Policy Disclaimers
    "the_seven_answered_count",
    "the_seven_overall_status",
    "regulatory_record_status",
    "safety_performance_inference",
    "report_audit_status",
]


class CsvWriter:
    def __init__(self, output_dir: str | Path):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def write_all(self, records: List[CompanyRecord]) -> Dict[str, Path]:
        paths = {
            "companies_summary": self.write_companies_summary(records),
            "field_evidence": self.write_field_evidence(records),
            "forward_signals": self.write_forward_signals(records),
            "public_accounts": self.write_public_accounts(records),
            "seven_patterns": self.write_seven_patterns(records),
            "validation_issues": self.write_validation_issues(records),
            "manual_review_workbook": self.write_manual_review_workbook(records),
        }
        return paths

    def write_companies_summary(self, records: List[CompanyRecord]) -> Path:
        out_path = self.output_dir / "companies_summary.csv"
        with open(out_path, mode="w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=COMPANIES_SUMMARY_HEADERS)
            writer.writeheader()
            for rec in records:
                emp_fe = rec.fields.get("people_employed")
                p_card_str = ""
                if emp_fe and emp_fe.profile_card_present is True:
                    p_card_str = "TRUE"
                elif emp_fe and emp_fe.profile_card_present is False:
                    p_card_str = "FALSE"

                row: Dict[str, Any] = {
                    "parser_version": rec.metadata.get("parser_version", ""),
                    "extraction_timestamp": rec.metadata.get("extraction_timestamp", ""),
                    "source_pdf_filename": rec.source_pdf_filename,
                    "company_id": rec.company_id,
                    "company_name": rec.company_name,
                    "extraction_review_required": rec.metadata.get("extraction_review_required", "FALSE"),
                    "source_verification_required": rec.metadata.get("source_verification_required", "FALSE"),
                    "analyst_normalization_review_required": rec.metadata.get("analyst_normalization_review_required", "FALSE"),
                    "manual_review_required": rec.metadata.get("manual_review_required", ""),
                    "manual_review_notes": rec.metadata.get("manual_review_notes", ""),
                    "wingman_tier": rec.wingman.tier,
                    "wingman_source": rec.wingman.source,
                    "headcount_source_type": emp_fe.source_type if (emp_fe and emp_fe.source_type) else "",
                    "headcount_source_date": emp_fe.source_date if (emp_fe and emp_fe.source_date) else "",
                    "headcount_value_context": emp_fe.value_context if (emp_fe and emp_fe.value_context) else "",
                    "headcount_profile_card_present": p_card_str,
                }
                for col in COMPANIES_SUMMARY_HEADERS:
                    if col in row:
                        continue
                    fe = rec.fields.get(col)
                    val = fe.standardized_value if (fe and fe.standardized_value is not None) else ""
                    row[col] = val
                writer.writerow(row)
        return out_path

    def write_field_evidence(self, records: List[CompanyRecord]) -> Path:
        out_path = self.output_dir / "field_evidence.csv"
        fieldnames = [
            "parser_version",
            "extraction_timestamp",
            "source_pdf_filename",
            "company_id",
            "company_name",
            "field_name",
            "report_native_value",
            "standardized_value",
            "source_evidence",
            "page_number",
            "confidence",
            "validation_status",
            "is_analyst_assigned",
            "source_type",
            "source_date",
            "value_context",
            "profile_card_present",
        ]
        with open(out_path, mode="w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for rec in records:
                for _, fe in rec.fields.items():
                    writer.writerow(fe.to_dict())
        return out_path

    def write_forward_signals(self, records: List[CompanyRecord]) -> Path:
        out_path = self.output_dir / "forward_signals.csv"
        fieldnames = [
            "parser_version",
            "extraction_timestamp",
            "source_pdf_filename",
            "company_id",
            "company_name",
            "signal_id",
            "signal_index",
            "headline",
            "reported_by",
            "implication_text",
            "page_number",
            "source_category",
        ]
        with open(out_path, mode="w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for rec in records:
                for sig in rec.forward_signals:
                    writer.writerow(sig.to_dict())
        return out_path

    def write_public_accounts(self, records: List[CompanyRecord]) -> Path:
        out_path = self.output_dir / "public_accounts.csv"
        fieldnames = [
            "parser_version",
            "extraction_timestamp",
            "source_pdf_filename",
            "company_id",
            "company_name",
            "account_id",
            "account_index",
            "year",
            "tag",
            "headline",
            "source_outlet",
            "description_snippet",
            "page_number",
            "official_status",
        ]
        with open(out_path, mode="w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for rec in records:
                for acc in rec.public_accounts:
                    writer.writerow(acc.to_dict())
        return out_path

    def write_seven_patterns(self, records: List[CompanyRecord]) -> Path:
        out_path = self.output_dir / "seven_patterns.csv"
        fieldnames = [
            "parser_version",
            "extraction_timestamp",
            "source_pdf_filename",
            "company_id",
            "company_name",
            "pattern_id",
            "pattern_number",
            "pattern_name",
            "quote",
            "company_record_status",
            "solution_closed_by",
            "sector_benchmark_summary",
            "sector_benchmark_source",
            "page_number",
        ]
        with open(out_path, mode="w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for rec in records:
                for pat in rec.seven_patterns:
                    writer.writerow(pat.to_dict())
        return out_path

    def write_validation_issues(self, records: List[CompanyRecord]) -> Path:
        out_path = self.output_dir / "validation_issues.csv"
        fieldnames = [
            "parser_version",
            "extraction_timestamp",
            "source_pdf_filename",
            "company_id",
            "company_name",
            "issue_id",
            "field_name",
            "issue_type",
            "description",
            "report_native_fragment",
            "page_number",
            "resolution_proposed",
        ]
        with open(out_path, mode="w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for rec in records:
                for iss in rec.validation_issues:
                    writer.writerow(iss.to_dict())
        return out_path

    def write_manual_review_workbook(self, records: List[CompanyRecord]) -> Path:
        out_path = self.output_dir / "manual_review_workbook.md"
        with open(out_path, mode="w", encoding="utf-8") as f:
            f.write("# EON Pattern Report - Manual Review Workbook\n\n")
            f.write("This review workbook details every extracted record alongside its verbatim source evidence and PDF page number.\n\n")
            
            for rec in records:
                f.write(f"## {rec.company_name} ({rec.company_id})\n\n")
                f.write(f"- **Source File**: `{rec.source_pdf_filename}`\n")
                f.write(f"- **Wingman Tier**: `{rec.wingman.tier}` (`{rec.wingman.source}`)\n")
                f.write(f"- **Manual Review Required**: `{rec.metadata.get('manual_review_required')}`\n")
                f.write(f"- **Manual Review Notes**: {rec.metadata.get('manual_review_notes')}\n\n")
                
                # Summary Fields Table
                f.write("### 1. Standardized Field Audit Trail\n\n")
                f.write("| Field Name | Report Native Value | Standardized Value | Page | Confidence | Status | Analyst Assigned | Source Evidence |\n")
                f.write("| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :--- |\n")
                for _, fe in rec.fields.items():
                    nat = f"`{fe.report_native_value}`" if fe.report_native_value else "*[Empty]*"
                    std = f"`{fe.standardized_value}`" if fe.standardized_value else "*[Empty]*"
                    pg = str(fe.page_number) if fe.page_number else "-"
                    ev = fe.source_evidence.replace("|", "\\|").replace("\n", " ")
                    f.write(f"| `{fe.field_name}` | {nat} | {std} | {pg} | {fe.confidence} | `{fe.validation_status}` | {'YES' if fe.is_analyst_assigned else 'NO'} | {ev} |\n")
                f.write("\n")

                # Forward Signals Table
                f.write("### 2. Forward Signals (WHAT YOU ARE BUILDING)\n\n")
                f.write("| Signal ID | Page | Reported By | Headline | Implication |\n")
                f.write("| :--- | :---: | :--- | :--- | :--- |\n")
                for sig in rec.forward_signals:
                    f.write(f"| `{sig.signal_id}` | {sig.page_number} | {sig.reported_by} | {sig.headline} | {sig.implication_text} |\n")
                f.write("\n")

                # Public Accounts Table
                f.write("### 3. Publicly Written Accounts\n\n")
                f.write("| Account ID | Page | Year | Tag | Outlet | Headline | Snippet |\n")
                f.write("| :--- | :---: | :---: | :--- | :--- | :--- | :--- |\n")
                for acc in rec.public_accounts:
                    yr = acc.year or "-"
                    tag = acc.tag or "-"
                    snip = acc.description_snippet.replace("|", "\\|")[:120] + ("..." if len(acc.description_snippet) > 120 else "")
                    f.write(f"| `{acc.account_id}` | {acc.page_number} | {yr} | {tag} | {acc.source_outlet} | {acc.headline} | {snip} |\n")
                f.write("\n")

                # The Seven Patterns Table
                f.write("### 4. The Seven Failure Mode Patterns\n\n")
                f.write("| Pattern ID | Num | Pattern Name | Company Record Status | Closed By | Benchmark Source | Quote |\n")
                f.write("| :--- | :---: | :--- | :--- | :--- | :--- | :--- |\n")
                for pat in rec.seven_patterns:
                    f.write(f"| `{pat.pattern_id}` | {pat.pattern_number} | {pat.pattern_name} | `{pat.company_record_status}` | {pat.solution_closed_by} | {pat.sector_benchmark_source} | \"{pat.quote}\" |\n")
                f.write("\n")

                # Validation Issues Table
                if rec.validation_issues:
                    f.write("### 5. Logged Discrepancies & Ambiguities\n\n")
                    f.write("| Issue ID | Field Name | Type | Description | Report Fragment | Proposed Resolution |\n")
                    f.write("| :--- | :--- | :--- | :--- | :--- | :--- |\n")
                    for iss in rec.validation_issues:
                        f.write(f"| `{iss.issue_id}` | `{iss.field_name}` | `{iss.issue_type}` | {iss.description} | {iss.report_native_fragment} | {iss.resolution_proposed} |\n")
                    f.write("\n")
                f.write("---\n\n")
        return out_path
