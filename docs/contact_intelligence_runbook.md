# Operational Runbook: Contact-Intelligence Integration

**Baseline Reference**: [`0174d25`](https://github.com/aafadar-git/eon-pattern-extractor/commit/0174d25)  
**Ranking & Adjudication Policy**: See [`docs/contact_ranking_policy.md`](contact_ranking_policy.md) for title tier hierarchy, scraper exclusions, and weak-match expander rules.  
**Service Endpoints**: `http://127.0.0.1:8787/api/contact-research` (Backend) | `http://localhost:8501` (Dashboard)  
**Test Suite Contract**: 248 tests passing (`pytest tests/`)

---

## 1. Environment Variable Configuration & Safe Validation

The contact research backend requires credentials for web search indexing and LLM adjudication.

### Required Variables
- `GENAI_API_KEY`: API token for Purdue GenAI / OpenAI-compatible upstream endpoint.
- `BRAVE_SEARCH_API_KEY`: API token for Brave Web Search API indexing.
- `CONTACT_API_URL` *(Optional, Dashboard-only)*: Backend API URL (defaults to `http://127.0.0.1:8787/api/contact-research`).

### Safe Validation (No Secret Printing)
Validate that variables are populated and non-empty without printing or logging token values:

```bash
# Audit variable status and character length safely
for var in GENAI_API_KEY BRAVE_SEARCH_API_KEY; do
  val="${!var}"
  if [ -n "$val" ]; then
    echo "$var: CONFIGURED (${#val} characters)"
  else
    echo "ERROR: $var is UNSET or EMPTY"
  fi
done
```

> [!NOTE]
> Never run `env`, `printenv`, or `echo $GENAI_API_KEY` directly in shared terminals, logs, or debugging sessions.

---

## 2. Managing the Local Backend Server (Port 8787)

### Starting the Server
Run the committed Purdue GenAI server daemon or in a dedicated terminal session:

```bash
# Run purdue v1 server (standard production backend)
/opt/anaconda3/bin/python contact_intelligence/eon_contact_research_server_purdue_v1.py

# Or run as a detached background process:
nohup /opt/anaconda3/bin/python contact_intelligence/eon_contact_research_server_purdue_v1.py \
  > /dev/null 2>&1 &
```

### Health & Connectivity Checking
Verify connectivity and endpoint responsiveness using `OPTIONS` (CORS preflight) and a payload connectivity probe:

```bash
# 1. CORS Preflight Health Check (Expected HTTP 204 No Content)
curl -s -o /dev/null -w "%{http_code}\n" -X OPTIONS http://127.0.0.1:8787/api/contact-research

# 2. Server Connectivity & Request Parsing Probe (NOT a formal error-contract guarantee)
curl -i -s -X POST http://127.0.0.1:8787/api/contact-research \
  -H "Content-Type: application/json" \
  -d '{}'
```

*Observed Connectivity Probe Output on Commit 1606da0:*
```http
HTTP/1.0 500 Internal Server Error
Content-Type: application/json

{"error": "company_name is required"}
```

> [!IMPORTANT]
> The missing-`company_name` test above serves solely as a connectivity and parser responsiveness probe. Formal downstream error contracts are reserved for structured model parsing failures.

### Stopping the Server
Locate and terminate any active process bound to port 8787:

```bash
# Gracefully terminate the process listening on port 8787
lsof -ti :8787 | xargs kill -15

# Verify port is released
lsof -i :8787 || echo "Port 8787 is clear"
```

---

## 3. Dashboard Startup & Expected Browser Behavior

### Starting Streamlit Dashboard
```bash
/opt/anaconda3/bin/streamlit run app.py --server.port 8501
```

### Expected Browser Behavior for "Find Target Contact"
1. **Navigation**: Open `http://localhost:8501` and navigate to **Company Browser** (`11_company_browser.py`).
2. **Company Selection**: Select a company from the dropdown selector (e.g., *Baker Hughes*).
3. **Execution State**:
   - Clicking **Find Target Contact** disables the button and updates the button label to:
     ```text
     Researching contact…
     ```
   - The status banner displays:
     ```text
     Querying local Agentic Contact Intelligence on http://127.0.0.1:8787/api/contact-research...
     ```
   - The frontend issues an asynchronous in-frame `fetch()` `POST` request to `http://127.0.0.1:8787/api/contact-research`.
   - The browser window **does not** navigate away, submit a parent `<form>`, or reload the host page.
4. **Success State**:
   - The button resets to `Find Target Contact`.
   - An inline result card renders immediately:
     - **Status Badge**: Reflects adjudicated tier (e.g., `Probable — High confidence` or `Verified Contact Found`).
     - **Primary Contact**: Displays Name, Title, ICP Level, Confidence, and Employment status.
     - **Employment Note**: Renders `employment_status_note` directly below contact metadata.
     - **Target Role & Decision Reason**: Displays ideal role and structured decision justification.
5. **Connection Failure / Offline State**:
   - If the backend is unreachable or refused, the browser stays on the current page.
   - An inline error callout renders: `Research Error: Failed to fetch (Verify local backend is listening on http://127.0.0.1:8787/api/contact-research)`.

---

## 4. Smoke-Test Sequence

### Case A: Success Case (Baker Hughes Deterministic Baseline)
```bash
curl -s -X POST http://127.0.0.1:8787/api/contact-research \
  -H "Content-Type: application/json" \
  -d '{"company_name": "Baker Hughes", "website": "bakerhughes.com", "segment": "Oilfield Services"}' \
  | python3 -c '
import sys, json
data = json.load(sys.stdin)
assert data.get("contact_research_status") == "Probable Contact Found", f"Unexpected status: {data.get(\"contact_research_status\")}"
assert data.get("primary_contact", {}).get("name") == "Jose Fernandez", f"Unexpected contact: {data.get(\"primary_contact\")}"
assert data.get("primary_contact", {}).get("evidence_confidence") == "High"
assert bool(data.get("primary_contact", {}).get("employment_status_note")) is True
print("CASE A PASSED: Deterministic status, primary contact, and employment note verified.")
'
```

### Case B: Malformed-Model-Output Error Contract
Execute the response-level contract test asserting that a non-conformant model payload triggers an exact `HTTP 500` without data or token leakage:

```bash
PYTHONPATH=. /opt/anaconda3/bin/pytest \
  tests/test_contact_research_smoke.py \
  -k "test_response_contract_malformed_model_output_error" -v
```

**Expected Contract Invariant**:
- Non-200 HTTP response code (`500`).
- Exact payload:
  ```json
  {"error":"Failed to parse structured model output as JSON"}
  ```
- Response body contains zero unescaped content, no Authorization headers, and no credential patterns (`sk-`, `BSAx`).

---

## 5. Rollback Procedure to Baseline Commit 1606da0

If subsequent rollout changes introduce regressions or unapproved schema mutations, restore the system to baseline commit `1606da0`:

> [!CAUTION]
> **Safety Warning**: `git reset --hard` and `git clean -fd` permanently discard all uncommitted changes and untracked files. Operators must confirm they are in the intended repository (`pwd`) and have safely stashed or preserved any uncommitted work before executing these commands.

```bash
# 1. Verify working repository directory
pwd

# 2. Reset hard to the accepted hardening baseline
git reset --hard 0174d25

# 3. Permanently remove untracked artifacts or scratch logs
git clean -fd

# 4. Confirm clean working tree
git status --short

# 5. Synchronize the shared package if needed
cp contact_intelligence/eon_contact_research_server_purdue_v1.py \
   /Users/anasafadar/Downloads/EON_Contact_Intelligence_Shared_Package/
cp contact_intelligence/eon_contact_research_server_agentic_v1.py \
   /Users/anasafadar/Downloads/EON_Contact_Intelligence_Shared_Package/

# 6. Run regression verification suite
/opt/anaconda3/bin/pytest tests/
```

**Target Baseline State**: **248 / 248 passed**, working tree completely clean.
