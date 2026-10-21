"""
Governance, Durability, and Authorization Controls for EON Commercial Intelligence.
Provides audit durability verification, operator authorization safeguards,
seed taxonomy formatting, and statutory executive card generation.
"""

import html
import json
import os
import urllib.request
from pathlib import Path
import hmac
import re
import streamlit as st

DEFAULT_AUDIT_LOG_PATH = "local_data/audit_enrichment_overrides.jsonl"

FORBIDDEN_QUERY_OVERRIDE_KEYS = frozenset({
    "override",
    "admin",
    "admin_override",
    "operator_override",
    "force_enrich",
    "bypass_hold",
    "execute_override",
    "auto_enrich",
})

FORBIDDEN_SESSION_BYPASS_KEYS = frozenset({
    "bypass_admin_gate",
    "bypass_operator_gate",
    "force_override_exec",
    "auto_execute_override",
    "admin_authenticated_bypass",
    "operator_authenticated_bypass",
})

DISALLOWED_PLACEHOLDER_REVIEWERS = frozenset({
    "user",
    "admin",
    "operator",
    "test",
    "tester",
    "anonymous",
    "none",
    "null",
    "guest",
    "default",
    "system",
})


def format_segment_taxonomy(company_row, prov_dict=None, enr_status="not_started") -> str:
    """
    Renders clarified taxonomy labeling distinguishing verified vs unverified seed categories.
    Where a seed segment conflicts with the resolved company profile or remains unverified,
    labels it as 'Seed segment (unverified): [value]' or 'Industry unconfirmed'.
    Never represents seed taxonomy as verified company intelligence.
    """
    raw_seg = str(company_row.get("segment", "") or "").strip()
    is_generic = not raw_seg or raw_seg.lower() in ("unspecified", "diversified industrial / unspecified", "none", "nan")

    sic_desc = None
    if prov_dict and isinstance(prov_dict, dict):
        sic_desc = prov_dict.get("sic_description", {}).get("value")

    if enr_status == "complete" and sic_desc and str(sic_desc).lower() not in ("unclassified", "unknown", "none"):
        if is_generic:
            return f"Statutory SIC: {sic_desc}"
        return f"Statutory SIC: {sic_desc} · Seed segment: {raw_seg}"

    if is_generic:
        return "Industry unconfirmed"

    return f"Seed segment (unverified): {raw_seg}"


def build_enrichment_executive_card_html(company_name: str, domain: str, enr_status: str, prov_dict: dict) -> str:
    """
    Constructs prominent presentation HTML for the Statutory & SEC Entity Quality summary card.
    Guarantees:
    - Displays enrichment status (Complete, Partial, Not Enriched)
    - Displays SEC status / CIK if accepted
    - Displays match quality classification (canonical exact vs. rejected / remediated / unknown)
    - Displays provenance or rationale summary
    - Displays explicit prior false-positive remediation note for Hawkins and West Group
    """
    clean_c = str(company_name or "").strip()
    clean_c_l = clean_c.lower()
    clean_dom = str(domain or "").strip().lower()
    enr_st = str(enr_status or "not_started").lower()

    if enr_st == "complete":
        st_badge = '<span style="background-color: #dcfce7; color: #166534; border: 1px solid #bbf7d0; padding: 2px 8px; border-radius: 4px; font-size: 0.76rem; font-weight: 600;">🟢 Current Verified (SEC Filings)</span>'
    elif enr_st == "partial":
        st_badge = '<span style="background-color: #fef9c3; color: #854d0e; border: 1px solid #fef08a; padding: 2px 8px; border-radius: 4px; font-size: 0.76rem; font-weight: 600;">🟡 Partial Statutory Records</span>'
    else:
        st_badge = '<span style="background-color: #f1f5f9; color: #475569; border: 1px solid #cbd5e1; padding: 2px 8px; border-radius: 4px; font-size: 0.76rem; font-weight: 600;">⚪ Not Yet Enriched</span>'

    sec_entry = prov_dict.get("sec_cik", {}) if isinstance(prov_dict, dict) else {}
    cik_val = sec_entry.get("value")
    cik_status = sec_entry.get("value_status")
    ticker_val = prov_dict.get("ticker", {}).get("value") if isinstance(prov_dict, dict) else None
    sic_desc = prov_dict.get("sic_description", {}).get("value") if isinstance(prov_dict, dict) else None

    is_remediated_hawkins = clean_c_l == "hawkins" or "hawkins.co.nz" in clean_dom
    is_remediated_west = clean_c_l == "west group" or "westgroup.com.br" in clean_dom

    if is_remediated_hawkins:
        cik_display = "<em>None / Unresolved</em> (Foreign ccTLD Conflict Safeguard)"
        match_quality = '<span style="background-color: #fee2e2; color: #991b1b; border: 1px solid #fecaca; padding: 2px 8px; border-radius: 4px; font-size: 0.75rem; font-weight: 600;">🛡️ Remediated False Positive (Phase 5.1B)</span>'
        rationale = "Account domain 'hawkins.co.nz' has a foreign country-code top-level domain (.nz). US registrant CIK 0000046254 (Hawkins Inc) was safely decoupled and rejected by the hardened cross-border entity resolver. Zero unverified statutory claims permitted."
        remediation_alert = """
        <div style="margin-top: 10px; padding: 9px 12px; background-color: #fef2f2; border: 1px solid #fee2e2; border-left: 3px solid #dc2626; border-radius: 4px; font-size: 0.81rem; color: #991b1b; line-height: 1.45;">
            <strong>🛡️ Identity Remediation Audit Note (Phase 5.1B)</strong>: Identified as a raw-batch statutory false positive due to foreign ccTLD collision (<code>.co.nz</code> vs US issuer Hawkins Inc). Fully remediated via <code>CompanyEnrichmentEngine.remediate_company_identity</code>. All SEC fields invalidated to Unknown status, accepted relationship removed, and resolver hardened against foreign ccTLD mismatches.
        </div>
        """
    elif is_remediated_west:
        cik_display = "<em>None / Unresolved</em> (Foreign ccTLD Conflict Safeguard)"
        match_quality = '<span style="background-color: #fee2e2; color: #991b1b; border: 1px solid #fecaca; padding: 2px 8px; border-radius: 4px; font-size: 0.75rem; font-weight: 600;">🛡️ Remediated False Positive (Phase 5.1A)</span>'
        rationale = "Account domain 'westgroup.com.br' has a Brazilian country-code top-level domain (.br). US registrant CIK 0000105770 (West Co) was safely rejected and cleared by identity precision guard; accepted SEC relationship removed."
        remediation_alert = """
        <div style="margin-top: 10px; padding: 9px 12px; background-color: #fef2f2; border: 1px solid #fee2e2; border-left: 3px solid #dc2626; border-radius: 4px; font-size: 0.81rem; color: #991b1b; line-height: 1.45;">
            <strong>🛡️ Identity Remediation Audit Note (Phase 5.1A)</strong>: Identified as a discrete statutory false positive due to Brazilian ccTLD collision (<code>.com.br</code> vs US CIK 0000105770). Fully remediated via <code>CompanyEnrichmentEngine.remediate_company_identity</code>. All SEC fields invalidated to Unknown status and relationship decoupled; canonical valid issuer mappings preserved.
        </div>
        """
    elif cik_val and cik_status == "exact":
        ticker_part = f" · {ticker_val}" if ticker_val else ""
        sic_part = f" ({sic_desc})" if sic_desc else ""
        cik_display = f"<code>{html.escape(str(cik_val))}</code>{ticker_part}{sic_part}"
        match_quality = '<span style="background-color: #dcfce7; color: #166534; border: 1px solid #bbf7d0; padding: 2px 8px; border-radius: 4px; font-size: 0.75rem; font-weight: 600;">Current Verified (Canonical Exact Match)</span>'
        rationale = f"Primary statutory disclosures verified via official SEC EDGAR 10-K regulatory filings (CIK {html.escape(str(cik_val))}). Exact legal entity identity confirmed with authoritative provenance."
        remediation_alert = ""
    elif clean_c_l == "saipem" or "saipem.com" in clean_dom:
        cik_display = "<em>None on File</em> (Non-SEC International Entity)"
        match_quality = '<span style="background-color: #f1f5f9; color: #475569; border: 1px solid #cbd5e1; padding: 2px 8px; border-radius: 4px; font-size: 0.75rem; font-weight: 600;">Historical Reference (Non-SEC Entity)</span>'
        rationale = "Italian multinational energy infrastructure corporation. Regulatory filings are non-SEC international disclosures (Milan / Borsa Italiana). Grounded directionally via Wikidata semantic entity Q673397."
        remediation_alert = ""
    else:
        cik_display = "<em>None on File</em> (Not Available from Verified Source)"
        match_quality = '<span style="background-color: #f1f5f9; color: #475569; border: 1px solid #cbd5e1; padding: 2px 8px; border-radius: 4px; font-size: 0.75rem; font-weight: 600;">Not Available from Verified Source</span>'
        rationale = "No current verified SEC statutory issuer mapping established yet. Account retains seed classification until targeted lookup is initiated."
        remediation_alert = ""

    card_html = f"""
    <div style="background-color: #f8fafc; border: 1px solid #cbd5e1; border-top: 3px solid #0f766e; border-radius: 6px; padding: 14px 18px; margin-top: 8px; margin-bottom: 12px; box-shadow: 0 1px 3px rgba(0,0,0,0.03);">
        <div style="display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #e2e8f0; padding-bottom: 8px; margin-bottom: 10px;">
            <div style="font-weight: 700; font-size: 0.92rem; color: #0f766e;">
                🏢 Statutory & SEC Entity Quality Summary
            </div>
            {st_badge}
        </div>
        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px; font-size: 0.82rem; color: #334155; margin-bottom: 8px;">
            <div><strong>SEC Statutory Status:</strong> {cik_display}</div>
            <div><strong>Match Quality:</strong> {match_quality}</div>
        </div>
        <div style="font-size: 0.81rem; color: #475569; line-height: 1.45;">
            <strong>Provenance & Rationale:</strong> {rationale}
        </div>
        {remediation_alert}
    </div>
    """
    try:
        from dashboard.contact_research import format_presentation_html
        return format_presentation_html(card_html)
    except Exception:
        return card_html


def _get_configured_audit_endpoint() -> tuple[str, str]:
    """Retrieves optional configured AUDIT_LOG_ENDPOINT and token from env or Streamlit secrets."""
    endpoint = os.environ.get("AUDIT_LOG_ENDPOINT", "").strip()
    token = os.environ.get("AUDIT_LOG_TOKEN", "").strip()
    if not endpoint:
        try:
            endpoint = str(st.secrets.get("AUDIT_LOG_ENDPOINT", "") or "").strip()
            token = str(st.secrets.get("AUDIT_LOG_TOKEN", "") or "").strip()
        except Exception:
            pass
    return endpoint, token


def is_running_in_streamlit_cloud() -> bool:
    """Detects if app is executing in Streamlit Community Cloud ephemeral environment."""
    return bool(
        os.environ.get("STREAMLIT_SHARING_HOST")
        or os.environ.get("HOSTNAME", "").startswith("streamlit")
        or os.path.exists("/mount/src")
        or os.environ.get("REQUIRE_DURABLE_AUDIT_LOG", "").lower() in ("1", "true", "yes")
    )


def verify_audit_log_writeable(audit_path: str = DEFAULT_AUDIT_LOG_PATH) -> tuple[bool, str]:
    """
    Verifies that the audit destination is writeable, retentive, and compliant with durability gates.
    In Streamlit Community Cloud, strictly fails-closed if only ephemeral local storage is available
    and no external durable audit destination ('AUDIT_LOG_ENDPOINT') is configured.
    """
    endpoint, token = _get_configured_audit_endpoint()
    in_cloud = is_running_in_streamlit_cloud()
    allow_fallback = not in_cloud

    if endpoint:
        if not (endpoint.startswith("https://") or endpoint.startswith("http://")):
            return (
                False,
                f"Configured AUDIT_LOG_ENDPOINT '{endpoint}' is invalid (must begin with https:// or http://).",
            )
        return True, f"Durable External Endpoint: {endpoint}"

    if in_cloud and not allow_fallback:
        return (
            False,
            "Durability Gate Failure: Streamlit Community Cloud local filesystem is ephemeral across container restarts. "
            "An external durable audit destination ('AUDIT_LOG_ENDPOINT') must be configured in Streamlit Secrets "
            "before any manual override write can execute. Override remains fail-closed.",
        )

    try:
        target = Path(audit_path)
        parent_dir = target.parent
        os.makedirs(parent_dir, exist_ok=True)
        if target.exists() and not os.access(target, os.W_OK):
            return (
                False,
                f"Audit log path '{audit_path}' is read-only or lacks write permission.",
            )
        with open(target, "a", encoding="utf-8") as f:
            f.flush()
        if not os.access(target, os.R_OK | os.W_OK):
            return (
                False,
                f"Audit log path '{audit_path}' could not be verified for read/write retention.",
            )
        return True, str(target)
    except Exception as exc:
        return (
            False,
            f"Audit log path '{audit_path}' is unavailable or read-only: {exc}",
        )


def record_override_audit_event(
    audit_record: dict,
    audit_path: str = DEFAULT_AUDIT_LOG_PATH,
) -> tuple[bool, str]:
    """
    Writes and verifies retention of a manual enrichment override audit event.
    Dispatches to durable external endpoint if configured, and also writes to local JSONL replica.
    Fails closed if the external write fails or if running in cloud without durable storage.
    """
    writable, msg = verify_audit_log_writeable(audit_path)
    if not writable:
        return False, msg

    endpoint, token = _get_configured_audit_endpoint()
    serialized = json.dumps(audit_record, sort_keys=True)

    if endpoint:
        try:
            req = urllib.request.Request(
                endpoint,
                data=serialized.encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "EON-Governance-Audit/1.0",
                    **({"Authorization": f"Bearer {token}"} if token else {}),
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status not in (200, 201, 202, 204):
                    return (
                        False,
                        f"External durable audit storage rejected event (HTTP {resp.status}).",
                    )
        except Exception as exc:
            return (
                False,
                f"External durable audit dispatch failed for '{endpoint}': {exc}. Override aborted.",
            )

    try:
        with open(audit_path, "a", encoding="utf-8") as f:
            f.write(serialized + "\n")
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass

        with open(audit_path, "r", encoding="utf-8") as f:
            lines = [ln.strip() for ln in f if ln.strip()]
        if not lines or lines[-1] != serialized:
            return (
                False,
                f"Audit log write verification failed: record was not retained in '{audit_path}'.",
            )
    except Exception as exc:
        if not endpoint:
            return (
                False,
                f"Audit log write failed for '{audit_path}': {exc}",
            )

    return True, (endpoint or audit_path)


def _get_configured_operator_key() -> str:
    """Retrieves optional configured OPERATOR_SAFEGUARD_KEY or ADMIN_OVERRIDE_KEY from environment or Streamlit secrets."""
    for key_name in ("OPERATOR_SAFEGUARD_KEY", "ADMIN_OVERRIDE_KEY"):
        env_val = os.environ.get(key_name, "").strip()
        if env_val:
            return env_val
        try:
            sec_val = str(st.secrets.get(key_name, "") or "").strip()
            if sec_val:
                return sec_val
        except Exception:
            pass
    return ""


_get_configured_admin_key = _get_configured_operator_key


def verify_operator_override_authorization(
    operator_id: str = None,
    reason: str = None,
    ack_hold: bool = None,
    query_params: dict = None,
    session_state: dict = None,
    operator_token: str = None,
    reviewer_id: str = None,
    admin_token: str = None,
) -> tuple[bool, str]:
    """
    Server-side safeguard validation for single-account manual enrichment override.
    Provides a single trusted operator capability model while enforcing critical safety controls:
    - Rejects URL parameters or session-state manipulation bypass attempts.
    - Requires explicit acknowledgement that Phase 5.1C remains on HOLD.
    - Requires a valid, attributable Operator ID (non-placeholder, >= 3 chars).
    - Requires a substantive justification (>= 10 chars).
    - Enforces configured OPERATOR_SAFEGUARD_KEY / ADMIN_OVERRIDE_KEY if present in environment/secrets.
    """
    effective_operator_id = operator_id if operator_id is not None else reviewer_id
    effective_token = operator_token if operator_token is not None else admin_token

    if query_params and isinstance(query_params, dict):
        injected_keys = FORBIDDEN_QUERY_OVERRIDE_KEYS.intersection(
            {str(k).lower().strip() for k in query_params.keys()}
        )
        if injected_keys:
            return (
                False,
                f"URL / query-parameter override bypass is prohibited (rejected keys: {sorted(injected_keys)}).",
            )

    if session_state and isinstance(session_state, dict):
        bypass_keys = [
            k for k in FORBIDDEN_SESSION_BYPASS_KEYS if session_state.get(k)
        ]
        if bypass_keys:
            return (
                False,
                f"Session-state authorization bypass is prohibited (rejected state: {sorted(bypass_keys)}).",
            )

    if ack_hold is not True:
        return (
            False,
            "Explicit acknowledgement that Phase 5.1C remains on HOLD is required before any write.",
        )

    clean_operator = str(effective_operator_id or "").strip()
    if len(clean_operator) < 3:
        return (
            False,
            "A valid Operator ID (minimum 3 characters) is required.",
        )
    if clean_operator.lower() in DISALLOWED_PLACEHOLDER_REVIEWERS:
        return (
            False,
            f"Operator ID '{clean_operator}' is a generic placeholder; provide an attributable operator identifier.",
        )
    if not re.match(r"^[a-zA-Z0-9_.\-@]+$", clean_operator):
        return (
            False,
            "Operator ID contains invalid characters; use alphanumeric, '_', '.', '-', or '@'.",
        )

    clean_reason = str(reason or "").strip()
    if len(clean_reason) < 10:
        return (
            False,
            "A substantive justification (minimum 10 characters) is required before executing an override.",
        )

    configured_key = _get_configured_operator_key()
    if configured_key:
        provided_key = str(effective_token or "").strip()
        if not provided_key or not hmac.compare_digest(provided_key, configured_key):
            return (
                False,
                "Invalid or missing Operator Safeguard Key required by production environment.",
            )

    return True, "Verified"


verify_admin_authorization = verify_operator_override_authorization
