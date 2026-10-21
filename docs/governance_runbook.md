# EON Production Governance & Operator Manual Override Runbook

**Document Version**: 1.1  
**Status**: APPROVED & ACTIVE  
**Governing Phase**: Phase 5.1B Closeout / Production Governance Baseline  
**Capability Model**: Single Trusted Operator (Unified User Experience)  
**Target Application**: Streamlit Cloud (`/company_browser`)  

---

## 1. Executive Summary & Policy Invariants

This runbook establishes operational and governance protocols for manual actions in the EON Commercial Intelligence system.

### Single Trusted Operator Model
- **Unified Experience**: All administrative vs. normal-user role distinctions have been eliminated from the UI, code paths, labels, and validation logic. There is one uniform user experience where all analytical and override capabilities are directly accessible to authorized operators.
- **Safeguards Without Role Tiers**: Dangerous actions (such as manual statutory enrichment overrides while Phase 5.1C is on HOLD) are protected by operator safeguards:
  1. Attributable Operator ID (non-placeholder, >= 3 characters).
  2. Documented justification (>= 10 characters).
  3. Explicit Phase 5.1C HOLD acknowledgement.
  4. Fail-closed audit durability gate.
  5. Optional environment safeguard key (`OPERATOR_SAFEGUARD_KEY`).

### Core Governance Invariants
1. **Phase 5.1C Strict HOLD**: Batch enrichment is unauthorized. Under no circumstances may an automated batch job or background queue worker be initiated against the 145 `not_started` production accounts.
2. **Review Precision Gate**: The observed reviewed-sample accepted-identity precision from Phase 5.1B stands at **17/18 = 94.44%**, which does not satisfy the required **≥98%** release gate. Phase 5.1C remains blocked pending architectural redesign of foreign-entity resolution.
3. **Ingestion Guard**: Automatic enrichment during single-company creation is permanently disabled. New accounts are created in `not_started` state and require explicit manual action to enrich.
4. **Single-Account Scoping**: Any ad-hoc enrichment is strictly confined to a single inspected company profile.
5. **Fail-Closed Durability Gate**: No statutory write may occur without verifiable, durable audit log retention.

---

## 2. Operator Safeguard & Manual Override Validation (`OPERATOR_SAFEGUARD_KEY`)

To prevent accidental mutations or automated pipeline writes, single-account enrichment overrides are protected by explicit operator safeguards. This is **not** an admin vs. user authorization layer, but a safeguard mechanism for trusted operators.

### Secret Configuration
Configure the secret through **Streamlit Community Cloud → App Settings → Secrets**:

```toml
# Streamlit Secrets (App Settings -> Secrets)
OPERATOR_SAFEGUARD_KEY = "sec_gov_override_alpha_998877"
# Note: ADMIN_OVERRIDE_KEY is also accepted as a backward-compatible fallback
```

### Safeguard Verification Behavior
* **When Configured**:
  * The Manual Override UI renders a masked password input: `Operator Safeguard Key (Required)`.
  * The provided key is compared against the secret using constant-time verification (`hmac.compare_digest`) to prevent side-channel timing attacks.
  * If the key is missing, empty, or mismatched, the server-side validator returns:
    `⛔ Safeguard Check Failed: Invalid or missing Operator Safeguard Key required by production environment.`
  * The database mutation is aborted immediately.
* **When Absent**:
  * In local/development environments where `OPERATOR_SAFEGUARD_KEY` is omitted, the form requires:
    1. A valid, attributable Operator ID (minimum 3 characters; generic placeholders like `test`, `operator`, `user`, `admin`, `guest` are rejected).
    2. A substantive justification (minimum 10 characters).
    3. An explicit boolean acknowledgement checkbox: `I acknowledge Phase 5.1C remains on HOLD`.
* **Bypass Protections**:
  * The validator strictly rejects URL/query-parameter overrides (`?override=1`, `?operator_override=1`, etc.).
  * Session-state manipulation flags (`bypass_operator_gate`, `force_override_exec`, etc.) trigger immediate server-side rejection.

---

## 3. Audit Log Durability & Cloud Architecture

### Ephemeral Storage vs. External Durable Storage
* **Streamlit Community Cloud Architecture**: App containers execute in an ephemeral container environment (`/mount/src/...`). When an app sleeps, restarts, or redeploys from GitHub, any uncommitted files written to the local container filesystem (e.g., `local_data/audit_enrichment_overrides.jsonl`) are **reset and lost**.
* **Fail-Closed Durability Gate**:
  * In ephemeral cloud environments, local filesystem logging is **insufficient** to satisfy compliance durability.
  * If the app detects an ephemeral cloud environment (e.g., `STREAMLIT_SHARING_HOST` or `REQUIRE_DURABLE_AUDIT_LOG=true`) and **no external durable endpoint is configured**, the override write is **FAIL-CLOSED**:
    `🚨 Audit Storage Failure: Durability Gate Failure: Streamlit Community Cloud local filesystem is ephemeral across container restarts. An external durable audit destination ('AUDIT_LOG_ENDPOINT') must be configured in Streamlit Secrets before any manual override write can execute. Override remains fail-closed.`

### Configuring the External Durable Backend
Add the following entries to **Streamlit Secrets**:

```toml
# External Durable Audit Destination (HTTPS POST)
AUDIT_LOG_ENDPOINT = "https://audit.compliance.eon.internal/v1/enrichment-events"
AUDIT_LOG_TOKEN = "bearer_token_audit_secure_xyz"
```

### Event Dispatch Protocol
When `AUDIT_LOG_ENDPOINT` is configured:
1. Prior to database mutation, `record_override_audit_event()` serializes the audit record.
2. The payload is transmitted via HTTPS `POST` with `Content-Type: application/json` and `Authorization: Bearer <token>`.
3. The remote endpoint must return an HTTP success code (`200`, `201`, `202`, or `204`).
4. If the remote endpoint fails, times out, or returns an error status, the override is aborted and no database write occurs.
5. A local copy is also mirrored to `local_data/audit_enrichment_overrides.jsonl` for in-container session diagnostics.

---

## 4. Audit Log Schema & Inspection

### Event Record Schema
Each audit record is serialized as a single-line JSON (`JSONL`) entry containing:

```json
{
  "timestamp": "2026-10-14T16:15:00.000000+00:00",
  "company_id": "comp_baker_hughes_e1885b15",
  "company_name": "Baker Hughes",
  "operator_id": "operator_anas",
  "user_reviewer": "operator_anas",
  "reason": "Targeted investigation of primary SEC CIK and SIC classification",
  "phase_hold_acknowledged": true,
  "outcome": "complete",
  "success": true,
  "error": null
}
```

### Inspecting Local Audit Logs
To inspect local audit records during development or troubleshooting:

```bash
# View all recorded override events
cat local_data/audit_enrichment_overrides.jsonl | jq .

# Count total overrides
wc -l local_data/audit_enrichment_overrides.jsonl
```

---

## 5. Contact Research: Strictness Policies & Cache Busting

The dashboard surfaces a three-tier contact strictness control designed to balance executive presentation safety with exploratory discovery:

### Strictness Tiers
1. **`Broad (default)` (Presentation / Exploratory Mode)**:
   * Displays confirmed contacts, unconfirmed contacts, and historical leads.
   * Every non-verified contact receives an unambiguous badge (`⚪ Unconfirmed current`, `🔴 Former employee`, `Weak third-party evidence`, `⚠️ Contradictory / likely stale`).
   * Explanatory callout banners explain the evidence basis to presenters.
2. **`Balanced` (Directory Candidate Mode)**:
   * Surfaces unconfirmed current contacts (e.g., Jose Fernandez at Baker Hughes).
   * Strictly suppresses former employees or stale leads (e.g., Marco Rossi at Saipem).
3. **`Strict` (Production Governance Mode)**:
   * Surfaces only corroborated current contacts with High/Medium evidence confidence (e.g., Sarah Jenkins at FMC Corporation).
   * Suppresses all weak, aggregator-only, or contradictory candidates from the primary card into the collapsed `🔍 Weak matches (unconfirmed)` expander.

### Invoking Cache-Busting Re-Verification
* Default page loads check the disk cache (`local_data/cache_contact_research.json`) and verified benchmarks in 0ms without invoking external APIs.
* To force live, multi-source re-verification against the live web:
  1. Open the company profile in **Company Browser**.
  2. Navigate to **Target Contact Intelligence**.
  3. Click **`🔄 Re-Verify Current Employment`**.
  4. The system invalidates the cached entry (`force_refresh=True`), allocates fresh query budgets, queries Brave Search API, and re-adjudicates tenure using the LLM agentic engine.

---

## 6. Pre-Flight Verification Checklist for Deployments

Before declaring any deployment ready for operational use, execute the following verification steps:

1. **Verify Database Invariant**:
   ```bash
   sqlite3 local_data/companies_master.db "SELECT enrichment_status, COUNT(*) FROM company_enrichment_status GROUP BY enrichment_status;"
   # Expected: complete: 109, not_started: 145, partial: 532, total: 786
   ```
2. **Verify Automated Regression Suite**:
   ```bash
   python3 -m pytest tests/test_ui_governance_and_unresolved_transparency.py tests/test_contact_research_smoke.py tests/test_company_enrichment.py
   # Expected: 117 passed
   ```
3. **Verify Remediation Invariants**:
   * Inspect **Hawkins**: SEC Status must display `None / Unresolved (Foreign ccTLD Conflict Safeguard)`.
   * Inspect **West Group**: SEC Status must display `None / Unresolved (Foreign ccTLD Conflict Safeguard)`.
4. **Verify Presentation Defaults**:
   * Inspect **Baker Hughes**: Default mode `Broad` must surface Jose Fernandez with `⚪ Unconfirmed current`. Switching to `Strict` must suppress him to `Role Found — Person Unresolved`.
   * Inspect **Saipem**: Default mode `Broad` must surface Marco Rossi with `🔴 Former employee`. Switching to `Balanced` must display `⚠️ Former Employee Suppressed (Balanced Mode)`.
   * Inspect **FMC Corporation**: Must render Sarah Jenkins with `🟢 Confirmed current` across all modes.
