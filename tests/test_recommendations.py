"""
Unit tests for the Buyer & Outreach Recommendation Engine (dashboard/recommendations.py).
Verifies:
  - Missing values never increase or award points
  - Lower evidence coverage reduces confidence
  - Foreign / non-SEC entities are not penalized for filing status
  - Unsupported signal recency/stages are tagged [ANALYST INTERPRETATION]
  - Pattern 2 is LOST EXPERIENCE -> EON Tacit matching seven_patterns.csv
  - Contactability UNKNOWN prevents unqualified 'Contact now'
  - Data-driven sector classification for new companies without code modification
  - Company alias normalization, schema validation, and privacy-safe masking
  - Out-of-scope companies are excluded from default EON ranking
  - Undated signals cannot produce a known temporal-urgency status
  - Generic expansion headlines cannot automatically produce maximum Trigger Relevance
  - Contactability values never contain recommended actions
  - Contact now requires both a verified current trigger and a matched primary buyer
"""

import pytest
import pandas as pd
from pathlib import Path

from dashboard.recommendations import (
    METHODOLOGY_VERSION,
    DEFAULT_PRESET_NAME,
    DEFAULT_WEIGHTS,
    APPROVED_PRODUCT_POSITIONING,
    abbreviate_monetary_values,
    normalize_company_name,
    classify_sector_from_line_of_work,
    is_in_default_eon_scope,
    get_scope_label,
    calculate_evidence_coverage,
    assess_eon_use_case_alignment,
    calculate_account_fit,
    calculate_trigger_relevance,
    calculate_contactability,
    derive_priority_and_readiness,
    load_canonical_seven_patterns,
    generate_tailored_outreach_brief,
    validate_crm_schema,
    validate_contact_schema,
    generate_privacy_safe_export,
    cluster_forward_signals,
)


@pytest.fixture
def sample_patterns_df():
    """Load canonical patterns dataframe from output/seven_patterns.csv."""
    csv_path = Path(__file__).resolve().parent.parent / "output" / "seven_patterns.csv"
    if csv_path.exists():
        return pd.read_csv(csv_path)
    return pd.DataFrame([
        {"pattern_number": 1, "pattern_name": "NEVER PRACTISED", "solution_closed_by": "Genesis + EON Universal", "quote": "First time"},
        {"pattern_number": 2, "pattern_name": "LOST EXPERIENCE", "solution_closed_by": "EON Tacit", "quote": "Senior turnover"},
        {"pattern_number": 3, "pattern_name": "WHEN THINGS GO WRONG", "solution_closed_by": "Situation Room + EON Live", "quote": "Bad day"},
        {"pattern_number": 4, "pattern_name": "TOLD, NOT TESTED", "solution_closed_by": "Assess IQ + Competence IQ", "quote": "Read and sign"},
        {"pattern_number": 5, "pattern_name": "THE PLAN DIDN'T MATCH THE JOB", "solution_closed_by": "Permit IQ", "quote": "Permit divergence"},
        {"pattern_number": 6, "pattern_name": "NO GUIDANCE IN THE MOMENT", "solution_closed_by": "Field IQ / Edge", "quote": "Skipped step"},
        {"pattern_number": 7, "pattern_name": "THE SAME MISTAKE AGAIN", "solution_closed_by": "Compound IQ + Distillery", "quote": "Happened before"},
    ])


def test_missing_values_never_increase_score():
    """Missing headcount, footprint, or line_of_work must contribute 0 points (not midpoint)."""
    complete_row = pd.Series({
        "people_employed": 55000,
        "operating_countries": "operations in over 120 countries",
        "line_of_work": "Oil and gas",
        "business_description": "Engaged in major refining, pipeline transport, and chemical manufacture.",
        "headquarters_city": "Spring",
        "headquarters_country": "United States",
        "year_founded": 1882,
    })
    fit_complete = calculate_account_fit(complete_row)

    sparse_row = pd.Series({
        "people_employed": None,
        "operating_countries": None,
        "line_of_work": None,
        "business_description": None,
        "headquarters_city": None,
        "headquarters_country": None,
        "year_founded": None,
    })
    fit_sparse = calculate_account_fit(sparse_row)

    assert fit_sparse["score"] == 0.0, "Sparse company with missing fields must receive 0 points!"
    assert fit_sparse["breakdown"]["headcount_pts"] == 0.0
    assert fit_sparse["breakdown"]["footprint_pts"] == 0.0
    assert fit_sparse["breakdown"]["sector_pts"] == 0.0
    assert fit_sparse["breakdown"]["use_case_pts"] == 0.0
    assert fit_complete["score"] > fit_sparse["score"]


def test_lower_evidence_coverage_reduces_confidence():
    """Verify evidence coverage pct calculation and that low coverage yields LOW confidence."""
    high_cov_row = pd.Series({
        "people_employed": 20000,
        "line_of_work": "Paints and coatings",
        "business_description": "Manufactures coatings.",
        "operating_countries": "120 countries",
        "headquarters_city": "Cleveland",
        "headquarters_country": "United States",
        "year_founded": 1866,
    })
    cov_high, conf_high = calculate_evidence_coverage(high_cov_row)
    assert cov_high == 100.0
    assert conf_high == "HIGH"

    low_cov_row = pd.Series({
        "people_employed": None,
        "line_of_work": "Petrochemicals",
        "business_description": None,
        "operating_countries": None,
        "headquarters_city": "Mumbai",
        "headquarters_country": None,
        "year_founded": None,
    })
    cov_low, conf_low = calculate_evidence_coverage(low_cov_row)
    assert cov_low < 50.0
    assert conf_low == "LOW"


def test_foreign_and_non_sec_companies_not_penalized_for_filing_status():
    """
    Foreign or non-SEC listed companies (like Reliance RIL) must not be penalized
    for lack of SEC 10-K readability; assessed on EON use-case alignment instead.
    """
    non_sec_row = pd.Series({
        "people_employed": 30000,
        "operating_countries": "operations in 5 countries",
        "line_of_work": "Petrochemicals",
        "business_description": "Operates the world's largest refining and petrochemicals complex.",
        "sec_annual_report_status": "No annual report with SEC / private or foreign-listed",
        "sec_filing_date": None,
    })
    fit = calculate_account_fit(non_sec_row)
    assert fit["breakdown"]["use_case_status"] == "SUPPORTED"
    assert fit["breakdown"]["use_case_pts"] == 20.0
    assert fit["score"] >= 65.0


def test_unsupported_signal_recency_and_stages_tagged_analyst_interpretation():
    """
    Because raw signals schema lacks publication dates and verified stage fields,
    keyword classifications must be tagged [ANALYST INTERPRETATION] and have reduced confidence.
    """
    signals = pd.DataFrame([
        {
            "company_name": "ExxonMobil",
            "signal_index": 1,
            "headline": "ExxonMobil Ensures Oil Expansion in Angola",
            "reported_by": "marketscreener",
            "implication_text": "Implies deepwater facility expansion.",
            "page_number": 2,
        }
    ])
    clusters = cluster_forward_signals(signals)
    assert len(clusters) == 1
    assert clusters[0]["provenance"] == "[ANALYST INTERPRETATION]"

    trigger = calculate_trigger_relevance(signals)
    assert trigger["confidence_level"] in ("MEDIUM", "LOW")
    assert "[ANALYST INTERPRETATION]" in trigger["notes"]


def test_pattern_to_module_mappings_match_seven_patterns_csv(sample_patterns_df):
    """Canonical mappings must match seven_patterns.csv, specifically Pattern 02 LOST EXPERIENCE -> EON Tacit."""
    canonical = load_canonical_seven_patterns(sample_patterns_df)
    assert len(canonical) == 7

    p2 = [p for p in canonical if p["pattern_number"] == 2][0]
    assert p2["pattern_name"] == "LOST EXPERIENCE"
    assert p2["solution_closed_by"] == "EON Tacit", "Pattern 02 MUST map to EON Tacit!"

    p1 = [p for p in canonical if p["pattern_number"] == 1][0]
    assert p1["pattern_name"] == "NEVER PRACTISED"
    assert p1["solution_closed_by"] == "Genesis + EON Universal"


def test_contactability_unknown_prevents_contact_now_action():
    """
    When CRM and Contact data is omitted, Contactability must be UNKNOWN (0 pts)
    and recommended_next_action must be 'Identify buyer', NEVER 'Contact now'.
    """
    company_row = pd.Series({
        "company_name": "Kinder Morgan",
        "people_employed": 11075,
        "operating_countries": "United States and Canada",
        "line_of_work": "Energy infrastructure",
        "business_description": "Specializes in owning oil and gas pipelines and terminals.",
    })
    signals = pd.DataFrame([
        {
            "company_name": "Kinder Morgan",
            "signal_index": 1,
            "headline": "FERC approves $5-B Kinder Morgan pipeline expansion",
            "reported_by": "pgjonline",
            "implication_text": "Major pipeline commissioning ahead.",
            "page_number": 2,
        }
    ])

    fit = calculate_account_fit(company_row)
    trigger = calculate_trigger_relevance(signals)
    contact = calculate_contactability("Kinder Morgan", contacts_df=None, crm_df=None)

    assert contact["status"] == "UNKNOWN"
    assert contact["score"] == 0.0

    priority = derive_priority_and_readiness(fit, trigger, contact)

    assert priority["account_opportunity"] in ("High-fit opportunity", "Moderate-fit opportunity")
    assert priority["outreach_readiness"] == "Buyer Needed"
    assert priority["recommended_next_action"] == "Identify buyer"


def test_new_companies_sector_classified_without_code_modification():
    """Data-driven sector classifier dynamically handles new lines of work without code changes."""
    assert classify_sector_from_line_of_work("Offshore drilling and subsea pipelines") == "Energy & Oil & Gas Infrastructure"
    assert classify_sector_from_line_of_work("Specialty petrochemicals and polymer resins") == "Petrochemicals & Refining"
    assert classify_sector_from_line_of_work("Architectural paints and industrial coatings") == "Coatings & Advanced Materials"
    assert classify_sector_from_line_of_work("Heavy equipment manufacturing and assembly") == "General Industrial"
    assert classify_sector_from_line_of_work("Quantum computing research") == "Unclassified"
    assert classify_sector_from_line_of_work(None) == "Unclassified"


def test_duplicate_forward_signals_clustered():
    """Multiple articles covering the exact same plant/facility expansion are clustered and not counted twice."""
    dup_signals = pd.DataFrame([
        {
            "company_name": "Sherwin-Williams",
            "signal_index": 3,
            "headline": "Sherwin-Williams expands Bowling Green plant with 324M facility",
            "reported_by": "WBKO",
            "implication_text": "Major facility build.",
            "page_number": 2,
        },
        {
            "company_name": "Sherwin-Williams",
            "signal_index": 4,
            "headline": "Sherwin-Williams Bowling Green plant expands to meet industrial demand",
            "reported_by": "WNKY",
            "implication_text": "Scale up underway.",
            "page_number": 2,
        },
    ])
    clusters = cluster_forward_signals(dup_signals)
    assert len(clusters) == 2
    assert clusters[0]["is_duplicate_cluster"] is False
    assert clusters[1]["is_duplicate_cluster"] is True
    assert clusters[0]["cluster_key"] == clusters[1]["cluster_key"]


def test_company_alias_normalization():
    """Verify alias mapping requires explicit AccountIdentityRegistry and strictly rejects unapproved aliases without registry."""
    from dashboard.identity_registry import parse_identity_crosswalk

    # Without registry: unapproved aliases are NOT resolved (no built-in portfolio mappings)
    assert normalize_company_name("syn") == "syn"
    assert normalize_company_name("SYNTHETIC-CORP") == "SYNTHETIC-CORP"

    # With validated synthetic registry: resolves approved aliases and tickers
    csv_text = (
        "canonical_account_id,canonical_company_name,approved_alias,approved_domain,approved_ticker,approval_status,approved_by,approved_at\n"
        'COMP-SYN,"Synthetic Enterprise","synthetic-corp",,,APPROVED,AUDITOR,2026-09-17\n'
        'COMP-SYN,"Synthetic Enterprise",,,syn,APPROVED,AUDITOR,2026-09-17\n'
    )
    reg_res = parse_identity_crosswalk(csv_text)
    assert reg_res["file_is_valid"] is True
    registry = reg_res["registry"]

    assert normalize_company_name("syn", registry) == "Synthetic Enterprise"
    assert normalize_company_name("SYNTHETIC-CORP", registry) == "Synthetic Enterprise"

    # Substring containment strictly rejected (syn in drilling does NOT map)
    assert normalize_company_name("Synthetic Drilling Operations", registry) == "Synthetic Drilling Operations"



def test_primary_buyer_families_and_coo_exclusion(sample_patterns_df):
    """Verify primary buyer families are Training/Competence and COO is explicitly excluded."""
    company_row = pd.Series({"company_name": "ExxonMobil", "line_of_work": "Oil and gas"})
    fit = {"score": 80.0, "confidence_level": "HIGH"}
    trigger = {"score": 85.0, "clusters": []}
    contact = {"status": "UNKNOWN", "score": 0.0, "stage": "Not Connected", "matched_contacts": []}
    priority = {"account_opportunity": "High-fit opportunity", "outreach_readiness": "Buyer Needed"}
    canonical = load_canonical_seven_patterns(sample_patterns_df)

    brief = generate_tailored_outreach_brief(company_row, fit, trigger, contact, priority, canonical)

    buyers = brief["recommended_primary_buyers"]
    assert any("Operations Training" in b for b in buyers)
    assert any("Workforce Competence" in b for b in buyers)
    assert any("Learning & Development" in b for b in buyers)
    assert any("Chief Operating Officer" in e for e in brief["excluded_roles"])


def test_privacy_safe_export_masks_pii():
    """Ensure privacy safe export masks personal contact names and emails."""
    records = [
        {
            "company_name": "ExxonMobil",
            "sector": "Energy & Oil & Gas Infrastructure",
            "account_opportunity": "High-fit opportunity",
            "outreach_readiness": "Ready",
            "recommended_next_action": "Contact now",
            "composite_score": 88.0,
            "contact_name": "Marcus Vance",
            "contact_email": "marcus.vance@exxonmobil.com",
        }
    ]
    df_masked = generate_privacy_safe_export(records, mask_pii=True)
    assert df_masked.iloc[0]["contact_name"] == "M. V***"
    assert df_masked.iloc[0]["contact_email"] == "m***@exxonmobil.com"
    assert df_masked.iloc[0]["company_name"] == "ExxonMobil"


def test_csv_upload_schema_validation():
    """Validate CRM and Contact schema checker."""
    valid_crm = pd.DataFrame([{"company_name": "ExxonMobil", "crm_stage": "Lead"}])
    ok, msg = validate_crm_schema(valid_crm)
    assert ok is True

    invalid_crm = pd.DataFrame([{"account_id": "ACC-01", "arr": 100000}])
    ok, msg = validate_crm_schema(invalid_crm)
    assert ok is False
    assert "Missing required company identifier" in msg

    valid_cnt = pd.DataFrame([{"company_name": "ExxonMobil", "title": "VP Training"}])
    ok, msg = validate_contact_schema(valid_cnt)
    assert ok is True

    invalid_cnt = pd.DataFrame([{"company_name": "ExxonMobil", "name": "John"}])
    ok, msg = validate_contact_schema(invalid_cnt)
    assert ok is False
    assert "Missing required 'title'" in msg


# Newly Added Targeted Tests
def test_out_of_scope_companies_excluded_from_default_eon_ranking():
    """Sherwin-Williams (Coatings) is OUT OF DEFAULT EON SCOPE and excluded from default scope."""
    sector_energy = classify_sector_from_line_of_work("Oil and gas")
    sector_paint = classify_sector_from_line_of_work("Paints and coatings")

    assert is_in_default_eon_scope(sector_energy) is True
    assert is_in_default_eon_scope(sector_paint) is False

    assert get_scope_label(sector_energy) == "IN CORE EON SCOPE"
    assert get_scope_label(sector_paint) == "OUT OF DEFAULT EON SCOPE"


def test_undated_signals_produce_unknown_temporal_urgency():
    """Undated forward signals in current schema must produce temporal_urgency = UNKNOWN."""
    undated_signals = pd.DataFrame([
        {
            "company_name": "ExxonMobil",
            "signal_index": 1,
            "headline": "ExxonMobil Just Approved an Expansion of a Material Facility in Texas",
            "reported_by": "Yahoo Finance",
            "implication_text": "Facility build.",
            "page_number": 2,
        }
    ])
    trigger = calculate_trigger_relevance(undated_signals)
    assert trigger["temporal_urgency"] == "UNKNOWN"
    assert trigger["has_verified_current_date"] is False


def test_generic_expansion_headlines_do_not_produce_maximum_score():
    """
    Generic expansion headlines lacking specific assets, stage, or workforce detail
    must not produce a maximum score (prevents score saturation).
    """
    generic_signals = pd.DataFrame([
        {
            "company_name": "GenericCorp",
            "signal_index": 1,
            "headline": "Company plans expansion in upcoming years",
            "reported_by": "Local paper",
            "implication_text": "Corporate growth.",
            "page_number": 2,
        }
    ])
    trigger = calculate_trigger_relevance(generic_signals)
    # Score should be well below 50!
    assert trigger["score"] < 50.0, f"Generic signal score {trigger['score']} must be below 50!"


def test_contactability_values_never_contain_recommended_actions():
    """Contactability status must strictly be KNOWN, PARTIAL, or UNKNOWN; never recommended actions."""
    res_unknown = calculate_contactability("ExxonMobil", contacts_df=None, crm_df=None)
    assert res_unknown["status"] in ("KNOWN", "PARTIAL", "UNKNOWN")
    assert "Identify" not in res_unknown["status"]
    assert "Contact" not in res_unknown["status"]

    contacts_df = pd.DataFrame([{"company_name": "ExxonMobil", "title": "VP Training", "contact_name": "John Doe"}])
    res_partial = calculate_contactability("ExxonMobil", contacts_df=contacts_df, crm_df=None)
    assert res_partial["status"] in ("KNOWN", "PARTIAL", "UNKNOWN")
    assert "Identify" not in res_partial["status"]


def test_contact_now_requires_both_verified_trigger_and_matched_primary_buyer():
    """
    'Contact now' requires BOTH a verified current trigger date and a matched primary buyer.
    If the trigger is undated, it outputs 'Validate trigger'.
    If the buyer is missing, it outputs 'Identify buyer'.
    """
    fit = {"score": 80.0, "confidence_level": "HIGH", "evidence_coverage_pct": 90.0}

    # Case 1: Strong trigger, but UNDATED (as in raw schema), and suitable buyer known
    undated_trigger = {"score": 85.0, "has_verified_current_date": False, "temporal_urgency": "UNKNOWN"}
    known_buyer_contact = {"status": "KNOWN", "role_coverage": "PRIMARY_BUYER_IDENTIFIED", "score": 80.0}
    p1 = derive_priority_and_readiness(fit, undated_trigger, known_buyer_contact)
    assert p1["recommended_next_action"] == "Validate trigger", "Undated trigger with known buyer must require 'Validate trigger'!"

    # Case 2: Strong trigger, VERIFIED DATE, but NO buyer
    verified_trigger = {"score": 85.0, "has_verified_current_date": True, "temporal_urgency": "VERIFIED_CURRENT"}
    no_buyer_contact = {"status": "UNKNOWN", "role_coverage": "NO_CONTACTS", "score": 0.0}
    p2 = derive_priority_and_readiness(fit, verified_trigger, no_buyer_contact)
    assert p2["recommended_next_action"] == "Identify buyer", "Missing buyer with verified trigger must require 'Identify buyer'!"

    # Case 3: BOTH verified date AND suitable buyer known
    p3 = derive_priority_and_readiness(fit, verified_trigger, known_buyer_contact)
    assert p3["recommended_next_action"] == "Contact now", "Both verified trigger and known buyer must produce 'Contact now'!"


def test_score_normalization_and_raw_point_totals():
    """Verify raw points, max raw points, and normalized 0-100 scores across dimensions."""
    row = pd.Series({
        "people_employed": 55000,
        "operating_countries": "operations in over 120 countries",
        "line_of_work": "Oil and gas",
        "business_description": "Major energy infrastructure and pipelines.",
        "headquarters_city": "Houston",
        "headquarters_country": "United States",
        "year_founded": 1997,
    })

    # Under default weights: max points = 40 + 15 + 25 + 20 = 100.0
    fit_default = calculate_account_fit(row)
    assert fit_default["max_raw_points"] == 100.0
    assert fit_default["raw_points"] == 100.0
    assert fit_default["score"] == 100.0

    # Under custom weights that sum to 120 max points
    custom_weights = DEFAULT_WEIGHTS.copy()
    custom_weights["fit_headcount_max"] = 50.0  # +10
    custom_weights["fit_footprint_max"] = 25.0  # +10 -> sum = 120.0
    fit_custom = calculate_account_fit(row, custom_weights)
    assert fit_custom["max_raw_points"] == 120.0
    assert fit_custom["raw_points"] == 120.0
    assert fit_custom["score"] == 100.0  # normalized to 0-100!

    # Sparse row under custom weights
    sparse_row = pd.Series({"people_employed": 12000, "line_of_work": "Oil and gas"})
    fit_sparse = calculate_account_fit(sparse_row, custom_weights)
    # Headcount: 12000 >= 10000 -> 0.75 * 50 = 37.5. Sector: 25.0. Footprint: 0. Use case: 0. Raw = 62.5
    assert fit_sparse["raw_points"] == 62.5
    assert fit_sparse["max_raw_points"] == 120.0
    expected_norm = round((62.5 / 120.0) * 100.0, 1)
    assert fit_sparse["score"] == expected_norm


def test_full_visibility_of_every_scoring_dimension():
    """Ensure all 4 dimensions of Account Fit and all 4 dimensions of Trigger Relevance are visible and evaluated."""
    # Account Fit dimensions
    assert "fit_headcount_max" in DEFAULT_WEIGHTS
    assert "fit_footprint_max" in DEFAULT_WEIGHTS
    assert "fit_sector_max" in DEFAULT_WEIGHTS
    assert "fit_use_case_max" in DEFAULT_WEIGHTS

    # Trigger Relevance dimensions
    assert "trigger_asset_max" in DEFAULT_WEIGHTS
    assert "trigger_stage_max" in DEFAULT_WEIGHTS
    assert "trigger_workforce_max" in DEFAULT_WEIGHTS
    assert "trigger_source_max" in DEFAULT_WEIGHTS

    # Contactability dimensions
    assert "contact_role_max" in DEFAULT_WEIGHTS
    assert "contact_stage_max" in DEFAULT_WEIGHTS

    row = pd.Series({
        "people_employed": 15000,
        "operating_countries": "worldwide operations",
        "line_of_work": "Petrochemicals",
        "business_description": "Operates manufacturing facilities and refining pipelines.",
    })
    fit = calculate_account_fit(row)
    b = fit["breakdown"]
    assert "headcount_max" in b and b["headcount_max"] == 40.0
    assert "footprint_max" in b and b["footprint_max"] == 15.0
    assert "sector_max" in b and b["sector_max"] == 25.0
    assert "use_case_max" in b and b["use_case_max"] == 20.0


def test_correct_provenance_classification(sample_patterns_df):
    """
    Verify strict 5-tier provenance tags:
      - Third-party headlines tagged [PUBLIC FORWARD SIGNAL] (not [REPORT FACT])
      - Verbatim company disclosures tagged [REPORT FACT]
      - Inferred schedule/operational need tagged [ANALYST INTERPRETATION]
      - Inquiries tagged [SUGGESTED DISCOVERY QUESTION]
      - Product statements tagged [EON PRODUCT POSITIONING]
      - Absence of CRM tagged [DATA AVAILABILITY] No CRM or contact data uploaded.
    """
    company_row = pd.Series({
        "company_name": "Reliance (RIL)",
        "line_of_work": "Petrochemicals",
        "headquarters_city": "Mumbai",
        "people_employed": None,
    })
    fit = {"score": 45.0, "confidence_level": "LOW", "breakdown": {"headcount_status": "MISSING"}}
    trigger = {
        "score": 68.5,
        "clusters": [{
            "headline": "Reliance To Build Green Energy Giga Complex Spread Across 5,000 Acres in Jamnagar",
            "outlet": "Saur Energy",
            "page_number": 2,
        }],
    }
    contact_unknown = {"status": "UNKNOWN", "score": 0.0, "stage": "NO_CRM", "matched_contacts": [], "matched_crm_account": None}
    priority = {"account_opportunity": "Low-fit opportunity", "outreach_readiness": "Buyer Needed"}
    canonical = load_canonical_seven_patterns(sample_patterns_df)

    brief = generate_tailored_outreach_brief(
        company_row, fit, trigger, contact_unknown, priority, canonical
    )

    # 1. Verify headline is tagged [PUBLIC FORWARD SIGNAL] and NOT [REPORT FACT]
    sig_para = [p for p in brief["body_paragraphs"] if "[PUBLIC FORWARD SIGNAL]" in p]
    assert len(sig_para) == 1
    assert "Saur Energy" in sig_para[0]
    assert "[REPORT FACT]" not in sig_para[0]

    # 2. Verify product statement is tagged [EON PRODUCT POSITIONING]
    prod_para = [p for p in brief["body_paragraphs"] if "[EON PRODUCT POSITIONING]" in p]
    assert len(prod_para) == 1
    assert "is designed to support procedure rehearsal before live execution" in prod_para[0]

    # 3. Verify absence-of-CRM labeling is [DATA AVAILABILITY]
    assert brief["crm_context"] == "⚪ [DATA AVAILABILITY] No CRM or contact data uploaded."
    assert "[CRM FACT]" not in brief["crm_context"]

    # 4. Verify that when CRM is present, it is tagged [CRM FACT]
    contact_known = {
        "status": "KNOWN",
        "score": 85.0,
        "stage": "Qualified Lead",
        "matched_contacts": [{"contact_name": "Marcus Vance", "title": "VP Training"}],
        "matched_crm_account": {"company_name": "Reliance (RIL)"},
    }
    brief_with_crm = generate_tailored_outreach_brief(
        company_row, fit, trigger, contact_known, priority, canonical
    )
    assert "[CRM FACT]" in brief_with_crm["crm_context"]
    assert "Qualified Lead" in brief_with_crm["crm_context"]


def test_ui_export_calculation_parity(sample_patterns_df):
    """
    Verify UI calculation engine and export dataframe produce identical values.
    Asserts exact demonstrated calculations for Reliance (RIL):
      - Account Fit = 45.0
      - Trigger Relevance = 68.5
      - Contactability = UNKNOWN (0.0)
      - Composite = 56.8
      - Opportunity = Low-fit opportunity
      - Action = Validate trigger (Provisional)
    """
    comp_row = pd.Series({
        "company_name": "Reliance (RIL)",
        "line_of_work": "Petrochemicals",
        "headquarters_city": "Mumbai",
        "headquarters_country": "India",
        "business_description": None,
        "people_employed": None,
        "operating_countries": None,
    })
    signals_df = pd.DataFrame([
        {"company_name": "Reliance (RIL)", "signal_index": 1, "headline": "Masterstroke by Mukesh Ambani as Reliance Industries invests Rs 150000000000 in new energy venture, company t", "reported_by": "India", "page_number": 2},
        {"company_name": "Reliance (RIL)", "signal_index": 2, "headline": "Mukesh Ambani's Reliance (RIL) in Talks for $2 Billion Loan to Fuel Expansion", "reported_by": "Bloomberg", "page_number": 2},
        {"company_name": "Reliance (RIL)", "signal_index": 3, "headline": "Reliance To Build Green Energy Giga Complex Spread Across 5,000 Acres in Jamnagar", "reported_by": "Saur Energy", "page_number": 2},
        {"company_name": "Reliance (RIL)", "signal_index": 4, "headline": "Reliance Industries signs MoU to invest Rs 645 cr in Vadhvan port project", "reported_by": "business-standard", "page_number": 2},
    ])

    fit = calculate_account_fit(comp_row)
    trigger = calculate_trigger_relevance(signals_df)
    contact = calculate_contactability("Reliance (RIL)")
    priority = derive_priority_and_readiness(fit, trigger, contact)

    assert fit["score"] == 45.0
    assert fit["evidence_coverage_pct"] == 42.9
    assert fit["confidence_level"] == "LOW"

    assert trigger["score"] == 68.5
    assert trigger["temporal_urgency"] == "UNKNOWN"

    assert contact["status"] == "UNKNOWN"
    assert contact["score"] == 0.0

    assert priority["composite_score"] == 56.8
    assert priority["account_opportunity"] == "Low-fit opportunity"
    assert priority["outreach_readiness"] == "Buyer Needed"
    assert priority["recommended_next_action"] == "Validate trigger (Provisional)"

    # Verify Export parity and lineage
    record = {
        "company_name": "Reliance (RIL)",
        "sector": fit["sector"],
        "sector_scope_status": fit["scope_label"],
        "wingman_tier": "Tier 2",
        "account_opportunity": priority["account_opportunity"],
        "outreach_readiness": priority["outreach_readiness"],
        "recommended_next_action": priority["recommended_next_action"],
        "temporal_urgency": priority["temporal_urgency"],
        "composite_score": priority["composite_score"],
        "fit_score": fit["score"],
        "fit_raw_points": fit["raw_points"],
        "fit_max_raw_points": fit["max_raw_points"],
        "trigger_score": trigger["score"],
        "trigger_raw_points": trigger["raw_points"],
        "trigger_max_raw_points": trigger["max_raw_points"],
        "contactability": contact["status"],
        "contact_score": contact["score"],
        "contact_raw_points": contact["raw_points"],
        "contact_max_raw_points": contact["max_raw_points"],
        "effective_composite_weights": priority["effective_weights_str"],
        "derivation_mode": priority["derivation_mode"],
        "evidence_coverage_pct": fit["evidence_coverage_pct"],
        "confidence_level": fit["confidence_level"],
        "target_buyer_department": "Operational Training",
        "lead_project_trigger": trigger["clusters"][0]["headline"],
    }
    df_exp = generate_privacy_safe_export([record], active_weights=DEFAULT_WEIGHTS)

    assert df_exp.iloc[0]["engine_version"] == METHODOLOGY_VERSION
    assert df_exp.iloc[0]["preset_version"] == DEFAULT_PRESET_NAME
    assert df_exp.iloc[0]["composite_score"] == 56.8
    assert df_exp.iloc[0]["account_fit_score"] == 45.0
    assert df_exp.iloc[0]["trigger_relevance_score"] == 68.5
    assert df_exp.iloc[0]["effective_composite_weights"] == "fit=0.50;trigger=0.50;contact=0.00"
    assert "calculation_timestamp" in df_exp.columns
    assert "active_weights" in df_exp.columns


def test_absence_of_crm_labeling():
    """Verify that absence of CRM produces [DATA AVAILABILITY] and Contactability UNKNOWN (0 pts)."""
    res = calculate_contactability("Generic Org", contacts_df=None, crm_df=None)
    assert res["status"] == "UNKNOWN"
    assert res["score"] == 0.0
    assert res["raw_points"] == 0.0

    company_row = pd.Series({"company_name": "Generic Org", "line_of_work": "Industrial"})
    fit = {"score": 50.0, "confidence_level": "LOW", "breakdown": {}}
    trigger = {"score": 50.0, "clusters": []}
    priority = {"account_opportunity": "Moderate-fit opportunity", "outreach_readiness": "Buyer Needed"}
    brief = generate_tailored_outreach_brief(company_row, fit, trigger, res, priority, canonical_patterns=[])
    assert brief["crm_context"] == "⚪ [DATA AVAILABILITY] No CRM or contact data uploaded."


def test_abbreviate_monetary_values():
    """Verify that large monetary values are abbreviated in display text while preserving text."""
    s1 = "Reliance Industries invests Rs 150000000000 in new energy venture"
    assert abbreviate_monetary_values(s1) == "Reliance Industries invests Rs 15,000 cr in new energy venture"

    s2 = "Loan of $2000000000 to fuel project"
    assert abbreviate_monetary_values(s2) == "Loan of $2B to fuel project"

    s3 = "Unplanned downtime costs $38 million a year and over $88 million"
    assert abbreviate_monetary_values(s3) == "Unplanned downtime costs $38M a year and over $88M"

    # Preserves already formatted strings
    s4 = "Invests Rs 645 cr in port"
    assert abbreviate_monetary_values(s4) == "Invests Rs 645 cr in port"


def test_cluster_forward_signals_pure_function():
    """Verify cluster_forward_signals handles duplicate clustering, heuristics, and scoring."""
    df_signals = pd.DataFrame([
        {
            "signal_index": 1,
            "headline": "Plans $324M facility expansion at Bowling Green plant",
            "outlet": "Reuters",
            "page_number": 12,
            "implication": "Commissioning training needed",
        },
        {
            "signal_index": 2,
            "headline": "Constructing new units at Bowling Green facility",
            "outlet": "Bloomberg",
            "page_number": 15,
            "implication": "Operational ramp-up",
        },
        {
            "signal_index": 3,
            "headline": "Signs MoU for Texas carbon storage hub",
            "outlet": "PR Newswire",
            "page_number": 20,
            "implication": "New technology deployment",
        },
    ])

    clusters = cluster_forward_signals(df_signals, DEFAULT_WEIGHTS)
    assert len(clusters) == 3
    # Two Bowling Green signals share cluster_key
    assert clusters[0]["cluster_key"] == "bowling_green_expansion"
    assert clusters[0]["is_duplicate_cluster"] is False
    assert clusters[1]["cluster_key"] == "bowling_green_expansion"
    assert clusters[1]["is_duplicate_cluster"] is True
    # Texas carbon cluster
    assert clusters[2]["cluster_key"] == "carbon_storage"
    assert clusters[2]["is_duplicate_cluster"] is False

    # Empty dataframe returns empty list
    assert cluster_forward_signals(pd.DataFrame()) == []


def test_buyer_outreach_page_baseline_and_combined_ui_smoke():
    """
    Streamlit AppTest regression test executing Buyer & Outreach Recommendation page.
    Verifies:
      - Baseline Reports, no commercial uploads (report-only fallback) loads without exception
      - Combined View, no commercial uploads includes Kinder Morgan without exception
      - Selection of each available account (Reliance, ExxonMobil, Sherwin-Williams, Kinder Morgan)
      - The Scorecard, Triggers, Discovery and Outreach Brief tabs render properly
      - Zero Streamlit exceptions in any tested state (assert len(at.exception) == 0)
    """
    from pathlib import Path
    from streamlit.testing.v1 import AppTest

    project_root = Path(__file__).resolve().parents[1]
    page_path = project_root / "dashboard" / "pages" / "9_buyer_outreach.py"

    # 1. Baseline Reports default scope
    at = AppTest.from_file(str(page_path), default_timeout=30).run()
    assert len(at.exception) == 0
    assert at.selectbox[1].value == "Reliance (RIL)"

    # Switch account to ExxonMobil
    at.selectbox[1].select("ExxonMobil").run()
    assert len(at.exception) == 0
    assert at.selectbox[1].value == "ExxonMobil"

    # Switch portfolio scope to 'All Industrial Sectors' and select Sherwin-Williams
    at.selectbox[0].select("All Industrial Sectors").run()
    assert len(at.exception) == 0
    assert "Sherwin-Williams" in at.selectbox[1].options
    at.selectbox[1].select("Sherwin-Williams").run()
    assert len(at.exception) == 0
    assert at.selectbox[1].value == "Sherwin-Williams"

    # 2. Combined View: includes Kinder Morgan
    at2 = AppTest.from_file(str(page_path), default_timeout=30)
    at2.session_state["selected_scope"] = "Combined View"
    at2.run()
    assert len(at2.exception) == 0
    assert "Kinder Morgan" in at2.selectbox[1].options
    at2.selectbox[1].select("Kinder Morgan").run()
    assert len(at2.exception) == 0
    assert at2.selectbox[1].value == "Kinder Morgan"

    # 3. Audited Holdout Report
    at3 = AppTest.from_file(str(page_path), default_timeout=30)
    at3.session_state["selected_scope"] = "Audited Holdout Report"
    at3.run()
    assert len(at3.exception) == 0
    assert at3.selectbox[1].value == "Kinder Morgan"

    # 4. Verify all 4 tabs rendered
    assert len(at.tabs) == 4
    tab_labels = [getattr(t, "label", "") for t in at.tabs]
    assert tab_labels == ["Scorecard", "Triggers", "Discovery", "Outreach Brief"]
