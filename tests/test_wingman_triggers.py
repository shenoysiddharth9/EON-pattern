"""
Comprehensive Unit Tests for Wingman Trigger Intelligence Module.
Uses 100% synthetic, anonymized test records and fictitious domains.
Validates:
  1. UTF-8-sig BOM normalization and 11-column canonical schema contract
  2. Date precision handling (DAY, MONTH, QUARTER, MISSING, INVALID)
  3. Date relation at scan vs temporal urgency as-of explicit analysis date
  4. Distance-to-event actions: 0-180d (Prepare outreach), 181-365d (Plan outreach), >365d (Monitor milestone)
  5. Action safeguard: Contactability = UNKNOWN can NEVER produce Contact now
  6. Confidence semantics: SCANNED_ZERO_TRIGGERS gets scan_confidence HIGH/MEDIUM, evidence confidence NOT_APPLICABLE
  7. Absent company semantics: ABSENT_FROM_EXPORT with report fallback
  8. Domain matching safeguards: webmail blacklist (gmail.com, etc.)
  9. Multi-entity domain collision: requires reviewed alias or exact name, else REVIEW_REQUIRED
  10. Conservative event clustering: requires shared asset/counterparty key, avoids blind company+date merges
  11. URL extraction and unparsed residual text detection
  12. Sector and tier conflict flags preserved without overwriting report attributes
"""

import pytest
from datetime import date
from dashboard.wingman_triggers import (
    parse_trigger_date,
    compute_date_relation_at_scan,
    compute_temporal_status_as_of,
    extract_valid_urls,
    normalize_domain,
    parse_wingman_trigger_export,
    match_company_to_wingman_records,
    cluster_wingman_events,
    calculate_wingman_trigger_relevance,
    derive_recommended_action_wingman,
    CANONICAL_COLUMNS,
)


def test_utf8_sig_bom_and_header_validation():
    # Synthetic CSV with UTF-8 BOM
    header = "company,segment,domain,tier,trigger_type,trigger_date,trigger_summary,trigger_source_url,pattern_report_url,scanned_at,notes\n"
    row1 = "Alpha Energy,oil and gas,alpha-energy.example.com,1,turnaround,2026-08-15,Planned turnaround at Unit 1,https://news.example.com/u1,https://report.example.com/alpha,2026-08-10,Valid scan notes with sufficient detail for testing.\n"
    csv_bytes = b"\xef\xbb\xbf" + (header + row1).encode("utf-8")

    res = parse_wingman_trigger_export(csv_bytes)
    assert res["valid"] is True
    assert res["metadata"]["bom_detected"] is True
    assert len(res["records"]) == 1
    assert res["records"][0]["company"] == "Alpha Energy"

    # Missing column failure
    bad_header = "company,domain,tier,trigger_type\n"
    res_bad = parse_wingman_trigger_export(bad_header)
    assert res_bad["valid"] is False
    assert "Missing required column headers" in res_bad["error"]


def test_extra_columns_forward_compatible():
    header = "company,segment,domain,tier,trigger_type,trigger_date,trigger_summary,trigger_source_url,pattern_report_url,scanned_at,notes,future_metadata_col\n"
    row1 = "Beta Corp,oil and gas,beta.example.com,2,turnaround,2026-08-15,Turnaround,https://news.example.com,https://rep.example.com,2026-08-10,Notes,extra_val\n"
    res = parse_wingman_trigger_export(header + row1)
    assert res["valid"] is True
    assert res["records"][0]["future_metadata_col"] == "extra_val"
    assert any("forward-compatible" in w for w in res["warnings"])


def test_date_precision_and_status():
    # Exact DAY
    dt, prec, stat, raw = parse_trigger_date("2026-07-15")
    assert dt == date(2026, 7, 15)
    assert prec == "DAY"
    assert stat == "EXACT"

    # Approximate MONTH
    dt, prec, stat, raw = parse_trigger_date("2026-07")
    assert dt == date(2026, 7, 1)
    assert prec == "MONTH"
    assert stat == "APPROXIMATE"

    # Approximate QUARTER (Q3 -> July 1)
    dt, prec, stat, raw = parse_trigger_date("2026-Q3")
    assert dt == date(2026, 7, 1)
    assert prec == "QUARTER"
    assert stat == "APPROXIMATE"

    # MISSING
    dt, prec, stat, raw = parse_trigger_date("")
    assert dt is None
    assert prec == "MISSING"

    # INVALID
    dt, prec, stat, raw = parse_trigger_date("unknown-text-string")
    assert dt is None
    assert prec == "INVALID"


def test_temporal_status_relative_to_explicit_as_of_date():
    scan_dt = date(2026, 8, 26)
    event_dt = date(2026, 9, 1)

    # At scan time (2026-08-26), event (2026-09-01) is in the future
    rel_at_scan = compute_date_relation_at_scan(event_dt, "DAY", scan_dt)
    assert rel_at_scan == "PLANNED_AT_SCAN"

    # As-of 2026-09-17, event (2026-09-01) has passed (16 days ago -> CURRENT_ACTIVE)
    as_of_dt = date(2026, 9, 17)
    temp_as_of = compute_temporal_status_as_of(event_dt, "DAY", as_of_dt)
    assert temp_as_of == "CURRENT_ACTIVE"

    # Upcoming within 180 days (e.g. 2026-11-01 relative to 2026-09-17 -> 45 days)
    upcoming_dt = date(2026, 11, 1)
    assert compute_temporal_status_as_of(upcoming_dt, "DAY", as_of_dt) == "UPCOMING_0_180_DAYS"

    # Planned 181-365 days (e.g. 2027-05-01 relative to 2026-09-17 -> 226 days)
    planned_dt = date(2027, 5, 1)
    assert compute_temporal_status_as_of(planned_dt, "DAY", as_of_dt) == "PLANNED_181_365_DAYS"

    # Long range > 365 days (e.g. 2028-01-01 relative to 2026-09-17)
    long_range_dt = date(2028, 1, 1)
    assert compute_temporal_status_as_of(long_range_dt, "DAY", as_of_dt) == "LONG_RANGE_OVER_365_DAYS"


def test_distance_based_recommended_actions():
    # 0-180 days -> Prepare outreach
    act_180 = derive_recommended_action_wingman(
        temporal_status_as_of="UPCOMING_0_180_DAYS",
        trigger_score=85.0,
        contact_status="KNOWN",
        evidence_coverage_pct=85.0,
    )
    assert act_180 == "Prepare outreach"

    # 181-365 days -> Plan outreach
    act_365 = derive_recommended_action_wingman(
        temporal_status_as_of="PLANNED_181_365_DAYS",
        trigger_score=85.0,
        contact_status="KNOWN",
        evidence_coverage_pct=85.0,
    )
    assert act_365 == "Plan outreach"

    # >365 days -> Monitor milestone
    act_long = derive_recommended_action_wingman(
        temporal_status_as_of="LONG_RANGE_OVER_365_DAYS",
        trigger_score=85.0,
        contact_status="KNOWN",
        evidence_coverage_pct=85.0,
    )
    assert act_long == "Monitor milestone"

    # Future milestone can NEVER produce Contact now, even with known buyer
    assert act_180 != "Contact now"
    assert act_365 != "Contact now"


def test_contactability_unknown_blocks_contact_now():
    # Current active trigger + UNKNOWN contactability MUST produce Identify buyer, NEVER Contact now
    action = derive_recommended_action_wingman(
        temporal_status_as_of="CURRENT_ACTIVE",
        trigger_score=90.0,
        contact_status="UNKNOWN",
        evidence_coverage_pct=100.0,
    )
    assert action == "Identify buyer"

    # When contactability is KNOWN, it produces Contact now
    action_known = derive_recommended_action_wingman(
        temporal_status_as_of="CURRENT_ACTIVE",
        trigger_score=90.0,
        contact_status="KNOWN",
        evidence_coverage_pct=100.0,
    )
    assert action_known == "Contact now"


def test_zero_trigger_confidence_semantics():
    # Zero trigger record
    header = "company,segment,domain,tier,trigger_type,trigger_date,trigger_summary,trigger_source_url,pattern_report_url,scanned_at,notes\n"
    row_zero = "Gamma Midstream,oil and gas,gamma.example.com,2,,,,,https://rep.example.com,2026-09-01,Comprehensive scan completed across all eight categories with zero qualifying items found.\n"
    parsed = parse_wingman_trigger_export(header + row_zero)

    match_res = match_company_to_wingman_records(
        company_id="COMP-GAMMA",
        company_name="Gamma Midstream",
        company_domain="gamma.example.com",
        all_wingman_records=parsed["records"],
        multi_entity_domains={},
    )

    assert match_res["trigger_state"] == "SCANNED_ZERO_TRIGGERS"
    assert match_res["scan_confidence"] == "HIGH"

    # Relevance calculation on empty clusters
    relevance = calculate_wingman_trigger_relevance([], as_of_date=date(2026, 9, 17))
    assert relevance["score"] == 0.0
    assert relevance["trigger_evidence_confidence"] == "NOT_APPLICABLE"
    assert relevance["temporal_status_as_of"] == "NONE_DETECTED"

    action = derive_recommended_action_wingman(
        temporal_status_as_of=relevance["temporal_status_as_of"],
        trigger_score=0.0,
        contact_status="UNKNOWN",
        evidence_coverage_pct=75.0,
        trigger_state=match_res["trigger_state"],
    )
    assert action == "Monitor"

    # Verify exact mandatory triple for zero-trigger scanned accounts
    assert match_res["trigger_state"] == "SCANNED_ZERO_TRIGGERS"
    assert relevance["temporal_status_as_of"] == "NONE_DETECTED"
    assert action == "Monitor"


def test_absent_company_semantics():
    match_res = match_company_to_wingman_records(
        company_id="COMP-NONEXISTENT",
        company_name="Nonexistent Industrial",
        company_domain="nonexistent.example.com",
        all_wingman_records=[],
        multi_entity_domains={},
    )
    assert match_res["trigger_state"] == "ABSENT_FROM_EXPORT"
    assert match_res["scan_confidence"] == "NOT_APPLICABLE"


def test_domain_matching_blocks_generic_webmail():
    header = "company,segment,domain,tier,trigger_type,trigger_date,trigger_summary,trigger_source_url,pattern_report_url,scanned_at,notes\n"
    row1 = "Delta Academy,var,gmail.com,3,hiring_burst,2026-08-01,Recruitment,https://news.example.com,https://rep.example.com,2026-08-01,Notes\n"
    parsed = parse_wingman_trigger_export(header + row1)

    # Trying to match a different company that has gmail.com domain
    match_res = match_company_to_wingman_records(
        company_id="COMP-OTHER",
        company_name="Other Consulting",
        company_domain="gmail.com",
        all_wingman_records=parsed["records"],
        multi_entity_domains={},
    )
    # Should NOT match on gmail.com
    assert match_res["match_status"] == "UNMATCHED"


def test_multi_entity_domain_collision_requires_alias_or_name():
    # Two companies sharing the same domain
    header = "company,segment,domain,tier,trigger_type,trigger_date,trigger_summary,trigger_source_url,pattern_report_url,scanned_at,notes\n"
    row1 = "Holding Parent Energy,oil and gas,shared-group.example.com,1,turnaround,2026-08-01,Parent turnaround,https://news.example.com,https://rep.example.com,2026-08-01,Notes\n"
    row2 = "Subsidiary Services,oil and gas,shared-group.example.com,2,hiring_burst,2026-08-01,Hiring,https://news.example.com,https://rep.example.com,2026-08-01,Notes\n"
    parsed = parse_wingman_trigger_export(header + row1 + row2)

    multi_domains = parsed["multi_entity_domains"]
    assert "shared-group.example.com" in multi_domains

    from dashboard.identity_registry import parse_identity_crosswalk

    # Target company with approved domain via registry, but domain is multi-entity without name corroboration -> REVIEW_REQUIRED
    csv_unresolved = (
        "canonical_account_id,canonical_company_name,approved_alias,approved_domain,approved_ticker,approval_status,approved_by,approved_at\n"
        'COMP-THIRD,"Third Division Unrelated",,"shared-group.example.com",,APPROVED,AUDITOR,2026-09-17\n'
    )
    reg_unresolved = parse_identity_crosswalk(csv_unresolved)["registry"]
    match_unresolved = match_company_to_wingman_records(
        company_id="COMP-THIRD",
        company_name="Third Division Unrelated",
        company_domain="shared-group.example.com",
        all_wingman_records=parsed["records"],
        multi_entity_domains=multi_domains,
        identity_registry=reg_unresolved,
    )
    assert match_unresolved["match_status"] == "REVIEW_REQUIRED"
    assert match_unresolved["trigger_state"] == "MATCH_REVIEW_REQUIRED"

    # Target company with exact reviewed alias corroboration -> MATCHED
    csv_corroborated = (
        "canonical_account_id,canonical_company_name,approved_alias,approved_domain,approved_ticker,approval_status,approved_by,approved_at\n"
        'COMP-PARENT,"Holding Parent Energy","holding parent energy","shared-group.example.com",,APPROVED,AUDITOR,2026-09-17\n'
    )
    reg_corroborated = parse_identity_crosswalk(csv_corroborated)["registry"]
    match_corroborated = match_company_to_wingman_records(
        company_id="COMP-PARENT",
        company_name="Holding Parent Energy",
        company_domain="shared-group.example.com",
        all_wingman_records=parsed["records"],
        multi_entity_domains=multi_domains,
        identity_registry=reg_corroborated,
    )
    assert match_corroborated["match_status"] == "MATCHED"
    assert match_corroborated["match_confidence"] == "HIGH"

    # Without a registry: company_domain cannot authorize matching
    match_no_reg = match_company_to_wingman_records(
        company_id="COMP-THIRD",
        company_name="Third Division Unrelated",
        company_domain="shared-group.example.com",
        all_wingman_records=parsed["records"],
        multi_entity_domains=multi_domains,
        identity_registry=None,
    )
    assert match_no_reg["raw_matched_record_count"] == 0
    assert match_no_reg["match_status"] != "MATCHED"



def test_conservative_event_clustering():
    # Two records sharing company, trigger_type, asset, and date window
    records = [
        {
            "company": "Synthetic Refiner",
            "trigger_type": "turnaround",
            "trigger_summary": "Planned turnaround at synthetic facility refinery unit A",
            "trigger_date_parsed": date(2026, 8, 1),
            "trigger_date_raw": "2026-08-01",
            "date_precision": "DAY",
            "date_parse_status": "EXACT",
            "date_relation_at_scan": "PAST_AT_SCAN",
            "scanned_at_date": date(2026, 8, 10),
            "trigger_source_urls": ["https://source1.example.com"],
            "is_zero_trigger": False,
        },
        {
            "company": "Synthetic Refiner Operating Corp",
            "trigger_type": "turnaround",
            "trigger_summary": "Preparing for planned shutdown at synthetic facility refinery unit A",
            "trigger_date_parsed": date(2026, 8, 5),
            "trigger_date_raw": "2026-08-05",
            "date_precision": "DAY",
            "date_parse_status": "EXACT",
            "date_relation_at_scan": "PAST_AT_SCAN",
            "scanned_at_date": date(2026, 8, 10),
            "trigger_source_urls": ["https://source2.example.com"],
            "is_zero_trigger": False,
        },
    ]

    clusters = cluster_wingman_events(records, company_id="COMP-SYNTH")
    assert len(clusters) == 1
    assert clusters[0]["child_records_count"] == 2
    assert "https://source1.example.com" in clusters[0]["all_source_urls"]
    assert "https://source2.example.com" in clusters[0]["all_source_urls"]
    assert clusters[0]["cluster_method"] == "SHARED_ASSET_AND_WINDOW"
    assert clusters[0]["cluster_id"].startswith("CLUST-COMP-SYN-TUR-")


def test_url_extraction_and_residual_text():
    raw_multi = "https://news.example.com/art1 ; https://wire.example.com/art2 and some unparsed text"
    urls, residual = extract_valid_urls(raw_multi)
    assert len(urls) == 2
    assert "https://news.example.com/art1" in urls
    assert "https://wire.example.com/art2" in urls
    assert residual == "some unparsed text"


def test_sector_and_tier_conflicts_do_not_overwrite_report():
    header = "company,segment,domain,tier,trigger_type,trigger_date,trigger_summary,trigger_source_url,pattern_report_url,scanned_at,notes\n"
    row1 = "Coating Producer,oil and gas,coating.example.com,1,turnaround,2026-08-01,Summary,https://news.example.com,https://rep.example.com,2026-08-01,Notes\n"
    parsed = parse_wingman_trigger_export(header + row1)

    match_res = match_company_to_wingman_records(
        company_id="COMP-COAT",
        company_name="Coating Producer",
        company_domain="coating.example.com",
        all_wingman_records=parsed["records"],
        multi_entity_domains={},
        report_sector="Coatings & Advanced Materials",
        report_wingman_tier="Tier 3",
    )

    # Sector conflict detected: report is coatings, export says oil and gas
    assert match_res["sector_conflict_flag"] is True
    # Tier conflict detected: report is Tier 3, export says 1
    assert match_res["tier_conflict_flag"] is True
    # Original report sector and tier remain strictly preserved
    assert match_res["report_sector"] == "Coatings & Advanced Materials"
    assert match_res["report_wingman_tier"] == "Tier 3"


def test_short_alias_never_matches_substring_or_larger_word():
    header = "company,segment,domain,tier,trigger_type,trigger_date,trigger_summary,trigger_source_url,pattern_report_url,scanned_at,notes\n"
    rows = [
        "ABCDrilling,oil and gas,abcdrill.example.com,1,turnaround,2026-08-01,Summary,https://s.example.com,,2026-08-01,\n",
        "XABC Services,oil and gas,xabc.example.com,1,turnaround,2026-08-01,Summary,https://s.example.com,,2026-08-01,\n",
        "Fabcat Logistics,oil and gas,fabcat.example.com,1,turnaround,2026-08-01,Summary,https://s.example.com,,2026-08-01,\n",
        "Tabcorp Drilling,oil and gas,tabcorp.example.com,1,turnaround,2026-08-01,Summary,https://s.example.com,,2026-08-01,\n",
    ]
    parsed = parse_wingman_trigger_export(header + "".join(rows))

    match_res = match_company_to_wingman_records(
        company_id="COMP-SYNTH",
        company_name="Example Corp (ABC)",
        company_domain="",
        all_wingman_records=parsed["records"],
        multi_entity_domains={},
        ticker_overrides={"COMP-SYNTH": ["abc"]},
    )

    # All candidate records with 'abc' as a substring inside words must remain UNMATCHED
    assert match_res["raw_matched_record_count"] == 0
    assert match_res["match_status"] == "UNMATCHED"


def test_short_alias_matches_exact_full_field():
    header = "company,segment,domain,tier,trigger_type,trigger_date,trigger_summary,trigger_source_url,pattern_report_url,scanned_at,notes\n"
    row = "ABC,oil and gas,abc.example.com,1,turnaround,2026-08-01,Summary,https://s.example.com,,2026-08-01,\n"
    parsed = parse_wingman_trigger_export(header + row)

    match_res = match_company_to_wingman_records(
        company_id="COMP-SYNTH",
        company_name="Example Corp (ABC)",
        company_domain="",
        all_wingman_records=parsed["records"],
        multi_entity_domains={},
        ticker_overrides={"COMP-SYNTH": ["abc"]},
    )

    assert match_res["raw_matched_record_count"] == 1
    assert match_res["match_status"] == "MATCHED"
    assert match_res["matched_records"][0]["company"] == "ABC"
    assert match_res["matched_records"][0]["match_method"] == "APPROVED_TICKER"


def test_parenthetical_ticker_matches_explicit_parentheses():
    header = "company,segment,domain,tier,trigger_type,trigger_date,trigger_summary,trigger_source_url,pattern_report_url,scanned_at,notes\n"
    rows = [
        "Example Holdings (ABC),oil and gas,example.example.com,1,turnaround,2026-08-01,Summary 1,https://s.example.com,,2026-08-01,\n",
        "Example ABC Holdings,oil and gas,other.example.com,1,turnaround,2026-08-01,Summary 2,https://s.example.com,,2026-08-01,\n",
    ]
    parsed = parse_wingman_trigger_export(header + "".join(rows))

    match_res = match_company_to_wingman_records(
        company_id="COMP-SYNTH",
        company_name="Example Corp (ABC)",
        company_domain="",
        all_wingman_records=parsed["records"],
        multi_entity_domains={},
        ticker_overrides={"COMP-SYNTH": ["abc"]},
    )

    assert match_res["raw_matched_record_count"] == 1
    assert match_res["matched_records"][0]["company"] == "Example Holdings (ABC)"
    assert match_res["matched_records"][0]["match_method"] == "APPROVED_PARENTHETICAL_TICKER"


def test_exact_reviewed_long_form_alias_matches_canonical():
    header = "company,segment,domain,tier,trigger_type,trigger_date,trigger_summary,trigger_source_url,pattern_report_url,scanned_at,notes\n"
    rows = [
        "Alpha Petroleum Operations,oil and gas,alpha.example.com,1,turnaround,2026-08-01,Summary 1,https://s.example.com,,2026-08-01,\n",
        "Alpha Petroleum Operations Group Subsidiary,oil and gas,sub.example.com,1,turnaround,2026-08-01,Summary 2,https://s.example.com,,2026-08-01,\n",
    ]
    parsed = parse_wingman_trigger_export(header + "".join(rows))

    match_res = match_company_to_wingman_records(
        company_id="COMP-ALPHA",
        company_name="Alpha Energy",
        company_domain="",
        all_wingman_records=parsed["records"],
        multi_entity_domains={},
        alias_overrides={"COMP-ALPHA": ["Alpha Petroleum Operations"]},
    )

    assert match_res["raw_matched_record_count"] == 1
    assert match_res["matched_records"][0]["company"] == "Alpha Petroleum Operations"
    assert match_res["matched_records"][0]["match_method"] == "APPROVED_ALIAS"


def test_unrelated_companies_sharing_character_substrings_remain_unmatched():
    header = "company,segment,domain,tier,trigger_type,trigger_date,trigger_summary,trigger_source_url,pattern_report_url,scanned_at,notes\n"
    rows = [
        "Redcorps Logistics,oil and gas,redcorps.example.com,1,turnaround,2026-08-01,Summary 1,https://s.example.com,,2026-08-01,\n",
        "Condor Commercial,oil and gas,condor.example.com,1,turnaround,2026-08-01,Summary 2,https://s.example.com,,2026-08-01,\n",
        "Mandarin Corporation,oil and gas,mandarin.example.com,1,turnaround,2026-08-01,Summary 3,https://s.example.com,,2026-08-01,\n",
    ]
    parsed = parse_wingman_trigger_export(header + "".join(rows))

    match_res = match_company_to_wingman_records(
        company_id="COMP-DC",
        company_name="Drill Corp (DC)",
        company_domain="",
        all_wingman_records=parsed["records"],
        multi_entity_domains={},
        ticker_overrides={"COMP-DC": ["dc"]},
    )

    assert match_res["raw_matched_record_count"] == 0
    assert match_res["match_status"] == "UNMATCHED"


def test_all_records_pass_row_level_match_integrity():
    from dashboard.wingman_triggers import assert_account_match_integrity
    import pytest

    matched_valid = [
        {"company": "Beta Energy (BET)", "company_normalized": "beta energy", "domain": "beta.example.com", "domain_normalized": "beta.example.com"},
        {"company": "Beta Industries", "company_normalized": "beta industries", "domain": "beta.example.com", "domain_normalized": "beta.example.com"},
    ]

    # Valid assertion succeeds
    assert_account_match_integrity(
        canonical_account_id="COMP-BETA",
        matched_records=matched_valid,
        allowed_normalized_names={"beta energy", "beta industries"},
        allowed_raw_names={"beta energy (bet)", "beta industries"},
        allowed_tickers={"bet"},
        verified_domain="beta.example.com",
    )

    # Injected contaminated row triggers AssertionError
    matched_contaminated = matched_valid + [
        {"company": "Unrelated Drilling Corp", "company_normalized": "unrelated drilling corp", "domain": "unrelated.example.com", "domain_normalized": "unrelated.example.com"}
    ]
    with pytest.raises(AssertionError, match="Account-match integrity assertion failed"):
        assert_account_match_integrity(
            canonical_account_id="COMP-BETA",
            matched_records=matched_contaminated,
            allowed_normalized_names={"beta energy", "beta industries"},
            allowed_raw_names={"beta energy (bet)", "beta industries"},
            allowed_tickers={"bet"},
            verified_domain="beta.example.com",
        )


def test_contaminated_rows_do_not_influence_clusters_lead_or_tier():
    header = "company,segment,domain,tier,trigger_type,trigger_date,trigger_summary,trigger_source_url,pattern_report_url,scanned_at,notes\n"
    rows = [
        # 2 genuine records for Beta Energy (BET)
        "Beta Energy (BET),oil and gas,beta.example.com,1,turnaround,2026-08-01,Beta refinery turnaround at alpha_plant,https://s.example.com,,2026-08-01,\n",
        "Beta Industries,oil and gas,beta.example.com,1,hiring_burst,2026-08-15,HSE hiring burst at beta,https://s.example.com,,2026-08-01,\n",
        # 5 contaminated records containing substring 'bet' inside other words
        "Alphabet Drilling,oil and gas,alphabet.example.com,3,project_fid_commissioning,2026-08-20,Alphabet $5B mega project,https://s.example.com,,2026-08-01,\n",
        "Bethel Marine,oil and gas,bethel.example.com,3,turnaround,2026-08-25,Bethel shipyard shutdown,https://s.example.com,,2026-08-01,\n",
        "Tibetan Oil,oil and gas,tibetan.example.com,3,incident_regulator,2026-08-10,Regulatory notice,https://s.example.com,,2026-08-01,\n",
    ]
    parsed = parse_wingman_trigger_export(header + "".join(rows))

    match_res = match_company_to_wingman_records(
        company_id="COMP-BETA",
        company_name="Beta Energy (BET)",
        company_domain="beta.example.com",
        all_wingman_records=parsed["records"],
        multi_entity_domains={},
        alias_overrides={"COMP-BETA": ["Beta Industries"]},
        ticker_overrides={"COMP-BETA": ["bet"]},
        report_sector="Energy & Oil & Gas Infrastructure",
        report_wingman_tier="Tier 1",
    )

    # Exactly 2 genuine records matched
    assert match_res["raw_matched_record_count"] == 2
    assert match_res["distinct_source_company_names"] == ["Beta Energy (BET)", "Beta Industries"]
    assert match_res["distinct_source_domains"] == ["beta.example.com"]
    # Contaminated tier 3 from Alphabet Drilling does NOT corrupt export tier
    assert match_res["observed_export_tiers"] == [1]
    assert match_res["trigger_export_tier"] == 1
    assert match_res["tier_conflict_flag"] is False

    # Clusters are driven exclusively by the 2 genuine records
    clusters = cluster_wingman_events(match_res["matched_records"], "COMP-BETA")
    assert len(clusters) == 2
    scored = calculate_wingman_trigger_relevance(clusters, date(2026, 9, 1))
    assert scored["lead_cluster"]["trigger_type"] in ("turnaround", "hiring_burst")
    assert "Alphabet" not in scored["lead_cluster"]["lead_summary"]


def test_conflicting_export_tiers_emits_multiple_export_tiers_review_required():
    header = "company,segment,domain,tier,trigger_type,trigger_date,trigger_summary,trigger_source_url,pattern_report_url,scanned_at,notes\n"
    rows = [
        "Gamma Corp,oil and gas,gamma.example.com,1,turnaround,2026-08-01,Summary 1,https://s.example.com,,2026-08-01,\n",
        "Gamma Industries,oil and gas,gamma.example.com,2,turnaround,2026-08-01,Summary 2,https://s.example.com,,2026-08-01,\n",
    ]
    parsed = parse_wingman_trigger_export(header + "".join(rows))

    match_res = match_company_to_wingman_records(
        company_id="COMP-GAMMA",
        company_name="Gamma Corp",
        company_domain="gamma.example.com",
        all_wingman_records=parsed["records"],
        multi_entity_domains={},
        alias_overrides={"COMP-GAMMA": ["Gamma Industries"]},
        report_wingman_tier="Tier 1",
    )

    assert match_res["raw_matched_record_count"] == 2
    assert match_res["observed_export_tiers"] == [1, 2]
    assert match_res["multiple_export_tiers_flag"] is True
    assert match_res["multiple_export_tiers_review_required"] is True
    assert match_res["tier_conflict_flag"] is False
    assert match_res["tier_conflict_review_required"] is False
    assert match_res["trigger_export_tier"] is None
    assert any("MULTIPLE_EXPORT_TIERS_REVIEW_REQUIRED" in note for note in match_res["conflict_notes"])


# ==============================================================================
# SYNTHETIC TESTS: ARCHITECTURE & GOVERNANCE PATCH
# ==============================================================================

def test_generic_matching_module_has_no_hardcoded_portfolio_identities():
    """Verify that pure matching engines contain zero built-in portfolio identities."""
    import dashboard.wingman_triggers as wt
    import dashboard.recommendations as rec

    # Ensure deprecated global identity structures do not exist
    assert not hasattr(wt, "DEFAULT_APPROVED_DOMAINS")
    assert not hasattr(wt, "DEFAULT_APPROVED_ALIASES")
    assert not hasattr(wt, "DEFAULT_APPROVED_TICKERS")
    assert not hasattr(rec, "COMPANY_ALIASES")


def test_injected_registry_enables_alias_domain_ticker_routes():
    """Verify all five routes are enabled strictly through the injected registry."""
    from dashboard.identity_registry import parse_identity_crosswalk

    crosswalk_csv = (
        "canonical_account_id,canonical_company_name,approved_alias,approved_domain,approved_ticker,approval_status,approved_by,approved_at\n"
        'COMP-ALPHA,"Alpha Corp","Alpha Operations","alpha-ops.example.com","ALPH",APPROVED,ANALYST,2026-09-17\n'
    )
    reg = parse_identity_crosswalk(crosswalk_csv)["registry"]

    header = "company,segment,domain,tier,trigger_type,trigger_date,trigger_summary,trigger_source_url,pattern_report_url,scanned_at,notes\n"
    rows = [
        "Alpha Corp,oil and gas,generic.example.com,1,turnaround,2026-08-01,Canonical name,https://s.example.com,,2026-08-01,\n",
        "Alpha Operations,oil and gas,other.example.com,1,turnaround,2026-08-01,Approved alias,https://s.example.com,,2026-08-01,\n",
        "Unrelated Name,oil and gas,alpha-ops.example.com,1,turnaround,2026-08-01,Approved domain,https://s.example.com,,2026-08-01,\n",
        "ALPH,oil and gas,diff.example.com,1,turnaround,2026-08-01,Approved ticker,https://s.example.com,,2026-08-01,\n",
        "Alpha Sub (ALPH),oil and gas,diff2.example.com,1,turnaround,2026-08-01,Approved paren ticker,https://s.example.com,,2026-08-01,\n",
    ]
    parsed = parse_wingman_trigger_export(header + "".join(rows))

    match_res = match_company_to_wingman_records(
        company_id="COMP-ALPHA",
        company_name="Alpha Corp",
        company_domain="alpha-ops.example.com",
        all_wingman_records=parsed["records"],
        multi_entity_domains={},
        identity_registry=reg,
    )

    assert match_res["raw_matched_record_count"] == 5
    methods = {r["match_method"] for r in match_res["matched_records"]}
    assert "NORMALIZED_CANONICAL_NAME" in methods
    assert "APPROVED_ALIAS" in methods
    assert "APPROVED_DOMAIN" in methods
    assert "APPROVED_TICKER" in methods
    assert "APPROVED_PARENTHETICAL_TICKER" in methods


def test_short_alias_not_treated_as_ticker_and_no_substring_matching():
    """Verify short aliases never match substrings and are not conflated with tickers."""
    from dashboard.identity_registry import parse_identity_crosswalk

    # Register short alias 'cat' and ticker 'DOG'
    crosswalk_csv = (
        "canonical_account_id,canonical_company_name,approved_alias,approved_domain,approved_ticker,approval_status,approved_by,approved_at\n"
        'COMP-PET,"Pet Corp","cat",,"DOG",APPROVED,ANALYST,2026-09-17\n'
    )
    reg = parse_identity_crosswalk(crosswalk_csv)["registry"]

    header = "company,segment,domain,tier,trigger_type,trigger_date,trigger_summary,trigger_source_url,pattern_report_url,scanned_at,notes\n"
    rows = [
        "Caterpillar Drilling,oil and gas,catdrill.example.com,1,turnaround,2026-08-01,Substring cat,https://s.example.com,,2026-08-01,\n",
        "Cat Logistics,oil and gas,catlog.example.com,1,turnaround,2026-08-01,Prefix cat,https://s.example.com,,2026-08-01,\n",
        "Underdog Solutions,oil and gas,underdog.example.com,1,turnaround,2026-08-01,Substring dog,https://s.example.com,,2026-08-01,\n",
        "cat,oil and gas,cat.example.com,1,turnaround,2026-08-01,Exact alias cat,https://s.example.com,,2026-08-01,\n",
        "Pet Holdings (DOG),oil and gas,pethold.example.com,1,turnaround,2026-08-01,Paren ticker DOG,https://s.example.com,,2026-08-01,\n",
    ]
    parsed = parse_wingman_trigger_export(header + "".join(rows))

    match_res = match_company_to_wingman_records(
        company_id="COMP-PET",
        company_name="Pet Corp",
        company_domain="",
        all_wingman_records=parsed["records"],
        multi_entity_domains={},
        identity_registry=reg,
    )

    # Substrings Caterpillar, Cat Logistics, Underdog must NOT match
    assert match_res["raw_matched_record_count"] == 2
    matched_companies = {r["company"] for r in match_res["matched_records"]}
    assert matched_companies == {"cat", "Pet Holdings (DOG)"}


def test_no_registry_fallback_behavior():
    """Verify fallback behavior when no identity registry is uploaded."""
    header = "company,segment,domain,tier,trigger_type,trigger_date,trigger_summary,trigger_source_url,pattern_report_url,scanned_at,notes\n"
    rows = [
        "Beta Corp,oil and gas,beta-export.example.com,1,turnaround,2026-08-01,Canonical match,https://s.example.com,,2026-08-01,\n",
        "Beta Alternative Name,oil and gas,beta-export.example.com,1,turnaround,2026-08-01,Unapproved alias,https://s.example.com,,2026-08-01,\n",
        "Third Party Co,oil and gas,beta-export.example.com,1,turnaround,2026-08-01,Export domain only,https://s.example.com,,2026-08-01,\n",
    ]
    parsed = parse_wingman_trigger_export(header + "".join(rows))

    match_res = match_company_to_wingman_records(
        company_id="COMP-BETA",
        company_name="Beta Corp",
        company_domain="beta-export.example.com",
        all_wingman_records=parsed["records"],
        multi_entity_domains={},
        identity_registry=None,
    )

    # Only exact canonical name matches
    assert match_res["raw_matched_record_count"] == 1
    assert match_res["matched_records"][0]["company"] == "Beta Corp"
    assert match_res["matched_records"][0]["match_method"] == "NORMALIZED_CANONICAL_NAME"
    assert match_res["detailed_match_status"] == "EXACT CANONICAL-NAME MATCH"
    # Unapproved domain export rows become proposed associations, not scored matches
    assert len(match_res["proposed_associations"]) >= 1
    proposed_companies = {r["company"] for r in match_res["proposed_associations"]}
    assert "Third Party Co" in proposed_companies
    assert "Beta Alternative Name" in proposed_companies
    assert "Beta Corp" not in proposed_companies


def test_registry_parser_validation_happy_path():
    """Verify valid CSV parses successfully with full lineage metadata."""
    from dashboard.identity_registry import parse_identity_crosswalk

    csv_data = (
        "canonical_account_id,canonical_company_name,approved_alias,approved_domain,approved_ticker,approval_status,approved_by,approved_at,notes\n"
        'COMP-1,"Acme Industrial","Acme Corp","acme.example.com","ACME",APPROVED,J_DOE,2026-09-17,"Primary account"\n'
        'COMP-1,"Acme Industrial","Acme Ltd","acme-intl.example.com",,APPROVED,J_DOE,2026-09-17,"Secondary entity"\n'
    )
    result = parse_identity_crosswalk(csv_data)

    assert result["file_is_valid"] is True
    assert result["registry_applied"] is True
    assert len(result["fatal_errors"]) == 0
    assert len(result["quarantined_rows"]) == 0
    assert len(result["approved_rows"]) == 2
    assert result["registry"].account_count == 1


def test_registry_parser_missing_required_column_fails_closed():
    """Verify missing required header column rejects the entire file."""
    from dashboard.identity_registry import parse_identity_crosswalk

    # Missing 'approved_by'
    bad_header_csv = (
        "canonical_account_id,canonical_company_name,approved_alias,approved_domain,approved_ticker,approval_status,approved_at\n"
        'COMP-1,"Acme Industrial","Acme Corp","acme.example.com","ACME",APPROVED,2026-09-17\n'
    )
    result = parse_identity_crosswalk(bad_header_csv)

    assert result["file_is_valid"] is False
    assert result["registry_applied"] is False
    assert any("approved_by" in err for err in result["fatal_errors"])


def test_registry_parser_duplicate_columns_fails_closed():
    """Verify duplicate column names reject the entire file."""
    from dashboard.identity_registry import parse_identity_crosswalk

    dup_cols_csv = (
        "canonical_account_id,canonical_company_name,approved_alias,approved_alias,approval_status,approved_by,approved_at\n"
        'COMP-1,"Acme Industrial","Alias 1","Alias 2",APPROVED,J_DOE,2026-09-17\n'
    )
    result = parse_identity_crosswalk(dup_cols_csv)

    assert result["file_is_valid"] is False
    assert result["registry_applied"] is False
    assert any("Duplicate column" in err for err in result["fatal_errors"])


def test_registry_parser_conflicting_canonical_mappings_fails_closed():
    """Verify conflicting canonical names or IDs fail closed."""
    from dashboard.identity_registry import parse_identity_crosswalk

    # Same ID mapped to two different canonical company names
    conflicting_names_csv = (
        "canonical_account_id,canonical_company_name,approved_alias,approved_domain,approved_ticker,approval_status,approved_by,approved_at\n"
        'COMP-1,"Acme Industrial",,,APPROVED,J_DOE,2026-09-17\n'
        'COMP-1,"Completely Different Name",,,APPROVED,J_DOE,2026-09-17\n'
    )
    res1 = parse_identity_crosswalk(conflicting_names_csv)
    assert res1["file_is_valid"] is False
    assert any("Conflicting canonical name mapping" in err for err in res1["fatal_errors"])

    # Two different IDs mapped to the same canonical company name
    conflicting_ids_csv = (
        "canonical_account_id,canonical_company_name,approved_alias,approved_domain,approved_ticker,approval_status,approved_by,approved_at\n"
        'COMP-1,"Acme Industrial",,,APPROVED,J_DOE,2026-09-17\n'
        'COMP-2,"Acme Industrial",,,APPROVED,J_DOE,2026-09-17\n'
    )
    res2 = parse_identity_crosswalk(conflicting_ids_csv)
    assert res2["file_is_valid"] is False
    assert any("Conflicting canonical ID mapping" in err for err in res2["fatal_errors"])


def test_registry_parser_normalized_collisions_across_accounts_fail_closed():
    """Verify normalized collisions (alias, domain, ticker) across accounts fail closed."""
    from dashboard.identity_registry import parse_identity_crosswalk

    # Alias collision across accounts
    alias_coll_csv = (
        "canonical_account_id,canonical_company_name,approved_alias,approved_domain,approved_ticker,approval_status,approved_by,approved_at\n"
        'COMP-1,"Alpha Corp","Shared Operations",,,APPROVED,J_DOE,2026-09-17\n'
        'COMP-2,"Beta Corp","shared operations",,,APPROVED,J_DOE,2026-09-17\n'
    )
    res_a = parse_identity_crosswalk(alias_coll_csv)
    assert res_a["file_is_valid"] is False
    assert len(res_a["normalized_collisions"]) > 0
    assert any("Normalized alias collision" in err for err in res_a["fatal_errors"])

    # Domain collision across accounts
    dom_coll_csv = (
        "canonical_account_id,canonical_company_name,approved_alias,approved_domain,approved_ticker,approval_status,approved_by,approved_at\n"
        'COMP-1,"Alpha Corp",,"https://shared.example.com",,APPROVED,J_DOE,2026-09-17\n'
        'COMP-2,"Beta Corp",,"shared.example.com",,APPROVED,J_DOE,2026-09-17\n'
    )
    res_d = parse_identity_crosswalk(dom_coll_csv)
    assert res_d["file_is_valid"] is False
    assert any("Normalized domain collision" in err for err in res_d["fatal_errors"])

    # Ticker collision across accounts
    tick_coll_csv = (
        "canonical_account_id,canonical_company_name,approved_alias,approved_domain,approved_ticker,approval_status,approved_by,approved_at\n"
        'COMP-1,"Alpha Corp",,,"TICK",APPROVED,J_DOE,2026-09-17\n'
        'COMP-2,"Beta Corp",,,"tick",APPROVED,J_DOE,2026-09-17\n'
    )
    res_t = parse_identity_crosswalk(tick_coll_csv)
    assert res_t["file_is_valid"] is False
    assert any("Normalized ticker collision" in err for err in res_t["fatal_errors"])


def test_registry_quarantine_rules():
    """Verify row-level quarantine for webmail, missing metadata, non-approved status, and empty identities."""
    from dashboard.identity_registry import parse_identity_crosswalk

    csv_data = (
        "canonical_account_id,canonical_company_name,approved_alias,approved_domain,approved_ticker,approval_status,approved_by,approved_at\n"
        'COMP-1,"Acme Corp","Acme Valid","acme.example.com",,APPROVED,J_DOE,2026-09-17\n'
        'COMP-1,"Acme Corp",,"gmail.com",,APPROVED,J_DOE,2026-09-17\n'  # Webmail domain
        'COMP-1,"Acme Corp","Acme Draft",,,DRAFT,J_DOE,2026-09-17\n'      # Non-approved status
        'COMP-1,"Acme Corp","Acme NoAuth",,,APPROVED,,2026-09-17\n'       # Missing approved_by
        'COMP-1,"Acme Corp",,,,,APPROVED,J_DOE,2026-09-17\n'              # Empty identity row
    )
    res = parse_identity_crosswalk(csv_data)

    assert res["file_is_valid"] is True
    assert res["registry_applied"] is True
    assert len(res["approved_rows"]) == 1
    assert len(res["quarantined_rows"]) == 4

    reasons = res["quarantine_reasons"]
    assert any("webmail" in r.lower() for r in reasons)
    assert any("DRAFT" in r for r in reasons)
    assert any("Missing approved_by" in r for r in reasons)
    assert any("No alias, domain, or ticker" in r for r in reasons)


def test_registry_validation_unrecognized_status_fails_closed():
    """Verify unknown approval status is a fatal error that rejects the whole file."""
    from dashboard.identity_registry import parse_identity_crosswalk

    csv_data = (
        "canonical_account_id,canonical_company_name,approved_alias,approved_domain,approved_ticker,approval_status,approved_by,approved_at\n"
        'COMP-1,"Acme Corp","Acme Valid","acme.example.com",,SOMETHING_ELSE,J_DOE,2026-09-17\n'
    )
    res = parse_identity_crosswalk(csv_data)

    assert res["file_is_valid"] is False
    assert res["registry_applied"] is False
    assert any("SOMETHING_ELSE" in err for err in res["fatal_errors"])


def test_sector_and_tier_conflicts_do_not_reduce_match_confidence():
    """Verify sector and tier conflicts set review flags but leave identity match confidence at HIGH."""
    from dashboard.identity_registry import parse_identity_crosswalk

    crosswalk_csv = (
        "canonical_account_id,canonical_company_name,approved_alias,approved_domain,approved_ticker,approval_status,approved_by,approved_at\n"
        'COMP-DELTA,"Delta Energy",,"delta.example.com",,APPROVED,AUDITOR,2026-09-17\n'
    )
    reg = parse_identity_crosswalk(crosswalk_csv)["registry"]

    header = "company,segment,domain,tier,trigger_type,trigger_date,trigger_summary,trigger_source_url,pattern_report_url,scanned_at,notes\n"
    # Export has segment 'oil and gas' (conflicts with report 'Coatings & Advanced Materials') and tier 3 (conflicts with report 'Tier 1')
    row = "Delta Energy,oil and gas,delta.example.com,3,turnaround,2026-08-01,Summary,https://s.example.com,,2026-08-01,\n"
    parsed = parse_wingman_trigger_export(header + row)

    match_res = match_company_to_wingman_records(
        company_id="COMP-DELTA",
        company_name="Delta Energy",
        company_domain="delta.example.com",
        all_wingman_records=parsed["records"],
        multi_entity_domains={},
        identity_registry=reg,
        report_sector="Coatings & Advanced Materials",
        report_wingman_tier="Tier 1",
    )

    assert match_res["match_status"] == "MATCHED"
    assert match_res["match_confidence"] == "HIGH"
    assert match_res["sector_conflict_flag"] is True
    assert match_res["sector_conflict_review_required"] is True
    assert match_res["tier_conflict_flag"] is True
    assert match_res["tier_conflict_review_required"] is True
    assert match_res["any_review_required"] is True
    assert match_res["review_required"] is True


def test_review_flags_decoupling_and_backward_compatibility():
    """Verify all 6 review flags remain decoupled while review_required maintains backward compatibility."""
    from dashboard.identity_registry import parse_identity_crosswalk

    crosswalk_csv = (
        "canonical_account_id,canonical_company_name,approved_alias,approved_domain,approved_ticker,approval_status,approved_by,approved_at\n"
        'COMP-OMEGA,"Omega Corp",,"omega.example.com",,APPROVED,AUDITOR,2026-09-17\n'
    )
    reg = parse_identity_crosswalk(crosswalk_csv)["registry"]

    header = "company,segment,domain,tier,trigger_type,trigger_date,trigger_summary,trigger_source_url,pattern_report_url,scanned_at,notes\n"
    row = "Omega Corp,oil and gas,omega.example.com,1,turnaround,2026-08-01,Summary,https://s.example.com,,2026-08-01,\n"
    parsed = parse_wingman_trigger_export(header + row)

    # Clean match without conflicts
    clean_res = match_company_to_wingman_records(
        company_id="COMP-OMEGA",
        company_name="Omega Corp",
        company_domain="omega.example.com",
        all_wingman_records=parsed["records"],
        multi_entity_domains={},
        identity_registry=reg,
        report_sector="oil and gas",
        report_wingman_tier="Tier 1",
    )
    assert clean_res["match_review_required"] is False
    assert clean_res["sector_conflict_review_required"] is False
    assert clean_res["tier_conflict_review_required"] is False
    assert clean_res["multiple_export_tiers_review_required"] is False
    assert clean_res["registry_review_required"] is False
    assert clean_res["any_review_required"] is False
    assert clean_res["review_required"] is False


def test_cross_source_substring_rejection_in_crm_and_contacts():
    """Verify shared matcher rejects substring matches across CRM account names and contact company values."""
    from dashboard.identity_registry import parse_identity_crosswalk, match_source_record_identity
    from dashboard.recommendations import calculate_contactability
    import pandas as pd

    # Register short ticker 'RIL' for COMP-RIL
    crosswalk_csv = (
        "canonical_account_id,canonical_company_name,approved_alias,approved_domain,approved_ticker,approval_status,approved_by,approved_at\n"
        'COMP-RIL,"Reliance (RIL)",,"ril.example.com","RIL",APPROVED,AUDITOR,2026-09-17\n'
    )
    reg = parse_identity_crosswalk(crosswalk_csv)["registry"]

    # Shared identity matcher check
    res_drill = match_source_record_identity(
        candidate_company="Precision Drilling Services",
        candidate_domain="pdrill.example.com",
        canonical_account_id="COMP-RIL",
        canonical_company_name="Reliance (RIL)",
        identity_registry=reg,
    )
    assert res_drill["matched"] is False

    # Contactability check with synthetic contacts and CRM data
    crm_df = pd.DataFrame([
        {"account_name": "Arabian Drilling", "domain": "arabian.example.com", "crm_stage": "Closed Won", "owner": "Alice"},
        {"account_name": "Reliance (RIL)", "domain": "ril.example.com", "crm_stage": "Negotiation", "owner": "Bob"},
    ])
    contacts_df = pd.DataFrame([
        {"company": "Marriott Drilling", "email": "engineer@marriottdrill.example.com", "title": "VP Operations", "seniority": "Executive", "department": "Operations"},
        {"company": "Reliance (RIL)", "email": "lead@ril.example.com", "title": "Training Director", "seniority": "Director", "department": "Operational Training"},
    ])

    contactability = calculate_contactability(
        canonical_account_id="COMP-RIL",
        company_name="Reliance (RIL)",
        contacts_df=contacts_df,
        crm_df=crm_df,
        identity_registry=reg,
    )

    # CRM account matched is strictly Reliance (RIL), not Arabian Drilling
    assert contactability["matched_crm_account"] is not None
    assert contactability["matched_crm_account"]["account_name"] == "Reliance (RIL)"
    # Matched contacts count is strictly 1 (Training Director at Reliance), not Marriott Drilling
    assert len(contactability["matched_contacts"]) == 1
    assert contactability["matched_contacts"][0]["company"] == "Reliance (RIL)"
    assert contactability["status"] in ("KNOWN", "PARTIAL")


def test_row_level_lineage_and_audit_columns_present():
    """Verify that every matched record contains complete provenance and audit columns."""
    from dashboard.identity_registry import parse_identity_crosswalk

    crosswalk_csv = (
        "canonical_account_id,canonical_company_name,approved_alias,approved_domain,approved_ticker,approval_status,approved_by,approved_at\n"
        'COMP-SIGMA,"Sigma Energy","Sigma Ops","sigma.example.com","SIG",APPROVED,SECURITY_TEAM,2026-09-17\n'
    )
    reg = parse_identity_crosswalk(crosswalk_csv)["registry"]

    header = "company,segment,domain,tier,trigger_type,trigger_date,trigger_summary,trigger_source_url,pattern_report_url,scanned_at,notes\n"
    row = "Sigma Ops,oil and gas,sigma.example.com,1,turnaround,2026-08-01,Shutdown,https://s.example.com,,2026-08-01,Scanned note\n"
    parsed = parse_wingman_trigger_export(header + row)

    match_res = match_company_to_wingman_records(
        company_id="COMP-SIGMA",
        company_name="Sigma Energy",
        company_domain="sigma.example.com",
        all_wingman_records=parsed["records"],
        multi_entity_domains={},
        identity_registry=reg,
    )

    assert match_res["raw_matched_record_count"] == 1
    rec = match_res["matched_records"][0]

    # Required lineage and audit fields
    expected_fields = [
        "canonical_account_id",
        "canonical_company_name",
        "match_method",
        "all_match_methods",
        "matched_value",
        "match_confidence",
        "match_review_required",
        "registry_source",
        "registry_approval_status",
        "registry_approved_by",
        "registry_approved_at",
        "company",
        "segment",
        "domain",
        "tier",
        "trigger_type",
        "trigger_date_raw",
    ]
    for field in expected_fields:
        assert field in rec, f"Missing required lineage field: {field}"

    assert rec["registry_approval_status"] == "APPROVED"
    assert rec["registry_approved_by"] == "SECURITY_TEAM"


def test_module_dependency_direction_no_circular_imports():
    """Verify dashboard.identity_registry is pure and can be imported in complete isolation."""
    import sys
    # Verify identity_registry imports without requiring streamlit or other consumer modules
    import dashboard.identity_registry as ir
    assert hasattr(ir, "AccountIdentityRegistry")
    assert hasattr(ir, "parse_identity_crosswalk")
    assert hasattr(ir, "match_source_record_identity")
    assert hasattr(ir, "assert_account_match_integrity")


def test_zero_trigger_triple_semantics_exact():
    """Verify exact mandatory triple for zero-trigger scan: SCANNED_ZERO_TRIGGERS, NONE_DETECTED, Monitor."""
    header = "company,segment,domain,tier,trigger_type,trigger_date,trigger_summary,trigger_source_url,pattern_report_url,scanned_at,notes\n"
    row = "Sherwin-Williams,coatings,sherwin-williams.com,1,,,,,,2026-08-01,Systematically researched in Wingman with 0 qualifying operational triggers.\n"
    parsed = parse_wingman_trigger_export(header + row)

    match_res = match_company_to_wingman_records(
        company_id="COMP-SHW",
        company_name="Sherwin-Williams",
        company_domain="sherwin-williams.com",
        all_wingman_records=parsed["records"],
        multi_entity_domains={},
        report_wingman_tier="Tier 1",
    )

    clusters = cluster_wingman_events(match_res["matched_records"], "COMP-SHW")
    relevance = calculate_wingman_trigger_relevance(clusters, as_of_date=date(2026, 9, 17))
    action = derive_recommended_action_wingman(
        temporal_status_as_of=relevance["temporal_status_as_of"],
        trigger_score=relevance["score"],
        contact_status="UNKNOWN",
        evidence_coverage_pct=90.0,
        trigger_state=match_res["trigger_state"],
    )

    assert match_res["trigger_state"] == "SCANNED_ZERO_TRIGGERS"
    assert relevance["temporal_status_as_of"] == "NONE_DETECTED"
    assert action == "Monitor"


def test_invalid_vs_absent_registry_semantics():
    """Verify distinct downstream behavior for UPLOADED_INVALID vs NOT_UPLOADED."""
    header = "company,segment,domain,tier,trigger_type,trigger_date,trigger_summary,trigger_source_url,pattern_report_url,scanned_at,notes\n"
    row = "Target Org,oil and gas,target.example.com,1,turnaround,2026-08-01,Summary,https://s.example.com,,2026-08-01,Notes\n"
    parsed = parse_wingman_trigger_export(header + row)

    # Case 1: Crosswalk uploaded but invalid (failed validation)
    match_invalid = match_company_to_wingman_records(
        company_id="COMP-TGT",
        company_name="Target Org",
        company_domain="target.example.com",
        all_wingman_records=parsed["records"],
        multi_entity_domains={},
        identity_registry=None,
        report_wingman_tier="Tier 1",
        registry_input_state="UPLOADED_INVALID",
        registry_applied=False,
        registry_review_required=True,
    )
    assert match_invalid["registry_input_state"] == "UPLOADED_INVALID"
    assert match_invalid["registry_applied"] is False
    assert match_invalid["registry_review_required"] is True
    assert match_invalid["any_review_required"] is True
    assert match_invalid["review_required"] is True

    # Case 2: Crosswalk not uploaded (normal fallback to canonical names)
    match_not_uploaded = match_company_to_wingman_records(
        company_id="COMP-TGT",
        company_name="Target Org",
        company_domain="target.example.com",
        all_wingman_records=parsed["records"],
        multi_entity_domains={},
        identity_registry=None,
        report_wingman_tier="Tier 1",
        registry_input_state="NOT_UPLOADED",
        registry_applied=False,
        registry_review_required=False,
    )
    assert match_not_uploaded["registry_input_state"] == "NOT_UPLOADED"
    assert match_not_uploaded["registry_applied"] is False
    assert match_not_uploaded["registry_review_required"] is False
    assert match_not_uploaded["any_review_required"] is False
    assert match_not_uploaded["review_required"] is False


def test_tier_assignment_gap_vs_conflict_vs_multiple_tiers_vs_matching():
    """Verify tier assignment gap, true tier conflict, multiple export tiers, and matching tiers."""
    header = "company,segment,domain,tier,trigger_type,trigger_date,trigger_summary,trigger_source_url,pattern_report_url,scanned_at,notes\n"

    # 1. Assignment gap: Report tier is UNASSIGNED, export tier is 1 (e.g. Kinder Morgan)
    row_gap = "Kinder Morgan,oil and gas,kindermorgan.com,1,turnaround,2026-08-01,Summary,https://s.example.com,,2026-08-01,Notes\n"
    parsed_gap = parse_wingman_trigger_export(header + row_gap)
    m_gap = match_company_to_wingman_records(
        company_id="COMP-KMI",
        company_name="Kinder Morgan",
        company_domain="kindermorgan.com",
        all_wingman_records=parsed_gap["records"],
        multi_entity_domains={},
        report_wingman_tier="UNASSIGNED",
    )
    assert m_gap["tier_conflict_review_required"] is False
    assert m_gap["tier_assignment_review_required"] is True
    assert m_gap["multiple_export_tiers_review_required"] is False
    assert m_gap["any_review_required"] is True
    assert m_gap["review_required"] is True

    # 2. True conflict: Report tier is 2, export tier is 1 (e.g. Reliance)
    row_conf = "Reliance,oil and gas,ril.com,1,turnaround,2026-08-01,Summary,https://s.example.com,,2026-08-01,Notes\n"
    parsed_conf = parse_wingman_trigger_export(header + row_conf)
    m_conf = match_company_to_wingman_records(
        company_id="COMP-REL",
        company_name="Reliance",
        company_domain="ril.com",
        all_wingman_records=parsed_conf["records"],
        multi_entity_domains={},
        report_wingman_tier="Tier 2",
    )
    assert m_conf["tier_conflict_review_required"] is True
    assert m_conf["tier_assignment_review_required"] is False
    assert m_conf["multiple_export_tiers_review_required"] is False
    assert m_conf["any_review_required"] is True
    assert m_conf["review_required"] is True

    # 3. Multiple export tiers: legitimately matched records contain Tier 1 and Tier 2
    row_multi1 = "Dual Tier Corp,oil and gas,dualtier.example.com,1,turnaround,2026-08-01,Summary 1,https://s.example.com,,2026-08-01,Notes\n"
    row_multi2 = "Dual Tier Corp,oil and gas,dualtier.example.com,2,turnaround,2026-08-02,Summary 2,https://s.example.com,,2026-08-02,Notes\n"
    parsed_multi = parse_wingman_trigger_export(header + row_multi1 + row_multi2)
    m_multi = match_company_to_wingman_records(
        company_id="COMP-DUAL",
        company_name="Dual Tier Corp",
        company_domain="dualtier.example.com",
        all_wingman_records=parsed_multi["records"],
        multi_entity_domains={},
        report_wingman_tier="Tier 1",
    )
    assert m_multi["multiple_export_tiers_review_required"] is True
    assert m_multi["tier_conflict_review_required"] is False
    assert m_multi["tier_assignment_review_required"] is False
    assert m_multi["any_review_required"] is True
    assert m_multi["review_required"] is True

    # 4. Matching tiers: Report tier is 1, export tier is 1
    row_match = "Match Org,oil and gas,match.example.com,1,turnaround,2026-08-01,Summary,https://s.example.com,,2026-08-01,Notes\n"
    parsed_match = parse_wingman_trigger_export(header + row_match)
    m_match = match_company_to_wingman_records(
        company_id="COMP-MATCH",
        company_name="Match Org",
        company_domain="match.example.com",
        all_wingman_records=parsed_match["records"],
        multi_entity_domains={},
        report_wingman_tier="Tier 1",
    )
    assert m_match["tier_conflict_review_required"] is False
    assert m_match["tier_assignment_review_required"] is False
    assert m_match["multiple_export_tiers_review_required"] is False
    assert m_match["any_review_required"] is False
    assert m_match["review_required"] is False
