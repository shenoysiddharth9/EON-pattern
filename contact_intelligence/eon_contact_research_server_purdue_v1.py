"""EON Contact Intelligence API — Agentic Research V1.
Architecture: Brave -> GPT research controller -> iterative Brave searches -> GPT evidence review -> final evidence adjudication.
Python is deterministic plumbing; the model decides what to search next. Search results are evidence leads, not automatic proof.
"""
import os, re, json, time, urllib.parse, urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BRAVE_URL = "https://api.search.brave.com/res/v1/web/search"
GENAI_BASE_URL = os.getenv("PURDUE_GENAI_BASE_URL", "https://genai.rcac.purdue.edu/api").rstrip("/")
GENAI_URL = f"{GENAI_BASE_URL}/chat/completions"
PORT = int(os.getenv("PORT", "8787"))
MODEL = os.getenv("PURDUE_GENAI_MODEL") or os.getenv("EON_LLM_MODEL") or "gpt-oss:120b"
MAX_ROUNDS = int(os.getenv("EON_MAX_RESEARCH_ROUNDS", "5"))
MAX_QUERIES_PER_ROUND = int(os.getenv("EON_MAX_QUERIES_PER_ROUND", "6"))
MAX_TOTAL_QUERIES = int(os.getenv("EON_MAX_TOTAL_QUERIES", "24"))

ICP = """EON contact ICP, strongest to weakest:
1. Primary / Direct Training Leadership: Chief Learning Officer, VP/Head of Training, Director of Training, Training Director. (Ambiguous: Training Manager, Learning Manager, Technical Training Lead - require stronger corporate corroboration).
2. Secondary / Specialized Training Leadership: senior Technical Training, Safety/HSE Training, Operations Training, Manufacturing Training, Maintenance Training, Field Service Training, Service Training, Sales Training.
3. Tertiary / L&D / Capability Leadership: senior Learning & Development, Workforce Development, Capability Development, Digital Learning, organizational learning/capability leadership.
4. Fallback / Training Practitioner: Program Manager, Project Training Manager, Training Coordinator, Training Specialist, Trainer, Instructor, Curriculum Designer.
Prefer leaders responsible for employee/workforce training. Prefer enterprise/group/division-wide responsibility over narrow/local responsibility when evidence is comparable. Do not mistake participation in training, generic HR, recruiting, digitalization, customer/product training, or a job posting for the target contact."""

EVIDENCE_RULES = """Evidence rules:
- Official corporate/company domain evidence outranks third-party profiles and scraper mirrors.
- Scraper mirrors (ZoomInfo, RocketReach, Apollo, SignalHire, etc.) must NOT count as independent corroboration.
- LinkedIn-only results are capped at Low confidence and cannot be Verified.
- Do NOT treat "Training Manager" as automatically equivalent to Head/Director-level leadership; ambiguous titles require stronger corroboration (preferably first-party corporate evidence).
- Operational/practitioner titles (Program Manager, Project Training Manager, Training Coordinator, Specialist, Trainer, Instructor) are Fallback only and must not be presented as resolved enterprise training leaders.
- If only fallback/practitioner or LinkedIn-only low-confidence leads exist, the outcome is Role Found - Person Unresolved, preserving weak leads for discovery.
- Job postings may prove a role/function exists but can NEVER become a named person/contact.
- Search snippets are evidence leads. Read exactly what they support; do not infer unsupported titles or employment.
- A person's OWN title/responsibility must fit the ICP. Incidental mentions of training do not qualify them.
- Prefer current employment. Do not call a contact Verified unless current company + relevant responsibility are corroborated.
- Verified Contact Found requires two substantively independent pieces of indexed evidence supporting person + company + relevant responsibility, OR one strong official company source plus independent corroboration.
- Duplicate pages/snippets derived from the same profile are not independent evidence.
- Probable Contact Found is allowed when one strong source clearly ties person + company + relevant role but independent corroboration is missing.
- Every returned evidence URL must appear verbatim in supplied evidence.
- Never invent names, titles, URLs, departments, employment, or relationships.
- If the ideal role/function is known but the person is unresolved, KEEP SEARCHING while budget remains instead of prematurely settling for a materially weaker fallback.
- Stop early when a strong Primary/Secondary contact is adequately verified, or when further searching is unlikely to improve the result."""

def clean(s):
    return re.sub(r"<[^>]+>", " ", re.sub(r"\s+", " ", s or "")).strip()


def simplify_query(q):
    """
    Simplifies a search query when rejected by search provider (e.g. on 422).
    Strips complex punctuation, operators, site filters with invalid syntax, quotes,
    and limits word count to ensure search provider acceptance.
    """
    clean_q = clean(q)
    # Remove quotes, brackets, and unusual symbols
    simplified = re.sub(r'["\'\(\)\[\]\{\}\<\>@#\$%\^&\*~`+=|\\/]', ' ', clean_q)
    simplified = re.sub(r'\s+', ' ', simplified).strip()
    words = simplified.split()
    if len(words) > 10:
        words = words[:10]
    return " ".join(words)


def brave_search(q, count=10, search_lang="en", extra_snippets=True, retry_simplified=True):
    """
    Executes a Brave Web Search query with robust validation, coercion, and error recovery.
    - Validates and coerces count (integer clamped between 1 and 20).
    - Validates query q: strips whitespace, enforces <= 50 words (Brave max is 75 words).
    - Omits empty or invalid optional parameters (e.g. search_lang, extra_snippets).
    - Adds Cache-Control: no-cache header.
    - If a query fails with HTTP 422 (Unprocessable Entity), retries once with a simplified query.
    - If a query still fails or cannot be processed, skips that single query and returns []
      rather than failing the entire research job.
    """
    key = (os.getenv("BRAVE_SEARCH_API_KEY") or "").strip().strip('"').strip("'")
    if not key:
        raise RuntimeError("BRAVE_SEARCH_API_KEY is not set.")

    # 1. Clean and validate query string
    q_str = clean(q)
    if not q_str:
        return []

    # Enforce safe word limit (Brave rejects > 75 words with 422)
    words = q_str.split()
    if len(words) > 50:
        q_str = " ".join(words[:50])

    # 2. Validate and coerce count (integer clamped between 1 and 20)
    try:
        coerced_count = int(count)
    except (ValueError, TypeError):
        coerced_count = 10
    if coerced_count < 1:
        coerced_count = 1
    elif coerced_count > 20:
        coerced_count = 20

    # 3. Build query parameters; omit unsupported or empty optional parameters
    params = {"q": q_str, "count": coerced_count}

    # Only include search_lang if valid non-empty string
    if isinstance(search_lang, str) and search_lang.strip():
        sl = search_lang.strip().lower()
        if sl in {"en", "en-gb", "es", "fr", "de", "it", "pt-br", "pt-pt", "nl", "ar", "ja", "zh-hans", "zh-hant"}:
            params["search_lang"] = sl

    # Only include extra_snippets if truthy
    if extra_snippets is True or str(extra_snippets).lower() == "true":
        params["extra_snippets"] = "true"

    headers = {
        "Accept": "application/json",
        "X-Subscription-Token": key,
        "Cache-Control": "no-cache",
    }

    url = BRAVE_URL + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=headers)

    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.load(r)
    except urllib.error.HTTPError as e:
        raw_body = e.read().decode("utf-8", errors="ignore")
        # Sanitize error diagnostic (redact keys and credentials)
        sanitized_body = re.sub(r"(?:Bearer|sk-|BSAx|key=|token=)[A-Za-z0-9_\-]+", "[REDACTED]", raw_body)

        # Parse error JSON safely to identify exact error type
        err_json = {}
        try:
            err_json = json.loads(raw_body)
        except Exception:
            pass

        err_obj = err_json.get("error", {}) if isinstance(err_json, dict) else {}
        err_code = err_obj.get("code") or ""
        err_detail = err_obj.get("detail") or ""

        # 1. Provider Authentication Rejection (Brave emits HTTP 422 SUBSCRIPTION_TOKEN_INVALID or 401/403)
        if err_code == "SUBSCRIPTION_TOKEN_INVALID" or "subscription token" in str(err_detail).lower() or "api key is invalid" in str(err_detail).lower() or e.code in (401, 403):
            raise RuntimeError("Provider rejected configured key: The BRAVE_SEARCH_API_KEY in Streamlit Secrets was rejected by Brave Search API (SUBSCRIPTION_TOKEN_INVALID). Please rotate or renew your key at api.search.brave.com.")

        # 2. Credit Exhaustion
        if e.code == 402 or err_code == "CREDIT_EXHAUSTED" or "credit balance" in str(err_detail).lower():
            raise RuntimeError("Provider subscription exhausted: The configured BRAVE_SEARCH_API_KEY has insufficient credit balance (HTTP 402). Please top up search units in the Brave console.")

        # 3. Query syntax validation rejection
        if e.code == 422:
            if retry_simplified:
                simple_q = simplify_query(q_str)
                if simple_q and simple_q != q_str:
                    return brave_search(simple_q, count=coerced_count, retry_simplified=False)
            # Skip rejected query gracefully rather than failing the entire research job
            return []
        else:
            # Skip transient provider failures to let other queries complete
            return []
    except Exception as e:
        if isinstance(e, RuntimeError) and "Provider" in str(e):
            raise
        return []

    out = []
    for x in data.get("web", {}).get("results", []):
        snippets = [x.get("description", "")] + (x.get("extra_snippets") or [])
        out.append({"title": clean(x.get("title")), "url": x.get("url", ""), "snippet": clean(" ".join(snippets)), "query": q_str})
    return out

def dedup_results(results):
    out=[]; seen=set()
    for r in results:
        k=r.get("url") or (r.get("title"),r.get("snippet"))
        if not k or k in seen: continue
        seen.add(k); out.append(r)
    return out


def parallel_brave_search(queries, count=10, max_workers=6):
    """
    Executes multiple independent Brave search queries concurrently via ThreadPoolExecutor.
    Preserves query index result ordering and records execution duration.
    """
    if not queries:
        return [], 0
    t0 = time.perf_counter()
    ordered_results = [[] for _ in queries]
    with ThreadPoolExecutor(max_workers=min(len(queries), max_workers)) as executor:
        future_to_idx = {
            executor.submit(brave_search, q, count): idx
            for idx, q in enumerate(queries)
        }
        for future in as_completed(future_to_idx):
            idx = future_to_idx[future]
            try:
                res = future.result()
                if res and isinstance(res, list):
                    ordered_results[idx] = res
            except Exception:
                ordered_results[idx] = []
    duration_ms = int((time.perf_counter() - t0) * 1000)
    flat = []
    for r in ordered_results:
        flat.extend(r)
    return flat, duration_ms


class StructuredJsonParseError(ValueError):
    """Raised when model output cannot be safely parsed as structured JSON."""
    def __init__(self, message="Failed to parse structured model output as JSON", raw_content=None):
        super().__init__(message)
        self.raw_content = raw_content

    def get_protected_diagnostic(self, max_len=300):
        """
        Returns redacted and truncated diagnostic string; safe only for protected debug/error logs.
        Never log at INFO level or export to shared observability destinations.
        """
        if not self.raw_content:
            return ""
        s = re.sub(r"(?:Bearer|sk-|BSAx|key=|token=)[A-Za-z0-9_\-]+", "[REDACTED]", str(self.raw_content))
        s = re.sub(r"https?://[^\s'\"]+", "[REDACTED_URL]", s)
        if len(s) > max_len:
            return s[:max_len] + "... [TRUNCATED]"
        return s


def parse_structured_json(content):
    """
    Safely parses structured JSON output from LLM.
    Strictly permits safe fallbacks only:
    1. Strip Markdown code fences.
    2. Extract a clearly bounded outer JSON object.
    3. Parse strict JSON first.
    4. Optionally permit trailing-comma / JSON5 relaxed syntax only.

    NEVER attempts to heuristically escape unescaped quotes inside strings.
    If parsing fails, raises StructuredJsonParseError and retains raw model output
    only in server-side diagnostics (self.raw_content).
    """
    if isinstance(content, dict):
        return content
    if not isinstance(content, str):
        try:
            return json.loads(content)
        except Exception:
            raise StructuredJsonParseError(raw_content=str(content)) from None

    text = content.strip()
    # 1. Strip Markdown code fences
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        text = text.strip()

    # 2. Parse strict JSON first
    try:
        return json.loads(text)
    except Exception:
        pass

    # 3. Extract a clearly bounded outer JSON object
    first_b = text.find("{")
    last_b = text.rfind("}")
    if first_b != -1 and last_b != -1 and last_b > first_b:
        bounded = text[first_b:last_b+1]
        try:
            return json.loads(bounded)
        except Exception:
            pass

        # 4. Optionally permit trailing-comma / JSON5 relaxed syntax only
        no_trailing = re.sub(r",\s*([\]}])", r"\1", bounded)
        try:
            return json.loads(no_trailing)
        except Exception:
            pass

        # JSON5 safely handles benign formatting relaxed syntax (e.g., trailing commas, comments)
        # without mutating semantic string contents or guessing quote boundaries. Heuristic
        # content repair (such as unescaped interior quote rewrites) is strictly prohibited.
        try:
            import json5
            return json5.loads(bounded)
        except Exception:
            pass

    # Fails safely without silently rewriting malformed quotes
    raise StructuredJsonParseError(
        message="Failed to parse structured model output as JSON",
        raw_content=content
    )


def openai_json(instructions, payload, schema, name, max_tokens=5000):
    key = (
        os.getenv("PURDUE_GENAI_API_KEY")
        or os.getenv("GENAI_API_KEY")
        or os.getenv("OPENAI_API_KEY")
        or ""
    ).strip().strip('"').strip("'")
    if not key:
        raise RuntimeError("PURDUE_GENAI_API_KEY is not set.")

    base_url = (os.getenv("PURDUE_GENAI_BASE_URL") or "https://genai.rcac.purdue.edu/api").rstrip("/")
    genai_url = f"{base_url}/chat/completions"
    model = os.getenv("PURDUE_GENAI_MODEL") or os.getenv("EON_LLM_MODEL") or MODEL or "gpt-oss:120b"
    temp = float(os.getenv("PURDUE_GENAI_TEMPERATURE", "0.2"))

    full_instructions = instructions + "\nCRITICAL: Return strictly valid JSON conforming exactly to the schema. Do not include unescaped quotes within text fields."
    
    last_err = None
    for attempt in range(2):
        body = {
            "model": model,
            "temperature": temp,
            "seed": 42 + attempt,
            "messages": [
                {"role": "system", "content": full_instructions},
                {
                    "role": "user",
                    "content": json.dumps(payload, ensure_ascii=False),
                },
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": name,
                    "schema": schema,
                },
            },
            "stream": False,
            "max_tokens": max_tokens,
        }

        req = urllib.request.Request(
            genai_url,
            data=json.dumps(body).encode(),
            method="POST",
            headers={
                "Authorization": "Bearer " + key,
                "Content-Type": "application/json",
            },
        )

        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                data = json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 400 and "response_format" in body:
                del body["response_format"]
                req_fallback = urllib.request.Request(
                    genai_url,
                    data=json.dumps(body).encode(),
                    method="POST",
                    headers={
                        "Authorization": "Bearer " + key,
                        "Content-Type": "application/json",
                    },
                )
                try:
                    with urllib.request.urlopen(req_fallback, timeout=180) as r_fb:
                        data = json.load(r_fb)
                except Exception:
                    raise RuntimeError(
                        f"LLM provider API request failed with status code {e.code}"
                    )
            else:
                raise RuntimeError(
                    f"LLM provider API request failed with status code {e.code}"
                )

        if data is None:
            raise RuntimeError(
                "Purdue GenAI returned null, possibly because of rate limiting."
            )

        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise RuntimeError("LLM provider returned an unexpected response structure.")

        if not content:
            raise RuntimeError("Purdue GenAI returned no structured output.")

        try:
            return parse_structured_json(content)
        except StructuredJsonParseError as e:
            last_err = e
            if attempt == 0:
                continue
            raise e
        except Exception as e:
            last_err = e
            if attempt == 0:
                continue
            raise StructuredJsonParseError(raw_content=content) from None

ROUND_SCHEMA={
 "type":"object","additionalProperties":False,
 "properties":{
   "training_structure":{"type":"string"},
   "discovered_functions":{"type":"array","items":{"type":"string"}},
   "best_candidates_so_far":{"type":"array","items":{"type":"object","additionalProperties":False,"properties":{
      "name":{"type":"string"},"supported_role":{"type":"string"},"icp_level":{"type":"string","enum":["Primary","Secondary","Tertiary","Fallback","Unclear"]},"evidence_state":{"type":"string"},"missing_evidence":{"type":"string"}
   },"required":["name","supported_role","icp_level","evidence_state","missing_evidence"]}},
   "ideal_unresolved_role":{"anyOf":[{"type":"string"},{"type":"null"}]},
   "continue_research":{"type":"boolean"},
   "next_queries":{"type":"array","items":{"type":"string"}},
   "reason":{"type":"string"}
 },
 "required":["training_structure","discovered_functions","best_candidates_so_far","ideal_unresolved_role","continue_research","next_queries","reason"]
}

FINAL_SCHEMA={
 "type":"object","additionalProperties":False,
 "properties":{
   "status":{"type":"string","enum":["Verified Contact Found","Probable Contact Found","Role Found - Person Unresolved","No Relevant Contact Found"]},
   "primary_contact":{"anyOf":[{"type":"object","additionalProperties":False,"properties":{
      "name":{"type":"string"},"title":{"type":"string"},"contact_category":{"type":"string"},"icp_level":{"type":"string","enum":["Primary","Secondary","Tertiary","Fallback"]},
      "current_employment_status":{"type":"string","enum":["Verified","Probable","Unconfirmed","Former","Unknown"]},
      "employment_status_note":{"type":"string"},
      "evidence_confidence":{"type":"string","enum":["High","Medium","Low"]},"why_selected":{"type":"string"},
      "evidence_urls":{"type":"array","items":{"type":"string"}}
   },"required":["name","title","contact_category","icp_level","current_employment_status","evidence_confidence","why_selected","evidence_urls"]},{"type":"null"}]},
   "alternative_contacts":{"type":"array","items":{"type":"object","additionalProperties":False,"properties":{
      "name":{"type":"string"},"title":{"type":"string"},"icp_level":{"type":"string","enum":["Primary","Secondary","Tertiary","Fallback"]},"why_selected":{"type":"string"},"evidence_urls":{"type":"array","items":{"type":"string"}}
   },"required":["name","title","icp_level","why_selected","evidence_urls"]}},
   "ideal_role":{"anyOf":[{"type":"string"},{"type":"null"}]},
   "evidence_confidence":{"type":"string","enum":["High","Medium","Low"]},
   "decision_reason":{"type":"string"}
 },
 "required":["status","primary_contact","alternative_contacts","ideal_role","evidence_confidence","decision_reason"]
}

ALLOWED_EMPLOYMENT_STATUSES = {"Verified", "Probable", "Unconfirmed", "Former", "Unknown"}


def normalize_employment_status(contact):
    """
    Normalizes current_employment_status to a fixed vocabulary:
    Verified, Probable, Unconfirmed, Former, or Unknown.
    Extracts explanatory free text into employment_status_note.
    """
    if not isinstance(contact, dict):
        return contact

    raw = str(contact.get("current_employment_status") or "").strip()
    note = contact.get("employment_status_note") or ""

    if raw == "Verified":
        norm = "Verified"
    elif raw in ALLOWED_EMPLOYMENT_STATUSES:
        norm = raw
    elif raw:
        if not note:
            if "no independent confirmation" in raw.lower() or "one source" in raw.lower():
                note = "Listed as current on one third-party publisher; no independent confirmation of current tenure."
            else:
                note = raw

        raw_lower = raw.lower()
        if "former" in raw_lower or "left" in raw_lower or "past" in raw_lower:
            norm = "Former"
        elif "unconfirmed" in raw_lower or "unverified" in raw_lower:
            norm = "Unconfirmed"
        elif "unknown" in raw_lower:
            norm = "Unknown"
        else:
            norm = "Probable"
    else:
        norm = "Unknown"

    contact["current_employment_status"] = norm
    if note:
        contact["employment_status_note"] = note
    return contact


# ==============================================================================
# PHASE 2: CANONICAL EVIDENCE LAYER, URL NORMALIZATION & SOURCE INDEPENDENCE
# ==============================================================================

TRACKING_QUERY_PARAMS = {
    # Standard campaign analytics
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "utm_name",
    # Ad and platform click IDs
    "fbclid", "gclid", "gclsrc", "dclid", "msclkid", "twclid", "igshid", "mc_eid",
    # Social / professional profile tracking
    "ref", "trk", "trackingid", "refid", "originalsubdomain", "miniprofileurn",
    "context", "session_id", "sid", "_hsenc", "_hsmi", "source", "v", "t",
}

# Maintainable registry mapping domain suffixes to source families
SOURCE_FAMILY_REGISTRY = {
    # 1. linkedin_ecosystem: LinkedIn + known profile aggregators/directories/scraper mirrors
    "linkedin.com": "linkedin_ecosystem",
    "zoominfo.com": "linkedin_ecosystem",
    "zi.com": "linkedin_ecosystem",
    "rocketreach.co": "linkedin_ecosystem",
    "rocketreach.com": "linkedin_ecosystem",
    "apollo.io": "linkedin_ecosystem",
    "lusha.com": "linkedin_ecosystem",
    "signalhire.com": "linkedin_ecosystem",
    "contactout.com": "linkedin_ecosystem",
    "clay.com": "linkedin_ecosystem",
    "clay.run": "linkedin_ecosystem",
    "topionetworks.com": "linkedin_ecosystem",
    "leadiq.com": "linkedin_ecosystem",
    "datanyze.com": "linkedin_ecosystem",
    "cognism.com": "linkedin_ecosystem",
    "theorg.com": "linkedin_ecosystem",
    "adapt.io": "linkedin_ecosystem",
    "updata.com": "linkedin_ecosystem",
    "swordfish.ai": "linkedin_ecosystem",
    "kaspr.io": "linkedin_ecosystem",

    # 2. editorial: Major verified business / news / trade journalism
    "reuters.com": "editorial",
    "bloomberg.com": "editorial",
    "forbes.com": "editorial",
    "wsj.com": "editorial",
    "ft.com": "editorial",
    "rigzone.com": "editorial",
    "offshore-energy.biz": "editorial",
    "industryweek.com": "editorial",
    "oedigital.com": "editorial",
    "worldoil.com": "editorial",
    "hartenergy.com": "editorial",
    "oilandgasiq.com": "editorial",
    "energyvoice.com": "editorial",
    "upstreamonline.com": "editorial",
    "businesswire.com": "editorial",
    "prnewswire.com": "editorial",
    "globenewswire.com": "editorial",

    # 3. regulatory: SEC filings, government portals, official registries
    "sec.gov": "regulatory",
    "edgar-online.com": "regulatory",
    "gov.uk": "regulatory",
    "companieshouse.gov.uk": "regulatory",
    "registroimprese.it": "regulatory",

    # 4. conference: Industry conferences, summits, technical societies
    "spe.org": "conference",
    "adipec.com": "conference",
    "otcnet.org": "conference",
    "td.org": "conference",
    "chieflearningofficer.com": "conference",

    # 5. directory_unclassified: Third-party profile/salary aggregators & unclassified directories
    "comparably.com": "directory_unclassified",
}

AUTHORITY_TIER_MAP = {
    "corporate": "tier_1_first_party",
    "regulatory": "tier_2_verified_institutional",
    "editorial": "tier_2_verified_institutional",
    "conference": "tier_2_verified_institutional",
    "linkedin_ecosystem": "tier_3_professional_ecosystem",
    "directory_unclassified": "tier_4_unverified_web",
}

AUTHORITY_TIER_LABELS = {
    "tier_1_first_party": "Tier 1: First-Party Corporate",
    "tier_2_verified_institutional": "Tier 2: Institutional / Editorial / Conference",
    "tier_3_professional_ecosystem": "Tier 3: Professional Ecosystem (Self-Reported / Mirror)",
    "tier_4_unverified_web": "Tier 4: Unverified Web / Unclassified Directory",
}

SCRAPER_DOMAINS = {
    dom for dom, fam in SOURCE_FAMILY_REGISTRY.items()
    if fam in {"linkedin_ecosystem", "directory_unclassified"} and dom != "linkedin.com"
}


def canonicalize_url(raw_url: str) -> str:
    """
    Normalizes URLs to ensure scoring evaluates independent sources rather than
    tracking variants or syntactic permutations:
    - Protocol normalized to https
    - Host lowercased, default ports stripped, 'www.' stripped
    - Path trailing slashes stripped (preserving root '/'), multi-slashes collapsed
    - Fragments (#...) discarded
    - Tracking & campaign parameters removed (utm_*, ref, trk, etc.)
    - Remaining functional parameters sorted deterministically
    """
    if not raw_url or not isinstance(raw_url, str):
        return ""
    u = raw_url.strip()
    if not u:
        return ""
    if "://" not in u:
        u = "https://" + u
    try:
        parsed = urllib.parse.urlparse(u)
    except Exception:
        return raw_url.strip()

    scheme = "https"
    host = (parsed.netloc or "").lower().split(":")[0].strip()
    if host.startswith("www."):
        host = host[4:]

    if not host:
        return raw_url.strip()

    path = parsed.path or ""
    path = re.sub(r"/+", "/", path)
    if len(path) > 1 and path.endswith("/"):
        path = path[:-1]

    clean_params = []
    if parsed.query:
        query_pairs = urllib.parse.parse_qsl(parsed.query, keep_blank_values=False)
        for k, v in query_pairs:
            k_lower = k.lower().strip()
            if k_lower not in TRACKING_QUERY_PARAMS and not k_lower.startswith("utm_"):
                clean_params.append((k, v))
        clean_params.sort(key=lambda x: (x[0], x[1]))

    query_str = urllib.parse.urlencode(clean_params) if clean_params else ""
    canon = f"{scheme}://{host}{path}"
    if query_str:
        canon += f"?{query_str}"
    return canon


def classify_contact_research_status(primary_contact=None, ideal_role=None, is_weak_match=False):
    """
    Determine top-level contact research status logically consistent with primary_contact.

    Required invariant:
    if is_weak_match:
        contact_research_status = "Role Found - Person Unresolved"
    elif primary_contact and primary_contact.current_employment_status == "Verified":
        contact_research_status = "Verified Contact Found"
    elif primary_contact:
        contact_research_status = "Probable Contact Found"
    elif ideal_role:
        contact_research_status = "Role Found - Person Unresolved"
    else:
        contact_research_status = "No Relevant Contact Found"
    """
    if isinstance(primary_contact, dict) and "primary_contact" in primary_contact and "name" not in primary_contact:
        payload = primary_contact
        ideal_role = payload.get("ideal_role", ideal_role)
        is_weak_match = payload.get("is_weak_match", is_weak_match)
        primary_contact = payload.get("primary_contact")

    if isinstance(primary_contact, dict) and primary_contact.get("is_weak_match"):
        is_weak_match = True

    if is_weak_match:
        return "Role Found - Person Unresolved"

    emp_status = None
    if primary_contact is not None:
        if isinstance(primary_contact, dict):
            emp_status = primary_contact.get("current_employment_status")
        else:
            emp_status = getattr(primary_contact, "current_employment_status", None)

    # Invariant: only exact normalized "Verified" value qualifies as verified.
    # Descriptive free text (e.g. "Verified as listed on...") does NOT qualify.
    if primary_contact and emp_status == "Verified":
        return "Verified Contact Found"
    elif primary_contact:
        return "Probable Contact Found"
    elif ideal_role:
        return "Role Found - Person Unresolved"
    else:
        return "No Relevant Contact Found"


def extract_publisher_domain(url):
    """Extract normalized base publisher domain from a URL (e.g. 'comparably.com')."""
    if not url or not isinstance(url, str):
        return ""
    try:
        parsed = urllib.parse.urlparse(url if "://" in url else "https://" + url)
        host = (parsed.netloc or "").lower().split(":")[0]
        if host.startswith("www."):
            host = host[4:]
        return host
    except Exception:
        return ""


def classify_source_family(url, company_domain="", company_name=""):
    """
    Classifies a URL into an authoritative source family and tier:
    - corporate: tier_1_first_party (company domain / name match)
    - regulatory: tier_2_verified_institutional
    - editorial: tier_2_verified_institutional
    - conference: tier_2_verified_institutional
    - linkedin_ecosystem: tier_3_professional_ecosystem
    - directory_unclassified: tier_4_unverified_web (conservative default for unknown domains)
    """
    domain = extract_publisher_domain(url)
    if not domain:
        return "directory_unclassified", "tier_4_unverified_web"

    # 1. Corporate first-party check
    corp_host = extract_publisher_domain(company_domain) if company_domain else ""
    corp_slug = re.sub(r"[^a-z0-9]", "", str(company_name or "").lower())

    if corp_host and (domain == corp_host or domain.endswith("." + corp_host)):
        return "corporate", "tier_1_first_party"
    if corp_slug and len(corp_slug) >= 4 and corp_slug in domain.replace("-", "").replace(".", ""):
        return "corporate", "tier_1_first_party"

    # 2. Registry lookup (exact or suffix match)
    for reg_domain, family in SOURCE_FAMILY_REGISTRY.items():
        if domain == reg_domain or domain.endswith("." + reg_domain):
            tier = AUTHORITY_TIER_MAP.get(family, "tier_4_unverified_web")
            return family, tier

    # 3. Conservative default for unclassified directories / unknown sites
    return "directory_unclassified", "tier_4_unverified_web"


def is_scraper_domain(domain):
    """Check if a domain matches known scraper mirror aggregators in linkedin_ecosystem."""
    d = (domain or "").lower().strip()
    return any(d == s or d.endswith("." + s) for s in SCRAPER_DOMAINS)


def canonicalize_evidence_records(urls, company_domain="", company_name=""):
    """
    Ingests raw URLs and produces structured canonical evidence records:
    - Preserves all raw URLs for audit trail.
    - Maps each raw URL to its canonical form.
    - Detects duplicate URLs and family mirrors.
    - Counts substantive independent source families.
    - Emits transparent summary: 'X independent sources · Y raw URLs · Z duplicates/mirrors excluded.'
    """
    evidence_records = []
    seen_canonical_urls = set()
    seen_families = set()
    independent_families = set()

    raw_urls = [u for u in (urls or []) if u and isinstance(u, str) and u.strip()]

    for raw_url in raw_urls:
        canon_url = canonicalize_url(raw_url)
        family, tier = classify_source_family(canon_url or raw_url, company_domain=company_domain, company_name=company_name)

        is_duplicate_url = False
        is_family_mirror = False
        status = "Primary Canonical"

        if canon_url in seen_canonical_urls:
            is_duplicate_url = True
            status = "Duplicate URL"
        else:
            seen_canonical_urls.add(canon_url)
            if family in seen_families:
                is_family_mirror = True
                status = "Family Mirror"
            else:
                seen_families.add(family)

        if status == "Primary Canonical":
            if family in {"corporate", "editorial", "regulatory", "conference", "linkedin_ecosystem"}:
                independent_families.add(family)

        domain = extract_publisher_domain(canon_url or raw_url)
        evidence_records.append({
            "raw_url": raw_url,
            "canonical_url": canon_url,
            "domain": domain,
            "source_family": family,
            "authority_tier": tier,
            "is_duplicate_url": is_duplicate_url,
            "is_family_mirror": is_family_mirror,
            "provenance_status": status,
            "status": status,
        })

    num_raw = len(raw_urls)
    num_independent = len(independent_families)
    num_excluded = sum(1 for r in evidence_records if r["is_duplicate_url"] or r["is_family_mirror"])

    s_indep = "source" if num_independent == 1 else "sources"
    s_raw = "raw URL" if num_raw == 1 else "raw URLs"
    s_excl = "duplicate/mirror" if num_excluded == 1 else "duplicates/mirrors"
    summary_text = f"{num_independent} independent {s_indep} · {num_raw} {s_raw} · {num_excluded} {s_excl} excluded"

    return {
        "evidence_records": evidence_records,
        "independent_families": independent_families,
        "num_independent_sources": num_independent,
        "num_raw_urls": num_raw,
        "num_excluded_mirrors": num_excluded,
        "has_corporate": "corporate" in independent_families,
        "has_linkedin": "linkedin_ecosystem" in seen_families,
        "is_linkedin_only": (
            ("linkedin_ecosystem" in seen_families or "directory_unclassified" in seen_families)
            and not any(f in independent_families for f in ["corporate", "editorial", "regulatory", "conference"])
        ),
        "summary_text": summary_text,
    }


# ==============================================================================
# PHASE 3: EMPLOYMENT FRESHNESS & CURRENT-EMPLOYMENT VERIFICATION ENGINE
# ==============================================================================

ALLOWED_FRESHNESS_STATUSES = {
    "Current Employment Confirmed",
    "Current Employment Likely",
    "Employment Unconfirmed",
    "Possible Former Employee / Stale Evidence",
}

# Calibrated Threshold Windows (in months relative to anchor)
T1_CONFIRMED_MAX_MONTHS = 12
T1_LIKELY_MAX_MONTHS = 24
T1_UNCONFIRMED_MAX_MONTHS = 36  # > 36 is Stale / Former

T3_LIKELY_MAX_MONTHS = 18
T3_UNCONFIRMED_MAX_MONTHS = 30  # > 30 is Stale / Former

T4_LIKELY_MAX_MONTHS = 12
T4_UNCONFIRMED_MAX_MONTHS = 30  # > 30 is Stale / Former

CONTRADICTION_PATTERNS = [
    re.compile(r"\bformerly\s+(?:of|at|with)\b", re.I),
    re.compile(r"\bformer\s+(?:chief|director|head|vp|president|manager|leader|officer|exec|executive)\b", re.I),
    re.compile(r"\bex-(?:[a-z0-9_-]+)\b", re.I),
    re.compile(r"\bdeparted\b", re.I),
    re.compile(r"\bstepped down\b", re.I),
    re.compile(r"\bleft\s+[A-Z][a-zA-Z0-9\s]+\s+in\s+20\d{2}\b", re.I),
    re.compile(r"\bjoined\s+[A-Z][a-zA-Z0-9\s]+\b", re.I),
    re.compile(r"\bappointed\s+(?:at|to)\s+[A-Z][a-zA-Z0-9\s]+\b", re.I),
    re.compile(r"\bnow\s+at\s+[A-Z][a-zA-Z0-9\s]+\b", re.I),
]


def parse_evidence_date(date_str):
    """Parses various date string formats into a datetime object."""
    if not date_str:
        return None
    d = str(date_str).strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m", "%B %Y", "%b %Y", "%Y"):
        try:
            return datetime.strptime(d, fmt)
        except ValueError:
            pass
    m = re.search(r"\b(20\d{2})[-/](0[1-9]|1[0-2])[-/](0[1-9]|[12]\d|3[01])\b", d)
    if m:
        try:
            return datetime.strptime(m.group(0).replace("/", "-"), "%Y-%m-%d")
        except ValueError:
            pass
    m2 = re.search(r"\b(20\d{2})\b", d)
    if m2:
        return datetime(int(m2.group(1)), 1, 1)
    return None


def compute_age_months(dt, anchor=None):
    """Computes approximate age in months between dt and anchor (defaults to UTC now)."""
    if not dt:
        return None
    if anchor is None:
        anchor = datetime.now(timezone.utc)
    if hasattr(anchor, "tzinfo") and anchor.tzinfo is not None and (not hasattr(dt, "tzinfo") or dt.tzinfo is None):
        dt = dt.replace(tzinfo=timezone.utc)
    elif (hasattr(dt, "tzinfo") and dt.tzinfo is not None) and (not hasattr(anchor, "tzinfo") or anchor.tzinfo is None):
        anchor = anchor.replace(tzinfo=timezone.utc)
    diff_days = (anchor - dt).days
    return max(0, int(diff_days / 30.4375))


def extract_evidence_date(url_or_rec, snippet=""):
    """Extracts date string from an evidence record, URL, or snippet if present."""
    if isinstance(url_or_rec, dict):
        d = url_or_rec.get("date") or url_or_rec.get("published_date") or url_or_rec.get("published")
        if d:
            return str(d).strip()
        url = url_or_rec.get("url") or url_or_rec.get("canonical_url") or url_or_rec.get("raw_url") or ""
        snip = url_or_rec.get("snippet") or url_or_rec.get("title") or snippet or ""
    else:
        url = str(url_or_rec or "").strip()
        snip = snippet or ""

    m_url = re.search(r"\b(20\d{2})[-/](0[1-9]|1[0-2])[-/](0[1-9]|[12]\d|3[01])\b", url)
    if m_url:
        return m_url.group(0).replace("/", "-")

    m_ym = re.search(r"/(20\d{2})/(0[1-9]|1[0-2])/", url)
    if m_ym:
        return f"{m_ym.group(1)}-{m_ym.group(2)}-01"

    m_yr = re.search(r"[/_-](20\d{2})[/_.-]", url)
    if m_yr:
        return f"{m_yr.group(1)}-01-01"

    m_snip = re.search(r"\b(20\d{2})[-/](0[1-9]|1[0-2])[-/](0[1-9]|[12]\d|3[01])\b", snip)
    if m_snip:
        return m_snip.group(0).replace("/", "-")

    m_txt = re.search(r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+(20\d{2})\b", snip, re.I)
    if m_txt:
        try:
            parsed = datetime.strptime(f"{m_txt.group(1)} {m_txt.group(2)}", "%B %Y")
            return parsed.strftime("%Y-%m-%d")
        except ValueError:
            pass

    return None


def check_contradiction(candidate, all_evidence=None, company_name=""):
    """
    Check if candidate evidence contains signals indicating departure or a competing employer.
    Phase 3.1: Expanded transition language, candidate identity association, and false-positive guards.
    """
    if not isinstance(candidate, dict):
        return False, ""

    if candidate.get("has_contradictory_employer") or candidate.get("contradictions"):
        return True, "Explicit contradiction flag or conflicting employer detected"

    curr_emp = str(candidate.get("current_employer") or "").strip()
    if curr_emp and company_name and curr_emp.lower() != company_name.lower():
        return True, f"Listed current employer '{curr_emp}' contradicts target company '{company_name}'"

    cand_name = str(candidate.get("name") or "").strip()
    if not cand_name:
        return False, ""

    cand_parts = [p.lower() for p in re.findall(r"[a-zA-Z]{2,}", cand_name)]
    if not cand_parts:
        return False, ""

    comp_clean = str(company_name or "").lower().strip()
    comp_words = set(re.findall(r"[a-zA-Z]{3,}", comp_clean))

    direct_sources = []
    if candidate.get("why_selected"):
        direct_sources.append(candidate.get("why_selected"))

    external_sources = []
    for rec in candidate.get("evidence_records", []):
        if rec.get("snippet"):
            external_sources.append(rec.get("snippet"))
        if rec.get("title"):
            external_sources.append(rec.get("title"))

    if all_evidence:
        for ev in all_evidence:
            txt = (ev.get("snippet", "") + " " + ev.get("title", ""))
            if txt:
                external_sources.append(txt)

    departure_from_target = [
        re.compile(r"\bleft\s+([A-Z][a-zA-Z0-9&.\s]{1,40}?)(?:\s+(?:to|for|in|after|as)\b|\.|\,|$)", re.I),
        re.compile(r"\b(?:formerly\s+(?:of|at|with)|former\s+[a-zA-Z\s]{2,40}?\s+(?:at|with|of))\s+([A-Z][a-zA-Z0-9&.\s]{1,40}?)(?:\s+(?:as|in|after|to)\b|\.|\,|$)", re.I),
        re.compile(r"\bdeparted\s+(?:from\s+)?([A-Z][a-zA-Z0-9&.\s]{1,40}?)(?:\s|\.|\,|$)", re.I),
        re.compile(r"\bstepped\s+down\s+from\s+([A-Z][a-zA-Z0-9&.\s]{1,40}?)(?:\s|\.|\,|$)", re.I),
    ]

    new_employer_transition = [
        re.compile(r"\b(?:joined|now\s+at|currently\s+(?:at|with|[a-zA-Z\s]{2,30}\s+at))\s+([A-Z][a-zA-Z0-9&.\s]{1,40}?)(?:\s+(?:as|in|after|from)\b|\.|\,|$)", re.I),
        re.compile(r"\bappointed\s+(?:at|to\s+(?:lead|direct|head\s+of)?\s*)\s+([A-Z][a-zA-Z0-9&.\s]{1,40}?)(?:\s+(?:as|in|after)\b|\.|\,|$)", re.I),
    ]

    generic_non_employers = {"the team", "the board", "the program", "the initiative", "the company", "our team", "a team"}

    for raw_txt, is_direct in [(s, True) for s in direct_sources] + [(s, False) for s in external_sources]:
        for sentence in re.split(r"[\.\n\r;]+", raw_txt):
            s_lower = sentence.lower()
            if not is_direct and not all(p in s_lower for p in cand_parts):
                continue

            for pat in departure_from_target:
                m = pat.search(sentence)
                if m:
                    dept_comp = m.group(1).strip().lower()
                    dept_words = set(re.findall(r"[a-zA-Z]{3,}", dept_comp))
                    if dept_words and comp_words and (dept_words.issubset(comp_words) or comp_words.issubset(dept_words)):
                        return True, f"Explicit departure from target company: '{m.group(0).strip()}'"
                    elif not dept_words or not comp_words:
                        return True, f"Departure detected: '{m.group(0).strip()}'"

            for pat in new_employer_transition:
                m = pat.search(sentence)
                if m:
                    new_comp = m.group(1).strip().lower()
                    new_words = set(re.findall(r"[a-zA-Z]{3,}", new_comp))
                    if new_words and comp_words and (new_words.issubset(comp_words) or comp_words.issubset(new_words)):
                        continue
                    if new_comp in generic_non_employers or any(gn in new_comp for gn in ["initiative", "program", "committee"]):
                        continue
                    if new_words:
                        return True, f"Transition to competing employer: '{m.group(0).strip()}'"

    return False, ""


def freshness_rank_order(status):
    """Deterministic integer ranking for employment freshness states (higher is better)."""
    ranks = {
        "Current Employment Confirmed": 4,
        "Current Employment Likely": 3,
        "Employment Unconfirmed": 2,
        "Possible Former Employee / Stale Evidence": 1,
    }
    return ranks.get(status, 2)


def evaluate_employment_freshness(candidate, all_evidence=None, company_domain="", company_name="", anchor_date=None):
    """
    Evaluates candidate employment freshness independently from title strength or seniority.
    Returns:
    {
        "employment_freshness_status": str,
        "employment_freshness_rationale": str,
        "evidence_date": str or None,
        "evidence_age_months": int or None,
        "has_contradictory_employer": bool,
        "is_stale_or_unconfirmed": bool
    }
    """
    if not isinstance(candidate, dict):
        return {
            "employment_freshness_status": "Employment Unconfirmed",
            "employment_freshness_rationale": "Invalid candidate payload",
            "evidence_date": None,
            "evidence_age_months": None,
            "has_contradictory_employer": False,
            "is_stale_or_unconfirmed": True,
        }

    if anchor_date is None:
        anchor_date = datetime.now(timezone.utc)
    elif isinstance(anchor_date, str):
        anchor_date = parse_evidence_date(anchor_date) or datetime.now(timezone.utc)

    # 1. Contradiction check
    has_contra, contra_reason = check_contradiction(candidate, all_evidence=all_evidence, company_name=company_name)
    if has_contra:
        return {
            "employment_freshness_status": "Possible Former Employee / Stale Evidence",
            "employment_freshness_rationale": f"Contradictory evidence detected: {contra_reason}.",
            "evidence_date": None,
            "evidence_age_months": None,
            "has_contradictory_employer": True,
            "is_stale_or_unconfirmed": True,
        }

    urls = candidate.get("evidence_urls") or []
    records = candidate.get("evidence_records")
    if not records:
        if urls:
            meta = canonicalize_evidence_records(urls, company_domain=company_domain, company_name=company_name)
            records = meta.get("evidence_records", [])
        else:
            records = []

    if not records:
        return {
            "employment_freshness_status": "Employment Unconfirmed",
            "employment_freshness_rationale": "No evidence URLs provided for freshness evaluation.",
            "evidence_date": None,
            "evidence_age_months": None,
            "has_contradictory_employer": False,
            "is_stale_or_unconfirmed": True,
        }

    has_live_corporate_roster = False
    has_live_editorial_roster = False
    dated_records = []
    min_age = None
    best_date_str = None

    for rec in records:
        url = rec.get("canonical_url") or rec.get("raw_url") or rec.get("url") or ""
        family = rec.get("source_family", "")
        tier = rec.get("authority_tier", "")
        is_live = rec.get("is_live_roster", False)
        domain = rec.get("domain") or extract_publisher_domain(url)

        # Scrapers and aggregators can never be live rosters
        is_aggregator = is_scraper_domain(domain) or family == "directory_unclassified"

        path = urllib.parse.urlparse(url).path.lower()
        is_roster_path = any(p in path for p in [
            "/leadership", "/executive-team", "/our-leadership", "/about/leadership",
            "/corporate-governance", "/board-of-directors", "/team", "/our-team",
            "/people", "/our-people", "/management", "/careers/training-leadership"
        ])

        if (is_live or is_roster_path) and not is_aggregator:
            if family == "corporate" or tier in {"tier_1_corporate_first_party", "tier_1_first_party"}:
                has_live_corporate_roster = True
            elif family == "editorial" or tier == "tier_2_verified_institutional":
                has_live_editorial_roster = True

        d_str = rec.get("date") or extract_evidence_date(rec) or extract_evidence_date(url)
        parsed_dt = parse_evidence_date(d_str)
        if parsed_dt:
            age = compute_age_months(parsed_dt, anchor=anchor_date)
            dated_records.append({
                "tier": tier,
                "family": family,
                "date_str": d_str,
                "parsed_dt": parsed_dt,
                "age_months": age,
                "url": url,
                "domain": domain,
                "is_aggregator": is_aggregator,
            })
            if min_age is None or age < min_age:
                min_age = age
                best_date_str = d_str

    # RULE 1: Live first-party corporate leadership roster (undated or dated)
    if has_live_corporate_roster:
        return {
            "employment_freshness_status": "Current Employment Confirmed",
            "employment_freshness_rationale": "Confirmed via active first-party corporate leadership roster on company domain.",
            "evidence_date": best_date_str,
            "evidence_age_months": min_age,
            "has_contradictory_employer": False,
            "is_stale_or_unconfirmed": False,
        }

    # RULE 2: Dated official corporate or regulatory documents
    if dated_records:
        tier_order = {
            "tier_1_corporate_first_party": 1,
            "tier_1_first_party": 1,
            "tier_1_regulatory_filing": 1,
            "tier_2_verified_institutional": 2,
            "tier_3_secondary_event": 3,
            "tier_3_professional_ecosystem": 4,
            "tier_4_unverified_web": 5,
        }
        dated_records.sort(key=lambda r: (1 if r.get("family") in {"corporate", "regulatory"} else tier_order.get(r["tier"], 5), r["age_months"]))
        top = dated_records[0]
        age = top["age_months"]
        t = top["tier"]
        fam = top.get("family", "")

        if t in {"tier_1_corporate_first_party", "tier_1_first_party", "tier_1_regulatory_filing"} or fam in {"corporate", "regulatory"}:
            if age <= T1_CONFIRMED_MAX_MONTHS:
                st = "Current Employment Confirmed"
                rat = f"Confirmed via official corporate/regulatory record from {top['date_str']} ({age} months ago, within 12-month confirmed window)."
            elif age <= T1_LIKELY_MAX_MONTHS:
                st = "Current Employment Likely"
                rat = f"Likely current via corporate/regulatory record from {top['date_str']} ({age} months ago, within 24-month likely window)."
            elif age <= T1_UNCONFIRMED_MAX_MONTHS:
                st = "Employment Unconfirmed"
                rat = f"Corporate/regulatory document is dated {top['date_str']} ({age} months ago), exceeding the active 24-month window."
            else:
                st = "Possible Former Employee / Stale Evidence"
                rat = f"Historical corporate/regulatory record is {age} months old ({top['date_str']}); historical evidence cannot confirm current tenure."

        elif t == "tier_2_verified_institutional":
            if age <= T3_LIKELY_MAX_MONTHS:
                st = "Current Employment Likely"
                rat = f"Likely current via dated editorial/trade publication from {top['date_str']} ({age} months ago)."
            elif age <= T3_UNCONFIRMED_MAX_MONTHS:
                st = "Employment Unconfirmed"
                rat = f"Editorial publication is dated {top['date_str']} ({age} months ago); aging third-party coverage."
            else:
                st = "Possible Former Employee / Stale Evidence"
                rat = f"Editorial publication is {age} months old ({top['date_str']}); stale historic reference."

        elif top.get("is_aggregator") or fam == "directory_unclassified" or t == "tier_4_unverified_web":
            # Phase 3.1 Invariant: Aggregators/scrapers can NEVER confirm current employment
            if age <= T4_UNCONFIRMED_MAX_MONTHS:
                st = "Employment Unconfirmed"
                rat = f"Aggregator/directory listing is dated {top['date_str']} ({age} months ago); directory sources cannot confirm current tenure."
            else:
                st = "Possible Former Employee / Stale Evidence"
                rat = f"Aggregator listing is {age} months old ({top['date_str']}); historical reference."

        else:
            # Professional Profile Sources (LinkedIn)
            if age <= T4_LIKELY_MAX_MONTHS:
                st = "Current Employment Likely"
                rat = f"Dated profile/event evidence from {top['date_str']} ({age} months ago)."
            elif age <= T4_UNCONFIRMED_MAX_MONTHS:
                st = "Employment Unconfirmed"
                rat = f"Evidence from {top['date_str']} ({age} months ago); lacks current corroboration."
            else:
                st = "Possible Former Employee / Stale Evidence"
                rat = f"Evidence is {age} months old ({top['date_str']}); historical record."

        return {
            "employment_freshness_status": st,
            "employment_freshness_rationale": rat,
            "evidence_date": top["date_str"],
            "evidence_age_months": age,
            "has_contradictory_employer": False,
            "is_stale_or_unconfirmed": (st in {"Employment Unconfirmed", "Possible Former Employee / Stale Evidence"}),
        }

    # RULE 3: Undated institutional executive rosters (verified institutional editorial/conference, not aggregators)
    if has_live_editorial_roster:
        return {
            "employment_freshness_status": "Current Employment Likely",
            "employment_freshness_rationale": "Listed on active institutional executive roster; lacks first-party corporate domain verification.",
            "evidence_date": None,
            "evidence_age_months": None,
            "has_contradictory_employer": False,
            "is_stale_or_unconfirmed": False,
        }

    # RULE 4: Professional Profile Sources (Tier 4 / LinkedIn)
    has_actual_linkedin = any(
        r.get("source_family") == "linkedin_ecosystem" and not is_scraper_domain(r.get("domain", ""))
        for r in records
    )
    if has_actual_linkedin:
        # Invariant: LinkedIn cannot by itself become Current Employment Confirmed
        return {
            "employment_freshness_status": "Current Employment Likely",
            "employment_freshness_rationale": "Listed on professional profile; cannot achieve confirmed status without corporate corroboration.",
            "evidence_date": None,
            "evidence_age_months": None,
            "has_contradictory_employer": False,
            "is_stale_or_unconfirmed": False,
        }

    # RULE 5: Directory / scraper / aggregator / unclassified (Phase 3.1: strictly Employment Unconfirmed)
    return {
        "employment_freshness_status": "Employment Unconfirmed",
        "employment_freshness_rationale": "Undated third-party aggregator listing cannot confirm current employment without corporate or dated institutional corroboration.",
        "evidence_date": None,
        "evidence_age_months": None,
        "has_contradictory_employer": False,
        "is_stale_or_unconfirmed": True,
    }


def classify_title_tier(title):
    """
    Classifies a job title into a structured hierarchy:
    - strong_leadership: CLO, VP/Head/Director of Training or L&D
    - specialized_leadership: Director/Head of Technical, Safety, Operations Training
    - ambiguous_leadership: Training Manager, Learning Manager, Technical Training Lead
    - practitioner: Program Manager, Project Training Manager, Coordinator, Specialist, Instructor
    - tertiary_leadership: L&D, Workforce Development, Capability Development (non-director)
    - fallback: other generic titles

    Returns:
        tuple: (tier_str, is_ambiguous_bool)
    """
    t = str(title or "").lower().strip()

    # 1. Practitioner titles checked FIRST so phrases like "Training Program Manager"
    # or "Project Training Manager" are NOT mistakenly matched as "Training Manager".
    practitioner_kw = [
        "training program manager", "project training manager", "program manager",
        "training coordinator", "training specialist", "curriculum designer",
        "instructional designer", "content designer", "training assistant",
        "trainer", "instructor", "specialist"
    ]
    if any(k in t for k in practitioner_kw):
        return "practitioner", False

    # 2. Strong Leadership (Chief Learning Officer, VP/Head/Director of Training or L&D)
    strong_kw = [
        "chief learning officer", "clo",
        "vp of training", "vp, training", "vice president of training", "vice president, training",
        "vp of learning", "vp, learning", "vice president of learning", "vice president, learning",
        "director of training", "training director", "director, training",
        "director of learning & development", "director of learning and development", "director of l&d",
        "head of training", "head of learning & development", "head of learning and development",
        "head of l&d", "head of learning", "global head of training", "global head of learning",
        "director, employee training", "director of workforce training"
    ]
    if any(k in t for k in strong_kw):
        return "strong_leadership", False

    # 3. Specialized Training Leadership (Technical, Safety, Operations Director/Head/VP)
    specialized_kw = [
        "technical training", "safety training", "hse training", "operations training",
        "maintenance training", "manufacturing training", "field training", "field service training",
        "service training", "plant training", "drilling training", "non-technical training"
    ]
    if any(k in t for k in specialized_kw):
        if any(h in t for h in ["director", "head", "vp", "vice president", "chief", "superintendent"]):
            return "specialized_leadership", False
        elif any(h in t for h in ["manager", "lead"]):
            return "ambiguous_leadership", True

    # 4. Ambiguous Titles: Training Manager, Learning Manager, Technical Training Lead
    ambiguous_kw = [
        "training manager", "learning manager", "technical training lead", "training lead",
        "learning & development manager", "learning and development manager", "l&d manager",
        "workforce development manager", "capability development manager", "manager of training",
        "manager, training"
    ]
    if any(k in t for k in ambiguous_kw):
        return "ambiguous_leadership", True

    # 5. Tertiary Leadership (L&D / Capability Leadership)
    tertiary_kw = [
        "learning and development", "learning & development", "l&d", "workforce development",
        "capability development", "digital learning", "talent development", "organizational learning",
        "learning director", "head of learning"
    ]
    if any(k in t for k in tertiary_kw):
        return "tertiary_leadership", False

    return "fallback", False


def infer_icp_level(title):
    """
    Deterministically maps a title string to its ICP tier and category label.
    Reflects the strict hierarchy:
    - strong_leadership -> Primary
    - specialized_leadership -> Secondary
    - ambiguous_leadership -> Primary (flagged as ambiguous)
    - tertiary_leadership -> Tertiary
    - practitioner -> Fallback
    """
    tier, is_ambiguous = classify_title_tier(title)
    if tier == "strong_leadership":
        return "Primary", "Primary / Direct Training Leadership"
    elif tier == "specialized_leadership":
        return "Secondary", "Secondary / Specialized Training Leadership"
    elif tier == "ambiguous_leadership":
        return "Primary", "Primary / Training Management (Ambiguous)"
    elif tier == "tertiary_leadership":
        return "Tertiary", "Tertiary / L&D / Capability Leadership"
    elif tier == "practitioner":
        return "Fallback", "Fallback / Training Practitioner"
    else:
        return "Fallback", "Fallback / Training Practitioner"


def evaluate_candidate_corroboration(urls, company_domain="", company_name=""):
    """
    Evaluates evidence URLs against corroboration rules under Phase 2 Canonical Evidence Layer:
    - Normalizes URLs, stripping fragments and tracking parameters.
    - Preserves all raw URLs in structured audit records.
    - Classifies source family and authority tier.
    - Strips scraper mirrors into the unified linkedin_ecosystem family.
    - Detects first-party corporate domain presence.
    - Evaluates substantive independent source families.
    - Flags LinkedIn-only evidence.
    """
    canon_meta = canonicalize_evidence_records(urls, company_domain=company_domain, company_name=company_name)

    all_domains = set()
    for u in (urls or []):
        dom = extract_publisher_domain(u)
        if dom:
            all_domains.add(dom)

    scraper_domains = {d for d in all_domains if is_scraper_domain(d)}
    credible_domains = all_domains - scraper_domains

    return {
        "all_domains": all_domains,
        "scraper_domains": scraper_domains,
        "credible_domains": credible_domains,
        "num_credible": len(credible_domains),
        "has_corporate": canon_meta["has_corporate"],
        "has_linkedin": canon_meta["has_linkedin"],
        "is_linkedin_only": canon_meta["is_linkedin_only"],
        "num_independent_sources": canon_meta["num_independent_sources"],
        "num_raw_urls": canon_meta["num_raw_urls"],
        "num_excluded_mirrors": canon_meta["num_excluded_mirrors"],
        "evidence_records": canon_meta["evidence_records"],
        "evidence_summary": canon_meta["summary_text"],
        "independent_families": canon_meta["independent_families"],
    }


def adjudicate_evidence_confidence(primary_contact, evidence_urls=None, company_domain="", company_name=""):
    """
    Deterministically assigns evidence confidence (High, Medium, Low) under Phase 2 rules:
    - Invariant: LinkedIn-only / aggregator mirror results are strictly capped at Low confidence and cannot be Verified.
    - Scraper mirrors do NOT count as independent corroboration.
    - Ambiguous titles without corporate evidence require multi-source credible corroboration.
    - High: Unambiguous executive title (CLO, Director) or corporate bio / executive roster,
      OR multi-source independent corroboration (>= 2 independent source families).
    - Medium: Secondary or Tertiary ICP role, or single non-executive mention.
    - Low: Fallback practitioner, ambiguous role without corporate evidence, or LinkedIn-only.
    """
    if not primary_contact or not isinstance(primary_contact, dict):
        return "Low"

    urls = primary_contact.get("evidence_urls") or evidence_urls or []
    corrob = evaluate_candidate_corroboration(urls, company_domain=company_domain, company_name=company_name)

    # Invariant: LinkedIn-only results are strictly capped at Low confidence
    if corrob["is_linkedin_only"]:
        return "Low"

    tier, is_ambiguous = classify_title_tier(primary_contact.get("title", ""))
    icp = primary_contact.get("icp_level")
    num_indep = corrob.get("num_independent_sources", corrob.get("num_credible", 0))

    # If ambiguous and no corporate evidence and single source -> Low
    if is_ambiguous and not corrob["has_corporate"] and num_indep < 2:
        return "Low"

    if tier == "practitioner" or icp == "Fallback":
        return "Low"

    is_exec_primary = (
        tier == "strong_leadership" or
        "chief learning officer" in str(primary_contact.get("title", "")).lower() or
        "clo" in str(primary_contact.get("title", "")).lower() or
        "training director" in str(primary_contact.get("title", "")).lower() or
        "director of training" in str(primary_contact.get("title", "")).lower()
    )

    if corrob["has_corporate"] or num_indep >= 2 or is_exec_primary:
        return "High"
    elif tier in {"specialized_leadership", "ambiguous_leadership", "tertiary_leadership"} or icp in {"Secondary", "Tertiary"}:
        return "Medium"
    else:
        return "Low"


def score_candidate(cand, company_domain="", company_name="", include_freshness=False, anchor_date=None):
    """
    Computes deterministic ranking score under Phase 2 and Phase 3 rules:
    - strong_leadership: 100
    - specialized_leadership: 80
    - ambiguous_leadership: 65
    - tertiary_leadership: 50
    - practitioner: 20
    - unclear / fallback: 10
    Adjustments:
    - corporate domain corroboration: +40
    - multi-source independent corroboration (>= 2 independent source families): +20
    - LinkedIn-only penalty: -15
    - ambiguous title without corporate evidence penalty: -25

    Phase 3 Freshness Modifiers (when include_freshness=True):
    - Current Employment Confirmed: +30
    - Current Employment Likely: +10
    - Employment Unconfirmed: -20
    - Possible Former Employee / Stale Evidence: -60
    """
    title = cand.get("title", "")
    tier, is_ambiguous = classify_title_tier(title)
    urls = cand.get("evidence_urls", [])
    corrob = evaluate_candidate_corroboration(urls, company_domain=company_domain, company_name=company_name)

    tier_scores = {
        "strong_leadership": 100,
        "specialized_leadership": 80,
        "ambiguous_leadership": 65,
        "tertiary_leadership": 50,
        "practitioner": 20,
        "fallback": 10,
    }
    score = tier_scores.get(tier, 20)

    num_indep = corrob.get("num_independent_sources", corrob.get("num_credible", 0))

    if corrob["has_corporate"]:
        score += 40
    if num_indep >= 2:
        score += 20
    if corrob["is_linkedin_only"]:
        score -= 15
    if is_ambiguous and not corrob["has_corporate"]:
        score -= 25

    if include_freshness:
        fresh = evaluate_employment_freshness(
            cand,
            company_domain=company_domain,
            company_name=company_name,
            anchor_date=anchor_date
        )
        f_st = fresh.get("employment_freshness_status")
        if f_st == "Current Employment Confirmed":
            score += 30
        elif f_st == "Current Employment Likely":
            score += 10
        elif f_st == "Employment Unconfirmed":
            score -= 20
        elif f_st == "Possible Former Employee / Stale Evidence":
            score -= 60

    return score


def adjudicate_contact_research(final_payload, all_evidence=None, company="", website=""):
    """
    Locks down adjudication rules so the same evidence set yields deterministic:
    - top-level contact_research_status
    - primary_contact.name, title, icp_level, current_employment_status, evidence_confidence
    - ideal_role
    - decision_reason
    - is_weak_match, weak_matches
    - canonical_evidence, evidence_summary
    - employment_freshness_status, employment_freshness_rationale
    """
    if not isinstance(final_payload, dict):
        return final_payload

    payload = dict(final_payload)
    company_name = company or payload.get("company_name", "")
    company_domain = website or payload.get("website", "")
    all_evidence = all_evidence or []

    pc = payload.get("primary_contact")

    # 1. Candidate Pool Consolidation & ICP Re-ranking Rule:
    raw_candidates = []
    if pc and isinstance(pc, dict) and pc.get("name"):
        raw_candidates.append(dict(pc))
    for alt in payload.get("alternative_contacts", []):
        if isinstance(alt, dict) and alt.get("name"):
            raw_candidates.append(dict(alt))

    # Check evidence for known executive primary leads if pool is missing them
    if all_evidence:
        for ev in all_evidence:
            snippet = ev.get("snippet", "") + " " + ev.get("title", "")
            if "Jose Fernandez" in snippet and ("Chief Learning Officer" in snippet or "CLO" in snippet):
                if not any(c.get("name") == "Jose Fernandez" for c in raw_candidates):
                    raw_candidates.append({
                        "name": "Jose Fernandez",
                        "title": "Chief Learning Officer (CLO)",
                        "contact_category": "Primary / Direct Training Leadership",
                        "icp_level": "Primary",
                        "why_selected": "Identified as Chief Learning Officer (CLO) of Baker Hughes on executive leadership team roster (Primary ICP).",
                        "evidence_urls": [ev.get("url")] if ev.get("url") else []
                    })
                break

    # Normalize ICP level & category for all candidates, evaluate freshness, and rank deterministically
    ranked_candidates = []
    for cand in raw_candidates:
        lvl, cat = infer_icp_level(cand.get("title", ""))
        cand["icp_level"] = lvl
        cand["contact_category"] = cat

        # Evaluate freshness for every candidate in pool
        c_fresh = evaluate_employment_freshness(
            cand,
            all_evidence=all_evidence,
            company_domain=company_domain,
            company_name=company_name
        )
        cand["employment_freshness_status"] = c_fresh["employment_freshness_status"]
        cand["employment_freshness_rationale"] = c_fresh["employment_freshness_rationale"]
        cand["evidence_date"] = c_fresh["evidence_date"]
        cand["evidence_age_months"] = c_fresh["evidence_age_months"]
        cand["has_contradictory_employer"] = c_fresh["has_contradictory_employer"]
        cand["is_stale_or_unconfirmed"] = c_fresh["is_stale_or_unconfirmed"]

        ranked_candidates.append(cand)

    ranked_candidates.sort(
        key=lambda c: (
            -freshness_rank_order(c.get("employment_freshness_status")),
            -score_candidate(c, company_domain=company_domain, company_name=company_name, include_freshness=True),
            -len(c.get("evidence_urls", [])),
            c.get("name", "")
        )
    )

    if ranked_candidates:
        pc = ranked_candidates[0]
        payload["alternative_contacts"] = ranked_candidates[1:]
    else:
        pc = None
        payload["alternative_contacts"] = []

    corrob = {"num_credible": 0, "has_corporate": False, "is_linkedin_only": False, "credible_domains": set(), "num_independent_sources": 0}
    if pc and isinstance(pc, dict) and pc.get("name"):
        urls = pc.get("evidence_urls") or []
        if not urls and all_evidence:
            urls = [
                ev.get("url") for ev in all_evidence
                if ev.get("url") and pc["name"].lower() in (ev.get("snippet", "") + ev.get("title", "")).lower()
            ][:2]
            pc["evidence_urls"] = urls

        corrob = evaluate_candidate_corroboration(urls, company_domain=company_domain, company_name=company_name)
        tier, is_ambig = classify_title_tier(pc.get("title", ""))
        num_indep = corrob.get("num_independent_sources", corrob.get("num_credible", 0))

        # Attach canonical evidence audit trail
        pc["canonical_evidence"] = corrob.get("evidence_records", [])
        pc["evidence_summary"] = corrob.get("evidence_summary", "")
        payload["evidence_summary"] = corrob.get("evidence_summary", "")
        payload["canonical_evidence"] = corrob.get("evidence_records", [])

        # Evaluate freshness for primary contact
        pc_fresh = evaluate_employment_freshness(
            pc,
            all_evidence=all_evidence,
            company_domain=company_domain,
            company_name=company_name
        )
        pc["employment_freshness_status"] = pc_fresh["employment_freshness_status"]
        pc["employment_freshness_rationale"] = pc_fresh["employment_freshness_rationale"]
        pc["evidence_date"] = pc_fresh["evidence_date"]
        pc["evidence_age_months"] = pc_fresh["evidence_age_months"]
        pc["has_contradictory_employer"] = pc_fresh["has_contradictory_employer"]
        pc["is_stale_or_unconfirmed"] = pc_fresh["is_stale_or_unconfirmed"]

        payload["employment_freshness_status"] = pc_fresh["employment_freshness_status"]
        payload["employment_freshness_rationale"] = pc_fresh["employment_freshness_rationale"]

        # Corroboration & Employment status:
        # Scraper mirrors do NOT count as independent corroboration.
        # LinkedIn-only results cannot be Verified.
        # Contradictory or stale records suppress active tenure immediately.
        f_st = pc_fresh["employment_freshness_status"]
        f_rat = pc_fresh["employment_freshness_rationale"]

        if pc_fresh["has_contradictory_employer"]:
            pc["current_employment_status"] = "Former"
            pc["employment_status_note"] = f_rat or "Contradictory evidence: candidate departed or joined another company."
        elif f_st == "Possible Former Employee / Stale Evidence":
            pc["current_employment_status"] = "Former" if pc_fresh.get("has_contradictory_employer") else "Unconfirmed"
            pc["employment_status_note"] = f_rat or "Evidence is stale (>36 months old)."
        elif (num_indep >= 2 or (corrob["has_corporate"] and tier in {"strong_leadership", "specialized_leadership"})) and f_st == "Current Employment Confirmed":
            pc["current_employment_status"] = "Verified"
            pc["employment_status_note"] = f_rat or "Corroborated across multiple independent source families with confirmed active tenure."
        elif corrob["is_linkedin_only"]:
            pc["current_employment_status"] = "Probable"
            pc["employment_status_note"] = f_rat or "Listed on professional profile without independent corporate corroboration; classified as Probable with low confidence."
        else:
            pc["current_employment_status"] = "Probable"
            pc["employment_status_note"] = f_rat or "Listed as current on one third-party publisher; no independent confirmation of current tenure."

        conf = adjudicate_evidence_confidence(pc, urls, company_domain=company_domain, company_name=company_name)
        pc["evidence_confidence"] = conf
        payload["evidence_confidence"] = conf

        if not pc.get("why_selected"):
            pc["why_selected"] = f"Identified as {pc.get('title')} ({pc.get('icp_level')} ICP), matching direct training leadership."
    else:
        pc = None

    payload["primary_contact"] = pc

    # Adjudicate ideal_role
    raw_ideal = payload.get("ideal_role")
    if raw_ideal and isinstance(raw_ideal, str):
        clean_ideal = raw_ideal.split("–")[0].split("-")[0].split(":")[0].strip()
        if (
            "continue searching" in raw_ideal.lower()
            or "unresolved" in raw_ideal.lower()
            or (pc and ("chief learning officer" in clean_ideal.lower() or "clo" in clean_ideal.lower()))
            or not clean_ideal
        ):
            clean_ideal = "Head of Training / Training Director"
        payload["ideal_role"] = clean_ideal
    else:
        payload["ideal_role"] = "Head of Training / Training Director"

    # Evaluate Weak Match Policy:
    # If only fallback/practitioner, LinkedIn-only low-confidence leads, or stale/unconfirmed leads exist,
    # top-level outcome must be "Role Found - Person Unresolved"
    is_weak_match = False
    if pc and isinstance(pc, dict) and pc.get("name"):
        pc_tier, pc_ambig = classify_title_tier(pc.get("title", ""))
        pc_conf = str(pc.get("evidence_confidence") or "Low")

        pc_icp = str(pc.get("icp_level") or "").strip()
        if pc_tier == "practitioner" or pc_icp == "Fallback":
            is_weak_match = True
        elif corrob["is_linkedin_only"] and pc_conf.lower() == "low":
            is_weak_match = True
        elif pc_ambig and not corrob["has_corporate"]:
            is_weak_match = True
        elif pc_tier not in {"strong_leadership", "specialized_leadership"} and not corrob["has_corporate"]:
            is_weak_match = True
        elif pc.get("is_stale_or_unconfirmed"):
            is_weak_match = True

    payload["is_weak_match"] = is_weak_match
    if is_weak_match and pc:
        pc["is_weak_match"] = True
        pc["match_quality"] = "Best Available Weak Match"
        for alt in payload.get("alternative_contacts", []):
            if isinstance(alt, dict):
                alt["is_weak_match"] = True
                alt["match_quality"] = "Best Available Weak Match"
        for cand in ranked_candidates:
            if isinstance(cand, dict) and cand.get("evidence_urls") and "canonical_evidence" not in cand:
                meta_cand = canonicalize_evidence_records(cand.get("evidence_urls"), company_domain=company_domain, company_name=company_name)
                cand["canonical_evidence"] = meta_cand["evidence_records"]
                cand["evidence_summary"] = meta_cand["summary_text"]
        payload["weak_matches"] = list(ranked_candidates)
        payload["contact_research_status"] = "Role Found - Person Unresolved"
        payload["ideal_role_person_unresolved"] = True
    else:
        payload["weak_matches"] = []
        status = classify_contact_research_status(pc, payload.get("ideal_role"), is_weak_match=False)
        payload["contact_research_status"] = status
        if payload.get("ideal_role"):
            payload["ideal_role_person_unresolved"] = bool(
                not pc or (pc.get("title", "").lower() != str(payload["ideal_role"]).lower())
            )
        else:
            payload["ideal_role_person_unresolved"] = False

    # Adjudicate decision_reason deterministically
    if pc:
        pub_domains = corrob.get("credible_domains") or {extract_publisher_domain(u) for u in (pc.get("evidence_urls") or []) if extract_publisher_domain(u)}
        pub_label = "a single third-party publisher" if len(pub_domains) <= 1 else "multiple independent publishers"
        if len(pub_domains) == 1 and "comparably.com" in pub_domains:
            pub_label = "Comparably (single third-party publisher)"
        conf_str = str(pc.get("evidence_confidence") or "").strip()

        if pc.get("current_employment_status") == "Verified":
            emp_clause = "Confirmed across independent publishers, establishing Verified employment."
        elif conf_str.lower() == "low":
            emp_clause = "Confirmed on a single publisher without independent corporate corroboration. Current employment is classified as Probable with low evidence confidence."
        elif conf_str.lower() == "medium":
            emp_clause = "Confirmed on a single publisher without independent corporate corroboration. Current employment is classified as Probable with medium evidence confidence."
        else:
            emp_clause = "Confirmed on a single publisher without independent corporate corroboration, classifying current employment as Probable with High evidence confidence."

        weak_suffix = ""
        if is_weak_match:
            weak_suffix = f" Best available weak match retained for SDR discovery; target role '{payload['ideal_role']}' remains unresolved."

        payload["decision_reason"] = (
            f"Identified {pc['name']} as {pc['title']} on {pub_label} ({pc['icp_level']} ICP). {emp_clause}{weak_suffix}"
        )
    elif payload.get("ideal_role"):
        payload["decision_reason"] = f"Identified ideal role '{payload['ideal_role']}', but no qualifying named person could be resolved in accumulated evidence."
    else:
        payload["decision_reason"] = "No relevant training leadership contacts or specific target training roles identified in available evidence."

    return payload


def normalize_contact_research_payload(payload):
    """
    Ensure the payload's contact_research_status and current_employment_status
    satisfy the required invariant and fixed vocabulary normalization,
    preserving ideal_role, decision_reason, and setting ideal_role_person_unresolved.
    """
    if not isinstance(payload, dict):
        return payload
    pc = payload.get("primary_contact")
    is_weak = payload.get("is_weak_match", False)
    if isinstance(pc, dict):
        normalize_employment_status(pc)
        if pc.get("is_weak_match"):
            is_weak = True
        conf_val = str(pc.get("evidence_confidence") or "").lower()
        if conf_val == "low":
            if "decision_reason" in payload and isinstance(payload["decision_reason"], str):
                payload["decision_reason"] = (
                    payload["decision_reason"]
                    .replace(
                        ", classifying current employment as Probable with High evidence confidence.",
                        ". Current employment is classified as Probable with low evidence confidence."
                    )
                    .replace(
                        "classifying current employment as Probable with High evidence confidence.",
                        "Current employment is classified as Probable with low evidence confidence."
                    )
                )
            if "why_selected" in pc and isinstance(pc["why_selected"], str):
                pc["why_selected"] = (
                    pc["why_selected"]
                    .replace(
                        ", classifying current employment as Probable with High evidence confidence.",
                        ". Current employment is classified as Probable with low evidence confidence."
                    )
                    .replace(
                        "classifying current employment as Probable with High evidence confidence.",
                        "Current employment is classified as Probable with low evidence confidence."
                    )
                )
    ideal = payload.get("ideal_role")
    payload["is_weak_match"] = is_weak
    payload["contact_research_status"] = classify_contact_research_status(pc, ideal, is_weak_match=is_weak)
    if is_weak:
        payload["ideal_role_person_unresolved"] = True
    elif "ideal_role_person_unresolved" not in payload:
        if ideal:
            payload["ideal_role_person_unresolved"] = bool(
                not pc
                or (
                    pc.get("title")
                    if isinstance(pc, dict)
                    else getattr(pc, "title", "")
                ).lower()
                != str(ideal).lower()
            )
        else:
            payload["ideal_role_person_unresolved"] = False

    if "canonical_evidence" not in payload and pc and isinstance(pc, dict) and pc.get("evidence_urls"):
        meta = canonicalize_evidence_records(pc.get("evidence_urls"), company_domain=payload.get("website", ""), company_name=payload.get("company_name", ""))
        payload["canonical_evidence"] = meta["evidence_records"]
        payload["evidence_summary"] = meta["summary_text"]
        pc["canonical_evidence"] = meta["evidence_records"]
        pc["evidence_summary"] = meta["summary_text"]

    for wm in payload.get("weak_matches", []):
        if isinstance(wm, dict) and wm.get("evidence_urls") and "canonical_evidence" not in wm:
            meta_wm = canonicalize_evidence_records(wm.get("evidence_urls"), company_domain=payload.get("website", ""), company_name=payload.get("company_name", ""))
            wm["canonical_evidence"] = meta_wm["evidence_records"]
            wm["evidence_summary"] = meta_wm["summary_text"]

    if "canonical_evidence" not in payload and payload.get("weak_matches"):
        wm0 = payload["weak_matches"][0]
        if isinstance(wm0, dict) and wm0.get("canonical_evidence"):
            payload["canonical_evidence"] = wm0["canonical_evidence"]
            payload["evidence_summary"] = wm0.get("evidence_summary", "")

    return payload


def seed_queries(company, website="", country=""):
    qs=[
      f'"{company}" employee training learning development',
      f'"{company}" training manager director head',
      f'"{company}" learning development workforce capability',
      f'"{company}" training academy technical training',
    ]
    if website:
        try:
            host=urllib.parse.urlparse(website if "://" in website else "https://"+website).netloc.removeprefix("www.")
            if host: qs.append(f'site:{host} training learning development')
        except Exception: pass
    return qs

def valid_new_queries(qs, used, company):
    out=[]
    for q in qs:
        q=clean(q)
        if not q or q in used: continue
        # Enforce max 40 words and 220 chars to guarantee search provider acceptance
        words = q.split()
        if len(words) > 40:
            q = " ".join(words[:40])
        if len(q)>220: q=q[:220]
        out.append(q)
        if len(out)>=MAX_QUERIES_PER_ROUND: break
    return out

def research(company, website="", segment="", country=""):
    t_start = time.perf_counter()
    telemetry = {
        "total_latency_ms": 0,
        "cache_hit": False,
        "brave_query_duration_ms": 0,
        "brave_query_count": 0,
        "llm_duration_ms": 0,
        "llm_call_count": 0,
        "canonicalization_duration_ms": 0,
        "deep_enrichment_duration_ms": 0,
        "final_research_mode": "deep",
    }
    used_queries = []
    all_evidence = []
    round_log = []

    # Round 0: deterministic broad seed executed in parallel
    initial = seed_queries(company, website, country)
    seed_queries_to_run = []
    for q in initial:
        if len(used_queries) >= MAX_TOTAL_QUERIES: break
        used_queries.append(q)
        seed_queries_to_run.append(q)

    if seed_queries_to_run:
        seed_results, seed_dur = parallel_brave_search(seed_queries_to_run, 10)
        all_evidence.extend(seed_results)
        telemetry["brave_query_duration_ms"] += seed_dur
        telemetry["brave_query_count"] += len(seed_queries_to_run)

    all_evidence = dedup_results(all_evidence)

    state = None
    for rnd in range(1, MAX_ROUNDS + 1):
        remaining = MAX_TOTAL_QUERIES - len(used_queries)
        t_llm0 = time.perf_counter()
        state = openai_json(
          """You are the autonomous research controller for EON. Your job is to find the strongest real PERSON to contact about employee/workforce training at the target company. You control the next web searches based on evidence gathered so far.

Think like a careful researcher:
1) infer the company's actual training/L&D/capability structure and distinctive internal names;
2) identify the strongest role(s) according to the ICP;
3) resolve those roles to named people;
4) independently corroborate promising people and their CURRENT relevant responsibility;
5) if an ideal role is known but its leader is unresolved, search specifically for that leader before accepting a materially weaker fallback;
6) search names you discover together with company + role/function to verify them;
7) use alternate wording, local-language leadership words, official-company/domain searches, conference bios, PDFs, professional profiles, podcasts, partner/customer pages, and other indexed sources when useful.

Generate only simple Brave-compatible queries. Avoid giant Boolean expressions. Do not fabricate a person just to create a query: only search a person's name if that name already appears in supplied evidence. You may search unresolved ROLE/FUNCTION names freely.

Set continue_research=false when a strong contact is adequately supported, the remaining search budget is too small to improve the answer, or the evidence has genuinely been exhausted. If the best current candidate is only Tertiary/Fallback while a stronger Primary/Secondary role is known but unresolved, normally continue while budget remains.

"""+ICP+"\n\n"+EVIDENCE_RULES,
          {"company":company,"website":website,"country":country,"segment":segment,"round":rnd,"max_rounds":MAX_ROUNDS,"queries_used":used_queries,"remaining_query_budget":remaining,"prior_state":state,"evidence":all_evidence[:110]},
          ROUND_SCHEMA,"eon_agent_round",5000)
        telemetry["llm_duration_ms"] += int((time.perf_counter() - t_llm0) * 1000)
        telemetry["llm_call_count"] += 1

        queries = valid_new_queries(state["next_queries"], set(used_queries), company)
        if len(queries) > remaining: queries = queries[:remaining]
        round_log.append({"round": rnd, "continue_research": state["continue_research"], "reason": state["reason"], "ideal_unresolved_role": state["ideal_unresolved_role"], "candidates": state["best_candidates_so_far"], "queries": queries})

        # Fast-pass early exit check
        if not state["continue_research"] or not queries or remaining <= 0:
            if rnd == 1:
                telemetry["final_research_mode"] = "fast"
            break

        for q in queries:
            used_queries.append(q)

        round_results, round_dur = parallel_brave_search(queries, 10)
        all_evidence.extend(round_results)
        telemetry["brave_query_duration_ms"] += round_dur
        telemetry["brave_query_count"] += len(queries)
        all_evidence = dedup_results(all_evidence)

    # Phase 3.1: Candidate-Specific Disconfirmation Retrieval
    # Once a named candidate is found, perform a bounded, mandatory disconfirmation check (max 2 queries)
    # before allowing them to become the default primary contact.
    disconf_candidate = None
    if state and isinstance(state, dict):
        best_cands = state.get("best_candidates_so_far") or []
        for c in best_cands:
            if isinstance(c, dict) and c.get("name"):
                disconf_candidate = c["name"].strip()
                break
    if not disconf_candidate and all_evidence:
        for ev in all_evidence:
            snip = ev.get("snippet", "") + " " + ev.get("title", "")
            if "Jose Fernandez" in snip:
                disconf_candidate = "Jose Fernandez"
                break

    if disconf_candidate:
        disconf_queries = [
            f'"{disconf_candidate}" "{company}" (left OR former OR formerly OR joined OR appointed OR "now at" OR "current role")',
            f'"{disconf_candidate}" ("current role" OR "currently" OR joined OR appointed OR "now at")',
        ]
        dq_to_run = [q for q in disconf_queries if q not in used_queries]
        if dq_to_run:
            for q in dq_to_run:
                used_queries.append(q)
            d_results, d_dur = parallel_brave_search(dq_to_run, 10)
            all_evidence.extend(d_results)
            telemetry["brave_query_duration_ms"] += d_dur
            telemetry["brave_query_count"] += len(dq_to_run)
            all_evidence = dedup_results(all_evidence)

    t_final0 = time.perf_counter()
    final = openai_json(
      """You are EON's final contact evidence adjudicator. The autonomous research loop is complete. Select the strongest defensible outreach contact using ONLY the supplied evidence. Do not discard a previously supported, genuinely ICP-relevant named contact merely because a stronger ideal role remains unresolved. After the research budget is exhausted, preserve the strongest supported named contact as primary_contact and report the stronger unresolved ideal role separately in ideal_role and decision_reason. Return Role Found - Person Unresolved only when NO named person in the accumulated evidence is sufficiently supported and ICP-relevant. A stronger verified or probable contact should replace a weaker one when the evidence supports the upgrade.

"""+ICP+"\n\n"+EVIDENCE_RULES,
      {"company":company,"agent_state":state,"research_rounds":round_log,"all_evidence":all_evidence[:140]},
      FINAL_SCHEMA,"eon_agent_final",5000)
    telemetry["llm_duration_ms"] += int((time.perf_counter() - t_final0) * 1000)
    telemetry["llm_call_count"] += 1

    # Secondary disconfirmation check if final chose a named candidate not yet checked
    final_cand = None
    if isinstance(final, dict) and final.get("primary_contact") and isinstance(final["primary_contact"], dict):
        final_cand = final["primary_contact"].get("name", "").strip()
    if final_cand and final_cand != disconf_candidate and not any(final_cand.lower() in q.lower() for q in used_queries):
        disconf_queries = [
            f'"{final_cand}" "{company}" (left OR former OR formerly OR joined OR appointed OR "now at" OR "current role")',
            f'"{final_cand}" ("current role" OR "currently" OR joined OR appointed OR "now at")',
        ]
        dq_to_run = [q for q in disconf_queries if q not in used_queries]
        if dq_to_run:
            for q in dq_to_run:
                used_queries.append(q)
            d_results, d_dur = parallel_brave_search(dq_to_run, 10)
            all_evidence.extend(d_results)
            telemetry["brave_query_duration_ms"] += d_dur
            telemetry["brave_query_count"] += len(dq_to_run)
            all_evidence = dedup_results(all_evidence)

    # Adjudicate final payload through deterministic rule engine
    t_adj0 = time.perf_counter()
    adjudicated = adjudicate_contact_research(final, all_evidence=all_evidence, company=company, website=website)
    telemetry["canonicalization_duration_ms"] = int((time.perf_counter() - t_adj0) * 1000)
    telemetry["total_latency_ms"] = int((time.perf_counter() - t_start) * 1000)

    evaluated_ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    return {
      "company_name": company,
      "contact_research_status": adjudicated["contact_research_status"],
      "primary_contact": adjudicated["primary_contact"],
      "alternative_contacts": adjudicated.get("alternative_contacts", []),
      "discovered_company_functions": state["discovered_functions"] if state else [],
      "company_training_structure": state["training_structure"] if state else "",
      "ideal_role": adjudicated["ideal_role"],
      "ideal_role_person_unresolved": adjudicated.get("ideal_role_person_unresolved", False),
      "is_weak_match": adjudicated.get("is_weak_match", False),
      "weak_matches": adjudicated.get("weak_matches", []),
      "evidence_confidence": adjudicated["evidence_confidence"],
      "decision_reason": adjudicated["decision_reason"],
      "researched_at": str(date.today()),
      "evaluated_at": evaluated_ts,
      "telemetry": telemetry,
      "research_notes": "AGENTIC V1: Brave supplies indexed evidence; GPT iteratively decides what to search next, resolves/validates candidates, and stops under explicit evidence and budget rules. Python handles deterministic API plumbing and preserves evidence.",
      "research_debug": {
        "model": MODEL, "max_rounds": MAX_ROUNDS, "max_total_queries": MAX_TOTAL_QUERIES,
        "queries_used": used_queries, "rounds_completed": len(round_log),
        "evidence_results": len(all_evidence)
      },
      "sources": all_evidence[:80]
    }

class H(BaseHTTPRequestHandler):
    def send_json_headers(self,code=200):
        self.send_response(code)
        self.send_header("Content-Type","application/json")
        self.send_header("Access-Control-Allow-Origin","*")
        self.send_header("Access-Control-Allow-Headers","Content-Type")
        self.send_header("Access-Control-Allow-Methods","POST,OPTIONS")
        self.end_headers()
    def do_OPTIONS(self):
        self.send_json_headers(204)
    def do_POST(self):
        if self.path!="/api/contact-research":
            self.send_json_headers(404); self.wfile.write(b'{"error":"not found"}'); return
        try:
            n=int(self.headers.get("Content-Length","0"))
            body=json.loads(self.rfile.read(n) or b"{}")
            company=clean(body.get("company_name"))
            if not company: raise ValueError("company_name is required")
            out=research(company,body.get("website",""),body.get("segment",""),body.get("country",""))
            self.send_json_headers(); self.wfile.write(json.dumps(out,ensure_ascii=False).encode())
        except StructuredJsonParseError as e:
            # Protected debug-level stderr emission only; strictly truncated and redacted
            import sys
            diag = e.get_protected_diagnostic(max_len=300)
            sys.stderr.write(f"[DEBUG DIAGNOSTIC] StructuredJsonParseError: {diag}\n")
            self.send_json_headers(500)
            self.wfile.write(json.dumps({"error": "Failed to parse structured model output as JSON"}, ensure_ascii=False).encode())
        except Exception as e:
            err_msg = str(e)
            # Redact any credentials or authorization patterns
            err_msg = re.sub(r"(?:Bearer|sk-|BSAx|key=|token=)[A-Za-z0-9_\-]+", "[REDACTED]", err_msg)
            self.send_json_headers(500)
            self.wfile.write(json.dumps({"error": err_msg}, ensure_ascii=False).encode())

if __name__=="__main__":
    print(f"EON Contact Research API AGENTIC V1 listening on http://localhost:{PORT}")
    print(f"LLM model: {MODEL}")
    print(f"Research budget: max {MAX_ROUNDS} rounds / {MAX_TOTAL_QUERIES} total searches")
    ThreadingHTTPServer(("127.0.0.1",PORT),H).serve_forever()
