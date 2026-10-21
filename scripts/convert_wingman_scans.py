#!/usr/bin/env python3
"""
scripts/convert_wingman_scans.py

Standalone offline converter that transforms Wingman company-scan JSON exports
(e.g. GET /api/scans or top-level array) into the Streamlit dashboard's canonical CSV format.

Architectural and Security Guarantees:
- Fully Offline: Zero external network requests, zero database connections, zero tokens.
- Privacy & Non-Leakage: Excludes internal IDs, contact identities, CRM ownership,
  suppression lists, and notes. contacts_held is reported only in the console summary.
- Separation of Concerns: source_tier is preserved strictly as informational metadata.
  computed_tier and business-model fit review are not populated; they are dynamically
  evaluated by the dashboard's analytics layer.
- Security: Applies formula-injection escaping (CWE-1236 / OWASP) across all exported text cells.
- Determinism: Canonical column ordering, case-insensitive company sort, preserved trigger order,
  UTF-8 encoding with deterministic LF line terminators.
"""

import argparse
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
from typing import Any, Dict, List, Optional, Tuple, Union
import urllib.parse

# Canonical column ordering for the dashboard CSV ingestion
CANONICAL_COLUMNS: List[str] = [
    "company",
    "segment",
    "domain",
    "source_tier",
    "trigger_type",
    "trigger_date",
    "trigger_summary",
    "trigger_source_url",
    "scanned_at",
]

# The 8 canonical trigger categories recognized by the dashboard
VALID_TRIGGER_TYPES = {
    "project_fid_commissioning",
    "turnaround",
    "incident_regulator",
    "new_leader",
    "hiring_burst",
    "audit_cycle",
    "ma_acquisition",
    "crew_change",
}

# Dangerous leading characters for CSV / spreadsheet formula injection (CWE-1236 / OWASP)
DANGEROUS_FORMULA_CHARS = ("=", "+", "-", "@", "\t", "\r", "\n")

DEFAULT_SEGMENT_FALLBACK = "Diversified Industrial / Unspecified"


def sanitize_value_for_csv(val: Any) -> str:
    """
    Sanitizes a single cell value against CSV / spreadsheet formula injection (CWE-1236 / OWASP).
    Prepends a single quote (') if the cell begins with =, +, -, @, tab, or newline,
    including after leading whitespace or control characters.
    """
    if val is None:
        return ""
    s = str(val)
    if not s:
        return ""
    if s[0] in DANGEROUS_FORMULA_CHARS:
        return "'" + s
    stripped_spaces = s.lstrip(" \x00\x0b\x0c")
    if stripped_spaces and stripped_spaces[0] in DANGEROUS_FORMULA_CHARS:
        return "'" + s
    stripped = s.lstrip(" \t\r\n\x00\x0b\x0c")
    if stripped and stripped[0] in DANGEROUS_FORMULA_CHARS:
        return "'" + s
    return s


def normalize_domain(domain: Any) -> str:
    """Standardizes domain string: lowercases and removes protocol, path, port, and www."""
    if not domain:
        return ""
    d = str(domain).strip(" ")
    if d and d[0] in DANGEROUS_FORMULA_CHARS:
        return d
    d_lower = d.lower()
    d_clean = re.sub(r"^https?://", "", d_lower)
    d_clean = re.sub(r"^www\.", "", d_clean)
    d_clean = d_clean.split("/")[0].split(":")[0]
    return d_clean


def standardize_segment(val: Any) -> Tuple[str, bool]:
    """
    Standardizes industry segment labels using the dashboard's normalization mappings.
    Returns (standardized_segment, is_fallback_used).
    """
    if val is None or not str(val).strip():
        return DEFAULT_SEGMENT_FALLBACK, True

    s = str(val).strip(" ")
    if s and s[0] in DANGEROUS_FORMULA_CHARS:
        return s, False

    s_lower = s.lower()

    if s_lower in ["oil and gas", "oil & gas", "oil & energy"]:
        return "Oil & Gas", False
    if s_lower in ["chemicals & petrochemicals", "chemical manufacturing", "chemicals"]:
        return "Chemicals & Petrochemicals", False
    if s_lower in ["var", "imported", "diversified industrial / unspecified"]:
        return DEFAULT_SEGMENT_FALLBACK, False
    if s_lower in ["diversified industrial"]:
        return "Diversified Industrial", False
    if s_lower == "information technology & services":
        return "Information Technology", False
    if s_lower in ["higher education", "education administration programs"]:
        return "Education & Training", False
    if s_lower == "paper & forest products":
        return "Forest Products", False
    if s_lower == "machinery":
        return "Machinery & Equipment", False
    if s_lower == "maritime":
        return "Maritime & Shipping", False
    if s_lower == "financial services":
        return "Financial Services", False
    if s_lower == "government administration":
        return "Government Administration", False
    if s_lower == "luxury goods & jewelry":
        return "Consumer / Specialty Goods", False
    if s_lower == "marketing & advertising":
        return "Marketing & Communications", False
    if s_lower == "retail":
        return "Retail Distribution", False
    if s_lower == "construction":
        return "Construction & Civil Works", False

    return s.title(), False


def validate_trigger_date(val: Any, company: str) -> Tuple[str, bool]:
    """
    Validates trigger date.
    Returns (date_str, is_blank_or_null).
    Raises ValueError on invalid or malformed nonblank dates.
    """
    if val is None:
        return "", True
    s = str(val).strip()
    if not s:
        return "", True

    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        raise ValueError(
            f"Invalid nonblank trigger date format: '{val}' for company '{company}'. Expected 'YYYY-MM-DD'."
        )

    try:
        parsed = datetime.strptime(s, "%Y-%m-%d").date()
        return parsed.strftime("%Y-%m-%d"), False
    except ValueError as e:
        raise ValueError(
            f"Impossible or invalid nonblank trigger date: '{val}' for company '{company}' ({e})."
        )


def parse_scanned_at(val: Any, company: str) -> str:
    """
    Parses scanned_at as ISO 8601 and exports its UTC calendar date as YYYY-MM-DD.
    Rejects malformed nonblank timestamps.
    """
    if val is None:
        return ""
    s = str(val).strip()
    if not s:
        return ""

    s_norm = s.replace("Z", "+00:00") if s.endswith("Z") else s
    try:
        dt = datetime.fromisoformat(s_norm)
        if dt.tzinfo is not None:
            dt_utc = dt.astimezone(timezone.utc)
        else:
            dt_utc = dt
        return dt_utc.strftime("%Y-%m-%d")
    except Exception as e:
        raise ValueError(
            f"Invalid nonblank scanned_at timestamp: '{val}' for company '{company}' ({e})."
        )


def is_valid_http_url(source: str) -> bool:
    """Checks whether source string is an HTTP or HTTPS URL."""
    s = str(source).strip()
    if not (s.startswith("http://") or s.startswith("https://")):
        return False
    try:
        parsed = urllib.parse.urlsplit(s)
        return bool(parsed.scheme and parsed.netloc)
    except Exception:
        return False


class ConversionError(Exception):
    """Raised for any blocking validation error."""
    pass


class ScanConverter:
    """Converts Wingman scan JSON data into canonical dashboard CSV rows."""

    def __init__(self):
        self.warnings: List[str] = []
        self.input_scan_records: int = 0
        self.unique_companies: int = 0
        self.output_trigger_rows: int = 0
        self.zero_trigger_companies: int = 0
        self.null_date_triggers: int = 0
        self.missing_segment_fallbacks: int = 0
        self.plaintext_citation_sources: int = 0
        self.valid_url_sources: int = 0
        self.total_contacts_held: int = 0
        self.missing_domains: int = 0
        self.null_trigger_arrays: int = 0
        self.output_rows: int = 0

    def parse_payload(self, raw_data: Union[dict, list, str]) -> List[Dict[str, Any]]:
        """Parses and validates the top-level payload structure."""
        if isinstance(raw_data, str):
            try:
                data = json.loads(raw_data)
            except json.JSONDecodeError as e:
                raise ConversionError(f"Malformed JSON: {e}")
        else:
            data = raw_data

        if isinstance(data, dict):
            if "ok" not in data or data["ok"] is not True:
                raise ConversionError(
                    "Unsupported top-level structure: expected {'ok': True, 'scans': [...]} or top-level array. 'ok' is missing or not True."
                )
            if "scans" not in data or not isinstance(data["scans"], list):
                raise ConversionError(
                    "Unsupported top-level structure: 'scans' key is absent or not an array."
                )
            return data["scans"]
        elif isinstance(data, list):
            return data
        else:
            raise ConversionError(
                f"Unsupported top-level structure: expected JSON object or array, got {type(data).__name__}."
            )

    def process_records(self, scans: List[Any]) -> List[Dict[str, str]]:
        """Validates all records and flattens them into canonical CSV row dictionaries."""
        self.input_scan_records = len(scans)
        seen_companies: set = set()
        validated_records: List[Dict[str, Any]] = []

        for idx, scan in enumerate(scans):
            if not isinstance(scan, dict):
                raise ConversionError(
                    f"Scan record at index {idx} is not an object ({type(scan).__name__})."
                )

            # 1. Company
            company_raw = scan.get("company")
            if company_raw is None or not str(company_raw).strip():
                raise ConversionError(
                    f"Scan record at index {idx} has missing or blank 'company'."
                )
            company = str(company_raw).strip(" ")
            norm_comp = company.lower()
            if norm_comp in seen_companies:
                raise ConversionError(
                    f"Duplicate company detected after case-insensitive normalization: '{company}'."
                )
            seen_companies.add(norm_comp)

            # 2. Source Tier
            tier_raw = scan.get("tier")
            if tier_raw is None:
                raise ConversionError(
                    f"Missing source tier for company '{company}'."
                )
            try:
                tier_val = int(tier_raw)
                if tier_val not in (1, 2, 3):
                    raise ValueError()
            except (ValueError, TypeError):
                raise ConversionError(
                    f"Invalid source tier for company '{company}': {tier_raw}. Expected 1, 2, or 3."
                )

            # 3. Contacts Held (Reporting only)
            ch = scan.get("contacts_held", 0)
            if isinstance(ch, (int, float)):
                self.total_contacts_held += int(ch)

            # 4. Scanned At
            scanned_at_raw = scan.get("scanned_at")
            try:
                scanned_at_str = parse_scanned_at(scanned_at_raw, company)
            except ValueError as e:
                raise ConversionError(str(e))

            # 5. Segment
            segment_raw = scan.get("segment")
            standardized_seg, used_fallback = standardize_segment(segment_raw)
            if used_fallback:
                self.missing_segment_fallbacks += 1
                self.warnings.append(
                    f"Missing or empty segment for company '{company}'; used fallback '{DEFAULT_SEGMENT_FALLBACK}'."
                )

            # 6. Domain
            domain_raw = scan.get("domain")
            if domain_raw is not None and str(domain_raw).strip():
                domain_clean = normalize_domain(domain_raw)
            else:
                domain_clean = ""
                self.missing_domains += 1
                self.warnings.append(f"Missing domain for company '{company}'.")

            # 7. Triggers
            triggers_raw = scan.get("triggers")
            if triggers_raw is None:
                triggers = []
                self.null_trigger_arrays += 1
                self.warnings.append(
                    f"Null triggers array normalized to [] for company '{company}'."
                )
            elif isinstance(triggers_raw, list):
                triggers = triggers_raw
            else:
                raise ConversionError(
                    f"Invalid triggers field for company '{company}': expected array or null, got {type(triggers_raw).__name__}."
                )

            # Process each trigger
            processed_triggers: List[Dict[str, str]] = []
            for t_idx, trigger in enumerate(triggers):
                if not isinstance(trigger, dict):
                    raise ConversionError(
                        f"Non-object trigger at index {t_idx} in company '{company}'."
                    )

                t_type = trigger.get("type")
                if not t_type or t_type not in VALID_TRIGGER_TYPES:
                    raise ConversionError(
                        f"Unknown trigger type '{t_type}' in company '{company}'. Must be one of: {sorted(list(VALID_TRIGGER_TYPES))}."
                    )

                # Trigger date
                t_date_raw = trigger.get("date")
                try:
                    t_date, is_blank_date = validate_trigger_date(t_date_raw, company)
                except ValueError as e:
                    raise ConversionError(str(e))

                if is_blank_date:
                    self.null_date_triggers += 1
                    self.warnings.append(
                        f"Null or blank trigger date in company '{company}' for trigger '{t_type}'."
                    )

                # Trigger summary
                t_value = str(trigger.get("value") or "").strip(" ")

                # Trigger source
                t_source = str(trigger.get("source") or "").strip(" ")
                if t_source:
                    if is_valid_http_url(t_source):
                        self.valid_url_sources += 1
                    else:
                        self.plaintext_citation_sources += 1
                        self.warnings.append(
                            f"Plain-text citation source preserved for company '{company}': '{t_source}'."
                        )

                processed_triggers.append({
                    "trigger_type": t_type,
                    "trigger_date": t_date,
                    "trigger_summary": t_value,
                    "trigger_source_url": t_source,
                })

            validated_records.append({
                "company": company,
                "segment": standardized_seg,
                "domain": domain_clean,
                "source_tier": str(tier_val),
                "scanned_at": scanned_at_str,
                "triggers": processed_triggers,
            })

        self.unique_companies = len(validated_records)

        # Sort companies case-insensitively for deterministic output
        validated_records.sort(key=lambda r: r["company"].strip().lower())

        # Flatten into output CSV rows
        flattened_rows: List[Dict[str, str]] = []
        for rec in validated_records:
            comp_sanitized = sanitize_value_for_csv(rec["company"])
            seg_sanitized = sanitize_value_for_csv(rec["segment"])
            dom_sanitized = sanitize_value_for_csv(rec["domain"])
            tier_str = rec["source_tier"]
            scanned_str = rec["scanned_at"]

            trigs = rec["triggers"]
            if not trigs:
                # Zero-trigger company: emit exactly 1 row with empty trigger fields
                self.zero_trigger_companies += 1
                flattened_rows.append({
                    "company": comp_sanitized,
                    "segment": seg_sanitized,
                    "domain": dom_sanitized,
                    "source_tier": tier_str,
                    "trigger_type": "",
                    "trigger_date": "",
                    "trigger_summary": "",
                    "trigger_source_url": "",
                    "scanned_at": scanned_str,
                })
            else:
                for t in trigs:
                    self.output_trigger_rows += 1
                    flattened_rows.append({
                        "company": comp_sanitized,
                        "segment": seg_sanitized,
                        "domain": dom_sanitized,
                        "source_tier": tier_str,
                        "trigger_type": t["trigger_type"],
                        "trigger_date": t["trigger_date"],
                        "trigger_summary": sanitize_value_for_csv(t["trigger_summary"]),
                        "trigger_source_url": sanitize_value_for_csv(t["trigger_source_url"]),
                        "scanned_at": scanned_str,
                    })

        self.output_rows = len(flattened_rows)
        return flattened_rows


def convert_wingman_scans(
    input_path: Union[str, Path],
    output_path: Union[str, Path],
) -> Dict[str, Any]:
    """
    Converts a Wingman scans JSON file to canonical dashboard CSV.
    Writes byte-identical deterministic UTF-8 CSV with LF line terminators.
    """
    in_p = Path(input_path)
    out_p = Path(output_path)

    if not in_p.exists():
        raise ConversionError(f"Input file not found: {in_p}")

    try:
        raw_text = in_p.read_text(encoding="utf-8")
    except Exception as e:
        raise ConversionError(f"Failed to read input file: {e}")

    converter = ScanConverter()
    scans_data = converter.parse_payload(raw_text)
    rows = converter.process_records(scans_data)

    # Ensure output parent directory exists
    out_p.parent.mkdir(parents=True, exist_ok=True)

    # Write CSV with explicit LF line terminators
    with out_p.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=CANONICAL_COLUMNS,
            lineterminator="\n",
            quoting=csv.QUOTE_MINIMAL,
        )
        writer.writeheader()
        writer.writerows(rows)

    summary = {
        "input_scan_records": converter.input_scan_records,
        "unique_companies": converter.unique_companies,
        "output_trigger_rows": converter.output_trigger_rows,
        "zero_trigger_companies": converter.zero_trigger_companies,
        "null_date_triggers": converter.null_date_triggers,
        "missing_segment_fallbacks": converter.missing_segment_fallbacks,
        "plaintext_citation_sources": converter.plaintext_citation_sources,
        "valid_url_sources": converter.valid_url_sources,
        "total_contacts_held": converter.total_contacts_held,
        "output_rows": converter.output_rows,
        "output_path": str(out_p),
        "warnings_count": len(converter.warnings),
    }

    return summary


def format_summary(summary: Dict[str, Any]) -> str:
    """Formats the conversion summary block for display."""
    lines = [
        "=" * 60,
        "Wingman Scan Converter Summary",
        "=" * 60,
        f"Input scan records:             {summary['input_scan_records']}",
        f"Unique companies:               {summary['unique_companies']}",
        f"Output trigger rows:            {summary['output_trigger_rows']}",
        f"Zero-trigger companies:         {summary['zero_trigger_companies']}",
        f"Null-date triggers:             {summary['null_date_triggers']}",
        f"Missing-segment fallbacks:      {summary['missing_segment_fallbacks']}",
        f"Plain-text citation sources:    {summary['plaintext_citation_sources']}",
        f"Valid URL sources:              {summary['valid_url_sources']}",
        f"Total contacts_held:            {summary['total_contacts_held']} (reporting only; not exported to CSV)",
        f"Output rows:                    {summary['output_rows']}",
        f"Output path:                    {summary['output_path']}",
        "=" * 60,
        "Conversion completed successfully.",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert Wingman company-scan JSON export to dashboard CSV format."
    )
    parser.add_argument(
        "--input", "-i", required=True, help="Path to input Wingman JSON file."
    )
    parser.add_argument(
        "--output", "-o", required=True, help="Path to output CSV file."
    )

    args = parser.parse_args()

    try:
        summary = convert_wingman_scans(args.input, args.output)
        print(format_summary(summary))
    except ConversionError as e:
        sys.stderr.write(f"Error: {e}\n")
        sys.exit(1)
    except Exception as e:
        sys.stderr.write(f"Unexpected error: {e}\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
