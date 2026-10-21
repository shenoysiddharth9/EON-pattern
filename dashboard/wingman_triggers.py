"""
Wingman Trigger Intelligence Ingestion and Processing Module.
Pure functional presentation-layer module for:
  - Validating and parsing Wingman Trigger Export CSVs (with utf-8-sig BOM handling)
  - Date precision handling (DAY, MONTH, QUARTER, MISSING, INVALID)
  - Temporal relations at scan vs as-of analysis date
  - URL-aware parsing and extraction with residual text detection
  - Safeguarded account matching (unique domain, reviewed alias, exact normalized name, generic webmail blacklist)
  - Conservative event clustering based on shared facility/asset/counterparty tokens
  - Independent trigger state, scan confidence, and trigger evidence confidence evaluation
  - Strict preservation of raw source evidence and un-overwritten report attributes
"""

import csv
import hashlib
import io
import re
import urllib.parse
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

# Canonical schema definition
CANONICAL_COLUMNS = [
    "company",
    "segment",
    "domain",
    "tier",
    "trigger_type",
    "trigger_date",
    "trigger_summary",
    "trigger_source_url",
    "pattern_report_url",
    "scanned_at",
    "notes",
]

# Canonical supported trigger types
VALID_TRIGGER_TYPES = {
    "project_fid_commissioning",
    "ma_acquisition",
    "hiring_burst",
    "turnaround",
    "new_leader",
    "incident_regulator",
    "audit_cycle",
    "crew_change",
}

from dashboard.identity_registry import (
    AccountIdentityRegistry,
    parse_identity_crosswalk,
    normalize_domain,
    normalize_company_name_conservative,
    normalize_ticker,
    is_valid_domain,
    is_webmail_or_disposable_domain,
    extract_parenthetical_tickers,
    match_source_record_identity,
    assert_account_match_integrity,
    WEBMAIL_DOMAINS,
    REQUIRED_CROSSWALK_COLUMNS,
    SUPPORTED_STATUSES,
)



def parse_trigger_date(date_val: Any) -> Tuple[Optional[date], str, str, str]:
    """
    Parses a trigger date string with precision preservation.
    Supports:
      - YYYY-MM-DD as DAY (EXACT)
      - YYYY-MM as MONTH (APPROXIMATE, anchored to 1st of month)
      - YYYY-Qn as QUARTER (APPROXIMATE, anchored to 1st day of quarter)
      - blank/whitespace as MISSING
      - unparseable as INVALID
    Returns:
      (parsed_date, date_precision, date_parse_status, raw_string)
    """
    if date_val is None or str(date_val).strip() == "" or str(date_val).lower() == "nan":
        return None, "MISSING", "MISSING", ""

    raw_str = str(date_val).strip()

    # 1. YYYY-MM-DD (DAY)
    m_day = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", raw_str)
    if m_day:
        try:
            y, m, d = int(m_day.group(1)), int(m_day.group(2)), int(m_day.group(3))
            dt = date(y, m, d)
            return dt, "DAY", "EXACT", raw_str
        except ValueError:
            return None, "INVALID", "INVALID", raw_str

    # 2. YYYY-MM (MONTH)
    m_mon = re.match(r"^(\d{4})-(\d{2})$", raw_str)
    if m_mon:
        try:
            y, m = int(m_mon.group(1)), int(m_mon.group(2))
            if 1 <= m <= 12:
                dt = date(y, m, 1)
                return dt, "MONTH", "APPROXIMATE", raw_str
            return None, "INVALID", "INVALID", raw_str
        except ValueError:
            return None, "INVALID", "INVALID", raw_str

    # 3. YYYY-Qn (QUARTER)
    m_qtr = re.match(r"^(\d{4})-[qQ]([1-4])$", raw_str)
    if m_qtr:
        try:
            y, q = int(m_qtr.group(1)), int(m_qtr.group(2))
            q_start_month = {1: 1, 2: 4, 3: 7, 4: 10}[q]
            dt = date(y, q_start_month, 1)
            return dt, "QUARTER", "APPROXIMATE", raw_str
        except ValueError:
            return None, "INVALID", "INVALID", raw_str

    # Commentary prefix matching
    m_qtr_prefix = re.match(r"^(\d{4})-[qQ]([1-4])\b", raw_str)
    if m_qtr_prefix:
        y, q = int(m_qtr_prefix.group(1)), int(m_qtr_prefix.group(2))
        q_start_month = {1: 1, 2: 4, 3: 7, 4: 10}[q]
        dt = date(y, q_start_month, 1)
        return dt, "QUARTER", "APPROXIMATE", raw_str

    m_mon_prefix = re.match(r"^(\d{4})-(\d{2})\b", raw_str)
    if m_mon_prefix:
        y, m = int(m_mon_prefix.group(1)), int(m_mon_prefix.group(2))
        if 1 <= m <= 12:
            dt = date(y, m, 1)
            return dt, "MONTH", "APPROXIMATE", raw_str

    return None, "INVALID", "INVALID", raw_str


def parse_scanned_at_date(scanned_val: Any) -> Tuple[Optional[date], str]:
    """Parses scanned_at YYYY-MM-DD date."""
    if not scanned_val or str(scanned_val).strip() == "" or str(scanned_val).lower() == "nan":
        return None, ""
    raw = str(scanned_val).strip()
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", raw)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3))), raw
        except ValueError:
            return None, raw
    return None, raw


def compute_date_relation_at_scan(
    parsed_date: Optional[date], precision: str, scanned_at: Optional[date]
) -> str:
    """
    Computes date relation at the time research observation was scanned:
    - PAST_AT_SCAN (D < -90)
    - CURRENT_AT_SCAN (-90 <= D <= 0)
    - PLANNED_AT_SCAN (D > 0)
    - UNKNOWN (missing, invalid, or scan date unknown)
    """
    if parsed_date is None or precision in ("MISSING", "INVALID") or scanned_at is None:
        return "UNKNOWN"

    diff = (parsed_date - scanned_at).days
    if diff > 0:
        return "PLANNED_AT_SCAN"
    elif -90 <= diff <= 0:
        return "CURRENT_AT_SCAN"
    else:
        return "PAST_AT_SCAN"


def compute_temporal_status_as_of(
    parsed_date: Optional[date],
    precision: str,
    as_of_date: date,
    is_zero_trigger: bool = False,
) -> str:
    """
    Computes temporal urgency status relative to an explicit analysis_as_of_date:
    - NONE_DETECTED: company scanned with zero qualifying triggers
    - UPCOMING_0_180_DAYS: planned milestone in 1 to 180 days
    - PLANNED_181_365_DAYS: planned milestone in 181 to 365 days
    - LONG_RANGE_OVER_365_DAYS: planned milestone > 365 days out
    - CURRENT_ACTIVE: recent operational event within 0 to 90 days in past
    - RECENT_PAST: operational event within 91 to 365 days in past
    - HISTORICAL: operational event > 365 days in past
    - UNKNOWN: undated, invalid date, or missing date
    """
    if is_zero_trigger:
        return "NONE_DETECTED"

    if parsed_date is None or precision in ("MISSING", "INVALID"):
        return "UNKNOWN"

    diff = (parsed_date - as_of_date).days
    if diff > 365:
        return "LONG_RANGE_OVER_365_DAYS"
    elif 180 < diff <= 365:
        return "PLANNED_181_365_DAYS"
    elif 0 < diff <= 180:
        return "UPCOMING_0_180_DAYS"
    elif -90 <= diff <= 0:
        return "CURRENT_ACTIVE"
    elif -365 <= diff < -90:
        return "RECENT_PAST"
    else:
        return "HISTORICAL"


def extract_valid_urls(raw_source_url: Any) -> Tuple[List[str], Optional[str]]:
    """
    URL-aware extractor that finds HTTP/HTTPS URLs and flags unparsed residual text.
    Preserves raw source string verbatim while extracting a clean list of URLs.
    """
    if not raw_source_url or str(raw_source_url).strip() == "" or str(raw_source_url).lower() == "nan":
        return [], None

    raw_text = str(raw_source_url).strip()
    url_pattern = re.compile(r"https?://[^\s,;]+", re.IGNORECASE)

    extracted_urls: List[str] = []
    for match in url_pattern.finditer(raw_text):
        u = match.group(0)
        u_clean = re.sub(r"[.,;:)\'\"]+$", "", u)
        try:
            parsed = urllib.parse.urlparse(u_clean)
            if parsed.scheme in ("http", "https") and parsed.netloc:
                extracted_urls.append(u_clean)
        except Exception:
            pass

    # Detect residual text by masking out matched URLs
    residual = raw_text
    for m in url_pattern.finditer(raw_text):
        residual = residual.replace(m.group(0), " ")

    residual = re.sub(r"\b(?:and|or)\b", " ", residual, flags=re.IGNORECASE)
    residual = re.sub(r"[,;]+", " ", residual)
    residual_text = residual.strip()

    return extracted_urls, (residual_text if residual_text else None)


def parse_wingman_trigger_export(
    file_or_content: Any,
) -> Dict[str, Any]:
    """
    Ingests and validates a Wingman Trigger Export CSV.
    - Handles UTF-8 BOM automatically via utf-8-sig
    - Verifies all 11 canonical column headers are present
    - Preserves extra columns with informational notice
    - Validates mandatory fields: company, scanned_at
    - Identifies valid zero-trigger rows vs active trigger rows
    - Quarantines rows with unsupported trigger types or missing mandatory keys
    - Detects multi-entity domain mappings
    """
    bom_detected = False
    if isinstance(file_or_content, (str, Path)):
        try:
            p = Path(file_or_content)
            if "\n" not in str(file_or_content) and p.is_file():
                with open(p, "rb") as f:
                    raw_bytes = f.read()
                if raw_bytes.startswith(b"\xef\xbb\xbf"):
                    bom_detected = True
                text_content = raw_bytes.decode("utf-8-sig", errors="replace")
                stream = io.StringIO(text_content)
            else:
                if str(file_or_content).startswith("\ufeff"):
                    bom_detected = True
                    text_content = str(file_or_content).lstrip("\ufeff")
                else:
                    text_content = str(file_or_content)
                stream = io.StringIO(text_content)
        except Exception:
            text_content = str(file_or_content)
            stream = io.StringIO(text_content)
    elif isinstance(file_or_content, bytes):
        if file_or_content.startswith(b"\xef\xbb\xbf"):
            bom_detected = True
        text_content = file_or_content.decode("utf-8-sig", errors="replace")
        stream = io.StringIO(text_content)
    elif hasattr(file_or_content, "read"):
        raw_bytes = file_or_content.read()
        if isinstance(raw_bytes, bytes):
            if raw_bytes.startswith(b"\xef\xbb\xbf"):
                bom_detected = True
            text_content = raw_bytes.decode("utf-8-sig", errors="replace")
        else:
            text_content = str(raw_bytes)
            if text_content.startswith("\ufeff"):
                bom_detected = True
                text_content = text_content.lstrip("\ufeff")
        stream = io.StringIO(text_content)
    else:
        raise ValueError("Unsupported input format. Must be bytes, str, Path, or file-like object.")

    reader = csv.reader(stream)
    try:
        raw_header = next(reader)
    except StopIteration:
        return {
            "valid": False,
            "error": "Uploaded CSV file is completely empty.",
            "records": [],
            "quarantined_records": [],
            "metadata": {},
            "warnings": ["Empty file"],
        }

    cleaned_header = [re.sub(r"^\ufeff", "", col).strip().lower() for col in raw_header]

    missing_cols = [c for c in CANONICAL_COLUMNS if c not in cleaned_header]
    if missing_cols:
        return {
            "valid": False,
            "error": f"Missing required column headers: {', '.join(missing_cols)}",
            "records": [],
            "quarantined_records": [],
            "metadata": {"bom_detected": bom_detected, "raw_header": raw_header},
            "warnings": [f"Missing required columns: {missing_cols}"],
        }

    extra_cols = [c for c in cleaned_header if c not in CANONICAL_COLUMNS]
    warnings: List[str] = []
    if extra_cols:
        warnings.append(f"Informational: Ingested file contains extra forward-compatible columns: {extra_cols}")

    col_idx = {col: idx for idx, col in enumerate(cleaned_header)}

    valid_records: List[Dict[str, Any]] = []
    quarantined_records: List[Dict[str, Any]] = []
    domain_to_entities: Dict[str, Set[str]] = {}

    row_num = 1
    for row in reader:
        row_num += 1
        if not row or all(c.strip() == "" for c in row):
            continue

        def get_val(c_name: str) -> str:
            i = col_idx.get(c_name)
            if i is not None and i < len(row):
                return row[i].strip()
            return ""

        comp_raw = get_val("company")
        scanned_at_raw = get_val("scanned_at")
        segment_raw = get_val("segment")
        domain_raw = get_val("domain")
        tier_raw = get_val("tier")
        trig_type_raw = get_val("trigger_type")
        trig_date_raw = get_val("trigger_date")
        trig_summary_raw = get_val("trigger_summary")
        trig_url_raw = get_val("trigger_source_url")
        pattern_url_raw = get_val("pattern_report_url")
        notes_raw = get_val("notes")

        if not comp_raw:
            quarantined_records.append({
                "row_number": row_num,
                "reason": "MISSING_COMPANY_NAME",
                "raw_data": row,
            })
            continue

        scanned_at_date, _ = parse_scanned_at_date(scanned_at_raw)
        if not scanned_at_date:
            quarantined_records.append({
                "row_number": row_num,
                "company": comp_raw,
                "reason": "MISSING_OR_INVALID_SCANNED_AT",
                "raw_data": row,
            })
            continue

        is_zero_trigger = False
        if not trig_type_raw and not trig_date_raw and not trig_summary_raw:
            is_zero_trigger = True

        if not is_zero_trigger and trig_type_raw.lower() not in VALID_TRIGGER_TYPES:
            quarantined_records.append({
                "row_number": row_num,
                "company": comp_raw,
                "reason": f"UNSUPPORTED_TRIGGER_TYPE: '{trig_type_raw}'",
                "raw_data": row,
            })
            continue

        dt_parsed, dt_prec, dt_stat, _ = parse_trigger_date(trig_date_raw)
        rel_at_scan = compute_date_relation_at_scan(dt_parsed, dt_prec, scanned_at_date)
        urls_list, residual_url_text = extract_valid_urls(trig_url_raw)

        parsed_tier: Optional[int] = None
        if tier_raw:
            try:
                parsed_tier = int(tier_raw)
            except ValueError:
                pass

        norm_dom = normalize_domain(domain_raw)
        if norm_dom:
            domain_to_entities.setdefault(norm_dom, set()).add(comp_raw)

        record = {
            "row_number": row_num,
            "company": comp_raw,
            "company_normalized": normalize_company_name_conservative(comp_raw),
            "segment": segment_raw,
            "domain": domain_raw,
            "domain_normalized": norm_dom,
            "tier": parsed_tier,
            "is_zero_trigger": is_zero_trigger,
            "trigger_type": trig_type_raw.lower() if trig_type_raw else None,
            "trigger_date_raw": trig_date_raw,
            "trigger_date_parsed": dt_parsed,
            "date_precision": dt_prec,
            "date_parse_status": dt_stat,
            "date_relation_at_scan": rel_at_scan,
            "trigger_summary": trig_summary_raw,
            "trigger_source_url_raw": trig_url_raw,
            "trigger_source_urls": urls_list,
            "unparsed_residual_url_text": residual_url_text,
            "pattern_report_url": pattern_url_raw,
            "scanned_at_date": scanned_at_date,
            "scanned_at_raw": scanned_at_raw,
            "notes": notes_raw,
        }

        for extra_c in extra_cols:
            record[extra_c] = get_val(extra_c)

        valid_records.append(record)

    multi_entity_domains: Dict[str, List[str]] = {
        dom: sorted(list(comps)) for dom, comps in domain_to_entities.items() if len(comps) > 1
    }

    metadata = {
        "bom_detected": bom_detected,
        "total_rows_ingested": len(valid_records) + len(quarantined_records),
        "valid_records_count": len(valid_records),
        "quarantined_records_count": len(quarantined_records),
        "zero_trigger_records_count": sum(1 for r in valid_records if r["is_zero_trigger"]),
        "active_trigger_records_count": sum(1 for r in valid_records if not r["is_zero_trigger"]),
        "unique_companies_count": len({r["company"] for r in valid_records}),
        "unique_normalized_domains_count": len({r["domain_normalized"] for r in valid_records if r["domain_normalized"]}),
        "multi_entity_domains_count": len(multi_entity_domains),
    }

    return {
        "valid": True,
        "records": valid_records,
        "quarantined_records": quarantined_records,
        "metadata": metadata,
        "warnings": warnings,
        "multi_entity_domains": multi_entity_domains,
    }


def _validate_and_build_overrides_registry(
    base_registry: Optional[AccountIdentityRegistry],
    company_id: str,
    company_name: str,
    alias_overrides: Optional[Dict[str, List[str]]] = None,
    ticker_overrides: Optional[Dict[str, List[str]]] = None,
    domain_overrides: Optional[Dict[str, str]] = None,
) -> AccountIdentityRegistry:
    """
    Deprecated override validator. Converts overrides into temporary registry rows
    and validates them strictly through crosswalk validation rules.
    Unchecked or malformed overrides are rejected.
    """
    csv_lines = [
        "canonical_account_id,canonical_company_name,approved_alias,approved_domain,approved_ticker,approval_status,approved_by,approved_at"
    ]
    if base_registry:
        for acc in base_registry.accounts:
            c_n = base_registry.get_canonical_name(acc) or acc
            for a in base_registry.get_approved_aliases(acc):
                csv_lines.append(f'"{acc}","{c_n}","{a}",,,"APPROVED","PREV_REGISTRY","2026-09-17"')
            for d in base_registry.get_approved_domains(acc):
                csv_lines.append(f'"{acc}","{c_n}",,"{d}",,"APPROVED","PREV_REGISTRY","2026-09-17"')
            for t in base_registry.get_approved_tickers(acc):
                csv_lines.append(f'"{acc}","{c_n}",,,"{t}","APPROVED","PREV_REGISTRY","2026-09-17"')

    if alias_overrides:
        for acc, aliases in alias_overrides.items():
            acc_name = company_name if acc == company_id else acc
            for a in aliases:
                csv_lines.append(f'"{acc}","{acc_name}","{a}",,,"APPROVED","DEPRECATED_OVERRIDE","2026-09-17"')

    if domain_overrides:
        for acc, dom in domain_overrides.items():
            acc_name = company_name if acc == company_id else acc
            csv_lines.append(f'"{acc}","{acc_name}",,"{dom}",,"APPROVED","DEPRECATED_OVERRIDE","2026-09-17"')

    if ticker_overrides:
        for acc, tickers in ticker_overrides.items():
            acc_name = company_name if acc == company_id else acc
            for t in tickers:
                csv_lines.append(f'"{acc}","{acc_name}",,,"{t}","APPROVED","DEPRECATED_OVERRIDE","2026-09-17"')

    res = parse_identity_crosswalk("\n".join(csv_lines))
    if not res["file_is_valid"] or not res["registry_applied"] or not res["registry"]:
        reasons = res["fatal_errors"] + res["quarantine_reasons"]
        raise ValueError(f"Override validation failed: {'; '.join(reasons)}")
    return res["registry"]


def match_company_to_wingman_records(
    company_id: str,
    company_name: str,
    company_domain: str = "",
    all_wingman_records: Optional[List[Dict[str, Any]]] = None,
    multi_entity_domains: Optional[Dict[str, List[str]]] = None,
    identity_registry: Optional[AccountIdentityRegistry] = None,
    report_sector: Optional[str] = None,
    report_wingman_tier: Optional[Any] = None,
    alias_overrides: Optional[Dict[str, List[str]]] = None,
    ticker_overrides: Optional[Dict[str, List[str]]] = None,
    domain_overrides: Optional[Dict[str, str]] = None,
    registry_input_state: str = "NOT_UPLOADED",
    registry_applied: Optional[bool] = None,
    registry_review_required: Optional[bool] = None,
) -> Dict[str, Any]:
    """
    Safeguarded matching of a single report company against parsed Wingman records.
    Requires an explicit AccountIdentityRegistry for authorized alias, domain, and ticker routes.
    Without a registry, only exact normalized canonical company name equality may authorize matching.
    An unapproved export domain is treated as a non-scoring PROPOSED ASSOCIATION.
    Preserves row-level lineage and separate review flags.
    """
    records_list = all_wingman_records or []
    multi_domains = multi_entity_domains or {}

    effective_registry = identity_registry
    if alias_overrides or ticker_overrides or domain_overrides:
        effective_registry = _validate_and_build_overrides_registry(
            base_registry=identity_registry,
            company_id=company_id,
            company_name=company_name,
            alias_overrides=alias_overrides,
            ticker_overrides=ticker_overrides,
            domain_overrides=domain_overrides,
        )

    # Resolve registry input state, application, and review semantics
    if registry_input_state == "NOT_UPLOADED" and effective_registry is not None:
        effective_input_state = "UPLOADED_VALID"
        reg_applied = True if registry_applied is None else registry_applied
        reg_review = False if registry_review_required is None else registry_review_required
    elif registry_input_state == "UPLOADED_INVALID":
        effective_input_state = "UPLOADED_INVALID"
        reg_applied = False if registry_applied is None else registry_applied
        reg_review = True if registry_review_required is None else registry_review_required
    elif registry_input_state == "NOT_UPLOADED":
        effective_input_state = "NOT_UPLOADED"
        reg_applied = False if registry_applied is None else registry_applied
        reg_review = False if registry_review_required is None else registry_review_required
    else:
        effective_input_state = registry_input_state
        reg_applied = (effective_registry is not None) if registry_applied is None else registry_applied
        reg_review = False if registry_review_required is None else registry_review_required

    registry_review_required_flag = reg_review
    registry_applied_flag = reg_applied
    registry_input_state_val = effective_input_state

    matched_records: List[Dict[str, Any]] = []
    proposed_records: List[Dict[str, Any]] = []
    conflict_notes: List[str] = []
    if registry_review_required_flag:
        conflict_notes.append(
            "Registry Review Required: Uploaded identity crosswalk is invalid; "
            "matching has fallen back to strict canonical equality."
        )
    has_multi_domain_collision = False

    for rec in records_list:
        rec_comp = rec.get("company", "")
        rec_dom = rec.get("domain_normalized", "") or rec.get("domain", "")

        res = match_source_record_identity(
            candidate_company=rec_comp,
            candidate_domain=rec_dom,
            canonical_account_id=company_id,
            canonical_company_name=company_name,
            identity_registry=effective_registry,
            allow_unapproved_domain_proposal=(effective_registry is None),
        )

        if res["matched"]:
            # Guard against multi-entity domain collision:
            # If matched via domain, and domain is multi-entity, require corroborating name/alias/ticker
            if res["route"] == "APPROVED_DOMAIN":
                norm_d = normalize_domain(rec_dom)
                if norm_d in multi_domains and len(res["all_routes"]) == 1:
                    has_multi_domain_collision = True
                    continue

            rec_copy = rec.copy()
            rec_copy["canonical_account_id"] = company_id
            rec_copy["canonical_company_name"] = company_name
            rec_copy["match_method"] = res["route"]
            rec_copy["all_match_methods"] = res["all_routes"]
            rec_copy["matched_value"] = res["matched_value"]
            rec_copy["match_confidence"] = res["confidence"]
            rec_copy["match_review_required"] = res["review_required"]
            for k, v in res["lineage"].items():
                rec_copy[k] = v
            matched_records.append(rec_copy)
        elif res.get("is_proposed_association"):
            # A domain in trigger export can be proposed for review only if every row
            # with that domain maps to one organization and is not webmail
            norm_rec_d = normalize_domain(rec_dom)
            norm_target_d = normalize_domain(company_domain)
            if norm_rec_d and norm_target_d and norm_rec_d == norm_target_d:
                if norm_rec_d not in multi_domains and not is_webmail_or_disposable_domain(norm_rec_d):
                    proposed_records.append(rec)

    # Status and confidence resolution
    match_status = "UNMATCHED"
    detailed_match_status = "UNMATCHED"
    match_confidence = "NONE"

    if matched_records:
        match_status = "MATCHED"
        if effective_registry is not None and any(r["match_method"] != "NORMALIZED_CANONICAL_NAME" for r in matched_records):
            detailed_match_status = "APPROVED MATCH"
        else:
            detailed_match_status = "EXACT CANONICAL-NAME MATCH"
        match_confidence = "HIGH" if any(r["match_confidence"] == "HIGH" for r in matched_records) else "MEDIUM"
        has_active = any(not r.get("is_zero_trigger") for r in matched_records)
        if has_active:
            trigger_state = "ACTIVE_TRIGGERS"
            scan_conf = "HIGH"
        else:
            trigger_state = "SCANNED_ZERO_TRIGGERS"
            lead_note = matched_records[0].get("notes", "")
            scan_conf = "HIGH" if len(lead_note) > 80 else "MEDIUM"

        # Integrity Assertion
        assert_account_match_integrity(
            canonical_account_id=company_id,
            matched_records=matched_records,
            canonical_company_name=company_name,
            identity_registry=effective_registry,
        )
    elif proposed_records:
        match_status = "PROPOSED_ASSOCIATION"
        detailed_match_status = "PROPOSED ASSOCIATION"
        match_confidence = "NONE"
        trigger_state = "PROPOSED_ASSOCIATION"
        scan_conf = "LOW"
    elif has_multi_domain_collision:
        match_status = "REVIEW_REQUIRED"
        detailed_match_status = "REVIEW REQUIRED"
        match_confidence = "LOW"
        trigger_state = "MATCH_REVIEW_REQUIRED"
        scan_conf = "LOW"
    else:
        match_status = "UNMATCHED"
        detailed_match_status = "UNMATCHED"
        match_confidence = "NONE"
        trigger_state = "ABSENT_FROM_EXPORT"
        scan_conf = "NOT_APPLICABLE"

    # Segment, Tier, and Conflict Resolution
    distinct_source_company_names = sorted(list({r.get("company") for r in matched_records if r.get("company")}))
    distinct_source_domains = sorted(list({r.get("domain") for r in matched_records if r.get("domain")}))
    observed_export_tiers = sorted(list({r.get("tier") for r in matched_records if r.get("tier") is not None}))
    used_match_methods = sorted(list({m for r in matched_records for m in r.get("all_match_methods", [r.get("match_method")]) if m}))

    export_segment: Optional[str] = None
    export_tier: Optional[int] = None
    sector_conflict_review_required = False
    tier_conflict_review_required = False
    tier_assignment_review_required = False
    multiple_export_tiers_review_required = False

    if matched_records:
        export_segment = matched_records[0].get("segment")

        if len(observed_export_tiers) == 1:
            export_tier = observed_export_tiers[0]
            multiple_export_tiers_review_required = False
        elif len(observed_export_tiers) > 1:
            multiple_export_tiers_review_required = True
            export_tier = None
            conflict_notes.append(
                f"MULTIPLE_EXPORT_TIERS_REVIEW_REQUIRED: Conflicting export tiers observed across legitimately matched records: {observed_export_tiers}"
            )

        if report_sector and export_segment:
            s_rep = str(report_sector).strip().lower()
            s_exp = str(export_segment).strip().lower()
            if "coating" in s_rep or "paint" in s_rep:
                if "oil" in s_exp or "gas" in s_exp:
                    sector_conflict_review_required = True
                    conflict_notes.append(
                        f"Sector Conflict: Report classifies as '{report_sector}', "
                        f"while Wingman export classifies as '{export_segment}'."
                    )

        if export_tier is not None:
            r_str = str(report_wingman_tier).strip().lower() if report_wingman_tier is not None else ""
            rep_tier_int: Optional[int] = None
            if "tier 1" in r_str or r_str == "1":
                rep_tier_int = 1
            elif "tier 2" in r_str or r_str == "2":
                rep_tier_int = 2
            elif "tier 3" in r_str or r_str == "3":
                rep_tier_int = 3

            if rep_tier_int is not None:
                if rep_tier_int != export_tier:
                    tier_conflict_review_required = True
                    conflict_notes.append(
                        f"Tier Conflict: Report tier is 'Tier {rep_tier_int}', "
                        f"while Wingman export tier is 'Tier {export_tier}'."
                    )
                else:
                    tier_conflict_review_required = False
            else:
                tier_assignment_review_required = True
                conflict_notes.append(
                    f"Tier Assignment Gap: Report tier is UNASSIGNED, "
                    f"while Wingman export assigns 'Tier {export_tier}'."
                )

    match_review_required = bool(
        has_multi_domain_collision
        or bool(proposed_records and not matched_records)
        or any(r.get("match_review_required") for r in matched_records)
    )

    any_review_required = bool(
        match_review_required
        or sector_conflict_review_required
        or tier_conflict_review_required
        or tier_assignment_review_required
        or multiple_export_tiers_review_required
        or registry_review_required_flag
    )
    review_required = any_review_required

    return {
        "company_id": company_id,
        "company_name": company_name,
        "canonical_account": company_name,
        "match_status": match_status,
        "detailed_match_status": detailed_match_status,
        "match_method": used_match_methods[0] if used_match_methods else "NONE",
        "match_methods": used_match_methods,
        "match_confidence": match_confidence,
        "trigger_state": trigger_state,
        "scan_confidence": scan_conf,
        "raw_matched_record_count": len(matched_records),
        "matched_records_count": len(matched_records),
        "matched_records": matched_records,
        "proposed_records": proposed_records,
        "proposed_associations": proposed_records,
        "distinct_source_company_names": distinct_source_company_names,
        "distinct_source_domains": distinct_source_domains,
        "observed_export_tiers": observed_export_tiers,
        "report_sector": report_sector,
        "trigger_export_segment": export_segment,
        "sector_conflict_flag": sector_conflict_review_required,
        "report_wingman_tier": report_wingman_tier,
        "trigger_export_tier": export_tier,
        "tier_conflict_flag": tier_conflict_review_required,
        "tier_conflict_review_required": tier_conflict_review_required,
        "tier_assignment_review_required": tier_assignment_review_required,
        "tier_data_gap_review_required": tier_assignment_review_required,
        "multiple_export_tiers_flag": multiple_export_tiers_review_required,
        "multiple_export_tiers_review_required": multiple_export_tiers_review_required,
        "match_review_required": match_review_required,
        "sector_conflict_review_required": sector_conflict_review_required,
        "registry_input_state": registry_input_state_val,
        "registry_applied": registry_applied_flag,
        "registry_review_required": registry_review_required_flag,
        "any_review_required": any_review_required,
        "review_required": review_required,
        "conflict_notes": conflict_notes,
    }


def extract_event_identity_key(summary: str, trigger_type: str) -> Tuple[Optional[str], str]:
    """
    Extracts a normalized project, facility, asset, or transaction counterparty token.
    Requires an explicit proper noun or asset/counterparty keyword to avoid blind merges.
    """
    if not summary or str(summary).strip() == "":
        return None, "EMPTY_SUMMARY"

    s_lower = summary.lower()

    # Counterparty in M&A / Partnerships
    m_acq = re.search(r"\b(?:acquire[sd]?|acquisition of|merger with|agreement with|bought|partnered with)\s+([a-zA-Z0-9\s&]+?)(?:\s+for|\s+in|\s+to|\s+closing|\s*,|\s*\.|\s*\(|$)", summary, re.IGNORECASE)
    if m_acq:
        c_token = normalize_company_name_conservative(m_acq.group(1))
        if len(c_token) >= 3:
            return f"cp_{c_token.replace(' ', '_')}", "TRANSACTION_COUNTERPARTY"

    # Facility / Asset patterns
    facility_patterns = [
        r"\b(?:at|for|near|of)\s+([a-zA-Z0-9_-]+(?:\s+[a-zA-Z0-9_-]+)?)\s+(?:refinery|plant|terminal|complex|facility|pipeline|platform|field|fpso|unit|cdu|fcc|lng|giga)\b",
        r"\b([a-zA-Z0-9_-]+(?:\s+[a-zA-Z0-9_-]+)?)\s+(?:refinery|plant|terminal|complex|pipeline|platform|field|fpso|unit|cdu|fcc|lng|giga)\b",
        r"\b(?:refinery|plant|terminal|complex|pipeline|platform|field|fpso|facility)\s+(?:at|near|in)\s+([a-zA-Z0-9_-]+)\b",
        r"\bProject\s+([a-zA-Z0-9_-]+)\b",
    ]
    stopwords = {"its", "the", "a", "an", "new", "major", "planned", "two", "active", "routine", "annual", "large"}
    for pat in facility_patterns:
        m = re.search(pat, summary, re.IGNORECASE)
        if m:
            raw_asset = m.group(1).strip().lower()
            tokens = [t for t in raw_asset.split() if t not in stopwords]
            if tokens:
                asset_token = re.sub(r"[^\w]", "_", "_".join(tokens)).strip("_")
                if len(asset_token) >= 3:
                    return f"asset_{asset_token}", "NAMED_ASSET_FACILITY"

    # Known industrial assets keyword scanner
    common_assets = [
        "jamnagar", "baytown", "beaumont", "golden_pass", "western_gateway",
        "trident", "monument", "jazan", "ras_tanura", "el_dorado", "puget_sound",
        "ruya", "al_shaheen", "umm_shaif", "noble_greatwhite", "cendramas",
    ]
    for ca in common_assets:
        clean_word = ca.replace("_", " ")
        if clean_word in s_lower:
            return f"asset_{ca}", "NAMED_ASSET_KEYWORD"

    return None, "NO_NAMED_ASSET_OR_COUNTERPARTY"


def cluster_wingman_events(
    matched_records: List[Dict[str, Any]],
    company_id: str,
) -> List[Dict[str, Any]]:
    """
    Conservative event clustering:
    - Never relies on company, trigger type, and date alone.
    - Requires a shared normalized asset, facility, transaction counterparty or project identifier.
    - Multi-entity and alias records describing the same event are merged into 1 scoring cluster.
    - Preserves all raw child records and source URLs.
    - Generates a deterministic hash-based cluster ID.
    """
    active_records = [r for r in matched_records if not r.get("is_zero_trigger")]
    if not active_records:
        return []

    clusters: List[Dict[str, Any]] = []

    by_type: Dict[str, List[Dict[str, Any]]] = {}
    for r in active_records:
        tt = r.get("trigger_type") or "other"
        by_type.setdefault(tt, []).append(r)

    for tt, recs in by_type.items():
        used_indices: Set[int] = set()

        for i in range(len(recs)):
            if i in used_indices:
                continue

            r1 = recs[i]
            event_key1, key_source1 = extract_event_identity_key(r1.get("trigger_summary", ""), tt)
            child_group = [r1]
            used_indices.add(i)

            cluster_review_required = False
            cluster_method = "SINGLETON"
            cluster_confidence = "HIGH"

            for j in range(i + 1, len(recs)):
                if j in used_indices:
                    continue
                r2 = recs[j]
                event_key2, key_source2 = extract_event_identity_key(r2.get("trigger_summary", ""), tt)

                has_shared_key = bool(event_key1 and event_key2 and event_key1 == event_key2)

                d1 = r1.get("trigger_date_parsed")
                d2 = r2.get("trigger_date_parsed")
                date_close = False
                if d1 and d2:
                    date_close = abs((d1 - d2).days) <= 30
                elif r1.get("trigger_date_raw") and r2.get("trigger_date_raw"):
                    date_close = r1.get("trigger_date_raw") == r2.get("trigger_date_raw")

                if has_shared_key and date_close:
                    child_group.append(r2)
                    used_indices.add(j)
                    cluster_method = "SHARED_ASSET_AND_WINDOW"
                    cluster_confidence = "HIGH"
                elif date_close and not has_shared_key:
                    cluster_review_required = True

            all_urls: List[str] = []
            for cr in child_group:
                for u in cr.get("trigger_source_urls", []):
                    if u not in all_urls:
                        all_urls.append(u)

            lead_child = max(
                child_group,
                key=lambda x: (
                    1 if x.get("date_precision") == "DAY" else 0,
                    len(x.get("trigger_summary", "")),
                ),
            )

            hash_input = (
                f"{company_id}|{tt}|{event_key1 or 'unidentified'}|"
                f"{lead_child.get('date_precision')}|{lead_child.get('trigger_date_parsed') or lead_child.get('trigger_date_raw')}"
            )
            cluster_hash = hashlib.sha256(hash_input.encode()).hexdigest()[:8].upper()
            cluster_id = f"CLUST-{company_id[:8]}-{tt[:3].upper()}-{cluster_hash}"

            clusters.append({
                "cluster_id": cluster_id,
                "company_id": company_id,
                "trigger_type": tt,
                "event_identity_key": event_key1,
                "event_key_source": key_source1,
                "lead_summary": lead_child.get("trigger_summary", ""),
                "lead_summary_raw": lead_child.get("trigger_summary", ""),
                "lead_date_parsed": lead_child.get("trigger_date_parsed"),
                "lead_date_raw": lead_child.get("trigger_date_raw"),
                "date_precision": lead_child.get("date_precision"),
                "date_parse_status": lead_child.get("date_parse_status"),
                "date_relation_at_scan": lead_child.get("date_relation_at_scan"),
                "scanned_at_date": lead_child.get("scanned_at_date"),
                "all_source_urls": all_urls,
                "child_records_count": len(child_group),
                "child_records": child_group,
                "cluster_method": cluster_method,
                "cluster_confidence": cluster_confidence,
                "cluster_review_required": cluster_review_required,
            })

    return clusters


def calculate_wingman_trigger_relevance(
    clusters: List[Dict[str, Any]],
    as_of_date: date,
    weights: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """
    Computes Trigger Relevance exclusively driven by Wingman dated triggers.
    - Evaluates each cluster across Asset, Stage, Workforce, and Source credibility
    - Applies recency/temporal decay based on analysis_as_of_date
    - Computes lead cluster and momentum blend across distinct project clusters
    - Derives temporal_status_as_of for the lead cluster
    - Sets trigger_evidence_confidence: HIGH, MEDIUM, LOW, or NOT_APPLICABLE
    """
    w = weights or {
        "trigger_asset_max": 25.0,
        "trigger_stage_max": 25.0,
        "trigger_workforce_max": 25.0,
        "trigger_source_max": 25.0,
    }

    if not clusters:
        return {
            "score": 0.0,
            "raw_points": 0.0,
            "max_raw_points": 100.0,
            "temporal_status_as_of": "NONE_DETECTED",
            "temporal_status_label": "No active Wingman triggers (0 detected)",
            "trigger_evidence_confidence": "NOT_APPLICABLE",
            "clusters": [],
            "distinct_projects_count": 0,
            "lead_cluster": None,
            "notes": "No Wingman trigger clusters found.",
        }

    scored_clusters: List[Dict[str, Any]] = []

    for c in clusters:
        tt = c["trigger_type"]
        s_lower = c["lead_summary"].lower()

        w_ast = float(w.get("trigger_asset_max", 25.0))
        if c.get("event_identity_key") and "asset_" in c.get("event_identity_key", ""):
            asset_pts = w_ast
            asset_detail = "Specific named operational facility or asset"
        elif c.get("event_identity_key"):
            asset_pts = round(w_ast * 0.70, 1)
            asset_detail = "Specific corporate counterparty or project identifier"
        else:
            asset_pts = round(w_ast * 0.30, 1)
            asset_detail = "Broad operational commentary without named asset"

        w_stg = float(w.get("trigger_stage_max", 25.0))
        if tt in ("project_fid_commissioning", "turnaround"):
            stage_pts = w_stg
            stage_heuristic = "Active Commissioning / Turnaround Shutdown"
        elif tt in ("incident_regulator", "audit_cycle"):
            stage_pts = round(w_stg * 0.85, 1)
            stage_heuristic = "Formal Regulatory Action / Compliance Audit"
        elif tt in ("ma_acquisition", "hiring_burst"):
            stage_pts = round(w_stg * 0.75, 1)
            stage_heuristic = "Transaction Execution / Active Workforce Recruitment"
        elif tt == "new_leader":
            stage_pts = round(w_stg * 0.60, 1)
            stage_heuristic = "Executive Leadership Transition"
        else:
            stage_pts = round(w_stg * 0.40, 1)
            stage_heuristic = "General Operational Activity"

        w_wrk = float(w.get("trigger_workforce_max", 25.0))
        if tt in ("hiring_burst", "turnaround"):
            workforce_pts = w_wrk
            workforce_detail = "Direct: Procedure execution, maintenance crews, or technician hiring"
        elif tt in ("incident_regulator", "audit_cycle"):
            workforce_pts = round(w_wrk * 0.85, 1)
            workforce_detail = "High: Safety compliance, competence qualification, and procedural audit"
        elif any(k in s_lower for k in ["training", "competence", "operator", "technician", "simulator", "safety", "workforce"]):
            workforce_pts = round(w_wrk * 0.75, 1)
            workforce_detail = "Moderate: Procedure execution or workforce readiness mentioned"
        else:
            workforce_pts = round(w_wrk * 0.40, 1)
            workforce_detail = "Indirect: Operational scaling requiring procedural alignment"

        w_src = float(w.get("trigger_source_max", 25.0))
        urls = c.get("all_source_urls", [])
        if any("sec.gov" in u or "phmsa" in u or "epa.gov" in u or "osha" in u for u in urls):
            source_pts = w_src
            source_tier = "Authoritative Regulatory Docket / Statutory Filing"
        elif any("bloomberg" in u or "reuters" in u or "business-standard" in u or "hydrocarbonprocessing" in u for u in urls):
            source_pts = round(w_src * 0.80, 1)
            source_tier = "Major Financial / Industry Wire"
        elif urls:
            source_pts = round(w_src * 0.60, 1)
            source_tier = "Online Trade / News Source"
        else:
            source_pts = round(w_src * 0.30, 1)
            source_tier = "Secondary Summary"

        base_raw_pts = asset_pts + stage_pts + workforce_pts + source_pts
        max_raw_pts = w_ast + w_stg + w_wrk + w_src

        temp_status = compute_temporal_status_as_of(
            c.get("lead_date_parsed"),
            c.get("date_precision", "MISSING"),
            as_of_date,
            is_zero_trigger=False,
        )

        if temp_status in ("CURRENT_ACTIVE", "UPCOMING_0_180_DAYS"):
            recency_mult = 1.00
        elif temp_status in ("PLANNED_181_365_DAYS", "RECENT_PAST"):
            recency_mult = 0.85
        elif temp_status == "LONG_RANGE_OVER_365_DAYS":
            recency_mult = 0.70
        elif temp_status == "HISTORICAL":
            recency_mult = 0.50
        else:
            recency_mult = 0.65

        calibrated_cluster_score = round(min(100.0, (base_raw_pts / max_raw_pts) * 100.0 * recency_mult), 1)

        c_copy = dict(c)
        c_copy.update({
            "asset_pts": asset_pts,
            "stage_pts": stage_pts,
            "workforce_pts": workforce_pts,
            "source_pts": source_pts,
            "base_raw_pts": base_raw_pts,
            "max_raw_pts": max_raw_pts,
            "recency_multiplier": recency_mult,
            "cluster_score": calibrated_cluster_score,
            "temporal_status_as_of": temp_status,
            "stage_heuristic": stage_heuristic,
            "workforce_detail": workforce_detail,
            "source_tier": source_tier,
        })
        scored_clusters.append(c_copy)

    scored_clusters.sort(key=lambda x: x["cluster_score"], reverse=True)
    lead_c = scored_clusters[0]

    lead_score = lead_c["cluster_score"]
    secondary_score = scored_clusters[1]["cluster_score"] if len(scored_clusters) > 1 else 0.0

    if len(scored_clusters) >= 3:
        final_score = min(100.0, round(0.70 * lead_score + 0.20 * secondary_score + 10.0, 1))
    elif len(scored_clusters) == 2:
        final_score = min(100.0, round(0.75 * lead_score + 0.20 * secondary_score + 5.0, 1))
    else:
        final_score = lead_score

    lead_prec = lead_c.get("date_precision")
    lead_urls = lead_c.get("all_source_urls", [])
    if lead_prec == "DAY" and lead_urls:
        trig_conf = "HIGH"
    elif lead_prec in ("MONTH", "QUARTER") or lead_urls:
        trig_conf = "MEDIUM"
    else:
        trig_conf = "LOW"

    return {
        "score": final_score,
        "raw_points": final_score,
        "max_raw_points": 100.0,
        "temporal_status_as_of": lead_c["temporal_status_as_of"],
        "trigger_evidence_confidence": trig_conf,
        "clusters": scored_clusters,
        "distinct_projects_count": len(scored_clusters),
        "lead_cluster": lead_c,
        "notes": f"Exclusively driven by Wingman trigger export ({len(scored_clusters)} distinct event clusters).",
    }


def derive_recommended_action_wingman(
    temporal_status_as_of: str,
    trigger_score: float,
    contact_status: str,
    evidence_coverage_pct: float,
    trigger_state: str = "ACTIVE_TRIGGERS",
) -> str:
    """
    Deterministic Recommended Next Action cascade incorporating distance-to-event rules:
    - Zero-trigger scan: Monitor
    - 0–180 days: Prepare outreach
    - 181–365 days: Plan outreach
    - >365 days: Monitor milestone
    - Current Active + matched buyer: Contact now
    - Current Active + unknown buyer: Identify buyer
    - Recent past / historical: Validate trigger
    - Unknown date: Validate trigger
    - Coverage < 50%: Append (Provisional)
    - Strict safeguard: Contactability = UNKNOWN can NEVER produce Contact now.
    """
    if trigger_state == "SCANNED_ZERO_TRIGGERS":
        return "Monitor"

    if trigger_state == "ABSENT_FROM_EXPORT":
        base_action = "Trigger research needed"
    elif temporal_status_as_of == "NONE_DETECTED":
        base_action = "Monitor"
    elif temporal_status_as_of == "UPCOMING_0_180_DAYS":
        base_action = "Prepare outreach"
    elif temporal_status_as_of == "PLANNED_181_365_DAYS":
        base_action = "Plan outreach"
    elif temporal_status_as_of == "LONG_RANGE_OVER_365_DAYS":
        base_action = "Monitor milestone"
    elif temporal_status_as_of == "CURRENT_ACTIVE":
        if contact_status in ("KNOWN", "PARTIAL") and trigger_score >= 65.0:
            base_action = "Contact now"
        else:
            base_action = "Identify buyer"
    elif temporal_status_as_of in ("RECENT_PAST", "HISTORICAL"):
        if trigger_score >= 60.0:
            base_action = "Validate trigger"
        else:
            base_action = "Monitor"
    else:  # UNKNOWN
        if trigger_score >= 70.0:
            base_action = "Identify buyer"
        elif trigger_score >= 50.0:
            base_action = "Validate trigger"
        else:
            base_action = "Monitor"

    if contact_status == "UNKNOWN" and base_action == "Contact now":
        base_action = "Identify buyer"

    if evidence_coverage_pct < 50.0 and base_action not in ("Monitor", "Monitor milestone"):
        return f"{base_action} (Provisional)"

    return base_action
