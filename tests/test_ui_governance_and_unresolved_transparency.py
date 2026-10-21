"""
Targeted Regression Test Suite:
1. Production Governance & Admin Enrichment Override Gating
2. Unresolved-Contact Transparency (Safe Role Found & Weak Matches Expander)
3. Seed Taxonomy Clarity (Unverified vs Verified Industry Labeling)
"""

import importlib
import json
import os
import pytest
import unittest.mock as mock
import pandas as pd
from dashboard.contact_research import (
    build_contact_card_html,
    build_weak_contact_card_html,
    render_contact_card,
)

cb_mod = importlib.import_module("dashboard.pages.11_company_browser")
format_segment_taxonomy = cb_mod.format_segment_taxonomy


def test_role_found_person_unresolved_never_shows_named_primary():
    """
    Acceptance Criterion:
    'Role Found — Person Unresolved' must NEVER render a named primary contact card.
    """
    payload = {
        "company_name": "Baker Hughes",
        "contact_research_status": "Role Found — Person Unresolved",
        "primary_contact": None,
        "ideal_role": "Chief Learning Officer (or equivalent senior L&D leader) at Baker Hughes",
        "decision_reason": "Identified ideal role, but no qualifying named person could be resolved in accumulated evidence.",
        "is_weak_match": False,
        "weak_matches": [],
    }

    card_html = build_contact_card_html(payload)
    assert "Role Found — Person Unresolved" in card_html
    assert "No verified individual contact was resolved for this account." in card_html
    assert "Chief Learning Officer" in card_html
    assert "Jose Fernandez" not in card_html


def test_weak_matches_expander_renders_subdued_card_with_mandatory_warning():
    """
    Acceptance Criterion:
    When candidates exist for an unresolved outcome, render collapsed 'Weak matches (unconfirmed)'
    expander with:
    - Candidate name, title, source links, employment qualifier
    - Clear warning: 'Unconfirmed — do not use for outreach without independent verification.'
    - No positive badges, no primary styling, no CTA buttons.
    """
    cand = {
        "name": "Jose Fernandez",
        "title": "Chief Learning Officer (CLO)",
        "contact_category": "Primary / Direct Training Leadership",
        "icp_level": "Primary",
        "evidence_confidence": "Low",
        "current_employment_status": "Probable",
        "employment_status_note": "Listed on undated aggregator directory without independent corporate corroboration.",
        "evidence_urls": [
            "https://www.comparably.com/companies/baker-hughes/jose-fernandez-26869"
        ],
        "why_selected": "CLO title on Comparably directory.",
        "employment_freshness_status": "Employment Unconfirmed",
        "match_quality": "Best Available Weak Match",
    }
    payload = {
        "company_name": "Baker Hughes",
        "contact_research_status": "Role Found — Person Unresolved",
        "primary_contact": None,
        "ideal_role": "Chief Learning Officer",
        "is_weak_match": True,
        "weak_matches": [cand],
    }

    # 1. Inspect weak candidate card HTML
    weak_card_html = build_weak_contact_card_html(cand)
    assert "Jose Fernandez" in weak_card_html
    assert "Chief Learning Officer (CLO)" in weak_card_html
    assert "Source Links:" in weak_card_html
    assert "https://www.comparably.com/companies/baker-hughes/jose-fernandez-26869" in weak_card_html
    assert "Employment Qualifier:" in weak_card_html
    assert "Listed on undated aggregator directory" in weak_card_html
    assert "⚠️ Unconfirmed — do not use for outreach without independent verification." in weak_card_html

    # Ensure no positive green badges or primary styling
    assert "#dcfce7" not in weak_card_html
    assert "🟢" not in weak_card_html
    assert "button" not in weak_card_html.lower()

    # 2. Inspect render_contact_card Streamlit expander
    with mock.patch("streamlit.markdown") as mock_md, \
         mock.patch("streamlit.expander") as mock_expander, \
         mock.patch("streamlit.warning") as mock_warning:

        render_contact_card(payload)

        # Expander called with exact title and collapsed by default
        mock_expander.assert_called_once_with("🔍 Weak matches (unconfirmed) (1)", expanded=False)

        # Warning rendered
        mock_warning.assert_called_once()
        warn_text = mock_warning.call_args[0][0]
        assert "Unconfirmed — do not use for outreach without independent verification." in warn_text


def test_weak_matches_expander_suppressed_when_no_candidates_exist():
    """
    Acceptance Criterion:
    When no candidate records exist in an unresolved result, the 'Weak matches (unconfirmed)'
    expander must NOT be rendered.
    """
    payload = {
        "company_name": "Acme Industrial",
        "contact_research_status": "Role Found — Person Unresolved",
        "primary_contact": None,
        "ideal_role": "VP Operations & Safety",
        "is_weak_match": False,
        "weak_matches": [],
        "candidates": [],
        "alternative_contacts": [],
    }

    with mock.patch("streamlit.markdown") as mock_md, \
         mock.patch("streamlit.expander") as mock_expander, \
         mock.patch("streamlit.warning") as mock_warning:

        render_contact_card(payload)

        # Verify no weak matches expander was rendered
        for call in mock_expander.call_args_list:
            arg = str(call[0][0])
            assert "Weak matches" not in arg
            assert "Weak Matches" not in arg

        mock_warning.assert_not_called()


def test_seed_taxonomy_clarity_labeling():
    """
    Acceptance Criterion:
    Where a seed industry/segment conflicts with the resolved company profile or remains unverified,
    label it as 'Seed segment (unverified): [value]' or 'Industry unconfirmed'.
    """
    # 1. Unverified account with seed segment (e.g., Hawkins NZ)
    hawkins_row = pd.Series({
        "company_name": "Hawkins",
        "segment": "Oil & Gas",
        "domain": "hawkins.co.nz",
    })
    label_hawkins = format_segment_taxonomy(hawkins_row, prov_dict={}, enr_status="not_started")
    assert label_hawkins == "Seed segment (unverified): Oil & Gas"

    # 2. Generic unverified account (e.g., West Group Brazil)
    west_group_row = pd.Series({
        "company_name": "West Group",
        "segment": "Diversified Industrial / Unspecified",
        "domain": "westgroup.com.br",
    })
    label_west = format_segment_taxonomy(west_group_row, prov_dict={}, enr_status="not_started")
    assert label_west == "Industry unconfirmed"

    # 3. Account with empty segment
    empty_row = pd.Series({
        "company_name": "Unknown Corp",
        "segment": "",
        "domain": "unknowncorp.com",
    })
    label_empty = format_segment_taxonomy(empty_row, prov_dict={}, enr_status="not_started")
    assert label_empty == "Industry unconfirmed"

    # 4. Verified complete enrichment with SIC description
    prov_complete = {
        "sic_description": {"value": "Oil and Gas Field Services, Not Elsewhere Classified"},
        "sic_code": {"value": "1389"},
    }
    baker_row = pd.Series({
        "company_name": "Baker Hughes",
        "segment": "Oil & Gas",
        "domain": "bakerhughes.com",
    })
    label_baker = format_segment_taxonomy(baker_row, prov_dict=prov_complete, enr_status="complete")
    assert "Statutory SIC: Oil and Gas Field Services, Not Elsewhere Classified" in label_baker
    assert "Seed segment: Oil & Gas" in label_baker


def test_audit_log_write_and_retention_in_environment(tmp_path):
    """
    Acceptance Criterion 1a:
    Verify the environment can write and retain audit_enrichment_overrides.jsonl.
    """
    verify_audit_log_writeable = cb_mod.verify_audit_log_writeable
    record_override_audit_event = cb_mod.record_override_audit_event

    # 1. Verify default production path in local_data/ is writeable in current environment
    prod_audit_path = "local_data/audit_enrichment_overrides.jsonl"
    existed_before = os.path.exists(prod_audit_path)
    ok_env, msg_env = verify_audit_log_writeable(prod_audit_path)
    assert ok_env is True
    assert "audit_enrichment_overrides.jsonl" in msg_env
    if not existed_before and os.path.exists(prod_audit_path) and os.path.getsize(prod_audit_path) == 0:
        os.remove(prod_audit_path)

    # 2. Verify full write + fsync + read-back retention in isolated file
    test_audit_file = str(tmp_path / "audit_enrichment_overrides.jsonl")
    sample_event = {
        "timestamp": "2026-10-12T22:00:00+00:00",
        "company_id": "comp_baker_hughes_test",
        "company_name": "Baker Hughes",
        "user_reviewer": "lead_reviewer_anas",
        "reason": "Targeted single-account verification check",
        "phase_hold_acknowledged": True,
        "outcome": "complete",
        "success": True,
        "error": None,
    }
    ok_rec, msg_rec = record_override_audit_event(sample_event, audit_path=test_audit_file)
    assert ok_rec is True
    assert os.path.exists(test_audit_file)

    with open(test_audit_file, "r", encoding="utf-8") as f:
        retained = [json.loads(line) for line in f if line.strip()]
    assert len(retained) == 1
    assert retained[0]["company_id"] == "comp_baker_hughes_test"
    assert retained[0]["user_reviewer"] == "lead_reviewer_anas"
    assert retained[0]["phase_hold_acknowledged"] is True


def test_audit_log_unavailable_or_readonly_surfaces_clear_failure_message(tmp_path):
    """
    Acceptance Criterion 1b:
    Verify clear failure message when audit path is unavailable or read-only.
    """
    import os
    verify_audit_log_writeable = cb_mod.verify_audit_log_writeable
    record_override_audit_event = cb_mod.record_override_audit_event

    # 1. Read-only file check
    ro_file = tmp_path / "readonly_audit.jsonl"
    ro_file.write_text("", encoding="utf-8")
    os.chmod(ro_file, 0o444)
    try:
        ok_ro, msg_ro = verify_audit_log_writeable(str(ro_file))
        assert ok_ro is False
        assert "read-only" in msg_ro.lower() or "permission" in msg_ro.lower()

        ok_rec, msg_rec = record_override_audit_event({"company_id": "x"}, audit_path=str(ro_file))
        assert ok_rec is False
        assert "read-only" in msg_rec.lower() or "permission" in msg_rec.lower()
    finally:
        os.chmod(ro_file, 0o644)

    # 2. Unavailable path (parent is a regular file, not a directory)
    blocking_file = tmp_path / "not_a_dir"
    blocking_file.write_text("file_blocks_subdir", encoding="utf-8")
    impossible_path = str(blocking_file / "audit_enrichment_overrides.jsonl")
    ok_unavail, msg_unavail = verify_audit_log_writeable(impossible_path)
    assert ok_unavail is False
    assert "unavailable or read-only" in msg_unavail.lower()


def test_audit_log_durability_fail_closed_in_cloud_environment(monkeypatch):
    """
    Acceptance Criterion:
    Verify fail-closed audit log durability gate in ephemeral cloud environments.
    - If in cloud environment and no external durable endpoint is configured, returns False.
    - If durable endpoint is configured, returns True and verifies remote dispatch.
    """
    verify_audit_log_writeable = cb_mod.verify_audit_log_writeable
    record_override_audit_event = cb_mod.record_override_audit_event

    # 1. Cloud environment without durable endpoint -> Fail-Closed
    monkeypatch.setenv("REQUIRE_DURABLE_AUDIT_LOG", "true")
    monkeypatch.delenv("AUDIT_LOG_ENDPOINT", raising=False)
    monkeypatch.delenv("ALLOW_LOCAL_AUDIT_FALLBACK", raising=False)

    ok, msg = verify_audit_log_writeable()
    assert ok is False
    assert "Durability Gate Failure" in msg
    assert "AUDIT_LOG_ENDPOINT" in msg

    ok_rec, msg_rec = record_override_audit_event({"company_id": "test"})
    assert ok_rec is False
    assert "Durability Gate Failure" in msg_rec

    # 2. Invalid endpoint format -> Fail-Closed
    monkeypatch.setenv("AUDIT_LOG_ENDPOINT", "ftp://invalid-scheme.com/audit")
    ok_inv, msg_inv = verify_audit_log_writeable()
    assert ok_inv is False
    assert "invalid" in msg_inv.lower()

    # 3. Valid endpoint configured -> Pass health check
    monkeypatch.setenv("AUDIT_LOG_ENDPOINT", "https://audit.compliance.eon.internal/v1/events")
    monkeypatch.setenv("AUDIT_LOG_TOKEN", "bearer_token_12345")
    ok_val, msg_val = verify_audit_log_writeable()
    assert ok_val is True
    assert "https://audit.compliance.eon.internal" in msg_val

    # 4. Mock remote endpoint response for record_override_audit_event
    with mock.patch("urllib.request.urlopen") as mock_urlopen:
        mock_resp = mock.MagicMock()
        mock_resp.status = 200
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        ok_disp, dest = record_override_audit_event({"company_id": "comp_test_123"})
        assert ok_disp is True
        assert dest == "https://audit.compliance.eon.internal/v1/events"
        mock_urlopen.assert_called_once()


def test_operator_override_safeguards_and_bypass_prevention(monkeypatch):
    """
    Acceptance Criterion 2:
    Confirm single trusted operator override enforces critical safety controls:
    - Rejects URL, query param, or session-state manipulation bypass.
    - Requires explicit HOLD acknowledgement, attributable Operator ID, and substantive justification.
    - Enforces configured OPERATOR_SAFEGUARD_KEY or ADMIN_OVERRIDE_KEY as safeguard.
    """
    verify_operator_override_authorization = cb_mod.verify_operator_override_authorization

    # 1. Reject URL / query-parameter override injection attempts
    for bad_qp in [
        {"override": "1"},
        {"admin": "true"},
        {"admin_override": "1"},
        {"operator_override": "1"},
        {"force_enrich": "true"},
        {"bypass_hold": "1"},
        {"execute_override": "true"},
    ]:
        ok, err = verify_operator_override_authorization(
            operator_id="operator_anas",
            reason="Targeted single-account entity audit",
            ack_hold=True,
            query_params=bad_qp,
            session_state={},
        )
        assert ok is False
        assert "query-parameter override bypass is prohibited" in err

    # 2. Reject session-state bypass manipulation
    for bad_ss in [
        {"bypass_admin_gate": True},
        {"bypass_operator_gate": True},
        {"force_override_exec": True},
        {"auto_execute_override": 1},
    ]:
        ok, err = verify_operator_override_authorization(
            operator_id="operator_anas",
            reason="Targeted single-account entity audit",
            ack_hold=True,
            query_params={},
            session_state=bad_ss,
        )
        assert ok is False
        assert "Session-state authorization bypass is prohibited" in err

    # 3. Reject missing or non-boolean HOLD acknowledgement
    for invalid_ack in [False, None, "true", 1, "1"]:
        ok, err = verify_operator_override_authorization(
            operator_id="operator_anas",
            reason="Targeted single-account entity audit",
            ack_hold=invalid_ack,
        )
        assert ok is False
        assert "Phase 5.1C remains on HOLD" in err

    # 4. Reject empty, short, or generic placeholder Operator IDs
    for bad_operator in ["", "  ", "ab", "admin", "user", "operator", "test", "anonymous", "guest", "bad id!"]:
        ok, err = verify_operator_override_authorization(
            operator_id=bad_operator,
            reason="Targeted single-account entity audit",
            ack_hold=True,
        )
        assert ok is False

    # 5. Reject missing or trivial justification reason
    for bad_reason in ["", "   ", "test", "fix now"]:
        ok, err = verify_operator_override_authorization(
            operator_id="operator_anas",
            reason=bad_reason,
            ack_hold=True,
        )
        assert ok is False
        assert "substantive justification" in err

    # 6. Enforce OPERATOR_SAFEGUARD_KEY (and backward-compatible ADMIN_OVERRIDE_KEY)
    monkeypatch.setenv("OPERATOR_SAFEGUARD_KEY", "sec_gov_token_998877")
    ok_missing_key, err_missing_key = verify_operator_override_authorization(
        operator_id="operator_anas",
        reason="Targeted single-account entity audit",
        ack_hold=True,
        operator_token="",
    )
    assert ok_missing_key is False
    assert "Operator Safeguard Key" in err_missing_key or "Admin Override Key" in err_missing_key

    ok_wrong_key, _ = verify_operator_override_authorization(
        operator_id="operator_anas",
        reason="Targeted single-account entity audit",
        ack_hold=True,
        operator_token="wrong_token",
    )
    assert ok_wrong_key is False

    ok_valid_key, msg_valid = verify_operator_override_authorization(
        operator_id="operator_anas",
        reason="Targeted single-account entity audit",
        ack_hold=True,
        operator_token="sec_gov_token_998877",
    )
    assert ok_valid_key is True
    assert msg_valid in ("Authorized", "Verified")

    # 7. Backward-compatibility alias check for verify_admin_authorization
    ok_alias, msg_alias = cb_mod.verify_admin_authorization(
        reviewer_id="operator_anas",
        reason="Targeted single-account entity audit",
        ack_hold=True,
        admin_token="sec_gov_token_998877",
    )
    assert ok_alias is True
    assert msg_alias in ("Authorized", "Verified")


def test_persistent_cache_vs_reverify_cache_busting(tmp_path):
    """
    Acceptance Criterion 3:
    Verify persistent caching vs. cache-busting:
    - Repeat views use disk cache (fast, cache_hit=True, mode='cached')
    - 'Re-Verify Current Employment' (force_refresh=True) invalidates cache and forces fresh evaluation.
    """
    from dashboard.contact_research import (
        PersistentContactResearchCacheProvider,
        execute_contact_research,
        set_cache_provider,
        get_cache_provider,
    )

    original_provider = get_cache_provider()
    cache_path = str(tmp_path / "test_cache_contact_research.json")
    try:
        provider1 = PersistentContactResearchCacheProvider(cache_file=cache_path)
        set_cache_provider(provider1)

        # 1. Initial execution populates memory + disk cache
        ok1, res1, err1 = execute_contact_research("Baker Hughes", force_refresh=False)
        assert ok1 is True
        assert os.path.exists(cache_path)
        assert res1["telemetry"]["cache_hit"] is False

        # 2. Simulate new session/worker reading from persistent disk cache
        provider2 = PersistentContactResearchCacheProvider(cache_file=cache_path)
        set_cache_provider(provider2)
        ok2, res2, err2 = execute_contact_research("Baker Hughes", force_refresh=False)
        assert ok2 is True
        assert res2["telemetry"]["cache_hit"] is True
        assert res2["telemetry"]["total_latency_ms"] <= 25

        # 3. Clicking 'Re-Verify Current Employment' (force_refresh=True) busts cache and re-evaluates
        ok3, res3, err3 = execute_contact_research("Baker Hughes", force_refresh=True)
        assert ok3 is True
        assert res3["telemetry"]["cache_hit"] is False
    finally:
        set_cache_provider(original_provider)


def test_live_smoke_hawkins_west_group_canonical_and_queue_invariants():
    """
    Acceptance Criteria 4 & 5:
    Verify against live database and portfolio:
    - Hawkins (hawkins.co.nz): safe display, unverified seed segment, 0 active signals, no accepted CIK 0000046250.
    - West Group (westgroup.com.br): safe display, industry unconfirmed, Business Model Review, no accepted CIK 0000105770.
    - Canonical valid companies (Baker Hughes CIK 0001701605, Chevron CIK 0000093410): statutory CIK preserved.
    - Strict invariant: 145 not_started accounts remain untouched (complete: 109, partial: 532, not_started: 145).
    """
    from dashboard.company_db import get_db_connection, get_company_field_provenance
    from dashboard.data_source import get_active_dataset

    ds = get_active_dataset()
    companies_df = ds["portfolio"]["companies_df"]

    with get_db_connection() as conn:
        cur = conn.cursor()

        # 1. Queue invariant check (Phase 5.1C strictly on HOLD)
        cur.execute(
            "SELECT enrichment_status, COUNT(*) FROM company_enrichment_status GROUP BY enrichment_status"
        )
        counts = dict(cur.fetchall())
        assert counts.get("not_started") == 145, f"Expected 145 not_started, got {counts}"
        assert counts.get("complete") == 109, f"Expected 109 complete, got {counts}"
        assert counts.get("partial") == 532, f"Expected 532 partial, got {counts}"

        # 2. Hawkins (hawkins.co.nz) check
        cur.execute(
            "SELECT c.company_id, c.company_name, c.domain, c.segment, s.enrichment_status "
            "FROM companies c JOIN company_enrichment_status s ON c.company_id = s.company_id "
            "WHERE c.company_name = 'Hawkins' AND c.domain = 'hawkins.co.nz'"
        )
        hawkins_db = cur.fetchone()
        assert hawkins_db is not None
        h_cid, h_name, h_dom, h_seg, h_status = hawkins_db
        assert h_status == "partial"
        h_prov = get_company_field_provenance(h_cid)
        assert h_prov.get("sec_cik", {}).get("value_status") == "unknown"
        assert h_prov.get("sec_cik", {}).get("value") is None
        assert h_prov.get("sic_description", {}).get("value") is None

        h_df_row = companies_df[companies_df["company_name"] == "Hawkins"].iloc[0]
        assert int(h_df_row["active_event_count"]) == 0
        assert format_segment_taxonomy(h_df_row, h_prov, h_status) == "Seed segment (unverified): Oil & Gas"

        # 3. West Group (westgroup.com.br) check
        cur.execute(
            "SELECT c.company_id, c.company_name, c.domain, c.segment, s.enrichment_status "
            "FROM companies c JOIN company_enrichment_status s ON c.company_id = s.company_id "
            "WHERE c.company_name = 'West Group' AND c.domain = 'westgroup.com.br'"
        )
        west_db = cur.fetchone()
        assert west_db is not None
        w_cid, w_name, w_dom, w_seg, w_status = west_db
        assert w_status == "partial"
        w_prov = get_company_field_provenance(w_cid)
        assert w_prov.get("sec_cik", {}).get("value_status") == "unknown"
        assert w_prov.get("sec_cik", {}).get("value") is None
        assert w_prov.get("sic_description", {}).get("value") is None

        w_df_row = companies_df[companies_df["company_name"] == "West Group"].iloc[0]
        assert w_df_row["current_status"] == "Business Model Review"
        assert format_segment_taxonomy(w_df_row, w_prov, w_status) == "Industry unconfirmed"

        # 4. Canonical valid companies (Baker Hughes & Chevron)
        cur.execute(
            "SELECT c.company_id, s.enrichment_status FROM companies c "
            "JOIN company_enrichment_status s ON c.company_id = s.company_id "
            "WHERE c.company_name = 'Baker Hughes'"
        )
        bh_cid, bh_status = cur.fetchone()
        assert bh_status == "complete"
        bh_prov = get_company_field_provenance(bh_cid)
        assert bh_prov.get("sec_cik", {}).get("value") == "0001701605"
        assert bh_prov.get("sec_cik", {}).get("value_status") == "exact"

        cur.execute(
            "SELECT c.company_id, s.enrichment_status FROM companies c "
            "JOIN company_enrichment_status s ON c.company_id = s.company_id "
            "WHERE c.company_name = 'Chevron'"
        )
        cvx_cid, cvx_status = cur.fetchone()
        assert cvx_status == "complete"
        cvx_prov = get_company_field_provenance(cvx_cid)
        assert cvx_prov.get("sec_cik", {}).get("value") == "0000093410"
        assert cvx_prov.get("sec_cik", {}).get("value_status") == "exact"


def test_contact_strictness_modes_behavior():
    """
    Acceptance Criteria for Presentation Readiness:
    1. Strict (Default):
       - Unconfirmed contacts (Baker Hughes / Jose Fernandez) suppressed from primary card.
       - Former employees (Saipem / Marco Rossi) suppressed from primary card.
       - Confirmed contacts (FMC / Sarah Jenkins) displayed in primary card.
    2. Balanced:
       - Unconfirmed current contact (Jose Fernandez) surfaced in primary card with explicit warning.
       - Former employees (Marco Rossi) remain suppressed from primary card.
       - Confirmed contacts (Sarah Jenkins) displayed in primary card.
    3. Broad:
       - Both unconfirmed current contacts (Jose Fernandez) and former employees (Marco Rossi)
         surfaced in primary card with explicit warning badges.
    """
    from dashboard.contact_research import (
        BAKER_HUGHES_BENCHMARK,
        SAIPEM_BENCHMARK,
        FMC_BENCHMARK,
    )

    # 1. Strict Mode
    bh_strict = build_contact_card_html(BAKER_HUGHES_BENCHMARK, strictness_mode="Strict (Default)")
    assert "Role Found — Person Unresolved" in bh_strict
    assert "⚠️ Enterprise Leadership Unresolved:" in bh_strict
    assert "Jose Fernandez" in bh_strict  # mentioned only in the unresolved explanation
    assert "Probable (Balanced Mode)" not in bh_strict

    saipem_strict = build_contact_card_html(SAIPEM_BENCHMARK, strictness_mode="Strict (Default)")
    assert "Role Found — Person Unresolved" in saipem_strict
    assert "Marco Rossi" in saipem_strict
    assert "Historical / Stale Lead (Broad Mode)" not in saipem_strict

    fmc_strict = build_contact_card_html(FMC_BENCHMARK, strictness_mode="Strict (Default)")
    assert "Verified Contact Found" in fmc_strict
    assert "Sarah Jenkins" in fmc_strict
    assert "🟢 Confirmed current" in fmc_strict

    # 2. Balanced Mode
    bh_balanced = build_contact_card_html(BAKER_HUGHES_BENCHMARK, strictness_mode="Balanced")
    assert "Probable (Balanced Mode)" in bh_balanced
    assert "Jose Fernandez" in bh_balanced
    assert "Chief Learning Officer (CLO)" in bh_balanced
    assert "⚪ Unconfirmed current" in bh_balanced
    assert "Weak third-party evidence" in bh_balanced
    assert "⚠️ Unconfirmed — do not use for outreach without independent verification." in bh_balanced

    saipem_balanced = build_contact_card_html(SAIPEM_BENCHMARK, strictness_mode="Balanced")
    assert "Role Found — Person Unresolved" in saipem_balanced
    assert "Former Employee Suppressed (Balanced Mode)" in saipem_balanced

    fmc_balanced = build_contact_card_html(FMC_BENCHMARK, strictness_mode="Balanced")
    assert "Verified Contact Found" in fmc_balanced
    assert "Sarah Jenkins" in fmc_balanced
    assert "🟢 Confirmed current" in fmc_balanced

    # 3. Broad Mode
    saipem_broad = build_contact_card_html(SAIPEM_BENCHMARK, strictness_mode="Broad")
    assert "Historical / Stale Lead (Broad Mode)" in saipem_broad
    assert "Marco Rossi" in saipem_broad
    assert "Technical Training Specialist" in saipem_broad
    assert "🔴 Former employee" in saipem_broad
    assert "⚠️ Contradictory / likely stale" in saipem_broad
    assert "⚠️ Stale / Former Employee — verify current status before any engagement." in saipem_broad

    bh_broad = build_contact_card_html(BAKER_HUGHES_BENCHMARK, strictness_mode="Broad")
    assert "Jose Fernandez" in bh_broad
    assert "⚪ Unconfirmed current" in bh_broad
    assert "Weak third-party evidence" in bh_broad

    # Also verify with "Broad (default)" label
    bh_broad_default = build_contact_card_html(BAKER_HUGHES_BENCHMARK, strictness_mode="Broad (default)")
    assert "Jose Fernandez" in bh_broad_default
    assert "⚪ Unconfirmed current" in bh_broad_default
    assert "Weak third-party evidence" in bh_broad_default

    saipem_broad_default = build_contact_card_html(SAIPEM_BENCHMARK, strictness_mode="Broad (default)")
    assert "Historical / Stale Lead (Broad Mode)" in saipem_broad_default
    assert "Marco Rossi" in saipem_broad_default
    assert "🔴 Former employee" in saipem_broad_default


def test_explicit_badges_for_weaker_contacts():
    """
    Acceptance Criteria:
    Required visible labels:
    - 🟢 Confirmed current
    - ⚪ Unconfirmed current
    - 🔴 Former employee
    - Weak third-party evidence
    - Contradictory / likely stale
    Never make weak contacts look equivalent to verified contacts.
    """
    from dashboard.contact_research import (
        classify_contact_evidence,
        build_weak_contact_card_html,
        SAIPEM_BENCHMARK,
        BAKER_HUGHES_BENCHMARK,
        FMC_BENCHMARK,
    )

    # 1. Confirmed current candidate
    fmc_cand = FMC_BENCHMARK["primary_contact"]
    fmc_meta = classify_contact_evidence(fmc_cand)
    assert fmc_meta["is_confirmed"] is True
    assert "🟢 Confirmed current" in fmc_meta["freshness_badge"]

    # 2. Unconfirmed current candidate
    bh_cand = BAKER_HUGHES_BENCHMARK["weak_matches"][0]
    bh_meta = classify_contact_evidence(bh_cand)
    assert bh_meta["is_unconfirmed"] is True
    assert "⚪ Unconfirmed current" in bh_meta["freshness_badge"]
    assert "Weak third-party evidence" in bh_meta["qualifier_badge"]

    bh_weak_html = build_weak_contact_card_html(bh_cand)
    assert "⚪ Unconfirmed current" in bh_weak_html
    assert "Weak third-party evidence" in bh_weak_html
    assert "⚠️ Unconfirmed — do not use for outreach without independent verification." in bh_weak_html
    assert "🟢" not in bh_weak_html

    # 3. Former employee candidate
    saipem_cand = SAIPEM_BENCHMARK["weak_matches"][0]
    saipem_meta = classify_contact_evidence(saipem_cand)
    assert saipem_meta["is_former"] is True
    assert "🔴 Former employee" in saipem_meta["freshness_badge"]
    assert "⚠️ Contradictory / likely stale" in saipem_meta["qualifier_badge"]

    saipem_weak_html = build_weak_contact_card_html(saipem_cand)
    assert "🔴 Former employee" in saipem_weak_html
    assert "⚠️ Contradictory / likely stale" in saipem_weak_html
    assert "⚠️ Stale / Former Employee — verify current status before any engagement." in saipem_weak_html
    assert "🟢" not in saipem_weak_html


def test_operator_feedback_friction_fixes():
    """
    Validates resolutions to 4 Operator Feedback items:
    1. Obvious row/name clicking with guidance banner and Open Dossier action column.
    2. Stateless 1-click Quick Inspect buttons & auto-clearing jump selectbox to eliminate state bounce.
    3. Statutory 'Unknown' disambiguation with historical claims and freshness policy explanations.
    4. Plain operational English labels (Your Name / Email, Lookup Reason, Authorize single-account lookup, Verified Commercial Intelligence).
    """
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file("dashboard/pages/11_company_browser.py")
    at.run()
    assert not at.exception

    # 1. Directory row guidance banner & footer
    markdown_texts = [m.value for m in at.markdown]
    assert any("Click any company name or row" in m for m in markdown_texts), "Guidance banner missing"
    assert any("Verified Commercial Intelligence" in m for m in markdown_texts), "Directory footer copy missing"

    # 2. Stateless 1-click Quick Inspect buttons
    assert at.button(key="btn_qi_0") is not None
    at.button(key="btn_qi_0").click().run()
    assert not at.exception
    assert at.session_state["browser_selected_company"] == "Baker Hughes"

    # 3. Statutory Key Indicators & Freshness policy explanations
    dossier_texts = [m.value for m in at.markdown]
    assert any("Current Statutory Filings & Disclosures" in m for m in dossier_texts), "Statutory indicators grid missing"
    assert any("No current verified value" in m for m in dossier_texts), "No current verified value missing for Baker Hughes"
    assert any("exceeds 3y freshness policy" in m for m in dossier_texts), "Freshness policy explanation missing"
    assert any("Verified Commercial Intelligence" in m for m in dossier_texts), "Dossier footer copy missing"

    # Historical claims must be collapsed by default in secondary reference expander
    hist_expanders = [exp for exp in at.expander if "Historical Reference Data" in exp.label]
    assert len(hist_expanders) > 0, "Historical Reference Data expander missing"
    assert hist_expanders[0].proto.expanded is False, "Historical Reference Data must be collapsed by default"

    # 4. Plain operational English labels
    inputs = {inp.label: inp for inp in at.text_input}
    assert "Your Name / Email" in inputs, "Your Name / Email missing"
    assert "Lookup Reason" in inputs, "Lookup Reason missing"

    checkboxes = {cb.label: cb for cb in at.checkbox}
    assert any("Authorize single-account SEC lookup and record to audit log" in lbl for lbl in checkboxes), "Plain auth checkbox missing"

    # 5. Clean Back navigation with zero bounce
    at.button(key="btn_close_dossier").click().run()
    assert not at.exception
    assert at.session_state["browser_selected_company"] == ""



