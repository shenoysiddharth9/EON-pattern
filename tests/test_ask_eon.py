"""
Unit & Integration Test Suite for Ask EON (Page 14):
1. Natural language intent parsing & company entity matching.
2. Multi-page Streamlit AppTest navigation & lifecycle.
3. Strictness adjustment (Broad, Balanced, Strict).
4. State-changing action confirmation safeguards (Add Company & Enrich Company).
5. Structured results workplace rendering.
"""

import importlib
import os
import pytest
import pandas as pd
from streamlit.testing.v1 import AppTest

ask_mod = importlib.import_module("dashboard.pages.14_ask_eon")
parse_ask_eon_intent = ask_mod.parse_ask_eon_intent
match_company_in_portfolio = ask_mod.match_company_in_portfolio
normalize_text = ask_mod.normalize_text


@pytest.fixture
def sample_companies_df():
    return pd.DataFrame([
        {
            "company_name": "Baker Hughes",
            "domain": "bakerhughes.com",
            "segment": "Oil & Gas",
            "current_status": "Research & Qualify Now",
            "distinct_category_count": 2,
        },
        {
            "company_name": "FMC Corporation",
            "domain": "fmc.com",
            "segment": "Chemicals",
            "current_status": "Ready for Outreach",
            "distinct_category_count": 0,
        },
        {
            "company_name": "Saipem",
            "domain": "saipem.com",
            "segment": "Energy Infrastructure",
            "current_status": "Monitor",
            "distinct_category_count": 1,
        },
        {
            "company_name": "Hawkins",
            "domain": "hawkins.co.nz",
            "segment": "Oil & Gas",
            "current_status": "Monitor",
            "distinct_category_count": 0,
        },
        {
            "company_name": "West Group",
            "domain": "westgroup.com.br",
            "segment": "Diversified Industrial",
            "current_status": "Business Model Review",
            "distinct_category_count": 1,
        },
    ])


# =============================================================================
# 1. INTENT PARSING & ENTITY MATCHING TESTS
# =============================================================================

def test_match_company_in_portfolio(sample_companies_df):
    """Verify robust matching across exact names, aliases, substrings, and domains."""
    # Exact & Case-insensitive
    assert match_company_in_portfolio("baker hughes", sample_companies_df) == "Baker Hughes"
    assert match_company_in_portfolio("BAKER HUGHES", sample_companies_df) == "Baker Hughes"
    assert match_company_in_portfolio("FMC Corporation", sample_companies_df) == "FMC Corporation"

    # Aliases
    assert match_company_in_portfolio("baker", sample_companies_df) == "Baker Hughes"
    assert match_company_in_portfolio("fmc", sample_companies_df) == "FMC Corporation"
    assert match_company_in_portfolio("saipem", sample_companies_df) == "Saipem"

    # Domains
    assert match_company_in_portfolio("bakerhughes.com", sample_companies_df) == "Baker Hughes"
    assert match_company_in_portfolio("hawkins.co.nz", sample_companies_df) == "Hawkins"
    assert match_company_in_portfolio("westgroup.com.br", sample_companies_df) == "West Group"

    # Unknown
    assert match_company_in_portfolio("Nonexistent Corp", sample_companies_df) is None


def test_parse_ask_eon_search_intent(sample_companies_df):
    """Verify natural-language search queries map to FIND_COMPANY."""
    p1 = parse_ask_eon_intent("Find Baker Hughes", "FMC Corporation", sample_companies_df)
    assert p1["action"] == "FIND_COMPANY"
    assert p1["company_name"] == "Baker Hughes"

    p2 = parse_ask_eon_intent("Search for FMC Corporation", "Baker Hughes", sample_companies_df)
    assert p2["action"] == "FIND_COMPANY"
    assert p2["company_name"] == "FMC Corporation"

    p3 = parse_ask_eon_intent("Tell me about Saipem", "Baker Hughes", sample_companies_df)
    assert p3["action"] == "FIND_COMPANY"
    assert p3["company_name"] == "Saipem"

    # Not found query
    p4 = parse_ask_eon_intent("Find Orbit Technologies", "Baker Hughes", sample_companies_df)
    assert p4["action"] == "NOT_FOUND"


def test_parse_ask_eon_contact_intent(sample_companies_df):
    """Verify contact lookups map to GET_CONTACTS."""
    # General contacts for currently selected company
    p1 = parse_ask_eon_intent("Show me contacts for this company", "Baker Hughes", sample_companies_df)
    assert p1["action"] == "GET_CONTACTS"
    assert p1["company_name"] == "Baker Hughes"

    p2 = parse_ask_eon_intent("Find contacts", "FMC Corporation", sample_companies_df)
    assert p2["action"] == "GET_CONTACTS"
    assert p2["company_name"] == "FMC Corporation"

    # Specific company named in query
    p3 = parse_ask_eon_intent("Who is the contact for Saipem?", "Baker Hughes", sample_companies_df)
    assert p3["action"] == "GET_CONTACTS"
    assert p3["company_name"] == "Saipem"


def test_parse_ask_eon_strictness_intent(sample_companies_df):
    """Verify strictness adjustments map to CHANGE_STRICTNESS with exact policy modes."""
    p1 = parse_ask_eon_intent("Be less strict", "Baker Hughes", sample_companies_df)
    assert p1["action"] == "CHANGE_STRICTNESS"
    assert p1["mode"] == "Broad (default)"

    p2 = parse_ask_eon_intent("Switch to balanced mode", "Baker Hughes", sample_companies_df)
    assert p2["action"] == "CHANGE_STRICTNESS"
    assert p2["mode"] == "Balanced"

    p3 = parse_ask_eon_intent("Strict mode only", "Baker Hughes", sample_companies_df)
    assert p3["action"] == "CHANGE_STRICTNESS"
    assert p3["mode"] == "Strict"


def test_parse_ask_eon_state_changing_intents(sample_companies_df):
    """Verify enrichment and add company queries map to confirmation triggers."""
    # Enrichment
    p1 = parse_ask_eon_intent("Enrich this company", "Baker Hughes", sample_companies_df)
    assert p1["action"] == "TRIGGER_ENRICH"
    assert p1["company_name"] == "Baker Hughes"

    p2 = parse_ask_eon_intent("Run statutory enrichment on Hawkins", "Baker Hughes", sample_companies_df)
    assert p2["action"] == "TRIGGER_ENRICH"
    assert p2["company_name"] == "Hawkins"

    # Add company
    p3 = parse_ask_eon_intent("Add company Apex Energy, domain apexenergy.com, segment Oil & Gas", "Baker Hughes", sample_companies_df)
    assert p3["action"] == "TRIGGER_ADD"
    assert "Apex Energy" in p3["company_name"]
    assert p3["domain"] == "apexenergy.com"
    assert p3["segment"] == "Oil & Gas"

    # Reset
    p4 = parse_ask_eon_intent("Clear chat", "Baker Hughes", sample_companies_df)
    assert p4["action"] == "RESET"


def test_parse_ask_eon_ranking_intent(sample_companies_df):
    """Verify ranking and list queries map to RANK_COMPANIES with parsed limits."""
    p1 = parse_ask_eon_intent("list 10 companies that should be contacted", "Baker Hughes", sample_companies_df)
    assert p1["action"] == "RANK_COMPANIES"
    assert p1["limit"] == 10

    p2 = parse_ask_eon_intent("companies to contact", "Baker Hughes", sample_companies_df)
    assert p2["action"] == "RANK_COMPANIES"

    p3 = parse_ask_eon_intent("show 5 top accounts to contact", "Baker Hughes", sample_companies_df)
    assert p3["action"] == "RANK_COMPANIES"
    assert p3["limit"] == 5

    p4 = parse_ask_eon_intent("what companies should we reach out to?", "Baker Hughes", sample_companies_df)
    assert p4["action"] == "RANK_COMPANIES"


def test_parse_ask_eon_alternative_contacts_intent(sample_companies_df):
    """Verify alternative / other contacts queries map to GET_ALTERNATIVE_CONTACTS."""
    p1 = parse_ask_eon_intent("are there other contacts?", "Baker Hughes", sample_companies_df)
    assert p1["action"] == "GET_ALTERNATIVE_CONTACTS"
    assert p1["company_name"] == "Baker Hughes"

    p2 = parse_ask_eon_intent("who else works at Saipem?", "Baker Hughes", sample_companies_df)
    assert p2["action"] == "GET_ALTERNATIVE_CONTACTS"
    assert p2["company_name"] == "Saipem"

    p3 = parse_ask_eon_intent("anyone else", "FMC Corporation", sample_companies_df)
    assert p3["action"] == "GET_ALTERNATIVE_CONTACTS"
    assert p3["company_name"] == "FMC Corporation"


def test_parse_ask_eon_unsupported_intent(sample_companies_df):
    """Verify out-of-scope prompts map to UNSUPPORTED for transparent limitation response."""
    p1 = parse_ask_eon_intent("what is the weather today?", "Baker Hughes", sample_companies_df)
    assert p1["action"] == "UNSUPPORTED"

    p2 = parse_ask_eon_intent("write a poem about cats", "Baker Hughes", sample_companies_df)
    assert p2["action"] == "UNSUPPORTED"


# =============================================================================
# 2. STREAMLIT APPTEST EXECUTION & PAGE RENDERING TESTS
# =============================================================================

def test_apptest_ask_eon_direct_page_render():
    """Verify direct AppTest execution of 14_ask_eon.py without exceptions."""
    at = AppTest.from_file("dashboard/pages/14_ask_eon.py", default_timeout=30)
    at.run()
    assert not at.exception, f"14_ask_eon.py crashed: {at.exception}"

    # Title assertion
    assert len(at.title) > 0
    assert "Ask EON" in at.title[0].value

    # Dominant input and lightweight prompt chips present
    assert len(at.chat_input) > 0
    # Example chips present on initial load
    button_labels = [b.label for b in at.button]
    assert any("Baker Hughes" in lbl for lbl in button_labels)


def test_apptest_multipage_journey_includes_ask_eon():
    """Verify complete multipage journey through app.py includes Ask EON."""
    at = AppTest.from_file("app.py", default_timeout=60).run()
    assert not at.exception

    # Default is Portfolio Insights
    assert "Portfolio Insights" in at.title[0].value

    # Switch to Ask EON
    at.switch_page("dashboard/pages/14_ask_eon.py").run()
    assert not at.exception
    assert "Ask EON" in at.title[0].value


def test_apptest_ask_eon_inline_company_and_contact_flow():
    """Verify conversational query execution and inline card rendering in AppTest."""
    at = AppTest.from_file("dashboard/pages/14_ask_eon.py", default_timeout=30).run()
    assert not at.exception

    # Send search query via chat_input
    at.chat_input[0].set_value("Find Baker Hughes").run()
    assert not at.exception

    page_text = " ".join([m.value for m in at.markdown])
    assert "Baker Hughes" in page_text
    assert "Oil & Gas" in page_text or "Why This Company Is Here" in page_text

    # Send contacts query via chat_input
    at.chat_input[0].set_value("Show me contacts for this company").run()
    assert not at.exception

    page_text_2 = " ".join([m.value for m in at.markdown])
    assert "Jose Fernandez" in page_text_2


def test_apptest_ask_eon_regenerate_flow():
    """Verify that clicking regenerate re-evaluates the latest turn."""
    at = AppTest.from_file("dashboard/pages/14_ask_eon.py", default_timeout=30).run()
    assert not at.exception

    # First turn
    at.chat_input[0].set_value("Find Baker Hughes").run()
    assert not at.exception
    assert any("Regenerate" in b.label for b in at.button)

    # Click regenerate button
    regen_btn = [b for b in at.button if "Regenerate" in b.label][0]
    regen_btn.click().run()
    assert not at.exception

    page_text = " ".join([m.value for m in at.markdown])
    assert "Baker Hughes" in page_text


def test_audit_durability_fail_closed_on_community_cloud(tmp_path, monkeypatch):
    """
    Verify strict fail-closed audit log durability on Community Cloud without external endpoint.
    """
    from dashboard.governance import verify_audit_log_writeable, record_override_audit_event

    test_audit_file = str(tmp_path / "test_audit.jsonl")
    monkeypatch.setenv("REQUIRE_DURABLE_AUDIT_LOG", "true")
    monkeypatch.delenv("AUDIT_LOG_ENDPOINT", raising=False)

    # 1. Cloud environment without AUDIT_LOG_ENDPOINT -> strictly fails closed
    ok_default, msg_default = verify_audit_log_writeable(test_audit_file)
    assert ok_default is False
    assert "Durability Gate Failure" in msg_default

    # 2. Record event in cloud environment without endpoint -> strictly fails closed
    sample_event = {
        "timestamp": "2026-10-14T20:00:00+00:00",
        "company_id": "comp_test_123",
        "company_name": "Baker Hughes",
        "operator_id": "operator_test",
        "reason": "Test enrichment override",
        "phase_hold_acknowledged": True,
        "outcome": "complete",
        "success": True,
    }
    rec_ok, rec_dest = record_override_audit_event(sample_event, test_audit_file)
    assert rec_ok is False
    assert "Durability Gate Failure" in rec_dest


def test_apptest_ask_eon_enrichment_confirmation_moment():
    """Verify that Ask EON enrichment trigger renders confirmation card and confirms cleanly."""
    at = AppTest.from_file("dashboard/pages/14_ask_eon.py", default_timeout=30).run()
    assert not at.exception

    # Prompt enrichment
    at.chat_input[0].set_value("Enrich Baker Hughes via SEC EDGAR").run()
    assert not at.exception

    page_text = " ".join([m.value for m in at.markdown])
    assert "Baker Hughes" in page_text

    # Verify confirmation button is rendered
    confirm_btns = [b for b in at.button if "confirm enrichment" in b.label.lower()]
    assert len(confirm_btns) > 0

    # Click confirm
    confirm_btns[0].click().run()
    assert not at.exception

    # Confirm message shows complete
    post_text = " ".join([m.value for m in at.markdown])
    assert "Statutory enrichment completed" in post_text or "CIK" in post_text or "Disclosures" in post_text


def test_apptest_ask_eon_ranking_flow():
    """Verify conversational company ranking returns structured prioritized list and inspect action."""
    at = AppTest.from_file("dashboard/pages/14_ask_eon.py", default_timeout=30).run()
    assert not at.exception

    at.chat_input[0].set_value("list 10 companies that should be contacted").run()
    assert not at.exception

    page_text = " ".join([m.value for m in at.markdown])
    assert "outreach priorities from the portfolio" in page_text
    assert "Kinder Morgan" in page_text or "CERONAV" in page_text

    # Inspect button should be rendered for top account
    inspect_btns = [b for b in at.button if "Inspect" in b.label]
    assert len(inspect_btns) > 0


def test_apptest_ask_eon_alternative_contacts_transparent_limitation():
    """Verify 'are there other contacts?' transparently states no additional contacts when none exist."""
    at = AppTest.from_file("dashboard/pages/14_ask_eon.py", default_timeout=30).run()
    assert not at.exception

    # First turn: Baker Hughes
    at.chat_input[0].set_value("Find Baker Hughes").run()
    assert not at.exception

    # Second turn: ask for other contacts
    at.chat_input[0].set_value("are there other contacts?").run()
    assert not at.exception

    page_text = " ".join([m.value for m in at.markdown])
    assert "No additional contacts or alternative leadership profiles were found on file for **Baker Hughes**" in page_text


def test_apptest_ask_eon_unsupported_prompt():
    """Verify out-of-scope query returns transparent capability limitation message."""
    at = AppTest.from_file("dashboard/pages/14_ask_eon.py", default_timeout=30).run()
    assert not at.exception

    at.chat_input[0].set_value("what is the weather today?").run()
    assert not at.exception

    page_text = " ".join([m.value for m in at.markdown])
    assert "I can only assist with EON commercial intelligence workflows" in page_text



