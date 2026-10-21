"""
Consultative Buyer & Outreach Recommendation Engine for EON Pattern Extractor.
Implements:
  - Decoupled 3-Component Scoring: Account Fit, Trigger Relevance, Contactability
  - Temporal Urgency field separated from Trigger Relevance (remains UNKNOWN if undated)
  - Zero-points for missing values (never awards midpoint or default points for missing data)
  - Separate score, evidence_coverage_pct, and confidence_level
  - EON Use-Case Alignment (replaces Reporting Maturity; no penalty for non-SEC or foreign entities)
  - Multi-dimensional Trigger Relevance (Asset, Stage, Workforce, Source) preventing score saturation
  - Canonical Seven Patterns loaded dynamically from seven_patterns.csv (Pattern 2 = LOST EXPERIENCE -> EON Tacit)
  - Clear separation of account_opportunity (Fit tiers) vs outreach_readiness vs recommended_next_action
  - Column semantics: Contactability displays only KNOWN, PARTIAL, or UNKNOWN
  - Next Action rules:
      * Verified current trigger + known suitable buyer -> Contact now
      * Strong relevant trigger + no buyer -> Identify buyer
      * Relevant but undated/unverified trigger -> Validate trigger
      * Weak/no trigger -> Monitor
      * Low evidence coverage (< 50%) -> append (Provisional)
  - Softened product claims: "is designed to support procedure rehearsal before live execution"
  - Default EON scope: Oil, Gas, Energy Infrastructure, Refining and Petrochemicals
  - Data-driven sector classification from line_of_work with Unclassified fallback
  - Company-alias normalizer and schema validation for optional CRM and Contact CSV uploads
  - Privacy-safe contact export with PII masking
"""

import re
from typing import Dict, Any, List, Optional, Tuple
import pandas as pd
import numpy as np

from dashboard.identity_registry import (
    AccountIdentityRegistry,
    match_source_record_identity,
    normalize_company_name_conservative,
)

# Methodological Version & Defaults
METHODOLOGY_VERSION = "1.1.0"
DEFAULT_PRESET_NAME = "Default Balanced Heuristic v1.1"

DEFAULT_EON_SCOPE = "Oil, Gas, Energy Infrastructure, Refining and Petrochemicals"

# Default scoring weights (Can be tuned via Advanced Settings)
DEFAULT_WEIGHTS = {
    "fit_headcount_max": 40.0,
    "fit_footprint_max": 15.0,
    "fit_sector_max": 25.0,
    "fit_use_case_max": 20.0,
    "trigger_asset_max": 25.0,
    "trigger_stage_max": 25.0,
    "trigger_workforce_max": 25.0,
    "trigger_source_max": 25.0,
    "contact_role_max": 50.0,
    "contact_stage_max": 50.0,
    "composite_weight_fit": 0.40,
    "composite_weight_trigger": 0.40,
    "composite_weight_contact": 0.20,
}

# Approved Product Positioning Copy Dictionary (Configurable)
APPROVED_PRODUCT_POSITIONING = {
    "simulation_suite": (
        "EON's industrial simulation suite ({solutions}) is designed to support procedure rehearsal before live execution."
    ),
    "operational_readiness": (
        "EON Genesis procedure simulation enables frontline crews to rehearse non-routine operating scenarios before live execution."
    ),
    "tacit_knowledge": (
        "EON Tacit captures veteran field expertise into interactive procedure modules for incoming operators."
    ),
    "competence_verification": (
        "Assess IQ + Competence IQ provides verified practical execution testing rather than read-and-sign compliance."
    ),
}


def abbreviate_monetary_values(text: str) -> str:
    """
    Abbreviates large monetary values in presentation strings without mutating source data.
    Examples:
      - 'Rs 150000000000' -> 'Rs 15,000 cr'
      - '$2000000000' -> '$2B'
      - '$150000000' -> '$150M'
      - '$38 million' -> '$38M'
    Preserves surrounding text verbatim.
    """
    if not text or not isinstance(text, str):
        return text

    # Handle Rs with 7+ digits (Indian crore system: 1 crore = 10,000,000)
    def _repl_rs(match):
        prefix = match.group(1)
        num_str = match.group(2).replace(",", "")
        try:
            val = float(num_str)
            if val >= 1e7:
                cr = val / 1e7
                cr_str = f"{int(cr):,}" if cr == int(cr) else f"{cr:,.1f}"
                return f"{prefix}{cr_str} cr"
        except ValueError:
            pass
        return match.group(0)

    res = re.sub(r'\b(Rs\.?\s*)(\d[\d,]{6,})\b', _repl_rs, text, flags=re.IGNORECASE)

    # Handle $ with 7+ digits
    def _repl_dollar(match):
        num_str = match.group(1).replace(",", "")
        try:
            val = float(num_str)
            if val >= 1e9:
                b = val / 1e9
                b_str = f"{int(b)}" if b == int(b) else f"{b:.1f}"
                return f"${b_str}B"
            elif val >= 1e6:
                m = val / 1e6
                m_str = f"{int(m)}" if m == int(m) else f"{m:.1f}"
                return f"${m_str}M"
        except ValueError:
            pass
        return match.group(0)

    res = re.sub(r'\$\s*(\d[\d,]{6,})\b', _repl_dollar, res)

    # Handle explicit '$XX million' or '$XX billion'
    res = re.sub(r'\$\s*(\d+(?:\.\d+)?)\s*billion\b', r'$\1B', res, flags=re.IGNORECASE)
    res = re.sub(r'\$\s*(\d+(?:\.\d+)?)\s*million\b', r'$\1M', res, flags=re.IGNORECASE)

    return res


def normalize_company_name(name: str, identity_registry: Optional[AccountIdentityRegistry] = None) -> str:
    """
    Normalize company name using conservative full-field normalization.
    If an approved AccountIdentityRegistry is supplied, resolves to canonical company name.
    Strictly prohibits substring containment (no regex or partial word matching).
    """
    if not name or pd.isna(name):
        return "Unknown"
    raw = str(name).strip()
    if not raw:
        return "Unknown"
    if identity_registry:
        alias_meta = identity_registry.resolve_alias(raw)
        if alias_meta:
            c_id = alias_meta["canonical_account_id"]
            return identity_registry.get_canonical_name(c_id) or alias_meta["canonical_company_name"]
        t_meta = identity_registry.resolve_ticker(raw)
        if t_meta:
            c_id = t_meta["canonical_account_id"]
            return identity_registry.get_canonical_name(c_id) or t_meta["canonical_company_name"]
    return raw



def classify_sector_from_line_of_work(line_of_work: Any) -> str:
    """
    Data-driven sector classification derived directly from normalized line_of_work.
    Supports any new company without hardcoding company-to-sector lists.
    """
    if not line_of_work or pd.isna(line_of_work):
        return "Unclassified"

    low_str = str(line_of_work).strip().lower()

    if any(k in low_str for k in ["oil", "gas", "pipeline", "terminal", "petroleum", "upstream", "midstream", "downstream", "energy infrastructure"]):
        return "Energy & Oil & Gas Infrastructure"
    elif any(k in low_str for k in ["petrochemical", "refin", "plastics", "polymers"]):
        return "Petrochemicals & Refining"
    elif any(k in low_str for k in ["paint", "coating", "varnish", "pigment"]):
        return "Coatings & Advanced Materials"
    elif any(k in low_str for k in ["chemical", "specialty chemicals"]):
        return "Specialty Chemicals"
    elif any(k in low_str for k in ["manufactur", "industrial", "fabrication"]):
        return "General Industrial"
    else:
        return "Unclassified"


def is_in_default_eon_scope(sector: str) -> bool:
    """
    Determines if a sector is within EON's core industrial focus:
    Oil, Gas, Energy Infrastructure, Refining and Petrochemicals.
    """
    return sector in (
        "Energy & Oil & Gas Infrastructure",
        "Petrochemicals & Refining",
    )


def get_scope_label(sector: str) -> str:
    """Returns official scope label for a sector."""
    return "IN CORE EON SCOPE" if is_in_default_eon_scope(sector) else "OUT OF DEFAULT EON SCOPE"


def calculate_evidence_coverage(company_row: pd.Series) -> Tuple[float, str]:
    """
    Calculate evidence coverage percentage based on key operational profile fields.
    Returns (coverage_pct, confidence_level).
    Lower evidence coverage directly reduces confidence level.
    """
    core_fields = [
        "people_employed",
        "line_of_work",
        "business_description",
        "operating_countries",
        "headquarters_city",
        "headquarters_country",
        "year_founded",
    ]
    present_count = 0
    for field in core_fields:
        val = company_row.get(field)
        if pd.notna(val) and str(val).strip() != "" and str(val).lower() not in ("nan", "not reported", "not disclosed"):
            present_count += 1

    coverage_pct = round((present_count / len(core_fields)) * 100.0, 1)

    if coverage_pct >= 80.0:
        confidence = "HIGH"
    elif coverage_pct >= 50.0:
        confidence = "MEDIUM"
    else:
        confidence = "LOW"

    return coverage_pct, confidence


def assess_eon_use_case_alignment(company_row: pd.Series, max_pts: float = 20.0) -> Tuple[float, str, str]:
    """
    Replaces Reporting Maturity. Evaluates whether available operational narrative
    indicates process-intensive operations, complex equipment, repeatable procedures,
    or facility commissioning.
    Zero points awarded if evidence is missing (marked NOT ASSESSED).
    Returns (points, assessment_status, evidence_quote).
    """
    desc = str(company_row.get("business_description") or "")
    low = str(company_row.get("line_of_work") or "")
    op_text = (desc + " " + low).lower()

    if not desc and not low:
        return 0.0, "NOT ASSESSED", "No narrative operational disclosures available in report."

    keywords_process = [
        "manufacture", "distribution", "refining", "pipelines", "terminals",
        "petrochemicals", "coatings", "production", "facilities", "energy infrastructure"
    ]
    matches = [k for k in keywords_process if k in op_text]

    if matches:
        evidence = desc if desc else f"Operating in {low}"
        return float(max_pts), "SUPPORTED", evidence
    else:
        return 0.0, "NOT ASSESSED", "Operational description does not explicitly describe process-intensive facility assets."


def calculate_account_fit(company_row: pd.Series, weights: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
    """
    Calculate Account Fit score (0-100 pts) with transparent raw points and explicit normalization.
    Strict rule: Missing values contribute ZERO points (not midpoint points).
    """
    w = weights or DEFAULT_WEIGHTS
    coverage_pct, confidence = calculate_evidence_coverage(company_row)

    # 1. Operational Scale (Headcount)
    headcount = company_row.get("people_employed")
    headcount_pts = 0.0
    headcount_status = "MISSING"
    if pd.notna(headcount) and str(headcount).replace(".", "").isdigit():
        emp = float(headcount)
        headcount_status = f"{int(emp):,} employees"
        if emp >= 50000:
            headcount_pts = w["fit_headcount_max"]
        elif emp >= 10000:
            headcount_pts = w["fit_headcount_max"] * 0.75
        elif emp > 0:
            headcount_pts = w["fit_headcount_max"] * 0.40
    else:
        # Zero points for missing headcount!
        headcount_pts = 0.0

    # 2. Operating Footprint
    footprint = company_row.get("operating_countries")
    footprint_pts = 0.0
    footprint_status = "MISSING"
    if pd.notna(footprint) and str(footprint).strip() and str(footprint).lower() != "nan":
        footprint_str = str(footprint).strip()
        footprint_status = footprint_str
        if any(term in footprint_str.lower() for term in ["120", "global", "worldwide", "international", "over"]):
            footprint_pts = w["fit_footprint_max"]
        else:
            footprint_pts = w["fit_footprint_max"] * 0.50
    else:
        # Zero points for missing footprint!
        footprint_pts = 0.0

    # 3. Sector Criticality
    sector = classify_sector_from_line_of_work(company_row.get("line_of_work"))
    sector_pts = 0.0
    if sector in ("Energy & Oil & Gas Infrastructure", "Petrochemicals & Refining"):
        sector_pts = w["fit_sector_max"]
    elif sector in ("Coatings & Advanced Materials", "Specialty Chemicals"):
        sector_pts = w["fit_sector_max"] * 0.80
    elif sector == "General Industrial":
        sector_pts = w["fit_sector_max"] * 0.50
    else:
        sector_pts = 0.0  # Unclassified

    # 4. EON Use-Case Alignment (Replaces Reporting Maturity)
    use_case_pts, use_case_status, use_case_evidence = assess_eon_use_case_alignment(
        company_row, w.get("fit_use_case_max", 20.0)
    )

    raw_points = headcount_pts + footprint_pts + sector_pts + use_case_pts
    max_raw_points = (
        w.get("fit_headcount_max", 40.0)
        + w.get("fit_footprint_max", 15.0)
        + w.get("fit_sector_max", 25.0)
        + w.get("fit_use_case_max", 20.0)
    )

    normalized_score = min(100.0, round((raw_points / max_raw_points) * 100.0, 1)) if max_raw_points > 0 else 0.0

    return {
        "score": normalized_score,
        "raw_points": round(raw_points, 1),
        "max_raw_points": round(max_raw_points, 1),
        "evidence_coverage_pct": coverage_pct,
        "confidence_level": confidence,
        "sector": sector,
        "is_in_core_eon_scope": is_in_default_eon_scope(sector),
        "scope_label": get_scope_label(sector),
        "breakdown": {
            "headcount_pts": headcount_pts,
            "headcount_max": w["fit_headcount_max"],
            "headcount_status": headcount_status,
            "footprint_pts": footprint_pts,
            "footprint_max": w["fit_footprint_max"],
            "footprint_status": footprint_status,
            "sector_pts": sector_pts,
            "sector_max": w["fit_sector_max"],
            "sector": sector,
            "use_case_pts": use_case_pts,
            "use_case_max": w["fit_use_case_max"],
            "use_case_status": use_case_status,
            "use_case_evidence": use_case_evidence,
        }
    }

def cluster_forward_signals(
    signals_df: pd.DataFrame,
    weights: Optional[Dict[str, float]] = None,
) -> List[Dict[str, Any]]:
    """
    Cluster forward signals by project/facility to prevent duplicate score inflation.
    Signals covering the same plant expansion (e.g. Bowling Green) are grouped.
    Tagged as [ANALYST INTERPRETATION] since raw schema lacks verified stage and recency.
    Evaluates 4 distinct dimensions:
      1. Named Asset/Facility Specificity
      2. Project Stage & Authorization
      3. Workforce & Training Connection
      4. Source Credibility
    """
    if signals_df.empty:
        return []

    w = weights or DEFAULT_WEIGHTS
    w_ast = w.get("trigger_asset_max", 25.0)
    w_stg = w.get("trigger_stage_max", 25.0)
    w_wrk = w.get("trigger_workforce_max", 25.0)
    w_src = w.get("trigger_source_max", 25.0)

    clusters = []
    seen_keywords = set()

    for _, sig in signals_df.iterrows():
        headline = str(sig.get("headline", ""))
        outlet = str(sig.get("reported_by", ""))
        implication = str(sig.get("implication_text", ""))
        page = sig.get("page_number")
        pub_date = sig.get("publication_date") or sig.get("source_date") or None

        # Cluster key derived from location or major project noun
        hl_lower = headline.lower()
        if "bowling green" in hl_lower:
            cluster_key = "bowling_green_expansion"
        elif "data center" in hl_lower:
            cluster_key = "data_center_partnership"
        elif "jamnagar" in hl_lower or "giga complex" in hl_lower:
            cluster_key = "jamnagar_giga_complex"
        elif "biogas" in hl_lower or "cbg" in hl_lower:
            cluster_key = "biogas_plants"
        elif "pipeline" in hl_lower or "ferc" in hl_lower or "gulf coast express" in hl_lower:
            cluster_key = "pipeline_infrastructure"
        elif "angola" in hl_lower:
            cluster_key = "angola_expansion"
        elif "carbon" in hl_lower or "ccs" in hl_lower:
            cluster_key = "carbon_storage"
        elif "louisiana" in hl_lower:
            cluster_key = "louisiana_investment"
        else:
            cluster_key = f"sig_{sig.get('signal_index')}"

        is_duplicate = cluster_key in seen_keywords
        seen_keywords.add(cluster_key)

        # Dimension 1: Named Asset / Facility Specificity
        named_assets = [
            "bowling green", "gulf coast express", "jamnagar", "baytown", "angola",
            "louisiana", "texas carbon", "cbg plants", "5-b kinder morgan"
        ]
        if any(a in hl_lower for a in named_assets):
            asset_pts = float(w_ast)
            asset_detail = "Specific named facility/asset identified"
        elif any(loc in hl_lower for loc in ["texas", "angola", "louisiana", "kentucky"]):
            asset_pts = round(float(w_ast) * 0.60, 1)
            asset_detail = "Regional project geography identified"
        else:
            asset_pts = 0.0
            asset_detail = "Generic or no specific asset/location named"

        # Dimension 2: Project Stage & Milestone Specificity
        if any(w_word in hl_lower for w_word in ["ferc approves", "places in service", "324m facility", "constructing", "underway"]):
            stage_pts = float(w_stg)
            stage_heuristic = "Active Build / Commissioning"
        elif any(w_word in hl_lower for w_word in ["signs mou", "approves", "invests in"]):
            stage_pts = round(float(w_stg) * 0.60, 1)
            stage_heuristic = "Formal Commitment / Authorized"
        elif any(w_word in hl_lower for w_word in ["in talks", "eyes", "exploring", "plans"]):
            stage_pts = round(float(w_stg) * 0.20, 1)
            stage_heuristic = "Early Stage / Exploratory"
        else:
            stage_pts = 0.0
            stage_heuristic = "Financial / General Commentary"

        # Dimension 3: Workforce, Training & Competence Connection
        if any(w_word in hl_lower for w_word in ["next generation", "partner", "giga complex", "carbon storage", "cbg plants", "biogas"]):
            workforce_pts = float(w_wrk)
            workforce_detail = "High: Novel technology, contractor readiness, or training integration"
        elif any(w_word in hl_lower for w_word in ["pipeline", "plant", "terminal", "refinery", "data center"]):
            workforce_pts = round(float(w_wrk) * 0.40, 1)
            workforce_detail = "Moderate: Specific operational facility infrastructure"
        else:
            workforce_pts = 0.0
            workforce_detail = "None: No operational facility or workforce connection"

        # Dimension 4: Source Detail & Credibility
        out_lower = outlet.lower()
        if any(s in out_lower for s in ["pgjonline", "pr newswire", "bic magazine", "carbon herald", "saur energy"]):
            source_pts = float(w_src)
            source_tier = "Specialized Trade / Technical Wire"
        elif any(s in out_lower for s in ["bloomberg", "yahoo", "business-standard"]):
            source_pts = round(float(w_src) * 0.60, 1)
            source_tier = "General Business Media"
        else:
            source_pts = round(float(w_src) * 0.20, 1)
            source_tier = "Regional / General News"

        cluster_raw_pts = asset_pts + stage_pts + workforce_pts + source_pts
        cluster_max_raw = float(w_ast + w_stg + w_wrk + w_src)
        cluster_score = round((cluster_raw_pts / cluster_max_raw) * 100.0, 1) if cluster_max_raw > 0 else 0.0

        clusters.append({
            "signal_index": sig.get("signal_index"),
            "signal_id": sig.get("signal_id"),
            "headline": headline,
            "outlet": outlet,
            "implication": implication,
            "page_number": page,
            "publication_date": pub_date,
            "cluster_key": cluster_key,
            "is_duplicate_cluster": is_duplicate,
            "cluster_raw_points": round(cluster_raw_pts, 1),
            "cluster_max_raw_points": round(cluster_max_raw, 1),
            "cluster_score": cluster_score,
            "asset_pts": asset_pts,
            "asset_max": w_ast,
            "asset_detail": asset_detail,
            "stage_pts": stage_pts,
            "stage_max": w_stg,
            "stage_heuristic": stage_heuristic,
            "workforce_pts": workforce_pts,
            "workforce_max": w_wrk,
            "workforce_detail": workforce_detail,
            "source_pts": source_pts,
            "source_max": w_src,
            "source_tier": source_tier,
            "provenance": "[ANALYST INTERPRETATION]",
        })

    return clusters


def calculate_trigger_relevance(company_signals_df: pd.DataFrame, weights: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
    """
    Calculate Trigger Relevance score (0-100 pts) based on Project and Readiness Signals.
    Prevents score saturation: requires multi-dimensional evidence (Asset, Stage, Workforce, Source).
    Evaluates temporal_urgency as a separate field (remains UNKNOWN if undated).
    Provides transparent raw points and normalized 0-100 score.
    """
    w = weights or DEFAULT_WEIGHTS
    if company_signals_df.empty:
        return {
            "score": 0.0,
            "raw_points": 0.0,
            "max_raw_points": 100.0,
            "confidence_level": "LOW",
            "temporal_urgency": "UNKNOWN",
            "temporal_urgency_detail": "No forward signals in report",
            "clusters": [],
            "distinct_projects_count": 0,
            "has_active_build": False,
            "has_verified_current_date": False,
            "notes": "No forward signals extracted in report."
        }

    clusters = cluster_forward_signals(company_signals_df, w)
    unique_clusters = [c for c in clusters if not c["is_duplicate_cluster"]]

    if not unique_clusters:
        return {
            "score": 0.0,
            "raw_points": 0.0,
            "max_raw_points": 100.0,
            "confidence_level": "LOW",
            "temporal_urgency": "UNKNOWN",
            "temporal_urgency_detail": "All signals were duplicates or unparsed",
            "clusters": clusters,
            "distinct_projects_count": 0,
            "has_active_build": False,
            "has_verified_current_date": False,
            "notes": "No unique forward project clusters."
        }

    # Sort unique clusters by cluster_score descending
    unique_clusters.sort(key=lambda c: c["cluster_score"], reverse=True)

    top_project = unique_clusters[0]
    lead_score = top_project["cluster_score"]

    # If multiple distinct projects exist, add a diversified project momentum bonus (up to 15 pts)
    secondary_score = unique_clusters[1]["cluster_score"] if len(unique_clusters) > 1 else 0.0
    if len(unique_clusters) >= 3:
        project_blend = 0.70 * lead_score + 0.20 * secondary_score + 10.0
    elif len(unique_clusters) == 2:
        project_blend = 0.75 * lead_score + 0.20 * secondary_score + 5.0
    else:
        project_blend = lead_score

    calibrated_score = min(100.0, round(project_blend, 1))

    # Evaluate temporal urgency strictly from dates
    # Current report schema does NOT have publication dates, so this remains UNKNOWN!
    has_verified_date = any(pd.notna(c.get("publication_date")) for c in clusters)
    if has_verified_date:
        temporal_urgency = "VERIFIED_CURRENT"
        temporal_detail = "Milestone dates confirmed in source data"
    else:
        temporal_urgency = "UNKNOWN"
        temporal_detail = "No publication or milestone dates in source report schema"

    has_active_build = any("Active Build" in c["stage_heuristic"] for c in unique_clusters)
    confidence = "MEDIUM" if len(unique_clusters) >= 2 else "LOW"

    return {
        "score": calibrated_score,
        "raw_points": calibrated_score,
        "max_raw_points": 100.0,
        "confidence_level": confidence,
        "temporal_urgency": temporal_urgency,
        "temporal_urgency_detail": temporal_detail,
        "has_verified_current_date": has_verified_date,
        "clusters": clusters,
        "distinct_projects_count": len(unique_clusters),
        "has_active_build": has_active_build,
        "notes": "Derived via multi-dimensional keyword heuristics [ANALYST INTERPRETATION].",
    }


# Backwards compatibility alias
calculate_timing_intent = calculate_trigger_relevance


def calculate_contactability(
    company_name: str,
    contacts_df: Optional[pd.DataFrame] = None,
    crm_df: Optional[pd.DataFrame] = None,
    weights: Optional[Dict[str, float]] = None,
    canonical_account_id: Optional[str] = None,
    identity_registry: Optional[AccountIdentityRegistry] = None,
) -> Dict[str, Any]:
    """
    Calculate Contactability score (0-100 pts) with transparent raw points and normalization.
    Strict column semantics: status is ONLY 'KNOWN', 'PARTIAL', or 'UNKNOWN'.
    Actions like 'Identify buyer' appear strictly in Recommended Next Action!
    Uses shared match_source_record_identity for exact full-field and approved registry resolution.
    Strictly prohibits substring containment (e.g. 'ril' in 'drilling' will never match).
    """
    w = weights or DEFAULT_WEIGHTS
    max_raw_points = float(w.get("contact_role_max", 50.0) + w.get("contact_stage_max", 50.0))

    has_contact_data = contacts_df is not None and not contacts_df.empty
    has_crm_data = crm_df is not None and not crm_df.empty

    if not has_contact_data and not has_crm_data:
        return {
            "status": "UNKNOWN",
            "score": 0.0,
            "raw_points": 0.0,
            "max_raw_points": max_raw_points,
            "role_coverage": "NO_CONTACTS",
            "stage": "NO_CRM",
            "matched_contacts": [],
            "matched_crm_account": None,
            "confidence_level": "LOW",
        }

    target_id = canonical_account_id or company_name
    target_name = company_name

    matched_contacts = []
    if has_contact_data:
        for _, row in contacts_df.iterrows():
            c_candidate = str(row.get("company_name") or row.get("account_name") or row.get("company") or "").strip()
            c_dom = str(row.get("domain", "")).strip() if "domain" in row else ""
            m_res = match_source_record_identity(
                candidate_company=c_candidate,
                candidate_domain=c_dom,
                canonical_account_id=target_id,
                canonical_company_name=target_name,
                identity_registry=identity_registry,
                allow_unapproved_domain_proposal=False,
            )
            if m_res["matched"]:
                matched_contacts.append(row.to_dict())

    matched_crm = None
    if has_crm_data:
        for _, row in crm_df.iterrows():
            c_candidate = str(row.get("company_name") or row.get("account_name") or row.get("company") or "").strip()
            c_dom = str(row.get("domain", "")).strip() if "domain" in row else ""
            m_res = match_source_record_identity(
                candidate_company=c_candidate,
                candidate_domain=c_dom,
                canonical_account_id=target_id,
                canonical_company_name=target_name,
                identity_registry=identity_registry,
                allow_unapproved_domain_proposal=False,
            )
            if m_res["matched"]:
                matched_crm = row.to_dict()
                break

    if not matched_contacts and not matched_crm:
        return {
            "status": "UNKNOWN",
            "score": 0.0,
            "raw_points": 0.0,
            "max_raw_points": max_raw_points,
            "role_coverage": "NO_MATCH",
            "stage": "NO_MATCH",
            "matched_contacts": [],
            "matched_crm_account": None,
            "confidence_level": "LOW",
        }

    # Evaluate Contact Role Coverage (Max 50)
    role_pts = 0.0
    primary_buyer_found = False
    influencer_found = False

    primary_keywords = ["training", "competence", "learning", "l&d", "qualification", "simulator", "ots"]
    influencer_keywords = ["capital projects", "engineering", "plant manager", "refinery manager", "hse", "process safety", "operations"]

    for contact in matched_contacts:
        title = str(contact.get("title", "")).lower()
        dept = str(contact.get("department", "")).lower()
        comb = title + " " + dept
        if any(k in comb for k in primary_keywords):
            primary_buyer_found = True
        elif any(k in comb for k in influencer_keywords):
            influencer_found = True

    if primary_buyer_found:
        role_pts = float(w["contact_role_max"])
    elif influencer_found:
        role_pts = round(float(w["contact_role_max"]) * 0.60, 1)
    elif matched_contacts:
        role_pts = round(float(w["contact_role_max"]) * 0.25, 1)
    else:
        role_pts = 0.0

    # Evaluate CRM Stage (Max 50)
    stage_pts = 0.0
    crm_stage_val = "Not Logged"
    if matched_crm:
        crm_stage_val = str(matched_crm.get("crm_stage", "")).lower()
        if any(s in crm_stage_val for s in ["opportunity", "discovery", "evaluating", "active"]):
            stage_pts = float(w["contact_stage_max"])
        elif any(s in crm_stage_val for s in ["qualified", "lead", "past customer"]):
            stage_pts = round(float(w["contact_stage_max"]) * 0.65, 1)
        else:
            stage_pts = round(float(w["contact_stage_max"]) * 0.25, 1)

    raw_points = role_pts + stage_pts
    normalized_score = min(100.0, round((raw_points / max_raw_points) * 100.0, 1)) if max_raw_points > 0 else 0.0

    # Determine status strictly as KNOWN or PARTIAL
    if primary_buyer_found and matched_crm:
        status = "KNOWN"
    elif matched_contacts or matched_crm:
        status = "PARTIAL"
    else:
        status = "UNKNOWN"

    return {
        "status": status,
        "score": normalized_score,
        "raw_points": round(raw_points, 1),
        "max_raw_points": round(max_raw_points, 1),
        "role_coverage": "PRIMARY_BUYER_IDENTIFIED" if primary_buyer_found else ("INFLUENCER_IDENTIFIED" if influencer_found else "GENERAL_CONTACT"),
        "stage": crm_stage_val,
        "matched_contacts": matched_contacts,
        "matched_crm_account": matched_crm,
        "confidence_level": "HIGH" if status == "KNOWN" else "MEDIUM",
    }


def derive_priority_and_readiness(
    fit_result: Dict[str, Any],
    trigger_result: Dict[str, Any],
    contact_result: Dict[str, Any],
    weights: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """
    Separates account_opportunity from outreach_readiness and recommended_next_action.
    - Opportunity tiers: High-fit opportunity, Moderate-fit opportunity, Low-fit opportunity, Insufficient evidence
    - Next action rules:
        * Verified current trigger + known suitable buyer -> Contact now
        * Strong relevant trigger + no buyer -> Identify buyer
        * Relevant but undated/unverified trigger -> Validate trigger
        * Weak/no trigger -> Monitor
        * Low evidence coverage (< 50%) -> append (Provisional)
    """
    w = weights or DEFAULT_WEIGHTS
    fit_score = fit_result["score"]
    trigger_score = trigger_result["score"]
    contact_score = contact_result["score"]
    is_contact_known = contact_result["status"] == "KNOWN"

    # Composite Score calculation
    if is_contact_known:
        sum_w = float(w["composite_weight_fit"] + w["composite_weight_trigger"] + w["composite_weight_contact"])
        eff_w_fit = w["composite_weight_fit"] / sum_w if sum_w > 0 else 0.333
        eff_w_trg = w["composite_weight_trigger"] / sum_w if sum_w > 0 else 0.333
        eff_w_cnt = w["composite_weight_contact"] / sum_w if sum_w > 0 else 0.333
        composite = (
            eff_w_fit * fit_score
            + eff_w_trg * trigger_score
            + eff_w_cnt * contact_score
        )
        derivation_mode = "3-Component Blended"
        effective_weights_str = f"fit={eff_w_fit:.2f};trigger={eff_w_trg:.2f};contact={eff_w_cnt:.2f}"
    else:
        # Re-weight only available components
        eff_w_fit = 0.50
        eff_w_trg = 0.50
        eff_w_cnt = 0.00
        composite = eff_w_fit * fit_score + eff_w_trg * trigger_score
        derivation_mode = "Reweighted (Fit 50% / Trigger 50% - No CRM Data)"
        effective_weights_str = f"fit=0.50;trigger=0.50;contact=0.00"

    composite = round(composite, 1)

    # 1. account_opportunity (Structural fit and relevance, non-temporal)
    if composite >= 75.0 and trigger_score >= 60.0:
        opportunity = "High-fit opportunity"
    elif composite >= 60.0:
        opportunity = "Moderate-fit opportunity"
    elif composite >= 40.0:
        opportunity = "Low-fit opportunity"
    else:
        opportunity = "Insufficient evidence"

    # 2. outreach_readiness (Actionable commercial maturity)
    if contact_result["status"] == "UNKNOWN":
        readiness = "Buyer Needed"
    elif contact_result["status"] == "PARTIAL":
        if contact_result.get("role_coverage") == "PRIMARY_BUYER_IDENTIFIED":
            readiness = "CRM Context Needed"
        else:
            readiness = "Buyer Needed"
    else:
        readiness = "Ready"

    # 3. recommended_next_action
    has_verified_current_trigger = trigger_result.get("has_verified_current_date", False) and trigger_score >= 70.0
    has_strong_trigger = trigger_score >= 70.0
    has_relevant_trigger = trigger_score >= 50.0
    has_known_suitable_buyer = contact_result.get("role_coverage") == "PRIMARY_BUYER_IDENTIFIED"

    if has_verified_current_trigger and has_known_suitable_buyer:
        base_action = "Contact now"
    elif has_strong_trigger and not has_known_suitable_buyer:
        base_action = "Identify buyer"
    elif has_relevant_trigger and (contact_result["status"] != "UNKNOWN" or not has_verified_current_trigger):
        base_action = "Validate trigger"
    elif not has_relevant_trigger:
        base_action = "Monitor"
    else:
        base_action = "Identify buyer"

    # Low evidence coverage modifier
    coverage_pct = fit_result.get("evidence_coverage_pct", 100.0)
    if coverage_pct < 50.0:
        recommended_next_action = f"{base_action} (Provisional)"
    else:
        recommended_next_action = base_action

    return {
        "composite_score": composite,
        "effective_weights_str": effective_weights_str,
        "account_opportunity": opportunity,
        "outreach_readiness": readiness,
        "recommended_next_action": recommended_next_action,
        "temporal_urgency": trigger_result.get("temporal_urgency", "UNKNOWN"),
        "derivation_mode": derivation_mode,
        "overall_confidence": "HIGH" if (fit_result["confidence_level"] == "HIGH" and is_contact_known) else ("MEDIUM" if fit_result["confidence_level"] != "LOW" else "LOW"),
    }


def load_canonical_seven_patterns(patterns_df: pd.DataFrame) -> List[Dict[str, Any]]:
    """
    Load canonical Seven Patterns from seven_patterns.csv.
    Preserves extracted solution_closed_by exactly (Pattern 2 = EON Tacit).
    """
    if patterns_df.empty:
        return []

    patterns = []
    seen = set()
    for _, row in patterns_df.iterrows():
        p_num = int(row.get("pattern_number", 0))
        if p_num in seen or p_num == 0:
            continue
        seen.add(p_num)

        p_name = str(row.get("pattern_name", "")).strip()
        closed_by = str(row.get("solution_closed_by", "")).strip()
        quote = str(row.get("quote", "")).strip()

        # Non-judgmental consultative discovery questions
        discovery_questions = {
            1: "During upcoming facility commissioning or turnaround milestones, how do your crews rehearse non-routine procedures before executing on live, energized assets?",
            2: "As veteran operators transition or retire during major facility expansions, how does your organization capture unwritten operational nuance and transfer it to incoming crews?",
            3: "How frequently are operational teams able to practice managing abnormal operating conditions and emergency scenarios in high-fidelity simulation?",
            4: "How does the organization verify that frontline technicians and contractors have demonstrated practical execution competence rather than completing read-and-sign compliance modules?",
            5: "When field conditions diverge from written permits or isolation plans during live work, how are frontline crews supported in reconciling procedures with equipment states safely?",
            6: "What real-time digital operational guidance is accessible to operators directly at the equipment edge during complex or safety-critical maintenance steps?",
            7: "How are operational learnings from past incidents and near-misses institutionalized into routine day-to-day training workflows so they aren't repeated?",
        }

        patterns.append({
            "pattern_number": p_num,
            "pattern_name": p_name,
            "solution_closed_by": closed_by,
            "quote": quote,
            "discovery_question": discovery_questions.get(p_num, "How does your team address this operational milestone?"),
        })

    patterns.sort(key=lambda x: x["pattern_number"])
    return patterns


def generate_tailored_outreach_brief(
    company_row: pd.Series,
    fit_result: Dict[str, Any],
    trigger_result: Dict[str, Any],
    contact_result: Dict[str, Any],
    priority_result: Dict[str, Any],
    canonical_patterns: List[Dict[str, Any]],
    product_copy_dict: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """
    Generate tailored consultative outreach brief with strict 5-tier provenance tags:
      - [PUBLIC FORWARD SIGNAL]: Third-party project initiatives & trade press accounts
      - [REPORT FACT]: Verbatim company operational disclosures (e.g. line of work, location, scale)
      - [ANALYST INTERPRETATION]: Inferred operational implications and schedule readiness
      - [SUGGESTED DISCOVERY QUESTION]: Non-judgmental consultative discovery inquiries
      - [EON PRODUCT POSITIONING]: Configurable approved solution capabilities
      - [DATA AVAILABILITY]: Explicit indicator when CRM or contact data is absent
    Softened claim: "is designed to support procedure rehearsal before live execution"
    """
    comp_name = company_row.get("company_name", "Organization")
    low = company_row.get("line_of_work") or "industrial operations"

    lead_cluster = None
    if trigger_result.get("clusters"):
        lead_cluster = trigger_result["clusters"][0]

    raw_headline = (
        lead_cluster.get("headline")
        or lead_cluster.get("lead_summary")
        or f"Recent operational initiatives in {low}"
    ) if lead_cluster else f"Recent operational initiatives in {low}"
    abbr_headline = abbreviate_monetary_values(raw_headline)
    trigger_outlet = (lead_cluster.get("outlet") or "Public trade release") if lead_cluster else "Public trade release"
    trigger_page = (lead_cluster.get("page_number") or 2) if lead_cluster else 2

    p1 = canonical_patterns[0] if canonical_patterns else {"solution_closed_by": "Genesis + EON Universal", "discovery_question": ""}
    p2 = canonical_patterns[1] if len(canonical_patterns) > 1 else {"solution_closed_by": "EON Tacit", "discovery_question": ""}

    subject_line = f"Operational Readiness for {comp_name}'s Upcoming Milestones"

    # Load approved product positioning from configurable dictionary
    copy_dict = product_copy_dict or APPROVED_PRODUCT_POSITIONING
    p1_sol = p1.get('solution_closed_by', 'Genesis')
    p2_sol = p2.get('solution_closed_by', 'EON Tacit')
    solutions_str = f"{p1_sol} & {p2_sol}"
    suite_template = copy_dict.get("simulation_suite", APPROVED_PRODUCT_POSITIONING["simulation_suite"])
    positioning_stmt = suite_template.format(solutions=solutions_str, p1_solution=p1_sol, p2_solution=p2_sol)

    # Operational profile facts
    headcount_disp = fit_result.get("breakdown", {}).get("headcount_status", "Headcount undisclosed")
    headquarters_city = company_row.get("headquarters_city") or "Head office not reported"

    body_paragraphs = [
        f"📰 [PUBLIC FORWARD SIGNAL] Publicly reported project initiative: \"{abbr_headline}\" (Reported by {trigger_outlet}, Page {trigger_page}).",
        f"🟢 [REPORT FACT] {comp_name} operates in {low} ({headcount_disp}, {headquarters_city}).",
        f"🟡 [ANALYST INTERPRETATION] As teams scale workforce capacity and commission new facilities, frontline operational readiness and procedure verification become critical to meeting schedule milestones safely.",
        f"🟣 [SUGGESTED DISCOVERY QUESTION] {p1.get('discovery_question')}",
        f"🟣 [SUGGESTED DISCOVERY QUESTION] {p2.get('discovery_question')}",
        f"🔷 [EON PRODUCT POSITIONING] {positioning_stmt}",
    ]

    # Explicit absence-of-CRM labeling vs CRM Fact
    if contact_result.get("status") == "UNKNOWN" and not contact_result.get("matched_contacts") and not contact_result.get("matched_crm_account"):
        crm_line = "⚪ [DATA AVAILABILITY] No CRM or contact data uploaded."
    else:
        crm_stage_str = contact_result.get("stage") or "Not Logged"
        crm_line = f"🔵 [CRM FACT] Account status in CRM: {crm_stage_str}"
        if contact_result.get("matched_contacts"):
            lead_contact = contact_result["matched_contacts"][0]
            crm_line += f" | Target Contact: {lead_contact.get('contact_name')} ({lead_contact.get('title')})"

    return {
        "subject_line": subject_line,
        "body_paragraphs": body_paragraphs,
        "crm_context": crm_line,
        "raw_trigger_headline": raw_headline,
        "abbreviated_trigger_headline": abbr_headline,
        "recommended_primary_buyers": [
            "VP / Director of Operations Training",
            "Head of Workforce Competence & Qualification",
            "Global Head of Industrial Learning & Development",
            "Director of Industrial Safety Training",
        ],
        "recommended_influencers": [
            "VP Capital Projects & Major Programs",
            "Plant / Refinery Operations Manager",
            "VP Process Safety Management (PSM)",
        ],
        "excluded_roles": ["Chief Operating Officer (COO) - Too broad for initial technical evaluation"],
    }


def validate_crm_schema(df: pd.DataFrame) -> Tuple[bool, str]:
    """Validate uploaded CRM accounts CSV schema."""
    if df.empty:
        return False, "Uploaded CRM file contains no rows."
    cols = [str(c).strip().lower() for c in df.columns]
    if "company_name" not in cols and "company" not in cols and "account_name" not in cols:
        return False, "Missing required company identifier column (expected 'company_name', 'company', or 'account_name')."
    return True, "Valid CRM schema."


def validate_contact_schema(df: pd.DataFrame) -> Tuple[bool, str]:
    """Validate uploaded contacts CSV schema."""
    if df.empty:
        return False, "Uploaded contacts file contains no rows."
    cols = [str(c).strip().lower() for c in df.columns]
    if "company_name" not in cols and "company" not in cols:
        return False, "Missing required 'company_name' column."
    if "title" not in cols:
        return False, "Missing required 'title' column for buyer role matching."
    return True, "Valid contact schema."


def generate_privacy_safe_export(
    records: List[Dict[str, Any]],
    mask_pii: bool = True,
    engine_version: str = METHODOLOGY_VERSION,
    preset_version: str = DEFAULT_PRESET_NAME,
    active_weights: Optional[Dict[str, float]] = None,
) -> pd.DataFrame:
    """
    Generate export dataframe with optional PII masking for contact personal data,
    including complete calculation lineage: engine version, preset version,
    active weights, raw points, normalized scores, effective composite weights,
    and calculation timestamp.
    """
    from datetime import datetime, timezone
    calc_ts = datetime.now(timezone.utc).isoformat()
    weights_dict = active_weights or DEFAULT_WEIGHTS
    weights_str = ";".join([f"{k}={v}" for k, v in sorted(weights_dict.items())])

    export_rows = []
    for r in records:
        row = {
            "engine_version": r.get("engine_version", engine_version),
            "preset_version": r.get("preset_version", preset_version),
            "calculation_timestamp": r.get("calculation_timestamp", calc_ts),
            "active_weights": r.get("active_weights", weights_str),
            "effective_composite_weights": r.get("effective_composite_weights", "fit=0.50;trigger=0.50;contact=0.00"),
            "company_name": r.get("company_name"),
            "sector": r.get("sector"),
            "sector_scope_status": r.get("sector_scope_status"),
            "wingman_tier": r.get("wingman_tier"),
            "account_opportunity": r.get("account_opportunity"),
            "outreach_readiness": r.get("outreach_readiness"),
            "recommended_next_action": r.get("recommended_next_action"),
            "temporal_urgency": r.get("temporal_urgency"),
            "composite_score": r.get("composite_score"),
            "account_fit_raw_points": r.get("fit_raw_points", r.get("fit_score")),
            "account_fit_max_raw_points": r.get("fit_max_raw_points", 100.0),
            "account_fit_score": r.get("fit_score"),
            "trigger_relevance_raw_points": r.get("trigger_raw_points", r.get("trigger_score")),
            "trigger_relevance_max_raw_points": r.get("trigger_max_raw_points", 100.0),
            "trigger_relevance_score": r.get("trigger_score"),
            "contactability": r.get("contactability"),
            "contactability_raw_points": r.get("contact_raw_points", 0.0),
            "contactability_max_raw_points": r.get("contact_max_raw_points", 100.0),
            "contactability_score": r.get("contact_score"),
            "derivation_mode": r.get("derivation_mode"),
            "evidence_coverage_pct": r.get("evidence_coverage_pct"),
            "confidence_level": r.get("confidence_level"),
            "target_buyer_department": r.get("target_buyer_department"),
            "lead_project_trigger": r.get("lead_project_trigger"),
            "wingman_export_ingested": r.get("wingman_export_ingested", False),
            "wingman_match_method": r.get("wingman_match_method", "NONE"),
            "wingman_match_confidence": r.get("wingman_match_confidence", "NONE"),
            "trigger_state": r.get("trigger_state", "ABSENT_FROM_EXPORT"),
            "scan_confidence": r.get("scan_confidence", "NOT_APPLICABLE"),
            "trigger_evidence_confidence": r.get("trigger_evidence_confidence", "NOT_APPLICABLE"),
            "wingman_trigger_count": r.get("wingman_trigger_count", 0),
            "wingman_cluster_count": r.get("wingman_cluster_count", 0),
            "sector_conflict_flag": r.get("sector_conflict_flag", False),
            "tier_conflict_flag": r.get("tier_conflict_flag", False),
            "analysis_as_of_date": r.get("analysis_as_of_date", ""),
        }

        contact_name = r.get("contact_name")
        email = r.get("contact_email")
        if mask_pii and contact_name:
            parts = str(contact_name).split()
            masked_name = f"{parts[0][0]}. " + (parts[-1][0] + "***" if len(parts) > 1 else "***")
            row["contact_name"] = masked_name
        else:
            row["contact_name"] = contact_name or ""

        if mask_pii and email:
            if "@" in str(email):
                usr, dom = str(email).split("@", 1)
                row["contact_email"] = f"{usr[0]}***@{dom}"
            else:
                row["contact_email"] = "***"
        else:
            row["contact_email"] = email or ""

        export_rows.append(row)

    return pd.DataFrame(export_rows)
