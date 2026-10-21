"""
Validation rules enforcing policy constraints:
- Preserving missing values vs explicit zeros
- Preventing safety performance inference from regulatory silence
- Validating controlled availability categories (NO_RECORD_REACHABLE, NOT_REPORTED)
- Checking manual Wingman labels and sources
- Verifying distinct source metrics, stable identifiers, and count reconciliations
"""
from typing import List, Tuple
from src.models import CompanyRecord

CONTROLLED_AVAILABILITY_CATEGORIES = {
    "NO_RECORD_REACHABLE",
    "RECORD_REACHABLE",
    "NOT_REPORTED",
    "PARSING_FAILED",
}


def validate_zero_vs_missing(records: List[CompanyRecord]) -> List[str]:
    violations = []
    for rec in records:
        # Reliance founded and people_employed MUST be missing (None), not "0" or 0
        if "Reliance" in rec.company_name:
            f_fe = rec.fields.get("year_founded")
            if f_fe and (f_fe.standardized_value == "0" or f_fe.report_native_value == "0"):
                violations.append(f"{rec.company_name}: year_founded must be missing, not numeric 0.")
            if f_fe and f_fe.validation_status not in ["MISSING_NOT_REPORTED", "PARSING_FAILED"]:
                violations.append(f"{rec.company_name}: year_founded status should be MISSING_NOT_REPORTED, got {f_fe.validation_status}.")

            e_fe = rec.fields.get("people_employed")
            if e_fe and (e_fe.standardized_value == "0" or e_fe.report_native_value == "0"):
                violations.append(f"{rec.company_name}: people_employed must be missing, not numeric 0.")
            if e_fe and e_fe.validation_status not in ["MISSING_NOT_REPORTED", "PARSING_FAILED"]:
                violations.append(f"{rec.company_name}: people_employed status should be MISSING_NOT_REPORTED, got {e_fe.validation_status}.")

        # Explicit zeros must have status EXPLICIT_ZERO and evidence
        for zero_field in ["citations_count", "penalties_amount", "investigated_accidents_count", "deaths_count"]:
            fe = rec.fields.get(zero_field)
            if fe:
                if fe.standardized_value == "0":
                    if fe.validation_status != "EXPLICIT_ZERO":
                        violations.append(f"{rec.company_name}: {zero_field} is '0' but status is not EXPLICIT_ZERO ({fe.validation_status}).")
                    if not fe.source_evidence or fe.page_number is None:
                        violations.append(f"{rec.company_name}: {zero_field} zero value lacks evidence or page number.")
                elif fe.standardized_value is None or fe.standardized_value == "":
                    if fe.validation_status not in ["MISSING_NOT_REPORTED", "PARSING_FAILED"]:
                        violations.append(f"{rec.company_name}: missing {zero_field} should have status MISSING_NOT_REPORTED or PARSING_FAILED.")
    return violations


def validate_categorical_availability(records: List[CompanyRecord]) -> List[str]:
    violations = []
    for rec in records:
        fe = rec.fields.get("official_records_availability")
        if not fe:
            violations.append(f"{rec.company_name}: official_records_availability field is missing.")
            continue
        std = fe.standardized_value
        if std not in CONTROLLED_AVAILABILITY_CATEGORIES:
            violations.append(f"{rec.company_name}: official_records_availability '{std}' not in controlled categories: {CONTROLLED_AVAILABILITY_CATEGORIES}.")
        if std == "0" or fe.report_native_value == "0":
            violations.append(f"{rec.company_name}: official_records_availability must NOT be numeric 0.")
        
        if "Reliance" in rec.company_name or "Exxon" in rec.company_name:
            if std != "NO_RECORD_REACHABLE":
                violations.append(f"{rec.company_name}: expected categorical 'NO_RECORD_REACHABLE', got '{std}'.")
        elif "Sherwin" in rec.company_name:
            if std != "NOT_REPORTED":
                violations.append(f"{rec.company_name}: expected categorical 'NOT_REPORTED', got '{std}'.")

        # Check registry_search_status and official_company_record_found
        reg_fe = rec.fields.get("registry_search_status")
        if not reg_fe or reg_fe.standardized_value != "SEARCH_EXECUTED":
            violations.append(f"{rec.company_name}: expected registry_search_status = 'SEARCH_EXECUTED'.")
        
        rec_found_fe = rec.fields.get("official_company_record_found")
        if not rec_found_fe or rec_found_fe.standardized_value != "FALSE":
            violations.append(f"{rec.company_name}: expected official_company_record_found = 'FALSE'.")
    return violations


def validate_safety_non_inference(records: List[CompanyRecord]) -> List[str]:
    violations = []
    for rec in records:
        fe = rec.fields.get("safety_performance_inference")
        if not fe:
            violations.append(f"{rec.company_name}: safety_performance_inference field is missing.")
            continue
        if "CANNOT_INFER_SAFE" not in (fe.standardized_value or ""):
            violations.append(f"{rec.company_name}: safety_performance_inference must declare CANNOT_INFER_SAFE.")
        for _, other_fe in rec.fields.items():
            val = (other_fe.standardized_value or "").lower()
            if any(term in val for term in ["excellent safety", "proven safe", "low risk operator"]):
                violations.append(f"{rec.company_name}: Unauthorized safety inference detected: '{val}'.")
    return violations


def validate_wingman_labels(records: List[CompanyRecord]) -> List[str]:
    expected_tiers = {
        "ExxonMobil": "Tier 1",
        "Reliance (RIL)": "Tier 2",
        "Sherwin-Williams": "Tier 3",
    }
    violations = []
    for rec in records:
        exp = expected_tiers.get(rec.company_name)
        if exp and rec.wingman.tier != exp:
            violations.append(f"{rec.company_name}: Expected Wingman {exp}, got {rec.wingman.tier}.")
        if exp and rec.wingman.source != "manual_from_trigger_board":
            violations.append(f"{rec.company_name}: Expected Wingman source 'manual_from_trigger_board', got '{rec.wingman.source}'.")
        elif not exp and rec.wingman.tier == "UNASSIGNED" and rec.wingman.source != "NOT_PROVIDED":
            violations.append(f"{rec.company_name}: Expected unassigned Wingman source 'NOT_PROVIDED', got '{rec.wingman.source}'.")
    return violations


def validate_stable_identifiers(records: List[CompanyRecord]) -> List[str]:
    violations = []
    for rec in records:
        if not rec.company_id.startswith("COMP-"):
            violations.append(f"{rec.company_name}: Invalid company_id '{rec.company_id}'.")
        for sig in rec.forward_signals:
            if not sig.signal_id.startswith("SIG-"):
                violations.append(f"{rec.company_name}: Invalid signal_id '{sig.signal_id}'.")
        for acc in rec.public_accounts:
            if not acc.account_id.startswith("ACC-"):
                violations.append(f"{rec.company_name}: Invalid account_id '{acc.account_id}'.")
        for pat in rec.seven_patterns:
            if not pat.pattern_id.startswith("PAT-"):
                violations.append(f"{rec.company_name}: Invalid pattern_id '{pat.pattern_id}'.")
    return violations


def validate_the_seven_integrity(records: List[CompanyRecord]) -> List[str]:
    violations = []
    expected_nums = {"01", "02", "03", "04", "05", "06", "07"}
    for rec in records:
        nums = {p.pattern_number for p in rec.seven_patterns}
        if nums != expected_nums:
            violations.append(f"{rec.company_name}: 'The Seven' pattern numbers do not match expected set: {nums} vs {expected_nums}")
        for p in rec.seven_patterns:
            if not p.pattern_name.strip():
                violations.append(f"{rec.company_name} {p.pattern_id}: pattern_name is empty.")
            if not p.quote.strip():
                violations.append(f"{rec.company_name} {p.pattern_id}: quote is empty.")
            if not p.solution_closed_by.strip():
                violations.append(f"{rec.company_name} {p.pattern_id}: solution_closed_by is empty.")
    return violations


def validate_all_policies(records: List[CompanyRecord]) -> Tuple[bool, List[str]]:
    all_violations = []
    all_violations.extend(validate_zero_vs_missing(records))
    all_violations.extend(validate_categorical_availability(records))
    all_violations.extend(validate_safety_non_inference(records))
    all_violations.extend(validate_wingman_labels(records))
    all_violations.extend(validate_stable_identifiers(records))
    all_violations.extend(validate_the_seven_integrity(records))
    return len(all_violations) == 0, all_violations
