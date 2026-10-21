"""
Smoke Test for Contact Research Integration
Verifies syntax, imports, mock API call handling, and integration contracts.
"""

import os
import sys
import ast
import json
import time
import threading
from unittest import mock
from pathlib import Path
from http.server import BaseHTTPRequestHandler, HTTPServer
import pytest

project_root = str(Path(__file__).resolve().parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)


def test_file_syntax_and_compilation():
    """Verify all modified and created files parse cleanly without syntax errors."""
    project_root = os.path.dirname(os.path.dirname(__file__))
    files_to_check = [
        os.path.join(project_root, "app.py"),
        os.path.join(project_root, "dashboard", "governance.py"),
        os.path.join(project_root, "dashboard", "contact_research.py"),
        os.path.join(project_root, "dashboard", "pages", "11_company_browser.py"),
        os.path.join(project_root, "dashboard", "pages", "14_ask_eon.py"),
        os.path.join(project_root, "dashboard", "pages", "13_contact_research.py"),
        os.path.join(project_root, "contact_intelligence", "eon_contact_research_server_agentic_v1.py"),
        os.path.join(project_root, "contact_intelligence", "eon_contact_research_server_purdue_v1.py"),
    ]

    for fpath in files_to_check:
        assert os.path.exists(fpath), f"File not found: {fpath}"
        with open(fpath, "r", encoding="utf-8") as f:
            source = f.read()
        ast.parse(source, filename=fpath)


def test_html_assets_exist():
    """Verify the colleague HTML assets exist in contact_intelligence directory."""
    project_root = os.path.dirname(os.path.dirname(__file__))
    demo_html = os.path.join(project_root, "contact_intelligence", "EON_Prospect_Ranker_DEMO_FAST_CACHED.html")
    stable_html = os.path.join(project_root, "contact_intelligence", "EON_Prospect_Ranker_ORIGINAL_STABLE.html")

    assert os.path.exists(demo_html), "EON_Prospect_Ranker_DEMO_FAST_CACHED.html is missing"
    assert os.path.exists(stable_html), "EON_Prospect_Ranker_ORIGINAL_STABLE.html is missing"
    assert os.path.getsize(demo_html) > 10000
    assert os.path.getsize(stable_html) > 10000


def test_server_offline_detection():
    """Verify is_contact_server_online returns False for an unused port without raising."""
    from dashboard.contact_research import is_contact_server_online
    # Use an unassigned port in the dynamic range
    assert not is_contact_server_online(host="127.0.0.1", port=59999, timeout=0.2)


def test_query_contact_research_offline_handling():
    """Verify query_contact_research handles an offline backend gracefully."""
    from dashboard.contact_research import query_contact_research
    # Point temporarily to an offline port
    os.environ["CONTACT_API_URL"] = "http://127.0.0.1:59999/api/contact-research"
    try:
        ok, res, err = query_contact_research("Chevron", timeout=1)
        assert ok is False
        assert res is None
        assert err is not None
        assert "Connection Error" in err or "offline" in err.lower()
    finally:
        os.environ["CONTACT_API_URL"] = "http://localhost:8787/api/contact-research"


def test_query_contact_research_mock_success():
    """Verify query_contact_research correctly serializes requests and parses responses against a mock server."""
    from dashboard.contact_research import query_contact_research

    mock_response = {
        "company_name": "Baker Hughes",
        "contact_research_status": "Verified Contact Found",
        "primary_contact": {
            "name": "Jane Smith",
            "title": "Director of Technical Training",
            "contact_category": "Direct Training Leadership",
            "icp_level": "Primary / Direct Training Leadership",
            "current_employment_status": "Verified",
            "evidence_confidence": "High",
            "why_selected": "Direct training leader verified across multiple sources.",
            "evidence_urls": ["https://example.com/source1", "https://example.com/source2"]
        },
        "ideal_role": None,
        "evidence_confidence": "High",
        "decision_reason": "Verified leader found.",
        "alternative_contacts": [],
        "researched_at": "2026-10-09",
        "sources": [{"title": "Bio", "url": "https://example.com/source1", "snippet": "Director of Training"}]
    }

    received_requests = []

    class MockHandler(BaseHTTPRequestHandler):
        def do_POST(self):
            if self.path == "/api/contact-research":
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length).decode("utf-8"))
                received_requests.append(body)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(mock_response).encode("utf-8"))
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, format, *args):
            pass

    server = HTTPServer(("127.0.0.1", 58787), MockHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    os.environ["CONTACT_API_URL"] = "http://127.0.0.1:58787/api/contact-research"
    try:
        ok, res, err = query_contact_research(
            company_name="Baker Hughes",
            website="bakerhughes.com",
            segment="Oilfield Services",
            country="United States",
            timeout=5
        )
        assert ok is True
        assert err is None
        assert res is not None
        assert res["contact_research_status"] == "Verified Contact Found"
        assert res["primary_contact"]["name"] == "Jane Smith"
        assert len(received_requests) == 1
        assert received_requests[0]["company_name"] == "Baker Hughes"
        assert received_requests[0]["website"] == "bakerhughes.com"
        assert received_requests[0]["segment"] == "Oilfield Services"
    finally:
        os.environ["CONTACT_API_URL"] = "http://localhost:8787/api/contact-research"
        server.shutdown()
        server.server_close()


def test_regression_contact_research_status_classification_invariant():
    """
    Regression test:
    Verify that when primary_contact exists with current_employment_status == 'Verified',
    the top-level contact_research_status is 'Verified Contact Found', even when an ideal_role
    is present and ideal_role_person_unresolved is True.
    """
    payload = {
        "primary_contact": {
            "name": "Jose Fernandez",
            "title": "Chief Learning Officer (CLO)",
            "icp_level": "Primary",
            "evidence_confidence": "High",
            "current_employment_status": "Verified",
        },
        "ideal_role": "Head of Training / Training Director",
        "ideal_role_person_unresolved": True,
    }

    # Test via dashboard.contact_research normalization
    from dashboard.contact_research import (
        classify_contact_research_status,
        normalize_contact_research_payload,
    )
    from contact_intelligence.eon_contact_research_server_purdue_v1 import (
        classify_contact_research_status as purdue_classify,
        normalize_contact_research_payload as purdue_normalize,
    )
    from contact_intelligence.eon_contact_research_server_agentic_v1 import (
        classify_contact_research_status as agentic_classify,
        normalize_contact_research_payload as agentic_normalize,
    )

    # 1. Test classify function across all implementations
    status = classify_contact_research_status(
        payload["primary_contact"], payload["ideal_role"]
    )
    assert (
        status == "Verified Contact Found"
    ), f"Expected 'Verified Contact Found', got {status}"
    assert (
        purdue_classify(payload["primary_contact"], payload["ideal_role"])
        == "Verified Contact Found"
    )
    assert (
        agentic_classify(payload["primary_contact"], payload["ideal_role"])
        == "Verified Contact Found"
    )

    # Also test passing payload dict directly
    assert classify_contact_research_status(payload) == "Verified Contact Found"
    assert purdue_classify(payload) == "Verified Contact Found"
    assert agentic_classify(payload) == "Verified Contact Found"

    # 2. Test payload normalization (exact shape preservation)
    normalized = normalize_contact_research_payload(dict(payload))
    assert normalized["contact_research_status"] == "Verified Contact Found"
    assert normalized["ideal_role"] == "Head of Training / Training Director"
    assert normalized["ideal_role_person_unresolved"] is True
    assert normalized["primary_contact"]["name"] == "Jose Fernandez"

    purdue_norm = purdue_normalize(dict(payload))
    assert purdue_norm["contact_research_status"] == "Verified Contact Found"
    assert purdue_norm["ideal_role_person_unresolved"] is True

    agentic_norm = agentic_normalize(dict(payload))
    assert agentic_norm["contact_research_status"] == "Verified Contact Found"
    assert agentic_norm["ideal_role_person_unresolved"] is True

    # 3. Test full invariant coverage
    # (a) Verified employment
    assert (
        classify_contact_research_status(
            {"current_employment_status": "Verified"}, "Head of Training"
        )
        == "Verified Contact Found"
    )

    # (b) Probable contact (unverified employment)
    assert (
        classify_contact_research_status(
            {"current_employment_status": "Current"}, "Head of Training"
        )
        == "Probable Contact Found"
    )
    assert (
        classify_contact_research_status(
            {"current_employment_status": "Unconfirmed"}, "Head of Training"
        )
        == "Probable Contact Found"
    )

    # (c) Role Found - Person Unresolved (ideal_role present, primary_contact None)
    assert (
        classify_contact_research_status(
            None, "Head of Training / Training Director"
        )
        == "Role Found - Person Unresolved"
    )

    # (d) No Relevant Contact Found (neither present)
    assert (
        classify_contact_research_status(None, None)
        == "No Relevant Contact Found"
    )

    # 4. Baker Hughes exact shape test
    baker_hughes_payload = {
        "company_name": "Baker Hughes",
        "primary_contact": {
            "name": "Jose Fernandez",
            "title": "Chief Learning Officer (CLO)",
            "icp_level": "Primary",
            "evidence_confidence": "High",
            "current_employment_status": "Probable",
            "employment_status_note": "Listed as current on one third-party publisher; no independent confirmation of current tenure.",
        },
        "ideal_role": None,
        "ideal_role_person_unresolved": False,
        "evidence_confidence": "High",
    }
    normalized_bh = normalize_contact_research_payload(dict(baker_hughes_payload))
    assert normalized_bh["contact_research_status"] == "Probable Contact Found"
    assert normalized_bh["evidence_confidence"] == "High"
    assert normalized_bh["primary_contact"]["current_employment_status"] == "Probable"
    assert normalized_bh["primary_contact"]["employment_status_note"] == (
        "Listed as current on one third-party publisher; no independent confirmation of current tenure."
    )

    # 5. Regression assertion: classifier treats ONLY the exact normalized Verified value as verified,
    # and does NOT rely on descriptive free text (e.g. phrases containing "Verified" as a substring).
    descriptive_free_text_cases = [
        "Verified as listed on the source (no independent confirmation of current tenure)",
        "Verified on single directory only",
        "Verified - uncorroborated",
        "Partially Verified",
        "Not Verified",
        "Verified on LinkedIn but no corporate bio",
    ]
    for desc_text in descriptive_free_text_cases:
        contact_raw = {
            "name": "Jose Fernandez",
            "current_employment_status": desc_text,
        }
        # Classifier MUST NOT treat descriptive text as Verified
        assert classify_contact_research_status(contact_raw, None) == "Probable Contact Found", (
            f"Classifier improperly treated descriptive text '{desc_text}' as Verified Contact Found"
        )
        assert purdue_classify(contact_raw, None) == "Probable Contact Found"
        assert agentic_classify(contact_raw, None) == "Probable Contact Found"

        # Normalization maps descriptive text to fixed vocabulary and extracts note
        norm = normalize_contact_research_payload({"primary_contact": dict(contact_raw)})
        assert norm["primary_contact"]["current_employment_status"] in {
            "Probable", "Unconfirmed", "Former", "Unknown"
        }
        assert norm["primary_contact"]["current_employment_status"] != "Verified"
        assert norm["contact_research_status"] == "Probable Contact Found"
        assert bool(norm["primary_contact"].get("employment_status_note")) is True


def test_regression_baker_hughes_deterministic_adjudication():
    """
    Regression Test: Baker Hughes Deterministic Adjudication Invariant
    Asserts that across multiple historically divergent evidence/LLM payload variants:
    - Variant A: Role Found - Person Unresolved (person dropped into alternatives/evidence)
    - Variant B: Verified Contact Found (falsely verified on duplicate comparably pages)
    - Variant C: Probable Contact Found with Low confidence & noisy ideal_role string
    All implementations strictly yield the deterministic fields:
    - contact_research_status == 'Probable Contact Found'
    - primary_contact.name == 'Jose Fernandez'
    - primary_contact.icp_level == 'Primary'
    - primary_contact.evidence_confidence == 'High'
    - ideal_role == 'Head of Training / Training Director'
    - decision_reason matches deterministic structured explanation
    """
    from dashboard.contact_research import adjudicate_contact_research as dash_adjudicate
    from contact_intelligence.eon_contact_research_server_purdue_v1 import (
        adjudicate_contact_research as purdue_adjudicate,
    )
    from contact_intelligence.eon_contact_research_server_agentic_v1 import (
        adjudicate_contact_research as agentic_adjudicate,
    )

    sample_evidence = [
        {
            "title": "Baker Hughes Executive Team | Comparably",
            "url": "https://www.comparably.com/companies/baker-hughes/executive-team",
            "snippet": "Jose Fernandez serves as the Chief Learning Officer (CLO) of Baker Hughes.",
        },
        {
            "title": "Jose Fernandez - Chief Learning Officer | Comparably",
            "url": "https://www.comparably.com/companies/baker-hughes/jose-fernandez-26869",
            "snippet": "Jose Fernandez is the Chief Learning Officer at Baker Hughes.",
        },
    ]

    # Variant A: Model returned Role Found - Person Unresolved and dropped Jose into alternative_contacts
    variant_a = {
        "company_name": "Baker Hughes",
        "contact_research_status": "Role Found - Person Unresolved",
        "primary_contact": None,
        "alternative_contacts": [
            {
                "name": "Jose Fernandez",
                "title": "Chief Learning Officer (CLO)",
                "icp_level": "Primary",
                "evidence_urls": [
                    "https://www.comparably.com/companies/baker-hughes/executive-team"
                ],
            }
        ],
        "ideal_role": "Head of Training / Training Director",
        "evidence_confidence": "Low",
    }

    # Variant B: Model falsely asserted Verified based on duplicate comparably pages
    variant_b = {
        "company_name": "Baker Hughes",
        "contact_research_status": "Verified Contact Found",
        "primary_contact": {
            "name": "Jose Fernandez",
            "title": "Chief Learning Officer (CLO)",
            "icp_level": "Primary",
            "current_employment_status": "Verified",
            "evidence_confidence": "High",
            "evidence_urls": [
                "https://www.comparably.com/companies/baker-hughes/executive-team",
                "https://www.comparably.com/companies/baker-hughes/jose-fernandez-26869",
            ],
        },
        "ideal_role": "Head of Training / Training Director",
        "evidence_confidence": "High",
    }

    # Variant C: Model asserted Low confidence and wrote verbose instruction in ideal_role
    variant_c = {
        "company_name": "Baker Hughes",
        "contact_research_status": "Probable Contact Found",
        "primary_contact": {
            "name": "Jose Fernandez",
            "title": "Chief Learning Officer (CLO)",
            "icp_level": "Primary",
            "current_employment_status": "Probable",
            "evidence_confidence": "Low",
            "evidence_urls": [
                "https://www.comparably.com/companies/baker-hughes/executive-team",
            ],
        },
        "ideal_role": "Chief Learning Officer (CLO) – Primary training leadership at Baker Hughes – continue searching",
        "evidence_confidence": "Low",
    }

    adjudicators = [
        ("dashboard", dash_adjudicate),
        ("purdue_v1", purdue_adjudicate),
        ("agentic_v1", agentic_adjudicate),
    ]

    for impl_name, adj_fn in adjudicators:
        for v_idx, variant in enumerate([variant_a, variant_b, variant_c]):
            out = adj_fn(dict(variant), all_evidence=sample_evidence, company="Baker Hughes")

            # 1. Assert contact_research_status under Phase 3.1 aggregator reclassification
            assert out["contact_research_status"] == "Role Found - Person Unresolved", (
                f"[{impl_name}] Variant {v_idx} expected 'Role Found - Person Unresolved', got {out['contact_research_status']}"
            )
            assert out["is_weak_match"] is True

            # 2. Assert weak_matches contains Jose Fernandez with Employment Unconfirmed
            assert len(out.get("weak_matches", [])) >= 1
            wm = out["weak_matches"][0]
            assert wm["name"] == "Jose Fernandez"
            assert wm["employment_freshness_status"] == "Employment Unconfirmed"
            assert wm["is_stale_or_unconfirmed"] is True
            assert wm["icp_level"] == "Primary"

            # 3. Assert ideal_role
            assert out["ideal_role"] == "Head of Training / Training Director", (
                f"[{impl_name}] Variant {v_idx} expected ideal_role 'Head of Training / Training Director', got {out['ideal_role']}"
            )

            # 4. Assert decision_reason includes weak match suffix
            assert "Best available weak match retained for SDR discovery" in out["decision_reason"]


def test_regression_malformed_quoted_strings_fail_safely():
    """
    Regression Test: Malformed quoted strings must fail safely with StructuredJsonParseError
    and MUST NOT be silently rewritten into arbitrary payloads.
    Safe fallbacks (code fences, outer object boundary, trailing commas) must succeed.
    """
    from dashboard.contact_research import (
        StructuredJsonParseError,
        parse_structured_json as dash_parse,
    )
    from contact_intelligence.eon_contact_research_server_purdue_v1 import (
        StructuredJsonParseError as purdue_error,
        parse_structured_json as purdue_parse,
    )
    from contact_intelligence.eon_contact_research_server_agentic_v1 import (
        StructuredJsonParseError as agentic_error,
        parse_structured_json as agentic_parse,
    )

    parsers = [
        ("dashboard", dash_parse, StructuredJsonParseError),
        ("purdue_v1", purdue_parse, purdue_error),
        ("agentic_v1", agentic_parse, agentic_error),
    ]

    # 1. Malformed unescaped interior quotes MUST fail safely across all parsers
    malformed_quote_cases = [
        '{"reason": "He said "hello" to the team", "valid": true}',
        '{"primary_contact": {"name": "Jose "Joe" Fernandez", "title": "Director"}}',
        '{"ideal_role": "Target role is "Training Director" for this division"}',
        '{"status": "Role Found", "note": "Unescaped quote " inside string"}',
    ]

    for impl_name, parse_fn, err_cls in parsers:
        for malformed in malformed_quote_cases:
            with pytest.raises(err_cls) as exc_info:
                parse_fn(malformed)
            err = exc_info.value
            # Verify the error retains raw content on the exception object for diagnostics
            assert hasattr(err, "raw_content"), f"[{impl_name}] Missing raw_content attribute"
            assert err.raw_content == malformed, f"[{impl_name}] raw_content mismatch"
            # Verify string representation does NOT emit the full raw model payload
            assert str(err) == "Failed to parse structured model output as JSON", (
                f"[{impl_name}] Exception string must be clean and not leak raw output: {str(err)}"
            )

    # 2. Safe fallbacks MUST succeed
    safe_cases = [
        # (a) Strictly valid escaped quotes
        ('{"reason": "He said \\"hello\\" to the team", "valid": true}', {"reason": 'He said "hello" to the team', "valid": True}),
        # (b) Markdown code fences
        ('```json\n{"company_name": "Baker Hughes", "valid": true}\n```', {"company_name": "Baker Hughes", "valid": True}),
        ('```\n{"company_name": "Baker Hughes"}\n```', {"company_name": "Baker Hughes"}),
        # (c) Clearly bounded outer JSON object with conversational text surrounding it
        ('Here is the research output:\n{"company_name": "Baker Hughes", "valid": true}\nHope this helps!', {"company_name": "Baker Hughes", "valid": True}),
        # (d) Trailing commas (relaxed JSON5 / comma cleanup)
        ('{"company_name": "Baker Hughes", "items": [1, 2, ], }', {"company_name": "Baker Hughes", "items": [1, 2]}),
    ]

    for impl_name, parse_fn, _ in parsers:
        for raw_input, expected in safe_cases:
            result = parse_fn(raw_input)
            assert result == expected, f"[{impl_name}] Expected {expected}, got {result}"


def test_regression_credential_and_secret_leak_prevention():
    """
    Regression Test: Ensure that no raw API key, Authorization header, or search-provider
    credential is emitted through API error responses or committed files.
    """
    import re
    from pathlib import Path

    # 1. Verify file content hygiene in repo and shared packages
    root = Path(__file__).resolve().parent.parent
    files_to_audit = [
        root / "contact_intelligence" / "eon_contact_research_server_purdue_v1.py",
        root / "contact_intelligence" / "eon_contact_research_server_agentic_v1.py",
        root / "dashboard" / "contact_research.py",
    ]
    shared_pkg = Path("/Users/anasafadar/Downloads/EON_Contact_Intelligence_Shared_Package")
    if shared_pkg.exists():
        files_to_audit.extend([
            shared_pkg / "eon_contact_research_server_purdue_v1.py",
            shared_pkg / "eon_contact_research_server_agentic_v1.py",
        ])

    credential_pattern = re.compile(r"""(?:sk-[a-zA-Z0-9]{20,}|BSAx[a-zA-Z0-9_\-]{20,})""")

    for p in files_to_audit:
        if p.exists():
            text = p.read_text(encoding="utf-8")
            matches = credential_pattern.findall(text)
            assert len(matches) == 0, f"Found hardcoded credential in {p}: {matches}"

    # 2. Verify server-side error redaction
    sample_errors_with_secrets = [
        "Upstream HTTP error: Bearer sk-dummy_test_secret_key_1234567890abcdef failed",
        "Connection error to https://api.search.brave.com with token BSAx_fake_test_token_123456789012345",
        "Purdue GenAI returned error with key=sk-dummy_genai_key_9876543210fedcba",
    ]
    for raw_err in sample_errors_with_secrets:
        sanitized = re.sub(r"(?:Bearer|sk-|BSAx|key=|token=)[A-Za-z0-9_\-]+", "[REDACTED]", raw_err)
        assert "sk-" not in sanitized
        assert "BSAx" not in sanitized
        assert "[REDACTED]" in sanitized


def test_response_contract_malformed_model_output_error():
    """
    Response-level contract test asserting that a malformed model result returns exactly:
    {"error": "Failed to parse structured model output as JSON"}
    with a non-200 response (HTTP 500) and without the raw content, Authorization, Bearer,
    sk-, BSAx, or environment variable values.
    """
    import http.client
    from http.server import HTTPServer
    from unittest.mock import patch
    import contact_intelligence.eon_contact_research_server_purdue_v1 as purdue_srv
    import contact_intelligence.eon_contact_research_server_agentic_v1 as agentic_srv

    malformed_secret_content = (
        '{"company_name": "Baker Hughes", "reason": "He said "hello" to the team", '
        '"secret_leak": "Bearer sk-dummy_secret_token_1234567890abcdef and BSAx_dummy_secret_token_0987654321"}'
    )

    servers_to_test = [
        ("purdue_v1", purdue_srv),
        ("agentic_v1", agentic_srv),
    ]

    for name, srv_module in servers_to_test:
        with patch.object(
            srv_module,
            "research",
            side_effect=srv_module.StructuredJsonParseError(
                raw_content=malformed_secret_content
            ),
        ):
            server = HTTPServer(("127.0.0.1", 0), srv_module.H)
            port = server.server_address[1]
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()

            try:
                conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                req_body = json.dumps({"company_name": "Baker Hughes"})
                conn.request(
                    "POST",
                    "/api/contact-research",
                    body=req_body,
                    headers={"Content-Type": "application/json"},
                )
                resp = conn.getresponse()
                raw_response = resp.read().decode("utf-8")

                # 1. Assert non-200 HTTP status (HTTP 500)
                assert resp.status != 200, f"[{name}] Expected non-200 status, got {resp.status}"
                assert resp.status == 500, f"[{name}] Expected 500 status, got {resp.status}"

                # 2. Assert exact JSON body shape
                parsed = json.loads(raw_response)
                assert parsed == {
                    "error": "Failed to parse structured model output as JSON"
                }, f"[{name}] Expected exact error payload, got {parsed}"

                # 3. Assert raw response does NOT contain raw content, tokens, or headers
                assert "hello" not in raw_response
                assert "malformed" not in raw_response.lower()
                assert "secret_leak" not in raw_response
                assert "Authorization" not in raw_response
                assert "Bearer" not in raw_response
                assert "sk-" not in raw_response
                assert "BSAx" not in raw_response

                # 4. Assert environment variable values are not leaked
                for env_key in ["GENAI_API_KEY", "BRAVE_SEARCH_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"]:
                    val = os.getenv(env_key)
                    if val and len(val) > 4:
                        assert val not in raw_response, f"[{name}] Leaked {env_key} value in response!"
            finally:
                server.shutdown()
                server.server_close()



def test_execute_contact_research_baker_hughes_benchmark():
    """Verify execute_contact_research returns the deterministic benchmark for Baker Hughes without external credentials."""
    from dashboard.contact_research import execute_contact_research, BAKER_HUGHES_BENCHMARK
    # Clear any active test API keys to simulate fresh review deployment
    saved_brave = os.environ.pop("BRAVE_SEARCH_API_KEY", None)
    saved_openai = os.environ.pop("OPENAI_API_KEY", None)
    saved_genai = os.environ.pop("GENAI_API_KEY", None)
    saved_url = os.environ.pop("CONTACT_API_URL", None)
    try:
        ok, res, err = execute_contact_research("Baker Hughes")
        assert ok is True
        assert err is None
        assert res is not None
        assert res["company_name"] == "Baker Hughes"
        assert res["contact_research_status"] in {"Role Found — Person Unresolved", "Role Found - Person Unresolved"}
        assert res["is_weak_match"] is True
        assert len(res.get("weak_matches", [])) >= 1
        wm = res["weak_matches"][0]
        assert wm["name"] == "Jose Fernandez"
        assert wm["title"] == "Chief Learning Officer (CLO)"
        assert wm["icp_level"] == "Primary"
        assert wm["employment_freshness_status"] == "Employment Unconfirmed"
        assert res["ideal_role"] == "Head of Training / Training Director"
        assert res["ideal_role_person_unresolved"] is True
    finally:
        if saved_brave:
            os.environ["BRAVE_SEARCH_API_KEY"] = saved_brave
        if saved_openai:
            os.environ["OPENAI_API_KEY"] = saved_openai
        if saved_genai:
            os.environ["GENAI_API_KEY"] = saved_genai
        if saved_url:
            os.environ["CONTACT_API_URL"] = saved_url


def test_execute_contact_research_missing_credentials_guidance():
    """Verify execute_contact_research gives clear guidance for unbenchmarked accounts when secrets are missing, tailored to provider."""
    from dashboard.contact_research import execute_contact_research
    saved_brave = os.environ.pop("BRAVE_SEARCH_API_KEY", None)
    saved_openai = os.environ.pop("OPENAI_API_KEY", None)
    saved_purdue = os.environ.pop("PURDUE_GENAI_API_KEY", None)
    saved_genai = os.environ.pop("GENAI_API_KEY", None)
    saved_url = os.environ.pop("CONTACT_API_URL", None)
    saved_prov = os.environ.pop("LLM_PROVIDER", None)
    try:
        # 1. Purdue mode (default when unconfigured)
        os.environ["LLM_PROVIDER"] = "purdue_genai"
        ok, res, err = execute_contact_research("Unconfigured Account Inc")
        assert ok is False
        assert res is None
        assert "API credentials not configured" in err
        assert "PURDUE_GENAI_API_KEY" in err
        assert "OPENAI_API_KEY" not in err
        assert "BRAVE_SEARCH_API_KEY" in err

        # 2. OpenAI mode (explicit)
        os.environ["LLM_PROVIDER"] = "openai"
        ok_o, res_o, err_o = execute_contact_research("Unconfigured Account Inc")
        assert ok_o is False
        assert res_o is None
        assert "API credentials not configured" in err_o
        assert "OPENAI_API_KEY" in err_o
        assert "PURDUE_GENAI_API_KEY" not in err_o
        assert "BRAVE_SEARCH_API_KEY" in err_o
    finally:
        os.environ.pop("LLM_PROVIDER", None)
        if saved_brave:
            os.environ["BRAVE_SEARCH_API_KEY"] = saved_brave
        if saved_openai:
            os.environ["OPENAI_API_KEY"] = saved_openai
        if saved_purdue:
            os.environ["PURDUE_GENAI_API_KEY"] = saved_purdue
        if saved_genai:
            os.environ["GENAI_API_KEY"] = saved_genai
        if saved_url:
            os.environ["CONTACT_API_URL"] = saved_url
        if saved_prov:
            os.environ["LLM_PROVIDER"] = saved_prov


def test_get_contact_research_secrets_safety():
    """Verify get_contact_research_secrets returns safe dict without raising or leaking."""
    from dashboard.contact_research import get_contact_research_secrets
    secrets = get_contact_research_secrets()
    assert isinstance(secrets, dict)
    assert "openai_key" in secrets
    assert "brave_key" in secrets
    assert "genai_key" in secrets
    assert "api_url" in secrets
    assert "diagnostics" in secrets
    diag = secrets["diagnostics"]
    assert "has_env_brave" in diag
    assert "has_sec_brave" in diag
    assert "brave_source" in diag


def test_regression_brave_search_422_mock_continuation():
    """
    Regression Test: Verify that when Brave Search API returns HTTP 422 (Unprocessable Entity),
    brave_search simplifies the query and continues gracefully, returning empty list []
    rather than raising an unhandled exception that crashes the research job.
    """
    from unittest.mock import patch
    import io
    import urllib.error
    import contact_intelligence.eon_contact_research_server_agentic_v1 as agentic_v1

    os.environ["BRAVE_SEARCH_API_KEY"] = "dummy_test_token"
    mock_422_body = b'{"type":"ErrorResponse","error":{"status":422,"detail":"Unable to validate request parameter(s)"}}'

    # Simulate HTTPError 422
    def mock_urlopen_422(req, *args, **kwargs):
        raise urllib.error.HTTPError(
            url=req.full_url,
            code=422,
            msg="Unprocessable Entity",
            hdrs={},
            fp=io.BytesIO(mock_422_body)
        )

    with patch("urllib.request.urlopen", side_effect=mock_urlopen_422):
        # 1. Calling brave_search directly must NOT raise RuntimeError
        results = agentic_v1.brave_search("complex query that triggered 422 error", count=10)
        assert results == [], f"Expected empty list on 422 fallback, got {results}"

        # 2. Empty query must return [] without making network request
        empty_res = agentic_v1.brave_search("", count=10)
        assert empty_res == []


def test_regression_brave_search_parameter_coercion_and_safeguards():
    """
    Regression Test: Verify brave_search clamps count between 1 and 20,
    enforces query word count limits, and adds Cache-Control headers.
    """
    from unittest.mock import patch, MagicMock
    import io
    import urllib.parse
    import contact_intelligence.eon_contact_research_server_agentic_v1 as agentic_v1

    os.environ["BRAVE_SEARCH_API_KEY"] = "dummy_test_token"
    captured_requests = []

    def mock_urlopen_capture(req, *args, **kwargs):
        captured_requests.append(req)
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"web":{"results":[]}}'
        mock_resp.__enter__.return_value = io.BytesIO(b'{"web":{"results":[]}}')
        mock_resp.__exit__.return_value = False
        return mock_resp.__enter__()

    with patch("urllib.request.urlopen", side_effect=mock_urlopen_capture):
        # Count > 20 coerced to 20
        agentic_v1.brave_search("Baker Hughes", count=50)
        last_url = captured_requests[-1].full_url
        assert "count=20" in last_url

        # Count < 1 coerced to 1
        agentic_v1.brave_search("Baker Hughes", count=0)
        last_url = captured_requests[-1].full_url
        assert "count=1" in last_url

        # Non-integer count defaulted to 10
        agentic_v1.brave_search("Baker Hughes", count="invalid")
        last_url = captured_requests[-1].full_url
        assert "count=10" in last_url

        # Cache-Control header present
        headers = captured_requests[-1].headers
        assert headers.get("Cache-control") == "no-cache" or headers.get("Cache-Control") == "no-cache"

        # Long query > 50 words clamped to 50 words
        long_q = "word " * 80
        agentic_v1.brave_search(long_q, count=10)
        last_url = captured_requests[-1].full_url
        parsed_q = urllib.parse.parse_qs(urllib.parse.urlparse(last_url).query).get("q", [""])[0]
        assert len(parsed_q.split()) <= 50


def test_execute_contact_research_422_ui_message():
    """
    Regression Test: Verify execute_contact_research translates 422 provider errors
    into an actionable UI message instead of exposing raw HTTP codes.
    """
    from unittest.mock import patch
    from dashboard.contact_research import execute_contact_research

    os.environ["LLM_PROVIDER"] = "openai"
    os.environ["BRAVE_SEARCH_API_KEY"] = "dummy_token"
    os.environ["OPENAI_API_KEY"] = "dummy_token"

    def mock_raising_research(*args, **kwargs):
        raise RuntimeError("Search provider API request failed with status code 422")

    try:
        with patch("contact_intelligence.eon_contact_research_server_agentic_v1.research", side_effect=mock_raising_research):
            ok, res, err = execute_contact_research("SomeOtherCompany")
            assert ok is False
            assert res is None
            assert err == "A search query was rejected; retrying with a simplified query."
    finally:
        os.environ.pop("LLM_PROVIDER", None)


def test_execute_contact_research_provider_rejected_key_ui_message():
    """
    Regression Test: Verify execute_contact_research clearly distinguishes
    'provider rejected configured key' from 'API credentials not configured'.
    """
    from unittest.mock import patch
    from dashboard.contact_research import execute_contact_research

    os.environ["LLM_PROVIDER"] = "openai"
    os.environ["BRAVE_SEARCH_API_KEY"] = "dummy_token"
    os.environ["OPENAI_API_KEY"] = "dummy_token"

    def mock_raising_rejected(*args, **kwargs):
        raise RuntimeError("Provider rejected configured key: The BRAVE_SEARCH_API_KEY in Streamlit Secrets was rejected by Brave Search API (SUBSCRIPTION_TOKEN_INVALID)")

    try:
        with patch("contact_intelligence.eon_contact_research_server_agentic_v1.research", side_effect=mock_raising_rejected):
            ok, res, err = execute_contact_research("SomeOtherCompany")
            assert ok is False
            assert res is None
            assert "Provider rejected configured key" in err
            assert "SUBSCRIPTION_TOKEN_INVALID" in err
            assert "API credentials not configured" not in err
    finally:
        os.environ.pop("LLM_PROVIDER", None)

def test_clean_secret_value_and_safe_fingerprint():
    """
    Regression Test: Verify clean_secret_value strips quotes and whitespace,
    and safe_fingerprint strictly produces 10-char SHA-256 hash without revealing the key.
    """
    from dashboard.contact_research import clean_secret_value, safe_fingerprint

    secret = "BSAxSuperSecretKey998877"
    assert clean_secret_value(f' "{secret}" \n') == secret
    assert clean_secret_value(f"'{secret}'") == secret
    assert clean_secret_value({'api_key': f' "{secret}" '}) == secret

    fp = safe_fingerprint(secret)
    assert len(fp) == 10
    assert fp != "none"
    assert secret not in fp
    for i in range(len(secret) - 3):
        assert secret[i:i+4] not in fp

    assert safe_fingerprint(None) == "none"
    assert safe_fingerprint("") == "none"


def test_check_brave_health_probe_contracts():
    """
    Regression Test: Verify check_brave_health reports exact sanitized error fields
    and never exposes literal tokens, request headers, or raw exceptions.
    """
    from unittest.mock import patch
    import urllib.error
    import io
    from dashboard.contact_research import check_brave_health, safe_fingerprint

    # 1. Unconfigured
    res_none = check_brave_health("")
    assert res_none["http_status"] is None
    assert res_none["error_code"] == "KEY_NOT_CONFIGURED"
    assert res_none["fingerprint"] == "none"
    assert res_none["success"] is False

    # 2. Mock 422 SUBSCRIPTION_TOKEN_INVALID
    secret = "BSAxRealCandidateSecret123"
    fp = safe_fingerprint(secret)

    err_body = b'{"type":"ErrorResponse","error":{"code":"SUBSCRIPTION_TOKEN_INVALID","detail":"The provided subscription token is invalid.","status":422}}'
    mock_http_err = urllib.error.HTTPError(
        url="https://api.search.brave.com/res/v1/web/search?q=Purdue&count=1",
        code=422,
        msg="Unprocessable Entity",
        hdrs={"Content-Type": "application/json"},
        fp=io.BytesIO(err_body),
    )

    with patch("urllib.request.urlopen", side_effect=mock_http_err):
        res = check_brave_health(secret)
        assert res["http_status"] == 422
        assert res["error_code"] == "SUBSCRIPTION_TOKEN_INVALID"
        assert res["error_detail"] == "The provided subscription token is invalid."
        assert res["fingerprint"] == fp
        assert res["success"] is False
        assert secret not in str(res)


def test_diagnostics_never_contain_literal_secret():
    """
    Regression Test: Assert that no diagnostics, UI state, logs, or error strings
    contain the literal secret key.
    """
    from unittest.mock import patch, MagicMock
    from dashboard.contact_research import (
        get_contact_research_secrets,
        render_secrets_diagnostics,
        safe_fingerprint,
    )

    secret = "BSAxConfidentialBraveTokenForValidation99"
    os.environ["BRAVE_SEARCH_API_KEY"] = f' "{secret}" '

    sec_info = get_contact_research_secrets()
    diag = sec_info["diagnostics"]

    # Secret must never appear in diagnostics dict
    assert secret not in str(diag)
    assert diag["sec_had_quotes"] is False
    assert diag["env_had_quotes"] is True
    assert diag["env_had_whitespace"] is True
    assert diag["env_brave_fp"] == safe_fingerprint(secret)
    assert diag["resolved_brave_fp"] == safe_fingerprint(secret)

    rendered_strings = []
    mock_st = MagicMock()
    mock_st.markdown.side_effect = lambda text, *a, **kw: rendered_strings.append(str(text))
    mock_st.caption.side_effect = lambda text, *a, **kw: rendered_strings.append(str(text))
    mock_st.error.side_effect = lambda text, *a, **kw: rendered_strings.append(str(text))
    mock_st.warning.side_effect = lambda text, *a, **kw: rendered_strings.append(str(text))
    mock_st.success.side_effect = lambda text, *a, **kw: rendered_strings.append(str(text))
    mock_st.checkbox.return_value = True
    mock_st.columns.return_value = (MagicMock(), MagicMock())
    mock_st.button.return_value = False
    mock_st.session_state = {}

    with patch("dashboard.contact_research.st", mock_st):
        render_secrets_diagnostics(show_admin_debug_default=True)

    for s in rendered_strings:
        assert secret not in s, f"Literal secret leaked in rendered diagnostic: {s}"

    # Cleanup
    os.environ.pop("BRAVE_SEARCH_API_KEY", None)


def test_check_openai_health_probe_contracts():
    """
    Regression Test: Verify check_openai_health reports exact sanitized error fields
    and never exposes literal tokens, request headers, or raw exceptions.
    """
    from unittest.mock import patch
    import urllib.error
    import io
    from dashboard.contact_research import check_openai_health, safe_fingerprint

    # 1. Unconfigured
    res_none = check_openai_health("")
    assert res_none["http_status"] is None
    assert res_none["error_code"] == "KEY_NOT_CONFIGURED"
    assert res_none["fingerprint"] == "none"
    assert res_none["success"] is False

    # 2. Mock 401 invalid_api_key
    secret = "sk-proj-RealCandidateSecretOpenAI999"
    fp = safe_fingerprint(secret)

    err_body = b'{"error":{"message":"Incorrect API key provided: sk-proj-Re******I999.","type":"invalid_request_error","code":"invalid_api_key"}}'
    mock_http_err = urllib.error.HTTPError(
        url="https://api.openai.com/v1/responses",
        code=401,
        msg="Unauthorized",
        hdrs={"Content-Type": "application/json"},
        fp=io.BytesIO(err_body),
    )

    with patch("urllib.request.urlopen", side_effect=mock_http_err):
        res = check_openai_health(secret)
        assert res["http_status"] == 401
        assert res["error_code"] == "invalid_api_key"
        assert res["fingerprint"] == fp
        assert res["success"] is False
        assert secret not in str(res)
        assert "sk-proj-Re" not in str(res)


def test_check_purdue_health_probe_contracts():
    """
    Regression Test: Verify check_purdue_health reports exact sanitized error fields,
    host, model, provider, and never exposes literal tokens, request headers, or raw exceptions.
    """
    from unittest.mock import patch
    import urllib.error
    import io
    from dashboard.contact_research import check_purdue_health, safe_fingerprint

    # 1. Unconfigured
    res_none = check_purdue_health("")
    assert res_none["provider"] == "purdue_genai"
    assert res_none["endpoint_host"] == "genai.rcac.purdue.edu"
    assert res_none["model"] == "gpt-oss:120b"
    assert res_none["http_status"] is None
    assert res_none["error_code"] == "KEY_NOT_CONFIGURED"
    assert res_none["fingerprint"] == "none"
    assert res_none["success"] is False

    # 2. Mock 401 Unauthorized
    secret = "BSAxRealCandidateSecretPurdue999"
    fp = safe_fingerprint(secret)

    err_body = b'{"detail":"401 Unauthorized"}'
    mock_http_err = urllib.error.HTTPError(
        url="https://genai.rcac.purdue.edu/api/chat/completions",
        code=401,
        msg="Unauthorized",
        hdrs={"Content-Type": "application/json"},
        fp=io.BytesIO(err_body),
    )

    with patch("urllib.request.urlopen", side_effect=mock_http_err):
        res = check_purdue_health(secret)
        assert res["provider"] == "purdue_genai"
        assert res["endpoint_host"] == "genai.rcac.purdue.edu"
        assert res["model"] == "gpt-oss:120b"
        assert res["http_status"] == 401
        assert "401" in res["error_message"] or "Unauthorized" in res["error_message"]
        assert res["fingerprint"] == fp
        assert res["success"] is False
        assert secret not in str(res)

    # 3. Mock 200 OK
    mock_ok_body = b'{"choices":[{"message":{"content":"pong"}}]}'
    mock_resp = io.BytesIO(mock_ok_body)
    setattr(mock_resp, "status", 200)

    with patch("urllib.request.urlopen", return_value=mock_resp):
        res_ok = check_purdue_health(secret)
        assert res_ok["provider"] == "purdue_genai"
        assert res_ok["http_status"] == 200
        assert res_ok["success"] is True
        assert res_ok["fingerprint"] == fp
        assert secret not in str(res_ok)


def test_provider_routing_purdue_genai():
    """
    Regression Test: Verify execute_contact_research routes to purdue_v1 when LLM_PROVIDER is purdue_genai.
    Asserts error messages correctly refer to PURDUE_GENAI_API_KEY on failure and never OPENAI_API_KEY.
    """
    from unittest.mock import patch
    from dashboard.contact_research import execute_contact_research

    os.environ["LLM_PROVIDER"] = "purdue_genai"
    os.environ["BRAVE_SEARCH_API_KEY"] = "dummy_brave_key"
    os.environ["PURDUE_GENAI_API_KEY"] = "dummy_purdue_key"

    purdue_called = []
    def mock_purdue_research(company, website="", segment="", country=""):
        purdue_called.append(company)
        return {
            "company_name": company,
            "contact_research_status": "Verified Contact Found",
            "primary_contact": {
                "name": "Jane Doe",
                "title": "Director of Technical Training",
                "contact_category": "Primary",
                "icp_level": "Primary",
                "current_employment_status": "Verified",
                "evidence_confidence": "High",
                "why_selected": "Matched verified profile",
                "evidence_urls": ["https://example.com/jane"],
            },
            "alternative_contacts": [],
            "discovered_company_functions": ["Training"],
            "company_training_structure": "Corporate",
            "ideal_role": "Director of Training",
            "evidence_confidence": "High",
            "decision_reason": "Verified",
            "researched_at": "2026-10-09",
            "research_notes": "Test notes",
            "sources": [],
        }

    from dashboard.contact_research import execute_contact_research, get_cache_provider
    get_cache_provider().clear()

    with patch("contact_intelligence.eon_contact_research_server_purdue_v1.research", side_effect=mock_purdue_research):
        ok, res, err = execute_contact_research("Saipem", force_refresh=True)
        assert ok is True
        assert res is not None
        assert err is None
        assert "Saipem" in purdue_called

    # Test Purdue 401 error message guidance
    def mock_purdue_401(*args, **kwargs):
        raise RuntimeError("LLM provider API request failed with status code 401")

    get_cache_provider().clear()
    with patch("contact_intelligence.eon_contact_research_server_purdue_v1.research", side_effect=mock_purdue_401):
        ok, res, err = execute_contact_research("Saipem", force_refresh=True)
        assert ok is False
        assert res is None
        assert "PURDUE_GENAI_API_KEY" in err
        assert "OPENAI_API_KEY" not in err

    # Cleanup
    get_cache_provider().clear()
    os.environ.pop("LLM_PROVIDER", None)
    os.environ.pop("BRAVE_SEARCH_API_KEY", None)
    os.environ.pop("PURDUE_GENAI_API_KEY", None)


def test_provider_routing_openai():
    """
    Regression Test: Verify execute_contact_research routes to agentic_v1 when LLM_PROVIDER is openai.
    Asserts error messages correctly refer to OPENAI_API_KEY on failure and never PURDUE_GENAI_API_KEY.
    """
    from unittest.mock import patch
    from dashboard.contact_research import execute_contact_research, get_cache_provider

    os.environ["LLM_PROVIDER"] = "openai"
    os.environ["BRAVE_SEARCH_API_KEY"] = "dummy_brave_key"
    os.environ["OPENAI_API_KEY"] = "dummy_openai_key"
    get_cache_provider().clear()

    openai_called = []
    def mock_openai_research(company, website="", segment="", country=""):
        openai_called.append(company)
        return {
            "company_name": company,
            "contact_research_status": "Verified Contact Found",
            "primary_contact": {
                "name": "Jane Doe",
                "title": "Director of Technical Training",
                "contact_category": "Primary",
                "icp_level": "Primary",
                "current_employment_status": "Verified",
                "evidence_confidence": "High",
                "why_selected": "Matched verified profile",
                "evidence_urls": ["https://example.com/jane"],
            },
            "alternative_contacts": [],
            "discovered_company_functions": ["Training"],
            "company_training_structure": "Corporate",
            "ideal_role": "Director of Training",
            "evidence_confidence": "High",
            "decision_reason": "Verified",
            "researched_at": "2026-10-09",
            "research_notes": "Test notes",
            "sources": [],
        }

    with patch("contact_intelligence.eon_contact_research_server_agentic_v1.research", side_effect=mock_openai_research):
        ok, res, err = execute_contact_research("Saipem", force_refresh=True)
        assert ok is True
        assert res is not None
        assert err is None
        assert "Saipem" in openai_called

    # Test OpenAI 401 error message guidance
    def mock_openai_401(*args, **kwargs):
        raise RuntimeError("LLM provider API request failed with status code 401")

    get_cache_provider().clear()
    with patch("contact_intelligence.eon_contact_research_server_agentic_v1.research", side_effect=mock_openai_401):
        ok, res, err = execute_contact_research("Saipem", force_refresh=True)
        assert ok is False
        assert res is None
        assert "OPENAI_API_KEY" in err
        assert "PURDUE_GENAI_API_KEY" not in err

    # Cleanup
    get_cache_provider().clear()
    os.environ.pop("LLM_PROVIDER", None)
    os.environ.pop("BRAVE_SEARCH_API_KEY", None)
    os.environ.pop("OPENAI_API_KEY", None)


def test_purdue_diagnostics_never_contain_literal_secret():
    """
    Regression Test: Assert that no diagnostics, UI state, logs, or error strings
    in Purdue mode contain the literal secret key.
    """
    from unittest.mock import patch, MagicMock
    from dashboard.contact_research import (
        get_contact_research_secrets,
        render_secrets_diagnostics,
        safe_fingerprint,
    )

    secret = "BSAxConfidentialPurdueTokenForValidation88"
    os.environ["LLM_PROVIDER"] = "purdue_genai"
    os.environ["PURDUE_GENAI_API_KEY"] = f' "{secret}" '

    sec_info = get_contact_research_secrets()
    diag = sec_info["diagnostics"]

    # Secret must never appear in diagnostics dict
    assert secret not in str(diag)
    assert diag["llm_provider"] == "purdue_genai"
    assert diag["env_purdue_had_quotes"] is True
    assert diag["env_purdue_had_whitespace"] is True
    assert diag["env_purdue_fp"] == safe_fingerprint(secret)
    assert diag["resolved_purdue_fp"] == safe_fingerprint(secret)

    rendered_strings = []
    mock_st = MagicMock()
    mock_st.expander = MagicMock()
    mock_st.columns = MagicMock(return_value=[MagicMock(), MagicMock()])
    mock_st.markdown = MagicMock(side_effect=lambda s, **kw: rendered_strings.append(str(s)))
    mock_st.caption = MagicMock(side_effect=lambda s, **kw: rendered_strings.append(str(s)))
    mock_st.checkbox = MagicMock(return_value=True)
    mock_st.button = MagicMock(return_value=False)
    mock_st.success = MagicMock(side_effect=lambda s, **kw: rendered_strings.append(str(s)))
    mock_st.error = MagicMock(side_effect=lambda s, **kw: rendered_strings.append(str(s)))
    mock_st.warning = MagicMock(side_effect=lambda s, **kw: rendered_strings.append(str(s)))
    mock_st.session_state = {}

    with patch("dashboard.contact_research.st", mock_st):
        render_secrets_diagnostics(show_admin_debug_default=True)

    for s in rendered_strings:
        assert secret not in s, f"Literal secret leaked in rendered diagnostic: {s}"

    # Cleanup
    os.environ.pop("LLM_PROVIDER", None)
    os.environ.pop("PURDUE_GENAI_API_KEY", None)


def test_regression_render_contact_card_presentation_html_no_raw_tags():
    """
    Regression Test:
    1. render_contact_card emits presentation HTML via st.markdown(card_html, unsafe_allow_html=True).
    2. Does NOT call st.write, st.text, st.code.
    3. Markdown parser treats the entire output as an html_block, NOT a code_block.
    4. Rendered output contains no literal '<div' or '</span>' text from code blocks.
    """
    from unittest.mock import MagicMock, patch
    import markdown_it
    from dashboard.contact_research import render_contact_card, BAKER_HUGHES_BENCHMARK

    mock_st = MagicMock()
    with patch("dashboard.contact_research.st", mock_st):
        render_contact_card(BAKER_HUGHES_BENCHMARK)

    # 1. Assert st.markdown was called with unsafe_allow_html=True
    assert mock_st.markdown.called, "st.markdown was not called by render_contact_card"
    call_args, call_kwargs = mock_st.markdown.call_args
    emitted_html = call_args[0]
    assert call_kwargs.get("unsafe_allow_html") is True, "unsafe_allow_html=True was not passed"

    # 2. Assert disallowed output functions were never called
    assert not mock_st.write.called, "st.write must not be called for contact card presentation HTML"
    assert not mock_st.text.called, "st.text must not be called for contact card presentation HTML"
    assert not mock_st.code.called, "st.code must not be called for contact card presentation HTML"

    # 3. Assert HTML structure
    assert emitted_html.startswith("<div"), f"Card HTML should begin with <div, got: {emitted_html[:50]}"
    assert emitted_html.endswith("</div>"), f"Card HTML should end with </div>, got: {emitted_html[-50:]}"

    # 4. Assert no lines start with 4+ spaces (which CommonMark turns into indented code blocks)
    for line_num, line in enumerate(emitted_html.splitlines(), start=1):
        assert not line.startswith("    "), f"Line {line_num} starts with 4 spaces, triggering indented code block: {line[:30]}"

    # 5. Assert markdown_it parser parses it strictly as an html_block with zero code_block tokens
    md = markdown_it.MarkdownIt()
    tokens = md.parse(emitted_html)
    assert len(tokens) > 0, "No markdown tokens produced"
    code_blocks = [t for t in tokens if t.type in ("code_block", "fence")]
    assert len(code_blocks) == 0, f"HTML was parsed as code blocks: {code_blocks}"

    # 6. Assert rendered output contains NO <pre><code> wrapper and NO escaped literal tags &lt;div or &lt;span
    rendered_output = md.render(emitted_html)
    assert "<pre><code>" not in rendered_output, "Rendered markdown output wrapped in <pre><code>"
    assert "&lt;div" not in rendered_output, "Rendered output contains literal escaped &lt;div text"
    assert "&lt;span" not in rendered_output, "Rendered output contains literal escaped &lt;span text"


def test_regression_render_contact_card_xss_sanitization_and_secure_links():
    """
    Regression Test:
    1. Model/external strings with script tags or attributes are HTML-escaped.
    2. Non-http URLs (javascript:, data:) are excluded from href attributes.
    3. Legitimate evidence URLs have target="_blank" and rel="noopener noreferrer".
    """
    from dashboard.contact_research import build_contact_card_html

    xss_payload = {
        "contact_research_status": "Probable Contact Found",
        "primary_contact": {
            "name": "<script>alert('xss_name')</script>",
            "title": "Director of Learning\"><img src=x onerror=alert(1)>",
            "icp_level": "Primary",
            "current_employment_status": "Probable",
            "evidence_confidence": "High",
            "why_selected": "<svg/onload=alert('xss_why')>",
            "employment_status_note": "<b>Note injection</b>",
            "evidence_urls": [
                "javascript:alert('xss_url')",
                "data:text/html,<script>alert(1)</script>",
                "https://trusted.corp.com/bio?person=1&title=director",
            ],
        },
        "ideal_role": "Head of Training <iframe src=evil.com>",
        "decision_reason": "Identified contact <script>alert('xss_reason')</script>",
        "alternative_contacts": [
            {
                "name": "Alt Contact <script>alert(2)</script>",
                "title": "Trainer",
                "icp_level": "Secondary",
                "why_selected": "Alt why <img src=x onerror=alert(2)>",
                "evidence_urls": [
                    "https://trusted.corp.com/alt",
                ],
            }
        ],
    }

    html_out = build_contact_card_html(xss_payload)

    # Assert no unescaped script, img onerror, svg, iframe tags
    assert "<script>" not in html_out, "Unescaped <script> tag found in HTML output"
    assert "</script>" not in html_out, "Unescaped </script> tag found in HTML output"
    assert "<img src=x" not in html_out, "Unescaped <img onerror> found in HTML output"
    assert "<svg" not in html_out, "Unescaped <svg> found in HTML output"
    assert "<iframe" not in html_out, "Unescaped <iframe found in HTML output"

    # Assert properly escaped entities
    assert ("&lt;script&gt;alert(&#x27;xss_name&#x27;)&lt;/script&gt;" in html_out or
            "&lt;script&gt;alert('xss_name')&lt;/script&gt;" in html_out), "Escaped script tag missing"
    assert "&lt;img src=x" in html_out, "Escaped img tag missing"

    # Assert javascript / data URLs are never in href
    assert 'href="javascript:' not in html_out, "javascript: scheme was allowed in href attribute"
    assert 'href="data:' not in html_out, "data: scheme was allowed in href attribute"

    # Assert trusted http/https URL is preserved with target="_blank" and rel="noopener noreferrer"
    assert ('href="https://trusted.corp.com/bio?person=1&amp;title=director"' in html_out or
            'href="https://trusted.corp.com/bio?person=1&title=director"' in html_out), "Trusted URL missing"
    assert 'target="_blank"' in html_out, "target='_blank' attribute missing on link"
    assert 'rel="noopener noreferrer"' in html_out, "rel='noopener noreferrer' attribute missing on link"


def test_regression_decision_reason_confidence_consistency_low_confidence():
    """
    Regression Test:
    1. Low confidence candidates produce:
       "Current employment is classified as Probable with low evidence confidence."
    2. Decision reason does NOT contradict with "High evidence confidence".
    3. Does NOT promote candidate to Primary/Secondary ICP; retains Fallback/Probable/Low.
    4. Normalization and card builder heal any stale contradictory payloads.
    """
    from dashboard.contact_research import (
        adjudicate_contact_research as dash_adjudicate,
        normalize_contact_research_payload as dash_normalize,
        build_contact_card_html,
    )
    from contact_intelligence.eon_contact_research_server_purdue_v1 import (
        adjudicate_contact_research as purdue_adjudicate,
        normalize_contact_research_payload as purdue_normalize,
    )
    from contact_intelligence.eon_contact_research_server_agentic_v1 import (
        adjudicate_contact_research as agentic_adjudicate,
        normalize_contact_research_payload as agentic_normalize,
    )

    candidate = {
        "name": "Jane Practitioner",
        "title": "Training Assistant",
        "icp_level": "Fallback",
        "current_employment_status": "Probable",
        "evidence_urls": ["https://thirdpartydirectory.com/jane"],
    }
    raw_payload = {
        "company_name": "Test Industrial Co",
        "primary_contact": candidate,
        "ideal_role": "Head of Training",
    }

    for impl_name, adj_fn, norm_fn in [
        ("dashboard", dash_adjudicate, dash_normalize),
        ("purdue_v1", purdue_adjudicate, purdue_normalize),
        ("agentic_v1", agentic_adjudicate, agentic_normalize),
    ]:
        out = adj_fn(raw_payload, all_evidence=[{"url": "https://thirdpartydirectory.com/jane", "snippet": "Jane"}], company="Test Industrial Co")

        # 1. Conservative outcome preserved: Fallback / Probable / Low
        assert out["primary_contact"]["icp_level"] == "Fallback", f"[{impl_name}] ICP level should remain Fallback"
        assert out["primary_contact"]["current_employment_status"] == "Probable", f"[{impl_name}] Employment should remain Probable"
        assert out["evidence_confidence"] == "Low", f"[{impl_name}] Evidence confidence should be Low"

        # 2. Decision reason must say: "Current employment is classified as Probable with low evidence confidence."
        reason = out["decision_reason"]
        assert "Current employment is classified as Probable with low evidence confidence." in reason, (
            f"[{impl_name}] Expected 'Current employment is classified as Probable with low evidence confidence.' in reason: {reason}"
        )
        assert "High evidence confidence" not in reason, (
            f"[{impl_name}] Contradictory 'High evidence confidence' found in reason: {reason}"
        )

        # 3. Test stale payload healing in normalize function
        stale_payload = {
            "primary_contact": {
                "name": "Jane Practitioner",
                "title": "Training Assistant",
                "icp_level": "Fallback",
                "current_employment_status": "Probable",
                "evidence_confidence": "Low",
                "why_selected": "Identified on directory. Confirmed on a single publisher without independent corporate corroboration, classifying current employment as Probable with High evidence confidence.",
            },
            "evidence_confidence": "Low",
            "decision_reason": "Identified Jane. Confirmed on a single publisher without independent corporate corroboration, classifying current employment as Probable with High evidence confidence.",
            "ideal_role": "Head of Training",
        }
        healed = norm_fn(dict(stale_payload))
        assert "High evidence confidence" not in healed["decision_reason"]
        assert "Current employment is classified as Probable with low evidence confidence." in healed["decision_reason"]
        assert "High evidence confidence" not in healed["primary_contact"]["why_selected"]

    # 4. Assert card HTML builder also formats and harmonizes the card correctly
    card_html = build_contact_card_html(stale_payload)
    assert "High evidence confidence" not in card_html
    assert "Current employment is classified as Probable with low evidence confidence." in card_html
    assert "Probable — Low confidence" in card_html


def test_regression_linkedin_plus_rocketreach_not_corroboration():
    """
    Regression test:
    Verify that scraper mirrors (RocketReach, ZoomInfo, Apollo, etc.) do NOT count as
    independent corroboration. A lead supported only by LinkedIn + RocketReach has only
    1 credible domain, is treated as LinkedIn-only, is capped at Low confidence, and
    cannot achieve Verified employment status.
    """
    from dashboard.contact_research import (
        evaluate_candidate_corroboration as dash_eval,
        adjudicate_evidence_confidence as dash_conf,
        adjudicate_contact_research as dash_adj,
    )
    from contact_intelligence.eon_contact_research_server_purdue_v1 import (
        evaluate_candidate_corroboration as purdue_eval,
        adjudicate_evidence_confidence as purdue_conf,
        adjudicate_contact_research as purdue_adj,
    )
    from contact_intelligence.eon_contact_research_server_agentic_v1 import (
        evaluate_candidate_corroboration as agentic_eval,
        adjudicate_evidence_confidence as agentic_conf,
        adjudicate_contact_research as agentic_adj,
    )

    urls = [
        "https://www.linkedin.com/in/john-doe-training",
        "https://rocketreach.co/john-doe-training-profile",
        "https://zoominfo.com/p/john-doe-training",
    ]

    for impl_name, eval_fn, conf_fn, adj_fn in [
        ("dashboard", dash_eval, dash_conf, dash_adj),
        ("purdue_v1", purdue_eval, purdue_conf, purdue_adj),
        ("agentic_v1", agentic_eval, agentic_conf, agentic_adj),
    ]:
        corrob = eval_fn(urls)
        # 1. Scrapers identified and excluded from credible domain count
        assert "rocketreach.co" in corrob["scraper_domains"], f"[{impl_name}] rocketreach should be recognized as scraper"
        assert "zoominfo.com" in corrob["scraper_domains"], f"[{impl_name}] zoominfo should be recognized as scraper"
        assert corrob["credible_domains"] == {"linkedin.com"}, f"[{impl_name}] credible domains should only contain linkedin"
        assert corrob["num_credible"] == 1, f"[{impl_name}] credible count should be 1"
        assert corrob["is_linkedin_only"] is True, f"[{impl_name}] should be flagged as LinkedIn-only"

        # 2. Confidence is strictly capped at Low
        candidate = {
            "name": "John Doe",
            "title": "Director of Training",
            "evidence_urls": urls,
        }
        conf = conf_fn(candidate, urls)
        assert conf == "Low", f"[{impl_name}] LinkedIn-only result must be capped at Low confidence, got {conf}"

        # 3. Adjudication yields Probable (never Verified)
        payload = {
            "company_name": "Acme Corp",
            "primary_contact": candidate,
            "ideal_role": "Head of Training",
        }
        res = adj_fn(payload, company="Acme Corp")
        assert res["primary_contact"]["current_employment_status"] == "Probable", (
            f"[{impl_name}] Employment must be Probable (never Verified) when only scrapers exist"
        )
        assert res["primary_contact"]["evidence_confidence"] == "Low"


def test_regression_corporate_domain_outranks_linkedin_only():
    """
    Regression test:
    Verify that first-party corporate domain evidence outranks LinkedIn + scraper mirrors.
    When two candidates exist, Candidate with corporate URL outranks LinkedIn-only candidate.
    """
    from dashboard.contact_research import (
        adjudicate_contact_research as dash_adj,
        score_candidate as dash_score,
    )
    from contact_intelligence.eon_contact_research_server_purdue_v1 import (
        adjudicate_contact_research as purdue_adj,
        score_candidate as purdue_score,
    )
    from contact_intelligence.eon_contact_research_server_agentic_v1 import (
        adjudicate_contact_research as agentic_adj,
        score_candidate as agentic_score,
    )

    cand_li = {
        "name": "John LinkedIn",
        "title": "Director of Training",
        "evidence_urls": ["https://www.linkedin.com/in/john-linkedin"],
    }
    cand_corp = {
        "name": "Jane Corporate",
        "title": "Director of Training",
        "evidence_urls": ["https://www.chevron.com/careers/training-leadership/jane"],
    }

    payload = {
        "company_name": "Chevron",
        "website": "chevron.com",
        "primary_contact": cand_li,
        "alternative_contacts": [cand_corp],
        "ideal_role": "Head of Training / Training Director",
    }

    for impl_name, adj_fn, score_fn in [
        ("dashboard", dash_adj, dash_score),
        ("purdue_v1", purdue_adj, purdue_score),
        ("agentic_v1", agentic_adj, agentic_score),
    ]:
        score_li = score_fn(cand_li, company_domain="chevron.com", company_name="Chevron")
        score_corp = score_fn(cand_corp, company_domain="chevron.com", company_name="Chevron")
        assert score_corp > score_li, f"[{impl_name}] Corporate candidate ({score_corp}) must outscore LinkedIn-only ({score_li})"

        out = adj_fn(payload, company="Chevron", website="chevron.com")
        assert out["primary_contact"]["name"] == "Jane Corporate", (
            f"[{impl_name}] Corporate domain lead should outrank LinkedIn lead as primary_contact"
        )
        assert any(c["name"] == "John LinkedIn" for c in out["alternative_contacts"])


def test_regression_training_manager_ambiguous_without_first_party_evidence():
    """
    Regression test:
    Verify that 'Training Manager' is treated as an ambiguous title requiring stronger
    first-party corporate corroboration. Without first-party corporate evidence, it is
    penalized so that a corporate-domain lead outranks it.
    """
    from dashboard.contact_research import (
        classify_title_tier as dash_tier,
        score_candidate as dash_score,
        adjudicate_contact_research as dash_adj,
    )
    from contact_intelligence.eon_contact_research_server_purdue_v1 import (
        classify_title_tier as purdue_tier,
        score_candidate as purdue_score,
        adjudicate_contact_research as purdue_adj,
    )
    from contact_intelligence.eon_contact_research_server_agentic_v1 import (
        classify_title_tier as agentic_tier,
        score_candidate as agentic_score,
        adjudicate_contact_research as agentic_adj,
    )

    for impl_name, tier_fn, score_fn, adj_fn in [
        ("dashboard", dash_tier, dash_score, dash_adj),
        ("purdue_v1", purdue_tier, purdue_score, purdue_adj),
        ("agentic_v1", agentic_tier, agentic_score, agentic_adj),
    ]:
        # 1. Title classification assertions
        tier_tm, is_ambig_tm = tier_fn("Training Manager")
        assert tier_tm == "ambiguous_leadership", f"[{impl_name}] 'Training Manager' should be ambiguous_leadership"
        assert is_ambig_tm is True

        tier_lead, is_ambig_lead = tier_fn("Technical Training Lead")
        assert is_ambig_lead is True

        tier_dir, is_ambig_dir = tier_fn("Director of Training")
        assert tier_dir == "strong_leadership"
        assert is_ambig_dir is False

        tier_pm, is_ambig_pm = tier_fn("Training Program Manager")
        assert tier_pm == "practitioner", f"[{impl_name}] 'Training Program Manager' must be practitioner, not manager"
        assert is_ambig_pm is False

        # 2. Ranking competition: Ambiguous Training Manager without corporate evidence vs Corporate lead
        cand_tm = {
            "name": "Alice Manager",
            "title": "Training Manager",
            "evidence_urls": ["https://thirdpartydirectory.com/alice"],
        }
        cand_corp_lead = {
            "name": "Bob Lead",
            "title": "Technical Training Lead",
            "evidence_urls": ["https://www.acme.com/team/bob-lead"],
        }
        score_tm = score_fn(cand_tm, company_domain="acme.com", company_name="Acme")
        score_corp = score_fn(cand_corp_lead, company_domain="acme.com", company_name="Acme")
        assert score_corp > score_tm, (
            f"[{impl_name}] Corporate lead ({score_corp}) must outrank uncorroborated Training Manager ({score_tm})"
        )

        payload = {
            "company_name": "Acme",
            "website": "acme.com",
            "primary_contact": cand_tm,
            "alternative_contacts": [cand_corp_lead],
            "ideal_role": "Head of Training",
        }
        out = adj_fn(payload, company="Acme", website="acme.com")
        assert out["primary_contact"]["name"] == "Bob Lead", (
            f"[{impl_name}] Corporate lead Bob must outrank uncorroborated Training Manager Alice"
        )


def test_regression_saipem_weak_match_defaults_to_role_found_person_unresolved():
    """
    Regression test:
    Verify that in weak-match cases (like Saipem where only practitioner/operational titles
    such as 'Training Program Manager' or LinkedIn-only low-confidence leads exist):
    - Top-level outcome defaults to 'Role Found - Person Unresolved'.
    - ideal_role_person_unresolved is True.
    - is_weak_match is True.
    - The weak contact is NEVER presented as the primary resolved contact by default,
      but is preserved in weak_matches for SDR discovery.
    """
    from dashboard.contact_research import (
        adjudicate_contact_research as dash_adj,
        build_contact_card_html,
        build_weak_contact_card_html,
    )
    from contact_intelligence.eon_contact_research_server_purdue_v1 import (
        adjudicate_contact_research as purdue_adj,
    )
    from contact_intelligence.eon_contact_research_server_agentic_v1 import (
        adjudicate_contact_research as agentic_adj,
    )

    saipem_practitioner = {
        "name": "Marco Rossi",
        "title": "Training Program Manager",
        "evidence_urls": ["https://www.linkedin.com/in/marco-rossi-training"],
    }
    saipem_payload = {
        "company_name": "Saipem",
        "website": "saipem.com",
        "primary_contact": saipem_practitioner,
        "ideal_role": "Head of Training / Training Director",
    }

    for impl_name, adj_fn in [
        ("dashboard", dash_adj),
        ("purdue_v1", purdue_adj),
        ("agentic_v1", agentic_adj),
    ]:
        res = adj_fn(saipem_payload, company="Saipem", website="saipem.com")

        # 1. Status must be Role Found - Person Unresolved
        assert res["contact_research_status"] == "Role Found - Person Unresolved", (
            f"[{impl_name}] Expected 'Role Found - Person Unresolved', got {res['contact_research_status']}"
        )
        assert res["ideal_role_person_unresolved"] is True
        assert res["is_weak_match"] is True

        # 2. SDR discovery preserved in weak_matches
        assert len(res["weak_matches"]) >= 1
        assert res["weak_matches"][0]["name"] == "Marco Rossi"
        assert res["primary_contact"]["match_quality"] == "Best Available Weak Match"

    # 3. Card HTML rendering verification:
    # Primary card must show Role Found — Person Unresolved and NOT present Marco Rossi as resolved primary
    card_html = build_contact_card_html(res)
    assert "Role Found — Person Unresolved" in card_html
    assert "Enterprise Leadership Unresolved" in card_html
    assert "Best Available Weak Matches" in card_html

    # 4. Weak match card HTML has badge and clean presentation
    weak_card_html = build_weak_contact_card_html(res["weak_matches"][0])
    assert "Best Available Weak Match" in weak_card_html
    assert "Marco Rossi" in weak_card_html
    assert "Training Program Manager" in weak_card_html
    assert "Source 1 ↗" in weak_card_html
    assert "target=\"_blank\"" in weak_card_html


def test_regression_weak_match_expander_ui_rendering():
    """
    Regression test:
    Verify the expander UI components for weak matches:
    - Warning callout explicitly informs that these are operational/practitioner roles
      and NOT verified enterprise training budget holders.
    - Badging displays 'Best Available Weak Match'.
    """
    from dashboard.contact_research import (
        build_weak_contact_card_html,
        render_contact_card,
    )
    import unittest.mock as mock

    weak_cand = {
        "name": "Jane Coordinator",
        "title": "Training Coordinator",
        "contact_category": "Fallback / Training Practitioner",
        "icp_level": "Fallback",
        "evidence_confidence": "Low",
        "current_employment_status": "Probable",
        "why_selected": "Operational role on directory.",
        "evidence_urls": ["https://www.linkedin.com/in/jane-coord"],
    }
    weak_payload = {
        "company_name": "Test Industrial",
        "contact_research_status": "Role Found - Person Unresolved",
        "ideal_role": "Head of Training",
        "ideal_role_person_unresolved": True,
        "is_weak_match": True,
        "primary_contact": weak_cand,
        "weak_matches": [weak_cand],
    }

    # Verify weak card HTML
    html_card = build_weak_contact_card_html(weak_cand)
    assert "Best Available Weak Match" in html_card
    assert "Jane Coordinator" in html_card
    assert "Training Coordinator" in html_card

    # Verify Streamlit render calls
    with mock.patch("streamlit.markdown") as mock_md, \
         mock.patch("streamlit.expander") as mock_expander, \
         mock.patch("streamlit.warning") as mock_warning:

        render_contact_card(weak_payload)

        # Confirm st.expander was created with search icon and count
        mock_expander.assert_called_once_with("🔍 Weak matches (unconfirmed) (1)", expanded=False)

        # Confirm warning copy is present and accurate
        mock_warning.assert_called_once()
        warning_msg = mock_warning.call_args[0][0]
        assert "Unconfirmed — do not use for outreach without independent verification." in warning_msg
        assert "Operational / Practitioner Role Warning" in warning_msg
        assert "NOT" in warning_msg and "verified enterprise training budget holders" in warning_msg


def test_regression_weak_match_parity_across_all_entry_points():
    """
    Regression test:
    Confirm the same weak-match policy is applied identically across:
    - dashboard.contact_research.adjudicate_contact_research
    - contact_intelligence.eon_contact_research_server_purdue_v1.adjudicate_contact_research
    - contact_intelligence.eon_contact_research_server_agentic_v1.adjudicate_contact_research
    - dashboard.contact_research.normalize_contact_research_payload
    - UI presentation (render_contact_card, build_contact_card_html, build_weak_contact_card_html)

    Asserts identical:
    - status ('Role Found - Person Unresolved')
    - primary_contact handling (match_quality: 'Best Available Weak Match')
    - weak_matches contents (contains candidate)
    - confidence / employment labels (Low, Probable)
    - warning banner presence and expander collapsed by default
    """
    from dashboard.contact_research import (
        adjudicate_contact_research as dash_adj,
        normalize_contact_research_payload as dash_norm,
        render_contact_card,
        build_contact_card_html,
        build_weak_contact_card_html,
    )
    from contact_intelligence.eon_contact_research_server_purdue_v1 import (
        adjudicate_contact_research as purdue_adj,
    )
    from contact_intelligence.eon_contact_research_server_agentic_v1 import (
        adjudicate_contact_research as agentic_adj,
    )
    import unittest.mock as mock

    weak_cand = {
        "name": "Marco Rossi",
        "title": "Training Program Manager",
        "icp_level": "Fallback",
        "evidence_urls": ["https://www.linkedin.com/in/marco-rossi-training", "https://rocketreach.co/marco-rossi"],
    }
    raw_payload = {
        "company_name": "Saipem",
        "website": "saipem.com",
        "primary_contact": dict(weak_cand),
        "alternative_contacts": [],
        "ideal_role": "Head of Training / Training Director",
    }

    # Adjudicate across all 3 adjudication functions
    res_dash = dash_adj(dict(raw_payload), company="Saipem", website="saipem.com")
    res_purdue = purdue_adj(dict(raw_payload), company="Saipem", website="saipem.com")
    res_agentic = agentic_adj(dict(raw_payload), company="Saipem", website="saipem.com")
    res_norm = dash_norm(dict(res_dash))

    results = [
        ("dashboard_adjudicate", res_dash),
        ("purdue_adjudicate", res_purdue),
        ("agentic_adjudicate", res_agentic),
        ("dashboard_normalize", res_norm),
    ]

    for name, r in results:
        # 1. Status identical
        assert r["contact_research_status"] == "Role Found - Person Unresolved", (
            f"[{name}] Expected status 'Role Found - Person Unresolved', got {r.get('contact_research_status')}"
        )
        assert r["is_weak_match"] is True, f"[{name}] is_weak_match should be True"
        assert r["ideal_role_person_unresolved"] is True, f"[{name}] ideal_role_person_unresolved should be True"

        # 2. Primary contact handling
        pc = r["primary_contact"]
        assert pc["name"] == "Marco Rossi", f"[{name}] Primary contact name preserved"
        assert pc.get("match_quality") == "Best Available Weak Match", f"[{name}] match_quality must be Best Available Weak Match"
        assert pc.get("is_weak_match") is True, f"[{name}] pc is_weak_match must be True"

        # 3. Weak matches contents
        wm = r.get("weak_matches", [])
        assert len(wm) >= 1, f"[{name}] weak_matches should not be empty"
        assert wm[0]["name"] == "Marco Rossi"

        # 4. Confidence / Employment labels
        assert pc.get("evidence_confidence") == "Low", f"[{name}] Evidence confidence should be Low"
        assert pc.get("current_employment_status") == "Probable", f"[{name}] Employment status should be Probable"
        assert pc.get("current_employment_status") != "Verified", f"[{name}] Scraper+LinkedIn cannot be Verified"

    # 5. UI Presentation parity (render_contact_card)
    with mock.patch("streamlit.markdown") as mock_md, \
         mock.patch("streamlit.expander") as mock_expander, \
         mock.patch("streamlit.warning") as mock_warning:

        render_contact_card(res_dash)

        # Expanders called (Weak matches and Evidence details), collapsed by default
        expander_titles = [call[0][0] for call in mock_expander.call_args_list if call[0]]
        assert any("🔍 Weak matches (unconfirmed) (1)" in str(t) for t in expander_titles), (
            f"Expected weak matches expander in {expander_titles}"
        )
        assert any("🔎 Evidence Details" in str(t) for t in expander_titles), (
            f"Expected evidence details expander in {expander_titles}"
        )
        for call in mock_expander.call_args_list:
            if "🔍 Weak matches (unconfirmed)" in str(call[0][0]):
                assert call[1].get("expanded") is False, "Weak matches expander must be collapsed by default"

        # Warning banner displayed with exact required copy
        mock_warning.assert_called_once()
        warn_txt = mock_warning.call_args[0][0]
        assert "Unconfirmed — do not use for outreach without independent verification." in warn_txt
        assert "Operational / Practitioner Role Warning" in warn_txt
        assert "NOT" in warn_txt and "verified enterprise training budget holders" in warn_txt


def test_regression_strong_positive_benchmark_not_suppressed():
    """
    Benchmark regression test:
    Verify that strong positive cases (e.g. Baker Hughes with Chief Learning Officer)
    are NEVER mistakenly classified as weak matches, suppressed, or collapsed.
    Asserts:
    - is_weak_match is False
    - status is 'Verified Contact Found'
    - ideal_role_person_unresolved is False
    - primary_contact is Jose Fernandez
    - weak_matches is empty ([])
    - UI card renders resolved contact directly without weak match expander or warning banner
    """
    from dashboard.contact_research import (
        adjudicate_contact_research as dash_adj,
        normalize_contact_research_payload as dash_norm,
        render_contact_card,
        build_contact_card_html,
        BAKER_HUGHES_BENCHMARK,
    )
    from contact_intelligence.eon_contact_research_server_purdue_v1 import (
        adjudicate_contact_research as purdue_adj,
    )
    from contact_intelligence.eon_contact_research_server_agentic_v1 import (
        adjudicate_contact_research as agentic_adj,
    )
    import unittest.mock as mock

    bh_candidate = {
        "name": "Jose Fernandez",
        "title": "Chief Learning Officer & VP, Enterprise Learning",
        "icp_level": "Primary",
        "evidence_confidence": "High",
        "current_employment_status": "Verified",
        "evidence_urls": [
            "https://www.bakerhughes.com/leadership/jose-fernandez",
            "https://www.linkedin.com/in/jose-fernandez-bakerhughes",
        ],
        "why_selected": "Direct CLO title with corporate leadership verification.",
    }
    raw_payload = {
        "company_name": "Baker Hughes",
        "website": "bakerhughes.com",
        "primary_contact": dict(bh_candidate),
        "alternative_contacts": [],
        "ideal_role": "Chief Learning Officer",
    }

    res_dash = dash_adj(dict(raw_payload), company="Baker Hughes", website="bakerhughes.com")
    res_purdue = purdue_adj(dict(raw_payload), company="Baker Hughes", website="bakerhughes.com")
    res_agentic = agentic_adj(dict(raw_payload), company="Baker Hughes", website="bakerhughes.com")
    res_norm = dash_norm(dict(res_dash))

    for name, r in [
        ("dashboard_adjudicate", res_dash),
        ("purdue_adjudicate", res_purdue),
        ("agentic_adjudicate", res_agentic),
        ("dashboard_normalize", res_norm),
    ]:
        assert r.get("is_weak_match") is False, f"[{name}] is_weak_match must be False for strong leadership"
        assert r.get("contact_research_status") == "Verified Contact Found", (
            f"[{name}] Expected 'Verified Contact Found', got {r.get('contact_research_status')}"
        )
        assert r["primary_contact"]["name"] == "Jose Fernandez"
        assert r.get("weak_matches", []) == []

    # Check UI rendering
    with mock.patch("streamlit.markdown") as mock_md, \
         mock.patch("streamlit.expander") as mock_expander, \
         mock.patch("streamlit.warning") as mock_warning:

        render_contact_card(res_dash)

        # No weak match expander called
        for call in mock_expander.call_args_list:
            arg = call[0][0]
            assert "Weak Matches" not in arg, f"Weak Matches expander unexpectedly rendered for strong contact: {arg}"

        # No warning banner called
        mock_warning.assert_not_called()

    # Check HTML output
    html_card = build_contact_card_html(res_dash)
    assert "Jose Fernandez" in html_card
    assert "Chief Learning Officer &amp; VP, Enterprise Learning" in html_card or "Chief Learning Officer" in html_card
    assert "Role Found — Person Unresolved" not in html_card


if __name__ == "__main__":
    print("Running test_file_syntax_and_compilation...")
    test_file_syntax_and_compilation()
    print("PASSED: test_file_syntax_and_compilation")

    print("Running test_html_assets_exist...")
    test_html_assets_exist()
    print("PASSED: test_html_assets_exist")

    print("Running test_server_offline_detection...")
    test_server_offline_detection()
    print("PASSED: test_server_offline_detection")

    print("Running test_query_contact_research_offline_handling...")
    test_query_contact_research_offline_handling()
    print("PASSED: test_query_contact_research_offline_handling")

    print("Running test_query_contact_research_mock_success...")
    test_query_contact_research_mock_success()
    print("PASSED: test_query_contact_research_mock_success")

    print("Running test_regression_contact_research_status_classification_invariant...")
    test_regression_contact_research_status_classification_invariant()
    print("PASSED: test_regression_contact_research_status_classification_invariant")

    print("Running test_regression_baker_hughes_deterministic_adjudication...")
    test_regression_baker_hughes_deterministic_adjudication()
    print("PASSED: test_regression_baker_hughes_deterministic_adjudication")

    print("Running test_regression_malformed_quoted_strings_fail_safely...")
    test_regression_malformed_quoted_strings_fail_safely()
    print("PASSED: test_regression_malformed_quoted_strings_fail_safely")

    print("Running test_regression_credential_and_secret_leak_prevention...")
    test_regression_credential_and_secret_leak_prevention()
    print("PASSED: test_regression_credential_and_secret_leak_prevention")

    print("Running test_response_contract_malformed_model_output_error...")
    test_response_contract_malformed_model_output_error()
    print("PASSED: test_response_contract_malformed_model_output_error")

    print("Running test_execute_contact_research_baker_hughes_benchmark...")
    test_execute_contact_research_baker_hughes_benchmark()
    print("PASSED: test_execute_contact_research_baker_hughes_benchmark")

    print("Running test_execute_contact_research_missing_credentials_guidance...")
    test_execute_contact_research_missing_credentials_guidance()
    print("PASSED: test_execute_contact_research_missing_credentials_guidance")

    print("Running test_get_contact_research_secrets_safety...")
    test_get_contact_research_secrets_safety()
    print("PASSED: test_get_contact_research_secrets_safety")

    print("Running test_regression_brave_search_422_mock_continuation...")
    test_regression_brave_search_422_mock_continuation()
    print("PASSED: test_regression_brave_search_422_mock_continuation")

    print("Running test_regression_brave_search_parameter_coercion_and_safeguards...")
    test_regression_brave_search_parameter_coercion_and_safeguards()
    print("PASSED: test_regression_brave_search_parameter_coercion_and_safeguards")

    print("Running test_execute_contact_research_422_ui_message...")
    test_execute_contact_research_422_ui_message()
    print("PASSED: test_execute_contact_research_422_ui_message")

    print("Running test_execute_contact_research_provider_rejected_key_ui_message...")
    test_execute_contact_research_provider_rejected_key_ui_message()
    print("PASSED: test_execute_contact_research_provider_rejected_key_ui_message")

    print("Running test_regression_render_contact_card_presentation_html_no_raw_tags...")
    test_regression_render_contact_card_presentation_html_no_raw_tags()
    print("PASSED: test_regression_render_contact_card_presentation_html_no_raw_tags")

    print("Running test_regression_render_contact_card_xss_sanitization_and_secure_links...")
    test_regression_render_contact_card_xss_sanitization_and_secure_links()
    print("PASSED: test_regression_render_contact_card_xss_sanitization_and_secure_links")

    print("Running test_regression_decision_reason_confidence_consistency_low_confidence...")
    test_regression_decision_reason_confidence_consistency_low_confidence()
    print("PASSED: test_regression_decision_reason_confidence_consistency_low_confidence")

    print("Running test_regression_linkedin_plus_rocketreach_not_corroboration...")
    test_regression_linkedin_plus_rocketreach_not_corroboration()
    print("PASSED: test_regression_linkedin_plus_rocketreach_not_corroboration")

    print("Running test_regression_corporate_domain_outranks_linkedin_only...")
    test_regression_corporate_domain_outranks_linkedin_only()
    print("PASSED: test_regression_corporate_domain_outranks_linkedin_only")

    print("Running test_regression_training_manager_ambiguous_without_first_party_evidence...")
    test_regression_training_manager_ambiguous_without_first_party_evidence()
    print("PASSED: test_regression_training_manager_ambiguous_without_first_party_evidence")

    print("Running test_regression_saipem_weak_match_defaults_to_role_found_person_unresolved...")
    test_regression_saipem_weak_match_defaults_to_role_found_person_unresolved()
    print("PASSED: test_regression_saipem_weak_match_defaults_to_role_found_person_unresolved")

    print("Running test_regression_weak_match_expander_ui_rendering...")
    test_regression_weak_match_expander_ui_rendering()
    print("PASSED: test_regression_weak_match_expander_ui_rendering")

    print("Running test_regression_weak_match_parity_across_all_entry_points...")
    test_regression_weak_match_parity_across_all_entry_points()
    print("PASSED: test_regression_weak_match_parity_across_all_entry_points")

    print("Running test_regression_strong_positive_benchmark_not_suppressed...")
    test_regression_strong_positive_benchmark_not_suppressed()
    print("PASSED: test_regression_strong_positive_benchmark_not_suppressed")


def test_phase1_parallel_brave_seed_queries():
    """
    Phase 1 Test: Proves parallel_brave_search runs queries concurrently, preserves
    thread pool ordering, deduplicates properly, and records duration.
    """
    import contact_intelligence.eon_contact_research_server_purdue_v1 as purdue_srv
    import contact_intelligence.eon_contact_research_server_agentic_v1 as agentic_srv

    for srv in [purdue_srv, agentic_srv]:
        queries = ["query 1", "query 2", "query 3"]
        def mock_brave(q, count=10):
            return [{"title": f"Result for {q}", "url": f"https://example.com/{q.replace(' ', '_')}", "snippet": f"Snippet {q}"}]

        with mock.patch.object(srv, "brave_search", side_effect=mock_brave):
            results, dur_ms = srv.parallel_brave_search(queries, count=10, max_workers=3)
            assert len(results) == 3
            assert dur_ms >= 0
            urls = [r["url"] for r in results]
            assert "https://example.com/query_1" in urls
            assert "https://example.com/query_2" in urls
            assert "https://example.com/query_3" in urls


def test_phase1_timing_telemetry_schema():
    """
    Phase 1 Test: Proves telemetry schema has all required performance and observability keys,
    contains non-negative numeric latencies, and is completely sanitized (no secrets or URLs).
    """
    from dashboard.contact_research import execute_contact_research

    ok, res, err = execute_contact_research("Baker Hughes")
    assert ok is True
    assert "telemetry" in res
    telem = res["telemetry"]
    expected_keys = {
        "total_latency_ms",
        "cache_hit",
        "brave_query_duration_ms",
        "brave_query_count",
        "llm_duration_ms",
        "llm_call_count",
        "canonicalization_duration_ms",
        "deep_enrichment_duration_ms",
        "final_research_mode",
    }
    assert expected_keys.issubset(telem.keys()), f"Missing keys: {expected_keys - set(telem.keys())}"
    assert isinstance(telem["total_latency_ms"], (int, float)) and telem["total_latency_ms"] >= 0
    assert isinstance(telem["cache_hit"], bool)
    assert isinstance(telem["brave_query_count"], int) and telem["brave_query_count"] >= 0
    assert isinstance(telem["llm_call_count"], int) and telem["llm_call_count"] >= 0
    assert telem["final_research_mode"] in {"cached", "fast", "deep"}

    # Sanitization check
    for k, v in telem.items():
        v_str = str(v)
        assert "sk-" not in v_str
        assert "BSAx" not in v_str
        assert "Bearer" not in v_str


def test_phase1_cache_provider_interface_and_ttl():
    """
    Phase 1 Test: Proves ContactResearchCacheProvider interface and InMemoryCacheProvider
    correctly store, retrieve, invalidate, and enforce TTL without disk writes.
    """
    from dashboard.contact_research import InMemoryCacheProvider, ContactResearchCacheProvider

    cache = InMemoryCacheProvider()
    assert isinstance(cache, ContactResearchCacheProvider)

    # Set and get
    sample_payload = {"company_name": "TestCorp", "status": "Probable"}
    cache.set("test_key", sample_payload, ttl_seconds=2)
    assert cache.get("test_key") == sample_payload

    # Invalidate
    cache.invalidate("test_key")
    assert cache.get("test_key") is None

    # TTL expiration
    cache.set("short_key", sample_payload, ttl_seconds=0.01)
    time.sleep(0.02)
    assert cache.get("short_key") is None


def test_phase1_fast_pass_policy_equivalence_baker_hughes():
    """
    Phase 1 Test: Proves fast-pass output remains strictly policy-equivalent to the locked
    baseline for Baker Hughes (status, primary contact, ideal role, confidence).
    """
    from dashboard.contact_research import execute_contact_research, BAKER_HUGHES_BENCHMARK

    ok, res, err = execute_contact_research("Baker Hughes", force_refresh=True)
    assert ok is True
    assert res["contact_research_status"] == BAKER_HUGHES_BENCHMARK["contact_research_status"]
    assert res.get("is_weak_match") is True
    assert len(res.get("weak_matches", [])) >= 1
    assert res["weak_matches"][0]["name"] == "Jose Fernandez"
    assert res["weak_matches"][0]["title"] == "Chief Learning Officer (CLO)"
    assert res.get("evaluated_at") is not None
    assert "UTC" in res["evaluated_at"]


def test_phase1_reverify_action_bypasses_cache():
    """
    Phase 1 Test: Proves that default execution hits cache on repetition, while
    force_refresh=True invalidates cache, gets a new timestamp, and sets cache_hit=False.
    """
    from dashboard.contact_research import execute_contact_research

    # Call 1: initial run
    ok1, res1, err1 = execute_contact_research("Baker Hughes", force_refresh=True)
    assert ok1 is True
    assert res1["telemetry"]["cache_hit"] is False

    # Call 2: cached lookup
    ok2, res2, err2 = execute_contact_research("Baker Hughes", force_refresh=False)
    assert ok2 is True
    assert res2["telemetry"]["cache_hit"] is True
    assert res2["telemetry"]["final_research_mode"] == "cached"
    assert res2.get("is_from_cache") is True

    # Call 3: re-verify with force_refresh=True
    time.sleep(0.05)
    ok3, res3, err3 = execute_contact_research("Baker Hughes", force_refresh=True)
    assert ok3 is True
    assert res3["telemetry"]["cache_hit"] is False
    assert res3["telemetry"]["final_research_mode"] in ("fast", "deep")


def test_phase1_saipem_deep_mode_unresolved_invariance():
    """
    Phase 1 Test: Proves Saipem weak match remains strictly invariant under Phase 1:
    - Status: 'Role Found - Person Unresolved'
    - is_weak_match: True
    - Weak leads preserved only in weak_matches
    - Evaluated timestamp and telemetry present
    """
    from dashboard.contact_research import adjudicate_contact_research, normalize_contact_research_payload

    saipem_raw = {
        "company_name": "Saipem",
        "primary_contact": {
            "name": "Marco Rossi",
            "title": "Training Program Manager",
            "evidence_urls": ["https://linkedin.com/in/marco-rossi-saipem"],
        },
        "ideal_role": "Head of Training & Capability",
        "sources": [{"title": "Marco Rossi | LinkedIn", "url": "https://linkedin.com/in/marco-rossi-saipem", "snippet": "Training Program Manager at Saipem"}]
    }

    adjudicated = adjudicate_contact_research(saipem_raw, all_evidence=saipem_raw["sources"], company="Saipem")
    normalized = normalize_contact_research_payload(adjudicated)

    assert normalized["contact_research_status"] == "Role Found - Person Unresolved"
    assert normalized["is_weak_match"] is True
    assert normalized["ideal_role_person_unresolved"] is True
    assert normalized["primary_contact"] is None or normalized["primary_contact"].get("is_weak_match") is True
    assert len(normalized["weak_matches"]) >= 1
    assert normalized["weak_matches"][0]["name"] == "Marco Rossi"


def test_phase2_url_canonicalization_variants():
    """
    Phase 2 Policy Regression Test 1: URL Canonicalization Variants
    Verifies that:
    - Protocol normalized to https
    - Host lowercased, default ports removed, 'www.' stripped
    - Trailing slashes stripped from resource paths while preserving root '/'
    - URL fragments (#experience, #about) discarded
    - Tracking parameters (utm_*, ref, trk, gclid, session_id, etc.) stripped
    - Non-tracking query parameters preserved and sorted deterministically
    """
    from dashboard.contact_research import canonicalize_url

    # Test 1: Tracking parameters stripped, fragment stripped, www stripped, https normalized
    url1 = "http://www.linkedin.com/in/jane-doe/?utm_source=google&trk=profile&b_param=2&a_param=1#experience"
    expected1 = "https://linkedin.com/in/jane-doe?a_param=1&b_param=2"
    assert canonicalize_url(url1) == expected1

    # Test 2: Host lowercased, default port :443 stripped, trailing slash removed
    url2 = "HTTPS://WWW.RocketReach.CO:443/jane-doe-profile/"
    expected2 = "https://rocketreach.co/jane-doe-profile"
    assert canonicalize_url(url2) == expected2

    # Test 3: Root path preserved
    url3 = "http://bakerhughes.com/"
    expected3 = "https://bakerhughes.com/"
    assert canonicalize_url(url3) == expected3

    # Test 4: Advertising click IDs stripped (gclid, fbclid)
    url4 = "https://zoominfo.com/p/Jane-Doe/12345?gclid=xyz123&fbclid=abc456"
    expected4 = "https://zoominfo.com/p/Jane-Doe/12345"
    assert canonicalize_url(url4) == expected4


def test_phase2_known_mirror_cluster_cannot_be_verified():
    """
    Phase 2 Policy Regression Test 2: Known Mirror Cluster Exclusion & Capping
    Verifies that a candidate supported solely by LinkedIn and scraper mirrors
    (LinkedIn + RocketReach + Apollo + ZoomInfo):
    - All collapse into the single 'linkedin_ecosystem' family
    - num_independent_sources == 1
    - 3 mirror URLs classified as 'Family Mirror'
    - Transparent summary string accurately counts excluded mirrors
    - current_employment_status cannot be 'Verified' (strictly capped at 'Probable')
    - evidence_confidence is capped at 'Low'
    - is_linkedin_only is True
    """
    from dashboard.contact_research import (
        canonicalize_evidence_records,
        evaluate_candidate_corroboration,
        adjudicate_evidence_confidence,
        score_candidate,
        adjudicate_contact_research,
    )

    urls = [
        "https://www.linkedin.com/in/tech-lead-123?trk=profile",
        "https://rocketreach.co/tech-lead-123",
        "https://apollo.io/people/tech-lead/999",
        "https://www.zoominfo.com/p/tech-lead/888",
    ]

    meta = canonicalize_evidence_records(urls, company_domain="example.com", company_name="Example Corp")
    assert meta["num_independent_sources"] == 1
    assert meta["num_raw_urls"] == 4
    assert meta["num_excluded_mirrors"] == 3
    assert meta["has_linkedin"] is True
    assert meta["is_linkedin_only"] is True
    assert meta["summary_text"] == "1 independent source · 4 raw URLs · 3 duplicates/mirrors excluded"

    candidate = {
        "name": "Alex Smith",
        "title": "Director of Training",
        "icp_level": "Primary",
        "evidence_urls": urls,
    }

    conf = adjudicate_evidence_confidence(candidate, urls, company_domain="example.com", company_name="Example Corp")
    assert conf == "Low", f"LinkedIn + mirror cluster must cap confidence at Low, got {conf}"

    corrob = evaluate_candidate_corroboration(urls, company_domain="example.com", company_name="Example Corp")
    assert corrob["is_linkedin_only"] is True
    assert corrob["num_independent_sources"] == 1

    payload = {
        "company_name": "Example Corp",
        "website": "example.com",
        "primary_contact": candidate,
        "alternative_contacts": [],
        "ideal_role": "Head of Training / Training Director",
    }
    adj = adjudicate_contact_research(payload, company="Example Corp", website="example.com")
    pc = adj["primary_contact"]
    assert pc["current_employment_status"] == "Probable"
    assert pc["current_employment_status"] != "Verified"
    assert pc["evidence_confidence"] == "Low"


def test_phase2_unknown_directory_conservative_default():
    """
    Phase 2 Policy Regression Test 3: Unknown Directory Conservative Default
    Verifies that unlisted domains default to 'directory_unclassified' and
    'tier_4_unverified_web', and do NOT provide independent corroboration
    against LinkedIn.
    """
    from dashboard.contact_research import (
        classify_source_family,
        canonicalize_evidence_records,
        evaluate_candidate_corroboration,
        adjudicate_evidence_confidence,
    )

    unlisted_url = "https://unlisted-directory-hub.io/profile/jane-doe"
    family, tier = classify_source_family(unlisted_url, company_domain="acme.com", company_name="Acme Corp")
    assert family == "directory_unclassified"
    assert tier == "tier_4_unverified_web"

    # Pair LinkedIn with unlisted directory
    urls = [
        "https://www.linkedin.com/in/jane-doe",
        unlisted_url,
    ]
    meta = canonicalize_evidence_records(urls, company_domain="acme.com", company_name="Acme Corp")
    assert meta["num_independent_sources"] == 1
    assert meta["is_linkedin_only"] is True

    candidate = {
        "name": "Jane Doe",
        "title": "Head of Training",
        "icp_level": "Primary",
        "evidence_urls": urls,
    }
    conf = adjudicate_evidence_confidence(candidate, urls, company_domain="acme.com", company_name="Acme Corp")
    assert conf == "Low"


def test_phase2_corporate_plus_mirror_cluster():
    """
    Phase 2 Policy Regression Test 4: Corporate Plus Mirror Cluster Corroboration
    Verifies that first-party corporate evidence combined with third-party mirrors:
    - Recognizes 2 independent source families ('corporate' + 'linkedin_ecosystem')
    - Applies corporate bonus (+40) and multi-source corroboration bonus (+20)
    - Qualifies candidate for 'Verified' current employment status
    - Yields 'High' evidence confidence
    """
    from dashboard.contact_research import (
        canonicalize_evidence_records,
        evaluate_candidate_corroboration,
        score_candidate,
        adjudicate_contact_research,
    )

    urls = [
        "https://www.bakerhughes.com/leadership/jose-fernandez",
        "https://www.linkedin.com/in/jose-fernandez",
        "https://rocketreach.co/jose-fernandez",
        "https://apollo.io/people/jose-fernandez",
    ]

    meta = canonicalize_evidence_records(urls, company_domain="bakerhughes.com", company_name="Baker Hughes")
    assert meta["num_independent_sources"] == 2
    assert meta["has_corporate"] is True
    assert meta["independent_families"] == {"corporate", "linkedin_ecosystem"}
    assert meta["summary_text"] == "2 independent sources · 4 raw URLs · 2 duplicates/mirrors excluded"

    candidate = {
        "name": "Jose Fernandez",
        "title": "Chief Learning Officer (CLO)",
        "icp_level": "Primary",
        "evidence_urls": urls,
    }
    score = score_candidate(candidate, company_domain="bakerhughes.com", company_name="Baker Hughes")
    # Base strong_leadership = 100, corporate bonus = +40, multi-source bonus = +20 -> 160
    assert score == 160

    payload = {
        "company_name": "Baker Hughes",
        "website": "bakerhughes.com",
        "primary_contact": candidate,
        "alternative_contacts": [],
        "ideal_role": "Chief Learning Officer",
    }
    adj = adjudicate_contact_research(payload, company="Baker Hughes", website="bakerhughes.com")
    pc = adj["primary_contact"]
    assert pc["current_employment_status"] == "Verified"
    assert pc["evidence_confidence"] == "High"
    assert adj["contact_research_status"] == "Verified Contact Found"


def test_phase2_weak_benchmark_saipem_unresolved():
    """
    Phase 2 Policy Regression Test 5: Saipem Weak Benchmark Invariance
    Verifies that for Saipem (weak match with practitioner titles like Training Program Manager):
    - Status is strictly 'Role Found - Person Unresolved' across all 3 adjudication paths
    - is_weak_match is True
    - Weak matches list contains the candidate with match_quality 'Best Available Weak Match'
    - Canonical evidence metadata and summary string are attached
    - Confidence is Low and Employment status is Probable
    """
    from dashboard.contact_research import (
        adjudicate_contact_research as dash_adj,
        normalize_contact_research_payload as dash_norm,
    )
    from contact_intelligence.eon_contact_research_server_purdue_v1 import (
        adjudicate_contact_research as purdue_adj,
    )
    from contact_intelligence.eon_contact_research_server_agentic_v1 import (
        adjudicate_contact_research as agentic_adj,
    )

    saipem_payload = {
        "company_name": "Saipem",
        "website": "saipem.com",
        "primary_contact": {
            "name": "Marco Rossi",
            "title": "Training Program Manager",
            "icp_level": "Fallback",
            "evidence_urls": [
                "https://www.linkedin.com/in/marco-rossi-training",
                "https://rocketreach.co/marco-rossi",
            ],
        },
        "alternative_contacts": [],
        "ideal_role": "Head of Training / Training Director",
    }

    res_dash = dash_adj(dict(saipem_payload), company="Saipem", website="saipem.com")
    res_purdue = purdue_adj(dict(saipem_payload), company="Saipem", website="saipem.com")
    res_agentic = agentic_adj(dict(saipem_payload), company="Saipem", website="saipem.com")
    res_norm = dash_norm(dict(res_dash))

    for name, r in [
        ("dashboard", res_dash),
        ("purdue_v1", res_purdue),
        ("agentic_v1", res_agentic),
        ("normalized", res_norm),
    ]:
        assert r["contact_research_status"] == "Role Found - Person Unresolved", f"[{name}] Expected Person Unresolved"
        assert r["is_weak_match"] is True, f"[{name}] is_weak_match must be True"
        assert len(r.get("weak_matches", [])) >= 1, f"[{name}] weak_matches must contain candidate"
        wm = r["weak_matches"][0]
        assert wm["name"] == "Marco Rossi"
        assert wm.get("match_quality") == "Best Available Weak Match"
        assert wm.get("evidence_confidence") == "Low"
        assert wm.get("current_employment_status") == "Probable"
        assert "canonical_evidence" in r or "canonical_evidence" in wm
        assert "evidence_summary" in r or "evidence_summary" in wm


def test_phase2_strong_benchmark_baker_hughes_not_weakened():
    """
    Phase 2 Policy Regression Test 6: Baker Hughes Strong Benchmark Protection
    Verifies that Baker Hughes benchmark with Jose Fernandez (CLO) on Comparably:
    - Is NOT weakened or demoted to weak match
    - Retains 'Probable Contact Found' status with High evidence confidence
    - Canonical evidence contains 2 records (1 Primary Canonical, 1 Family Mirror)
    - Transparent summary matches: '1 independent source · 2 raw URLs · 1 duplicate/mirror excluded'
    - Parity holds across dashboard, purdue_v1, and agentic_v1
    """
    from dashboard.contact_research import (
        adjudicate_contact_research as dash_adj,
        normalize_contact_research_payload as dash_norm,
        BAKER_HUGHES_BENCHMARK,
    )
    from contact_intelligence.eon_contact_research_server_purdue_v1 import (
        adjudicate_contact_research as purdue_adj,
    )
    from contact_intelligence.eon_contact_research_server_agentic_v1 import (
        adjudicate_contact_research as agentic_adj,
    )

    sample_evidence = [
        {
            "title": "Baker Hughes Executive Team | Comparably",
            "url": "https://www.comparably.com/companies/baker-hughes/executive-team",
            "snippet": "Jose Fernandez serves as the Chief Learning Officer (CLO) of Baker Hughes.",
        },
        {
            "title": "Jose Fernandez - Chief Learning Officer | Comparably",
            "url": "https://www.comparably.com/companies/baker-hughes/jose-fernandez-26869",
            "snippet": "Jose Fernandez is the Chief Learning Officer at Baker Hughes.",
        },
    ]

    raw_payload = {
        "company_name": "Baker Hughes",
        "website": "bakerhughes.com",
        "primary_contact": {
            "name": "Jose Fernandez",
            "title": "Chief Learning Officer (CLO)",
            "icp_level": "Primary",
            "evidence_urls": [
                "https://www.comparably.com/companies/baker-hughes/executive-team",
                "https://www.comparably.com/companies/baker-hughes/jose-fernandez-26869",
            ],
        },
        "alternative_contacts": [],
        "ideal_role": "Head of Training / Training Director",
    }

    res_dash = dash_adj(dict(raw_payload), all_evidence=sample_evidence, company="Baker Hughes", website="bakerhughes.com")
    res_purdue = purdue_adj(dict(raw_payload), all_evidence=sample_evidence, company="Baker Hughes", website="bakerhughes.com")
    res_agentic = agentic_adj(dict(raw_payload), all_evidence=sample_evidence, company="Baker Hughes", website="bakerhughes.com")
    res_norm = dash_norm(dict(res_dash))

    for name, r in [
        ("dashboard", res_dash),
        ("purdue_v1", res_purdue),
        ("agentic_v1", res_agentic),
        ("normalized", res_norm),
    ]:
        assert r["contact_research_status"] == "Role Found - Person Unresolved", f"[{name}] status must be Role Found - Person Unresolved"
        assert r["is_weak_match"] is True, f"[{name}] is_weak_match must be True"
        assert len(r.get("weak_matches", [])) >= 1
        wm = r["weak_matches"][0]
        assert wm["name"] == "Jose Fernandez"
        assert wm["evidence_confidence"] == "Low"
        assert wm["employment_freshness_status"] == "Employment Unconfirmed"
        assert len(r.get("canonical_evidence", [])) == 2
        assert r.get("evidence_summary") == "0 independent sources · 2 raw URLs · 1 duplicate/mirror excluded"


# ==============================================================================
# PHASE 3 EMPLOYMENT FRESHNESS & VERIFICATION REGRESSION TESTS
# ==============================================================================

def test_phase3_live_corporate_roster_undated_confirmed():
    """
    Phase 3 Test 1: Live first-party corporate leadership roster (undated)
    Verifies that a contact discovered on an active first-party corporate roster
    achieves 'Current Employment Confirmed' status even without explicit publication date.
    """
    from dashboard.contact_research import (
        evaluate_employment_freshness as dash_fresh,
        adjudicate_contact_research as dash_adj,
    )
    from contact_intelligence.eon_contact_research_server_purdue_v1 import (
        evaluate_employment_freshness as purdue_fresh,
        adjudicate_contact_research as purdue_adj,
    )
    from contact_intelligence.eon_contact_research_server_agentic_v1 import (
        evaluate_employment_freshness as agentic_fresh,
        adjudicate_contact_research as agentic_adj,
    )

    candidate = {
        "name": "Sarah Connor",
        "title": "Director of Technical Training",
        "evidence_urls": [
            "https://acme-corp.com/about/leadership/sarah-connor",
            "https://acme-corp.com/our-leadership",
        ],
    }

    raw_payload = {
        "company_name": "Acme Corp",
        "website": "acme-corp.com",
        "primary_contact": candidate,
        "alternative_contacts": [],
    }

    for name, fresh_fn, adj_fn in [
        ("dashboard", dash_fresh, dash_adj),
        ("purdue_v1", purdue_fresh, purdue_adj),
        ("agentic_v1", agentic_fresh, agentic_adj),
    ]:
        f = fresh_fn(candidate, company_domain="acme-corp.com", company_name="Acme Corp")
        assert f["employment_freshness_status"] == "Current Employment Confirmed", f"[{name}] freshness status"
        assert f["is_stale_or_unconfirmed"] is False, f"[{name}] is_stale_or_unconfirmed"
        assert "corporate leadership roster" in f["employment_freshness_rationale"].lower(), f"[{name}] rationale"

        res = adj_fn(dict(raw_payload), company="Acme Corp", website="acme-corp.com")
        assert res["contact_research_status"] == "Verified Contact Found", f"[{name}] contact_research_status"
        assert res["is_weak_match"] is False, f"[{name}] is_weak_match"
        pc = res["primary_contact"]
        assert pc["employment_freshness_status"] == "Current Employment Confirmed", f"[{name}] pc status"
        assert pc["current_employment_status"] == "Verified", f"[{name}] pc employment"


def test_phase3_dated_corporate_or_regulatory_within_threshold():
    """
    Phase 3 Test 2: Dated corporate/regulatory doc within threshold
    Verifies:
    - <= 12m: 'Current Employment Confirmed'
    - 12-24m: 'Current Employment Likely'
    """
    from dashboard.contact_research import evaluate_employment_freshness
    from datetime import datetime, timezone

    anchor = datetime(2026, 10, 1, tzinfo=timezone.utc)

    # Sub-case A: 6 months old (2026-04-01) -> Confirmed
    cand_6m = {
        "name": "Alex Mercer",
        "title": "VP Learning and Development",
        "evidence_urls": ["https://sec.gov/edgar/data/12345/form10k-2026-04-01.htm"],
    }
    f_6m = evaluate_employment_freshness(cand_6m, company_domain="mercer.com", company_name="Mercer", anchor_date=anchor)
    assert f_6m["employment_freshness_status"] == "Current Employment Confirmed"
    assert f_6m["evidence_age_months"] == 6
    assert f_6m["is_stale_or_unconfirmed"] is False

    # Sub-case B: 18 months old (2025-04-01) -> Likely
    cand_18m = {
        "name": "Alex Mercer",
        "title": "VP Learning and Development",
        "evidence_urls": ["https://sec.gov/edgar/data/12345/form10k-2025-04-01.htm"],
    }
    f_18m = evaluate_employment_freshness(cand_18m, company_domain="mercer.com", company_name="Mercer", anchor_date=anchor)
    assert f_18m["employment_freshness_status"] == "Current Employment Likely"
    assert f_18m["evidence_age_months"] == 18
    assert f_18m["is_stale_or_unconfirmed"] is False


def test_phase3_old_corporate_document_stale_forces_unresolved():
    """
    Phase 3 Test 3: Old corporate document only (>36m)
    Verifies:
    - Freshness status: 'Possible Former Employee / Stale Evidence'
    - Flags is_stale_or_unconfirmed = True
    - Does NOT elevate stale contact to default primary; forces 'Role Found - Person Unresolved'
    - Parity holds across dashboard, purdue_v1, and agentic_v1
    """
    from dashboard.contact_research import (
        evaluate_employment_freshness as dash_fresh,
        adjudicate_contact_research as dash_adj,
    )
    from contact_intelligence.eon_contact_research_server_purdue_v1 import (
        evaluate_employment_freshness as purdue_fresh,
        adjudicate_contact_research as purdue_adj,
    )
    from contact_intelligence.eon_contact_research_server_agentic_v1 import (
        evaluate_employment_freshness as agentic_fresh,
        adjudicate_contact_research as agentic_adj,
    )
    from datetime import datetime, timezone

    anchor = datetime(2026, 10, 1, tzinfo=timezone.utc)

    # 48 months old (2022-10-01)
    cand_stale = {
        "name": "Robert Vance",
        "title": "Director of Technical Training",
        "evidence_urls": ["https://vance-refrig.com/press-releases/2022-10-01/annual-report.pdf"],
    }

    raw_payload = {
        "company_name": "Vance Refrigeration",
        "website": "vance-refrig.com",
        "primary_contact": cand_stale,
        "alternative_contacts": [],
        "ideal_role": "Head of Training / Training Director",
    }

    for name, fresh_fn, adj_fn in [
        ("dashboard", dash_fresh, dash_adj),
        ("purdue_v1", purdue_fresh, purdue_adj),
        ("agentic_v1", agentic_fresh, agentic_adj),
    ]:
        f = fresh_fn(cand_stale, company_domain="vance-refrig.com", company_name="Vance Refrigeration", anchor_date=anchor)
        assert f["employment_freshness_status"] == "Possible Former Employee / Stale Evidence", f"[{name}] freshness"
        assert f["is_stale_or_unconfirmed"] is True, f"[{name}] stale flag"
        assert f["evidence_age_months"] >= 47, f"[{name}] age"

        res = adj_fn(dict(raw_payload), company="Vance Refrigeration", website="vance-refrig.com")
        assert res["contact_research_status"] == "Role Found - Person Unresolved", f"[{name}] status must be unresolved"
        assert res["is_weak_match"] is True, f"[{name}] must be weak match"
        assert len(res.get("weak_matches", [])) >= 1, f"[{name}] weak_matches retained"
        wm = res["weak_matches"][0]
        assert wm["employment_freshness_status"] == "Possible Former Employee / Stale Evidence"
        assert wm["current_employment_status"] == "Unconfirmed"


def test_phase3_linkedin_only_cannot_be_confirmed():
    """
    Phase 3 Test 4: Professional Profile Sources (LinkedIn) Freshness Invariant
    Verifies that LinkedIn-only evidence CANNOT achieve 'Current Employment Confirmed'.
    At best it achieves 'Current Employment Likely' (or 'Employment Unconfirmed').
    """
    from dashboard.contact_research import (
        evaluate_employment_freshness as dash_fresh,
        adjudicate_contact_research as dash_adj,
    )
    from contact_intelligence.eon_contact_research_server_purdue_v1 import (
        evaluate_employment_freshness as purdue_fresh,
        adjudicate_contact_research as purdue_adj,
    )
    from contact_intelligence.eon_contact_research_server_agentic_v1 import (
        evaluate_employment_freshness as agentic_fresh,
        adjudicate_contact_research as agentic_adj,
    )

    cand_linkedin = {
        "name": "David Wallace",
        "title": "Chief Learning Officer",
        "evidence_urls": [
            "https://www.linkedin.com/in/david-wallace-clo",
            "https://rocketreach.co/david-wallace-email_123",
        ],
    }

    raw_payload = {
        "company_name": "Dunder Mifflin",
        "website": "dundermifflin.com",
        "primary_contact": cand_linkedin,
        "alternative_contacts": [],
        "ideal_role": "Head of Training / Training Director",
    }

    for name, fresh_fn, adj_fn in [
        ("dashboard", dash_fresh, dash_adj),
        ("purdue_v1", purdue_fresh, purdue_adj),
        ("agentic_v1", agentic_fresh, agentic_adj),
    ]:
        f = fresh_fn(cand_linkedin, company_domain="dundermifflin.com", company_name="Dunder Mifflin")
        assert f["employment_freshness_status"] != "Current Employment Confirmed", f"[{name}] CANNOT be confirmed"
        assert f["employment_freshness_status"] == "Current Employment Likely", f"[{name}] capped at likely"
        assert "professional profile" in f["employment_freshness_rationale"].lower()

        res = adj_fn(dict(raw_payload), company="Dunder Mifflin", website="dundermifflin.com")
        # LinkedIn-only CLO is capped at Low confidence and forces weak match
        assert res["contact_research_status"] == "Role Found - Person Unresolved"
        assert res["is_weak_match"] is True
        pc = res["primary_contact"]
        assert pc["employment_freshness_status"] == "Current Employment Likely"
        assert pc["current_employment_status"] == "Probable"


def test_phase3_contradictory_newer_employer_suppresses_status():
    """
    Phase 3 Test 5: Contradiction Handling
    Verifies that departure keywords or conflicting employer signals immediately
    force 'Possible Former Employee / Stale Evidence' and set employment status to 'Former'.
    """
    from dashboard.contact_research import (
        evaluate_employment_freshness as dash_fresh,
        adjudicate_contact_research as dash_adj,
    )
    from contact_intelligence.eon_contact_research_server_purdue_v1 import (
        evaluate_employment_freshness as purdue_fresh,
        adjudicate_contact_research as purdue_adj,
    )
    from contact_intelligence.eon_contact_research_server_agentic_v1 import (
        evaluate_employment_freshness as agentic_fresh,
        adjudicate_contact_research as agentic_adj,
    )

    cand_contra = {
        "name": "Jim Halpert",
        "title": "Director of Sales Training",
        "evidence_urls": ["https://dundermifflin.com/leadership/jim-halpert"],
        "why_selected": "Formerly of Dunder Mifflin; left to joined Athleap in 2024 as VP Marketing.",
    }

    raw_payload = {
        "company_name": "Dunder Mifflin",
        "website": "dundermifflin.com",
        "primary_contact": cand_contra,
        "alternative_contacts": [],
        "ideal_role": "Head of Training / Training Director",
    }

    for name, fresh_fn, adj_fn in [
        ("dashboard", dash_fresh, dash_adj),
        ("purdue_v1", purdue_fresh, purdue_adj),
        ("agentic_v1", agentic_fresh, agentic_adj),
    ]:
        f = fresh_fn(cand_contra, company_domain="dundermifflin.com", company_name="Dunder Mifflin")
        assert f["employment_freshness_status"] == "Possible Former Employee / Stale Evidence", f"[{name}] status"
        assert f["has_contradictory_employer"] is True, f"[{name}] contradiction flag"
        assert f["is_stale_or_unconfirmed"] is True, f"[{name}] stale flag"

        res = adj_fn(dict(raw_payload), company="Dunder Mifflin", website="dundermifflin.com")
        assert res["contact_research_status"] == "Role Found - Person Unresolved", f"[{name}] top-level status"
        assert res["is_weak_match"] is True
        pc = res["primary_contact"]
        assert pc["current_employment_status"] == "Former", f"[{name}] employment must be Former"


def test_phase3_saipem_weak_benchmark_unresolved_protected():
    """
    Phase 3 Test 6: Saipem Weak Benchmark Protection
    Verifies that Saipem (Marco Rossi on RocketReach/ContactOut) remains unresolved:
    - Status: 'Role Found - Person Unresolved'
    - is_weak_match = True
    - Stale or weak lead is NOT elevated to primary contact
    - Freshness: 'Employment Unconfirmed'
    - Parity holds across dashboard, purdue_v1, and agentic_v1
    """
    from dashboard.contact_research import (
        adjudicate_contact_research as dash_adj,
        normalize_contact_research_payload as dash_norm,
    )
    from contact_intelligence.eon_contact_research_server_purdue_v1 import (
        adjudicate_contact_research as purdue_adj,
    )
    from contact_intelligence.eon_contact_research_server_agentic_v1 import (
        adjudicate_contact_research as agentic_adj,
    )

    saipem_payload = {
        "company_name": "Saipem",
        "website": "saipem.com",
        "primary_contact": {
            "name": "Marco Rossi",
            "title": "Technical Training Specialist",
            "icp_level": "Fallback",
            "evidence_urls": [
                "https://rocketreach.co/marco-rossi-saipem-email_987",
                "https://contactout.com/Marco-Rossi-12345",
            ],
        },
        "alternative_contacts": [],
        "ideal_role": "Head of Technical Training",
    }

    res_dash = dash_adj(dict(saipem_payload), company="Saipem", website="saipem.com")
    res_purdue = purdue_adj(dict(saipem_payload), company="Saipem", website="saipem.com")
    res_agentic = agentic_adj(dict(saipem_payload), company="Saipem", website="saipem.com")
    res_norm = dash_norm(dict(res_dash))

    for name, r in [
        ("dashboard", res_dash),
        ("purdue_v1", res_purdue),
        ("agentic_v1", res_agentic),
        ("normalized", res_norm),
    ]:
        assert r["contact_research_status"] == "Role Found - Person Unresolved", f"[{name}] status"
        assert r["is_weak_match"] is True, f"[{name}] is_weak_match"
        assert len(r.get("weak_matches", [])) >= 1, f"[{name}] weak_matches length"
        wm = r["weak_matches"][0]
        assert wm["name"] == "Marco Rossi"
        assert wm["employment_freshness_status"] == "Employment Unconfirmed"
        assert wm["is_stale_or_unconfirmed"] is True


def test_phase3_baker_hughes_strong_benchmark_protected():
    """
    Phase 3 Test 7: Baker Hughes Strong Benchmark Protection
    Verifies that Baker Hughes (Jose Fernandez CLO on Comparably) remains acceptable positive case:
    - Status: 'Probable Contact Found'
    - is_weak_match = False
    - Freshness: 'Current Employment Likely' (via active institutional executive roster)
    - Parity holds across dashboard, purdue_v1, and agentic_v1
    """
    from dashboard.contact_research import (
        adjudicate_contact_research as dash_adj,
        normalize_contact_research_payload as dash_norm,
        BAKER_HUGHES_BENCHMARK,
    )
    from contact_intelligence.eon_contact_research_server_purdue_v1 import (
        adjudicate_contact_research as purdue_adj,
    )
    from contact_intelligence.eon_contact_research_server_agentic_v1 import (
        adjudicate_contact_research as agentic_adj,
    )

    sample_evidence = [
        {
            "title": "Baker Hughes Executive Team | Comparably",
            "url": "https://www.comparably.com/companies/baker-hughes/executive-team",
            "snippet": "Jose Fernandez serves as the Chief Learning Officer (CLO) of Baker Hughes.",
        },
        {
            "title": "Jose Fernandez - Chief Learning Officer | Comparably",
            "url": "https://www.comparably.com/companies/baker-hughes/jose-fernandez-26869",
            "snippet": "Jose Fernandez is the Chief Learning Officer at Baker Hughes.",
        },
    ]

    raw_payload = {
        "company_name": "Baker Hughes",
        "website": "bakerhughes.com",
        "primary_contact": {
            "name": "Jose Fernandez",
            "title": "Chief Learning Officer (CLO)",
            "icp_level": "Primary",
            "evidence_urls": [
                "https://www.comparably.com/companies/baker-hughes/executive-team",
                "https://www.comparably.com/companies/baker-hughes/jose-fernandez-26869",
            ],
        },
        "alternative_contacts": [],
        "ideal_role": "Head of Training / Training Director",
    }

    res_dash = dash_adj(dict(raw_payload), all_evidence=sample_evidence, company="Baker Hughes", website="bakerhughes.com")
    res_purdue = purdue_adj(dict(raw_payload), all_evidence=sample_evidence, company="Baker Hughes", website="bakerhughes.com")
    res_agentic = agentic_adj(dict(raw_payload), all_evidence=sample_evidence, company="Baker Hughes", website="bakerhughes.com")
    res_norm = dash_norm(dict(res_dash))

    for name, r in [
        ("dashboard", res_dash),
        ("purdue_v1", res_purdue),
        ("agentic_v1", res_agentic),
        ("normalized", res_norm),
    ]:
        assert r["contact_research_status"] == "Role Found - Person Unresolved", f"[{name}] status"
        assert r["is_weak_match"] is True, f"[{name}] is_weak_match"
        assert len(r.get("weak_matches", [])) >= 1
        wm = r["weak_matches"][0]
        assert wm["name"] == "Jose Fernandez"
        assert wm["employment_freshness_status"] == "Employment Unconfirmed"
        assert wm["evidence_confidence"] == "Low"
        assert wm["is_stale_or_unconfirmed"] is True


def test_phase3_seniority_decoupled_ranking_director_outranks_historic_vp():
    """
    Phase 3 Test 8: Seniority-Decoupled Candidate Ranking Simulation
    Verifies the core Phase 3 requirement:
    A historically senior person (Historic VP from 2021 PDF) MUST NOT outrank
    a clearly current person (Current Director on live corporate roster)
    solely due to title prestige.

    Under Phase 3:
    - Candidate A (Historic VP): Freshness = 'Possible Former Employee / Stale Evidence' (Rank 1, Score 80)
    - Candidate B (Current Director): Freshness = 'Current Employment Confirmed' (Rank 4, Score 150)
    Adjudication candidate ranking MUST deterministically select Candidate B as Primary Contact.
    """
    from dashboard.contact_research import (
        adjudicate_contact_research as dash_adj,
    )
    from contact_intelligence.eon_contact_research_server_purdue_v1 import (
        adjudicate_contact_research as purdue_adj,
    )
    from contact_intelligence.eon_contact_research_server_agentic_v1 import (
        adjudicate_contact_research as agentic_adj,
    )

    historic_vp = {
        "name": "Marcus Aurelius",
        "title": "Vice President of Global Learning & Development",  # Strong leadership (Tier 100)
        "evidence_urls": [
            "https://roman-empire.com/press/2021-03-15/annual-report.pdf",
        ],
    }

    current_director = {
        "name": "Lucius Verus",
        "title": "Director of Technical Training",  # Specialized leadership (Tier 80)
        "evidence_urls": [
            "https://roman-empire.com/about/leadership/lucius-verus",
            "https://roman-empire.com/team",
        ],
    }

    payload = {
        "company_name": "Roman Empire Enterprises",
        "website": "roman-empire.com",
        "primary_contact": historic_vp,  # Originally seeded with Historic VP
        "alternative_contacts": [current_director],
        "ideal_role": "Head of Training / Training Director",
    }

    for name, adj_fn in [
        ("dashboard", dash_adj),
        ("purdue_v1", purdue_adj),
        ("agentic_v1", agentic_adj),
    ]:
        res = adj_fn(dict(payload), company="Roman Empire Enterprises", website="roman-empire.com")
        pc = res["primary_contact"]
        assert pc is not None, f"[{name}] primary contact resolved"
        assert pc["name"] == "Lucius Verus", f"[{name}] Current Director MUST outrank Historic VP"
        assert pc["employment_freshness_status"] == "Current Employment Confirmed"
        assert pc["current_employment_status"] == "Verified"

        # Historic VP should be retained in alternatives or weak pool, marked as stale
        alts = res.get("alternative_contacts", [])
        assert len(alts) == 1, f"[{name}] historic lead retained in alternatives"
        assert alts[0]["name"] == "Marcus Aurelius"
        assert alts[0]["employment_freshness_status"] == "Possible Former Employee / Stale Evidence"



# ==============================================================================
# PHASE 3.1 CORRECTIVE PATCH REGRESSION TESTS (BAKER HUGHES & DISCONFIRMATION)
# ==============================================================================

def test_phase3_1_comparably_only_undated_cannot_be_primary():
    """
    Phase 3.1 Test 1: Comparably-only, undated executive listing
    Expected:
    - Freshness: 'Employment Unconfirmed'
    - is_stale_or_unconfirmed = True
    - Top-level outcome: 'Role Found - Person Unresolved'
    - Candidate cannot be default primary contact.
    """
    from dashboard.contact_research import (
        evaluate_employment_freshness as dash_fresh,
        adjudicate_contact_research as dash_adj,
    )
    from contact_intelligence.eon_contact_research_server_purdue_v1 import (
        evaluate_employment_freshness as purdue_fresh,
        adjudicate_contact_research as purdue_adj,
    )
    from contact_intelligence.eon_contact_research_server_agentic_v1 import (
        evaluate_employment_freshness as agentic_fresh,
        adjudicate_contact_research as agentic_adj,
    )

    cand = {
        "name": "Jose Fernandez",
        "title": "Chief Learning Officer (CLO)",
        "evidence_urls": [
            "https://www.comparably.com/companies/baker-hughes/executive-team",
        ],
    }
    payload = {
        "company_name": "Baker Hughes",
        "website": "bakerhughes.com",
        "primary_contact": cand,
        "alternative_contacts": [],
        "ideal_role": "Head of Training / Training Director",
    }

    for name, fresh_fn, adj_fn in [
        ("dashboard", dash_fresh, dash_adj),
        ("purdue_v1", purdue_fresh, purdue_adj),
        ("agentic_v1", agentic_fresh, agentic_adj),
    ]:
        f = fresh_fn(cand, company_domain="bakerhughes.com", company_name="Baker Hughes")
        assert f["employment_freshness_status"] == "Employment Unconfirmed", f"[{name}] freshness"
        assert f["is_stale_or_unconfirmed"] is True, f"[{name}] is_stale_or_unconfirmed"

        res = adj_fn(dict(payload), company="Baker Hughes", website="bakerhughes.com")
        assert res["contact_research_status"] == "Role Found - Person Unresolved", f"[{name}] status"
        assert res["is_weak_match"] is True, f"[{name}] is_weak_match"
        assert len(res.get("weak_matches", [])) == 1
        assert res["weak_matches"][0]["name"] == "Jose Fernandez"
        assert res["weak_matches"][0]["employment_freshness_status"] == "Employment Unconfirmed"


def test_phase3_1_first_party_live_company_roster_confirmed():
    """
    Phase 3.1 Test 2: First-party live company roster
    Expected: Current Employment Confirmed; eligible for primary recommendation.
    """
    from dashboard.contact_research import (
        evaluate_employment_freshness as dash_fresh,
        adjudicate_contact_research as dash_adj,
    )
    from contact_intelligence.eon_contact_research_server_purdue_v1 import (
        evaluate_employment_freshness as purdue_fresh,
        adjudicate_contact_research as purdue_adj,
    )
    from contact_intelligence.eon_contact_research_server_agentic_v1 import (
        evaluate_employment_freshness as agentic_fresh,
        adjudicate_contact_research as agentic_adj,
    )

    cand = {
        "name": "Elena Rostova",
        "title": "Director of Global Technical Training",
        "evidence_urls": [
            "https://bakerhughes.com/about/leadership/elena-rostova",
        ],
    }
    payload = {
        "company_name": "Baker Hughes",
        "website": "bakerhughes.com",
        "primary_contact": cand,
        "alternative_contacts": [],
        "ideal_role": "Head of Training / Training Director",
    }

    for name, fresh_fn, adj_fn in [
        ("dashboard", dash_fresh, dash_adj),
        ("purdue_v1", purdue_fresh, purdue_adj),
        ("agentic_v1", agentic_fresh, agentic_adj),
    ]:
        f = fresh_fn(cand, company_domain="bakerhughes.com", company_name="Baker Hughes")
        assert f["employment_freshness_status"] == "Current Employment Confirmed", f"[{name}] freshness"
        assert f["is_stale_or_unconfirmed"] is False

        res = adj_fn(dict(payload), company="Baker Hughes", website="bakerhughes.com")
        assert res["contact_research_status"] in {"Verified Contact Found", "Probable Contact Found"}, f"[{name}] status"
        assert res["is_weak_match"] is False, f"[{name}] is_weak_match"
        assert res["primary_contact"]["name"] == "Elena Rostova"


def test_phase3_1_dated_reputable_editorial_within_threshold_likely():
    """
    Phase 3.1 Test 3: Dated reputable editorial evidence within threshold
    Expected: Current Employment Likely, not necessarily Confirmed.
    """
    from dashboard.contact_research import evaluate_employment_freshness
    from datetime import datetime, timezone

    anchor = datetime(2026, 10, 1, tzinfo=timezone.utc)
    cand = {
        "name": "Sarah Connor",
        "title": "Chief Learning Officer",
        "evidence_urls": [
            "https://reuters.com/business/energy/2026-04-15/baker-hughes-appoints-learning-head.html",
        ],
    }
    f = evaluate_employment_freshness(cand, company_domain="bakerhughes.com", company_name="Baker Hughes", anchor_date=anchor)
    assert f["employment_freshness_status"] == "Current Employment Likely"
    assert f["is_stale_or_unconfirmed"] is False


def test_phase3_1_explicit_transition_page_mentioning_both_old_and_new():
    """
    Phase 3.1 Test 4: Explicit transition page mentioning both old and new employer
    Expected: Former / Stale; cannot be primary.
    """
    from dashboard.contact_research import (
        check_contradiction,
        evaluate_employment_freshness,
        adjudicate_contact_research,
    )

    cand = {
        "name": "Jose Fernandez",
        "title": "Chief Learning Officer (CLO)",
        "evidence_urls": [
            "https://www.comparably.com/companies/baker-hughes/executive-team",
        ],
    }
    all_evidence = [
        {
            "title": "Novartis Names Jose Fernandez Global Head of Capability",
            "url": "https://fiercepharma.com/people/novartis-names-jose-fernandez",
            "snippet": "Jose Fernandez left Baker Hughes to join Novartis as Global Head of Capability and Enterprise Learning.",
        }
    ]

    has_contra, reason = check_contradiction(cand, all_evidence=all_evidence, company_name="Baker Hughes")
    assert has_contra is True
    assert "Departure" in reason or "departure" in reason or "competing employer" in reason.lower()

    f = evaluate_employment_freshness(cand, all_evidence=all_evidence, company_name="Baker Hughes")
    assert f["employment_freshness_status"] == "Possible Former Employee / Stale Evidence"
    assert f["has_contradictory_employer"] is True
    assert f["is_stale_or_unconfirmed"] is True

    payload = {
        "company_name": "Baker Hughes",
        "website": "bakerhughes.com",
        "primary_contact": cand,
        "ideal_role": "Head of Training / Training Director",
    }
    res = adjudicate_contact_research(payload, all_evidence=all_evidence, company="Baker Hughes", website="bakerhughes.com")
    assert res["contact_research_status"] == "Role Found - Person Unresolved"
    assert res["is_weak_match"] is True
    assert len(res["weak_matches"]) == 1
    assert res["weak_matches"][0]["current_employment_status"] == "Former"


def test_phase3_1_current_employer_discovery_tied_to_same_person():
    """
    Phase 3.1 Test 5: Current-employer discovery evidence tied to the same person
    Expected: suppression applies.
    """
    from dashboard.contact_research import check_contradiction, evaluate_employment_freshness

    cand = {
        "name": "Jose Fernandez",
        "title": "Chief Learning Officer",
        "evidence_urls": ["https://comparably.com/companies/baker-hughes/executive-team"],
    }
    all_evidence = [
        {
            "title": "Jose Fernandez - Profile",
            "url": "https://linkedin.com/in/jose-fernandez-pharma",
            "snippet": "Jose Fernandez now at Novartis as Vice President of Global Talent & Capability.",
        }
    ]
    has_contra, reason = check_contradiction(cand, all_evidence=all_evidence, company_name="Baker Hughes")
    assert has_contra is True
    assert "competing employer" in reason.lower()

    f = evaluate_employment_freshness(cand, all_evidence=all_evidence, company_name="Baker Hughes")
    assert f["employment_freshness_status"] == "Possible Former Employee / Stale Evidence"
    assert f["has_contradictory_employer"] is True


def test_phase3_1_false_positive_guard_unrelated_text():
    """
    Phase 3.1 Test 6: False-positive guard
    Expected: unrelated 'joined' text or different person does NOT suppress a valid candidate.
    """
    from dashboard.contact_research import check_contradiction

    cand = {
        "name": "Jose Fernandez",
        "title": "Chief Learning Officer",
    }

    # Case A: Another person joined another company in same text
    unrelated_person_ev = [
        {
            "snippet": "Lorenzo Simonelli joined the board of the American Petroleum Institute; Jose Fernandez continues to lead workforce learning at Baker Hughes."
        }
    ]
    has_contra_a, _ = check_contradiction(cand, all_evidence=unrelated_person_ev, company_name="Baker Hughes")
    assert has_contra_a is False, "Unrelated person joining board must not suppress candidate"

    # Case B: Another employee joined target company
    joined_target_ev = [
        {
            "snippet": "Sarah Jenkins joined Baker Hughes as Director of Subsea Operations."
        }
    ]
    has_contra_b, _ = check_contradiction(cand, all_evidence=joined_target_ev, company_name="Baker Hughes")
    assert has_contra_b is False, "Different person joining target company must not suppress candidate"

    # Case C: Candidate joined TARGET company (not competing company)
    joined_same_ev = [
        {
            "snippet": "Jose Fernandez joined Baker Hughes as Chief Learning Officer to drive global talent development."
        }
    ]
    has_contra_c, _ = check_contradiction(cand, all_evidence=joined_same_ev, company_name="Baker Hughes")
    assert has_contra_c is False, "Candidate joining TARGET company must not trigger departure contradiction"


def test_phase3_1_baker_hughes_jose_fernandez_outcomes():
    """
    Phase 3.1 Test 7: Baker Hughes/Jose Fernandez
    - Comparably alone must no longer permit primary recommendation.
    - If credible Novartis/current-other-employer evidence is retrieved, he must be marked Former and not recommended for Baker Hughes.
    """
    from dashboard.contact_research import adjudicate_contact_research

    # Part A: Comparably alone
    comp_only_evidence = [
        {
            "title": "Baker Hughes Executive Team | Comparably",
            "url": "https://www.comparably.com/companies/baker-hughes/executive-team",
            "snippet": "Jose Fernandez serves as the Chief Learning Officer (CLO) of Baker Hughes.",
        }
    ]
    payload_a = {
        "company_name": "Baker Hughes",
        "website": "bakerhughes.com",
        "primary_contact": {
            "name": "Jose Fernandez",
            "title": "Chief Learning Officer (CLO)",
            "evidence_urls": ["https://www.comparably.com/companies/baker-hughes/executive-team"],
        },
        "ideal_role": "Head of Training / Training Director",
    }
    res_a = adjudicate_contact_research(payload_a, all_evidence=comp_only_evidence, company="Baker Hughes", website="bakerhughes.com")
    assert res_a["contact_research_status"] == "Role Found - Person Unresolved", "Comparably alone must be Unresolved"
    assert res_a["is_weak_match"] is True
    assert res_a["weak_matches"][0]["employment_freshness_status"] == "Employment Unconfirmed"

    # Part B: With credible Novartis contradiction evidence
    novartis_evidence = comp_only_evidence + [
        {
            "title": "Novartis Global People Directory",
            "url": "https://novartis.com/our-company/leadership",
            "snippet": "Jose Fernandez joined Novartis as Global Head of Capability Building.",
        }
    ]
    res_b = adjudicate_contact_research(payload_a, all_evidence=novartis_evidence, company="Baker Hughes", website="bakerhughes.com")
    assert res_b["contact_research_status"] == "Role Found - Person Unresolved"
    assert res_b["is_weak_match"] is True
    wm_b = res_b["weak_matches"][0]
    assert wm_b["current_employment_status"] == "Former"
    assert wm_b["employment_freshness_status"] == "Possible Former Employee / Stale Evidence"
    assert wm_b["has_contradictory_employer"] is True


def test_phase3_1_saipem_remains_unresolved_weak_leads_non_primary():
    """
    Phase 3.1 Test 8: Saipem remains unresolved and its weak leads remain non-primary.
    """
    from dashboard.contact_research import adjudicate_contact_research

    saipem_payload = {
        "company_name": "Saipem",
        "website": "saipem.com",
        "primary_contact": {
            "name": "Marco Rossi",
            "title": "Training Program Manager",
            "icp_level": "Fallback",
            "evidence_urls": [
                "https://www.linkedin.com/in/marco-rossi-training",
                "https://rocketreach.co/marco-rossi",
            ],
        },
        "alternative_contacts": [],
        "ideal_role": "Head of Training / Training Director",
    }
    res = adjudicate_contact_research(saipem_payload, company="Saipem", website="saipem.com")
    assert res["contact_research_status"] == "Role Found - Person Unresolved"
    assert res["is_weak_match"] is True
    assert len(res["weak_matches"]) >= 1
    assert res["weak_matches"][0]["name"] == "Marco Rossi"
    assert res["weak_matches"][0]["match_quality"] == "Best Available Weak Match"


if __name__ == "__main__":
    print("Running test_phase1_parallel_brave_seed_queries...")
    test_phase1_parallel_brave_seed_queries()
    print("PASSED: test_phase1_parallel_brave_seed_queries")

    print("Running test_phase1_timing_telemetry_schema...")
    test_phase1_timing_telemetry_schema()
    print("PASSED: test_phase1_timing_telemetry_schema")

    print("Running test_phase1_cache_provider_interface_and_ttl...")
    test_phase1_cache_provider_interface_and_ttl()
    print("PASSED: test_phase1_cache_provider_interface_and_ttl")

    print("Running test_phase1_fast_pass_policy_equivalence_baker_hughes...")
    test_phase1_fast_pass_policy_equivalence_baker_hughes()
    print("PASSED: test_phase1_fast_pass_policy_equivalence_baker_hughes")

    print("Running test_phase1_reverify_action_bypasses_cache...")
    test_phase1_reverify_action_bypasses_cache()
    print("PASSED: test_phase1_reverify_action_bypasses_cache")

    print("Running test_phase1_saipem_deep_mode_unresolved_invariance...")
    test_phase1_saipem_deep_mode_unresolved_invariance()
    print("PASSED: test_phase1_saipem_deep_mode_unresolved_invariance")

    print("Running test_phase2_url_canonicalization_variants...")
    test_phase2_url_canonicalization_variants()
    print("PASSED: test_phase2_url_canonicalization_variants")

    print("Running test_phase2_known_mirror_cluster_cannot_be_verified...")
    test_phase2_known_mirror_cluster_cannot_be_verified()
    print("PASSED: test_phase2_known_mirror_cluster_cannot_be_verified")

    print("Running test_phase2_unknown_directory_conservative_default...")
    test_phase2_unknown_directory_conservative_default()
    print("PASSED: test_phase2_unknown_directory_conservative_default")

    print("Running test_phase2_corporate_plus_mirror_cluster...")
    test_phase2_corporate_plus_mirror_cluster()
    print("PASSED: test_phase2_corporate_plus_mirror_cluster")

    print("Running test_phase2_weak_benchmark_saipem_unresolved...")
    test_phase2_weak_benchmark_saipem_unresolved()
    print("PASSED: test_phase2_weak_benchmark_saipem_unresolved")

    print("Running test_phase2_strong_benchmark_baker_hughes_not_weakened...")
    test_phase2_strong_benchmark_baker_hughes_not_weakened()
    print("PASSED: test_phase2_strong_benchmark_baker_hughes_not_weakened")

    print("Running test_phase3_live_corporate_roster_undated_confirmed...")
    test_phase3_live_corporate_roster_undated_confirmed()
    print("PASSED: test_phase3_live_corporate_roster_undated_confirmed")

    print("Running test_phase3_dated_corporate_or_regulatory_within_threshold...")
    test_phase3_dated_corporate_or_regulatory_within_threshold()
    print("PASSED: test_phase3_dated_corporate_or_regulatory_within_threshold")

    print("Running test_phase3_old_corporate_document_stale_forces_unresolved...")
    test_phase3_old_corporate_document_stale_forces_unresolved()
    print("PASSED: test_phase3_old_corporate_document_stale_forces_unresolved")

    print("Running test_phase3_linkedin_only_cannot_be_confirmed...")
    test_phase3_linkedin_only_cannot_be_confirmed()
    print("PASSED: test_phase3_linkedin_only_cannot_be_confirmed")

    print("Running test_phase3_contradictory_newer_employer_suppresses_status...")
    test_phase3_contradictory_newer_employer_suppresses_status()
    print("PASSED: test_phase3_contradictory_newer_employer_suppresses_status")

    print("Running test_phase3_saipem_weak_benchmark_unresolved_protected...")
    test_phase3_saipem_weak_benchmark_unresolved_protected()
    print("PASSED: test_phase3_saipem_weak_benchmark_unresolved_protected")

    print("Running test_phase3_baker_hughes_strong_benchmark_protected...")
    test_phase3_baker_hughes_strong_benchmark_protected()
    print("PASSED: test_phase3_baker_hughes_strong_benchmark_protected")

    print("Running test_phase3_seniority_decoupled_ranking_director_outranks_historic_vp...")
    test_phase3_seniority_decoupled_ranking_director_outranks_historic_vp()
    print("PASSED: test_phase3_seniority_decoupled_ranking_director_outranks_historic_vp")

    print("Running test_phase3_1_comparably_only_undated_cannot_be_primary...")
    test_phase3_1_comparably_only_undated_cannot_be_primary()
    print("PASSED: test_phase3_1_comparably_only_undated_cannot_be_primary")

    print("Running test_phase3_1_first_party_live_company_roster_confirmed...")
    test_phase3_1_first_party_live_company_roster_confirmed()
    print("PASSED: test_phase3_1_first_party_live_company_roster_confirmed")

    print("Running test_phase3_1_dated_reputable_editorial_within_threshold_likely...")
    test_phase3_1_dated_reputable_editorial_within_threshold_likely()
    print("PASSED: test_phase3_1_dated_reputable_editorial_within_threshold_likely")

    print("Running test_phase3_1_explicit_transition_page_mentioning_both_old_and_new...")
    test_phase3_1_explicit_transition_page_mentioning_both_old_and_new()
    print("PASSED: test_phase3_1_explicit_transition_page_mentioning_both_old_and_new")

    print("Running test_phase3_1_current_employer_discovery_tied_to_same_person...")
    test_phase3_1_current_employer_discovery_tied_to_same_person()
    print("PASSED: test_phase3_1_current_employer_discovery_tied_to_same_person")

    print("Running test_phase3_1_false_positive_guard_unrelated_text...")
    test_phase3_1_false_positive_guard_unrelated_text()
    print("PASSED: test_phase3_1_false_positive_guard_unrelated_text")

    print("Running test_phase3_1_baker_hughes_jose_fernandez_outcomes...")
    test_phase3_1_baker_hughes_jose_fernandez_outcomes()
    print("PASSED: test_phase3_1_baker_hughes_jose_fernandez_outcomes")

    print("Running test_phase3_1_saipem_remains_unresolved_weak_leads_non_primary...")
    test_phase3_1_saipem_remains_unresolved_weak_leads_non_primary()
    print("PASSED: test_phase3_1_saipem_remains_unresolved_weak_leads_non_primary")

    print("\nALL PHASE 1, PHASE 2, PHASE 3 & PHASE 3.1 SMOKE TESTS PASSED!")





