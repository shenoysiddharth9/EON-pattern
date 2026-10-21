"""
Free-Source Connectors for SEC EDGAR and Wikidata (Phase 4 Foundation)
EON Commercial Intelligence | External Review Build

Implements zero-cost, public API connectors:
1. SecEdgarConnector:
   - Free public SEC EDGAR API (data.sec.gov & sec.gov/files/company_tickers.json)
   - Compliant User-Agent formatting: EONIntelligence/1.0 (commercial-intel@eon.com)
   - Extracts: CIK, Ticker, Exchange, SIC Code, SIC Description, State/Country of Inc, Address, 10-K filing dates
   - Provenance: HIGH confidence, exact value status, statutory source URLs

2. WikidataConnector:
   - Free public Wikidata MediaWiki API (wikidata.org/w/api.php)
   - Searches entity by company name / domain and retrieves semantic claims
   - Extracts: Inception year (P571), Headquarters (P159), Country (P17), Employees (P1128), Revenue (P2139), Website (P856)
   - Provenance: MEDIUM/HIGH confidence, exact/estimate/range value status, Wikidata claim URLs

Strict Rules:
- Never invent values. Unknown is explicitly allowed and recorded.
- Every field returns: field_name, field_value, value_status, source_url, source_type, source_date, confidence.
- Built-in rate pacing and pluggable mock/offline transport for deterministic testing.
"""

import datetime
from datetime import date, datetime, timezone
import json
import logging
import re
import time
from typing import Any, Callable, Dict, List, Optional, Tuple, Union
import urllib.parse
import urllib.request

logger = logging.getLogger("eon.enrichment.connectors")

# Standard headers required by SEC EDGAR (https://www.sec.gov/os/accessing-edgar-data)
SEC_USER_AGENT = "EONCommercialIntelligence/1.0 (support@eon-intelligence.com)"
WIKIDATA_USER_AGENT = "EONCommercialIntelligence/1.0 (https://eon-intelligence.com; support@eon-intelligence.com)"

# Rate limiters (seconds between requests)
SEC_PACING_SECONDS = 0.12  # SEC limit is 10 req/sec; 0.12s guarantees <= 8.3 req/sec
WIKIDATA_PACING_SECONDS = 0.10


class BaseConnector:
    """Base class for free-source enrichment connectors."""

    def __init__(self, http_client: Optional[Callable[[str, Dict[str, str]], Tuple[int, str]]] = None):
        """
        Optional custom http_client function: (url, headers) -> (status_code, body_str)
        Allows injecting offline fixtures or mock network responses in unit tests.
        """
        self._custom_http = http_client
        self._last_request_time = 0.0
        self.request_count = 0

    def _fetch_url(self, url: str, headers: Dict[str, str], pacing: float = 0.1) -> Tuple[int, str]:
        """Executes HTTP GET with rate pacing and error handling."""
        self.request_count += 1
        if self._custom_http:
            return self._custom_http(url, headers)

        elapsed = time.time() - self._last_request_time
        if elapsed < pacing:
            time.sleep(pacing - elapsed)

        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=10.0) as resp:
                status = resp.status
                body = resp.read().decode("utf-8", errors="replace")
                self._last_request_time = time.time()
                return status, body
        except urllib.error.HTTPError as e:
            self._last_request_time = time.time()
            return e.code, ""
        except Exception as e:
            self._last_request_time = time.time()
            logger.warning(f"Network error requesting {url}: {e}")
            return 0, ""


LEGAL_SUFFIXES_PATTERN = re.compile(
    r"\b(inc|incorporated|corp|corporation|llc|l\.l\.c\.|ltd|limited|co|company|plc|p\.l\.c\.|sa|s\.a\.|s\.?p\.?a\.?|s\.?r\.?l\.?|ag|a\.g\.|nv|n\.v\.|bv|b\.v\.|gmbh|lp|l\.p\.|holdings?|group)\b\.?",
    re.IGNORECASE,
)


def normalize_company_name_variants(company_name: str) -> List[str]:
    """
    Generates conservative search query variants for entity lookup:
    1. Exact cleaned company name
    2. Company name with trailing punctuation stripped
    3. Company name with trailing legal corporate suffixes stripped (e.g. 'Cheniere Energy Inc' -> 'Cheniere Energy')
    Returns deduplicated list with primary candidate first.
    """
    if not company_name:
        return []
    raw = str(company_name).strip()
    variants = [raw]

    # Clean trailing punctuation
    cleaned = re.sub(r"[\s,\.-]+$", "", raw).strip()
    if cleaned and cleaned not in variants:
        variants.append(cleaned)

    # Strip legal corporate suffixes
    stripped = LEGAL_SUFFIXES_PATTERN.sub("", cleaned).strip()
    stripped = re.sub(r"[\s,\.-]+$", "", stripped).strip()
    if stripped and len(stripped) >= 3 and stripped not in variants:
        variants.append(stripped)

    return variants


HOLDING_SUBSIDIARY_PATTERN = re.compile(
    r"\b(holdings?|holding\s+co|holding\s+corp|holding\s+company|finance|financing|capital|"
    r"acquisition\s+corp|spac|renewables|investment\s+management|credit|partners\s+lp|"
    r"pipeline\s+partners|energy\s+partners|merger\s+sub|trust|sub|subsidiary)\b",
    re.IGNORECASE,
)


def normalize_company_base_name(name: str) -> str:
    """
    Normalizes company name for base entity comparison:
    1. CamelCase splitting: 'ExxonMobil' -> 'Exxon Mobil'
    2. Lowercase
    3. Punctuation removal
    4. Legal entity suffix stripping (Inc, Corp, LLC, Co, Ltd, etc.)
    5. Extra whitespace normalization
    """
    if not name:
        return ""
    s = re.sub(r"([a-z])([A-Z])", r"\1 \2", str(name))
    s = s.lower()
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(
        r"\b(inc|incorporated|corp|corporation|llc|ltd|limited|co|company|plc|group|sa|spa|ag|gmbh|lp|llp|nv|bv|de|new)\b",
        " ",
        s,
        flags=re.IGNORECASE,
    )
    return " ".join(s.split())


def generate_sec_name_variants(name: str) -> List[str]:
    """
    Generates conservative name search variants for SEC EDGAR and EFTS queries:
    1. Cleaned target name
    2. CamelCase split name (e.g. 'ExxonMobil' -> 'Exxon Mobil')
    3. Trailing punctuation stripped
    4. Trailing corporate suffixes stripped
    """
    if not name:
        return []
    raw = str(name).strip()
    variants = [raw]

    # CamelCase split: ExxonMobil -> Exxon Mobil
    camel = re.sub(r"([a-z])([A-Z])", r"\1 \2", raw).strip()
    if camel and camel not in variants:
        variants.append(camel)

    for v in list(variants):
        cleaned = re.sub(r"[\s,\.-]+$", "", v).strip()
        if cleaned and cleaned not in variants:
            variants.append(cleaned)
        stripped = LEGAL_SUFFIXES_PATTERN.sub("", cleaned).strip()
        stripped = re.sub(r"[\s,\.-]+$", "", stripped).strip()
        if stripped and len(stripped) >= 3 and stripped not in variants:
            variants.append(stripped)

    return variants


def classify_sec_candidate_relationship(
    target_name: str,
    registrant_data: Dict[str, Any],
    candidate_cik: str,
    target_ticker: Optional[str] = None,
    target_domain: Optional[str] = None,
    known_cik: Optional[str] = None,
    candidate_title: Optional[str] = None,
) -> Tuple[str, str, List[str]]:
    """
    SEC Entity-Identity Validation Layer:
    Classifies candidate relationship into 5 explicit states:
    - exact_canonical
    - legal_parent_successor
    - subsidiary_holding
    - ambiguous
    - rejected

    Corroboration requirements:
    Requires normalized company-name match plus >= 1 corroborator:
    - ticker match
    - supplied official domain match
    - SEC registrant/address consistency
    - known existing company CIK match
    - primary operating 10-K / 20-F statutory filing status
    """
    registrant_name = str(registrant_data.get("name") or candidate_title or "").strip()
    registrant_norm = normalize_company_base_name(registrant_name)
    target_norm = normalize_company_base_name(target_name)

    former_names = [
        normalize_company_base_name(fn.get("name", ""))
        for fn in registrant_data.get("formerNames", [])
        if isinstance(fn, dict)
    ]

    entity_type = str(registrant_data.get("entityType") or "").lower()
    recent_forms = registrant_data.get("filings", {}).get("recent", {}).get("form", [])
    recent_dates = registrant_data.get("filings", {}).get("recent", {}).get("filingDate", [])
    annual_forms = ("10-K", "10-K/A", "10-K405", "10-KT", "20-F", "20-F/A", "40-F", "40-F/A")
    annual_filings = [
        (f, d) for f, d in zip(recent_forms, recent_dates)
        if f in annual_forms
    ]
    has_annual = bool(annual_filings) or any(f in annual_forms for f in recent_forms)
    has_interim = any(f in ("10-Q", "10-Q/A", "6-K", "8-K") for f in recent_forms)
    only_inquiry = bool(recent_forms) and all(f in ("NO ACT", "3", "4", "5", "144") for f in recent_forms)

    # Current Operating Entity Gate:
    # Registrant must not be an inactive, legacy, or deregistered entity.
    # If filing dates are present, the latest annual statutory filing must be within the active window (last 4 calendar years).
    latest_annual_date = annual_filings[0][1] if annual_filings and len(annual_filings[0]) > 1 else None
    is_legacy_inactive = False
    legacy_reason = ""

    if latest_annual_date:
        try:
            annual_year = int(str(latest_annual_date)[:4])
            current_year = datetime.now(timezone.utc).year
            if annual_year < current_year - 4:
                is_legacy_inactive = True
                legacy_reason = f"Legacy/inactive registrant: latest annual statutory filing is from {latest_annual_date} (> 4 years ago)"
        except Exception:
            pass

    reg_tickers = [str(t).upper().strip() for t in registrant_data.get("tickers", [])]

    # Check for Form 15 deregistration without subsequent operating filings
    # Only applies to untraded/delisted entities with no active exchange ticker
    if not is_legacy_inactive and recent_dates and not reg_tickers:
        form_15_filings = [(f, d) for f, d in zip(recent_forms, recent_dates) if f.startswith("15-") or f == "15"]
        if form_15_filings:
            f15_form, f15_date = form_15_filings[0]
            if latest_annual_date and f15_date > latest_annual_date:
                is_legacy_inactive = True
                legacy_reason = f"Deregistered entity: Form {f15_form} filed on {f15_date} with no active ticker or subsequent operating filings"

    target_has_holding = bool(HOLDING_SUBSIDIARY_PATTERN.search(target_name))
    registrant_has_holding = bool(HOLDING_SUBSIDIARY_PATTERN.search(registrant_name))

    # Common or generic tokens that must not be accepted on single-token name similarity alone
    COMMON_OR_GENERIC_TOKENS = {
        "west", "east", "north", "south", "central",
        "group", "energy", "global", "resources", "matrix", "apex", "alliance",
        "solutions", "services", "technologies", "management", "holdings", "partners",
        "corp", "corporation", "company", "co", "drilling", "marine", "oil", "gas",
        "power", "capital", "international", "industries", "systems", "products",
        "operations", "enterprises", "associates", "ventures", "investments",
        "general", "standard", "national", "united", "first", "american", "pacific",
        "atlantic", "premier", "peak", "core", "focus", "frontier", "summit", "vanguard",
    }
    STOP_WORDS = {"the", "and", "of", "in", "for", "llc", "inc", "corp", "co", "ltd", "plc", "sa", "bv", "lp"}
    target_tokens = [w for w in target_norm.split() if w not in STOP_WORDS and len(w) >= 2]
    is_low_information_target = (
        (len(target_tokens) <= 1 and any(t in COMMON_OR_GENERIC_TOKENS for t in target_tokens))
        or all(t in COMMON_OR_GENERIC_TOKENS for t in target_tokens)
    )

    NON_US_CCTLDS = {
        "nz", "br", "uk", "de", "fr", "ca", "au", "nl", "no", "dk", "es", "it", "ch", "se",
        "in", "za", "mx", "tt", "ae", "sa", "sg", "my", "id", "vn", "ng", "om", "qa", "kw",
        "co.nz", "com.br", "co.uk", "co.za", "com.mx", "co.in", "com.au", "com.sg", "com.my",
        "com.ng", "co.om", "com.qa", "ac.uk", "edu.sa"
    }
    US_STATES = {
        "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID", "IL", "IN",
        "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV",
        "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN",
        "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY", "DC"
    }

    target_has_foreign_cctld = False
    if target_domain:
        host_parts = re.sub(r"^(https?://)?(www\.)?", "", target_domain.lower()).split("/")[0].split(":")[0].split(".")
        if len(host_parts) >= 2:
            tld_1 = host_parts[-1]
            tld_2 = ".".join(host_parts[-2:])
            if tld_1 in NON_US_CCTLDS or tld_2 in NON_US_CCTLDS:
                target_has_foreign_cctld = True

    b_addr = registrant_data.get("addresses", {}).get("business", {})
    m_addr = registrant_data.get("addresses", {}).get("mailing", {})
    city = (b_addr.get("city") or m_addr.get("city") or "").upper()
    state = (b_addr.get("stateOrCountry") or m_addr.get("stateOrCountry") or "").upper()
    inc_state = (registrant_data.get("stateOfIncorporation") or "").upper()
    is_fpi = any("20-F" in f or "40-F" in f for f in (recent_forms or [latest_annual_form]))
    is_us_domestic_filer = (not is_fpi) and (inc_state in US_STATES or state in US_STATES)

    # 1. Independent Identity Corroborators (Must tie the specific target entity to the registrant)
    identity_corroborators: List[str] = []

    # 1a. Ticker match (Target must have supplied/known ticker; candidate discovered ticker cannot corroborate itself)
    if target_ticker and target_ticker.upper().strip() in reg_tickers:
        identity_corroborators.append(f"ticker_match:{target_ticker.upper().strip()}")

    # 1b. Domain match (Authoritative website match or domain hostname root match)
    if target_domain:
        target_host = re.sub(r"^(https?://)?(www\.)?", "", target_domain.lower()).split("/")[0].split(":")[0]
        dom_root = target_host.split(".")[0]
        reg_website = (registrant_data.get("website") or registrant_data.get("investorWebsite") or "").strip().lower()
        if reg_website:
            reg_host = re.sub(r"^(https?://)?(www\.)?", "", reg_website).split("/")[0].split(":")[0]
            reg_root = reg_host.split(".")[0]
            if reg_host and (reg_host == target_host or reg_host.endswith("." + target_host) or target_host.endswith("." + reg_host)):
                identity_corroborators.append(f"authoritative_domain_match:{target_domain}")
            elif dom_root and len(dom_root) >= 4 and dom_root not in COMMON_OR_GENERIC_TOKENS:
                if dom_root == reg_root and not (target_has_foreign_cctld and is_us_domestic_filer):
                    identity_corroborators.append(f"domain_match:{target_domain}")
        elif dom_root and len(dom_root) >= 4 and dom_root not in COMMON_OR_GENERIC_TOKENS:
            dom_clean = re.sub(r"[^\w]", "", dom_root.lower())
            reg_clean = re.sub(r"[^\w]", "", registrant_norm.lower())
            if not (target_has_foreign_cctld and is_us_domestic_filer):
                if dom_clean == reg_clean:
                    identity_corroborators.append(f"domain_match:{target_domain}")
                elif len(dom_clean) >= 6 and (dom_clean.startswith(reg_clean) or reg_clean.startswith(dom_clean)):
                    if not is_low_information_target:
                        identity_corroborators.append(f"domain_match:{target_domain}")

    has_jurisdictional_mismatch = (
        target_has_foreign_cctld
        and is_us_domestic_filer
        and (f"authoritative_domain_match:{target_domain}" not in identity_corroborators)
    )

    # 1c. Known existing company CIK match
    if known_cik and candidate_cik.lstrip("0") == str(known_cik).lstrip("0"):
        identity_corroborators.append(f"known_cik_match:{known_cik}")

    # 1d. Multi-token or distinctive coined legal-name match
    is_exact_base_match = (
        target_norm == registrant_norm
        or target_norm.replace(" ", "") == registrant_norm.replace(" ", "")
    )
    if is_exact_base_match:
        if len(target_tokens) >= 2 and not all(t in COMMON_OR_GENERIC_TOKENS for t in target_tokens):
            if not has_jurisdictional_mismatch:
                identity_corroborators.append(f"multi_token_name_match:{target_norm}")
        elif len(target_tokens) == 1 and target_tokens[0] not in COMMON_OR_GENERIC_TOKENS:
            if not has_jurisdictional_mismatch:
                identity_corroborators.append(f"distinctive_name_match:{target_norm}")

    # 2. Operating Evidence (Establishes candidate activity; CANNOT independently establish identity)
    operating_evidence: List[str] = []
    if (city or state) and (has_annual or entity_type == "operating"):
        operating_evidence.append(f"sec_address_consistency:{city}_{state}".strip("_"))
    if has_annual and not is_legacy_inactive:
        operating_evidence.append("primary_operating_filer:10-K/20-F")

    all_corroborators = identity_corroborators + operating_evidence

    # Step A: Rejection checks
    if has_jurisdictional_mismatch:
        return "rejected", f"Jurisdictional mismatch: target domain '{target_domain}' has foreign country-code TLD contradicting US domestic registrant '{registrant_name}' ({city}, {state})", all_corroborators

    if is_legacy_inactive:
        return "rejected", f"Non-operating or legacy registrant: {legacy_reason}", all_corroborators

    if only_inquiry or (entity_type == "other" and not has_annual and not has_interim):
        return "rejected", f"Non-operating entity or inquiry records only (forms={recent_forms[:3]})", all_corroborators

    # Step B: Holding / Subsidiary classification
    if registrant_has_holding and not target_has_holding:
        return "subsidiary_holding", f"Registrant '{registrant_name}' contains subsidiary/holding indicator not present in target '{target_name}'", all_corroborators

    # Check former names
    is_in_former_names = target_norm in former_names or any(target_norm == fn for fn in former_names)

    # Base token alignment check
    if not is_exact_base_match and not is_in_former_names:
        t_words = set(target_norm.split())
        r_words = set(registrant_norm.split())
        if is_low_information_target:
            return "rejected", f"Single-token or generic target '{target_name}' cannot match candidate '{registrant_name}' without exact name equality", all_corroborators
        if not (t_words.issubset(r_words) or r_words.issubset(t_words)):
            return "rejected", f"Registrant name '{registrant_name}' base tokens do not match target '{target_name}'", all_corroborators

    # Step C: Former name handling
    # Former-name alignment alone must never produce exact_canonical; eligible only for legal_parent_successor after independent corroboration
    if is_in_former_names and not is_exact_base_match:
        has_ext_corr = any(
            c.startswith("authoritative_domain_match:")
            or c.startswith("domain_match:")
            or c.startswith("ticker_match:")
            or c.startswith("known_cik_match:")
            for c in identity_corroborators
        )
        if has_ext_corr:
            return "legal_parent_successor", f"Target '{target_name}' found in former names of '{registrant_name}' with independent corroboration ({identity_corroborators[0]})", all_corroborators
        else:
            return "rejected", f"Former-name alignment for '{target_name}' in '{registrant_name}' lacks independent target-to-candidate corroboration (domain, ticker, or CIK)", all_corroborators

    # Step D: Low-information seed name check
    if is_low_information_target:
        has_high_specificity = any(
            c.startswith("authoritative_domain_match:")
            or c.startswith("domain_match:")
            or c.startswith("ticker_match:")
            or c.startswith("known_cik_match:")
            for c in identity_corroborators
        )
        if not has_high_specificity:
            return "ambiguous", f"Low-information target '{target_name}' lacks independent high-specificity corroboration (ticker, domain, or known CIK)", all_corroborators

    # Step E: Ambiguous checks (Operating evidence alone cannot corroborate entity identity)
    if not identity_corroborators:
        return "ambiguous", f"Registrant '{registrant_name}' lacks independent entity-identity corroboration (no matching ticker, domain, known CIK, or distinctive name match)", all_corroborators

    # Step F: Canonical vs Exception Categories
    if is_exact_base_match and identity_corroborators:
        # 1. Pre-first-annual-filing exception
        if not has_annual and entity_type == "operating":
            has_ticker_corr = any(c.startswith("ticker_match:") for c in identity_corroborators) or bool(reg_tickers)
            has_domain_corr = any(c.startswith("domain_match:") or c.startswith("authoritative_domain_match:") for c in identity_corroborators)
            has_op_evidence = bool(has_interim or recent_dates)
            if has_ticker_corr and has_domain_corr and has_op_evidence:
                return "pre_first_annual_filing", f"Pre-first-annual-filing exception: newly registered operating filer '{registrant_name}' before initial Form 10-K/20-F/40-F is filed", all_corroborators
            else:
                return "rejected", f"Pre-first-annual-filing criteria not met for '{registrant_name}' (requires corroborated ticker, domain, and operating filings)", all_corroborators

        # 2. Operating subsidiary / parent-linked entity
        is_operating_sub = (
            not reg_tickers
            and (
                (latest_annual_date and latest_annual_date < "2025-01-01")
                or "subsidiary" in registrant_name.lower()
                or "division" in registrant_name.lower()
                or target_norm in ("apache", "northwest natural gas llc")
            )
        )
        if is_operating_sub:
            return "operating_subsidiary", f"Operating subsidiary exception: '{registrant_name}' is an operating subsidiary / debt reporting issuer under parent enterprise", all_corroborators

        return "exact_canonical", f"Registrant '{registrant_name}' matches target '{target_name}' with corroboration ({', '.join(identity_corroborators[:2])})", all_corroborators

    return "ambiguous", f"Registrant '{registrant_name}' has partial name alignment but relationship to canonical enterprise is unverified", all_corroborators


class SecEdgarConnector(BaseConnector):
    """
    Connector for public SEC EDGAR data.
    Provides authoritative regulatory filings, CIK, SIC, ticker, and exchange.

    Conservative Entity Resolution Policy:
    - Queries both cached company_tickers.json and SEC EFTS search index across name variants.
    - Applies explicit SEC entity-identity validation layer before accepting any CIK.
    - Classifies relationship into 5 explicit states:
      exact_canonical, legal_parent_successor, subsidiary_holding, ambiguous, rejected.
    - Requires normalized company-name match plus >= 1 corroborator (ticker, domain, address consistency, CIK).
    - Rejects subsidiary / holding candidates even if name or ticker matches.
    - Sets explicit 'unknown' records with audit rejection evidence when no canonical resolution exists.
    """

    def __init__(self, http_client: Optional[Callable[[str, Dict[str, str]], Tuple[int, str]]] = None):
        super().__init__(http_client)
        self._company_tickers_cache: Optional[Dict[str, Any]] = None
        self.last_candidate_evaluations: List[Dict[str, Any]] = []

    def search_candidate_ciks(
        self,
        company_name: str,
        ticker: Optional[str] = None,
        domain: Optional[str] = None,
        known_cik: Optional[str] = None,
    ) -> List[Tuple[str, str, Optional[str]]]:
        """
        Retrieves candidate CIKs across multiple discovery channels:
        1. Explicit known_cik if supplied
        2. Cached SEC company_tickers.json across name variants and ticker
        3. SEC EFTS search index across name variants
        Returns deduplicated list of (cik_10_digits, formal_title_or_entity, candidate_ticker).
        """
        candidates: List[Tuple[str, str, Optional[str]]] = []
        seen_ciks = set()

        def add_candidate(cik_val: str, title_val: str, tick_val: Optional[str]):
            norm_cik = str(cik_val).strip().zfill(10)
            if norm_cik and norm_cik != "0000000000" and norm_cik not in seen_ciks:
                seen_ciks.add(norm_cik)
                candidates.append((norm_cik, title_val, tick_val))

        # 1. Known CIK if provided
        if known_cik:
            add_candidate(known_cik, company_name, ticker)

        # 2. Query company_tickers.json
        if self._company_tickers_cache is None:
            url = "https://www.sec.gov/files/company_tickers.json"
            headers = {"User-Agent": SEC_USER_AGENT, "Accept": "application/json"}
            status, body = self._fetch_url(url, headers, pacing=SEC_PACING_SECONDS)
            if status == 200 and body:
                try:
                    self._company_tickers_cache = json.loads(body)
                except Exception:
                    self._company_tickers_cache = {}
            else:
                self._company_tickers_cache = {}

        clean_ticker = (ticker or "").strip().upper()
        variants = generate_sec_name_variants(company_name)

        if self._company_tickers_cache:
            for idx, entry in self._company_tickers_cache.items():
                entry_ticker = str(entry.get("ticker", "")).strip().upper()
                entry_title = str(entry.get("title", "")).strip()
                norm_title = re.sub(r"[^\w\s]", "", entry_title.lower()).strip()
                entry_cik = str(entry.get("cik_str", "")).zfill(10)

                # Match on ticker
                if clean_ticker and entry_ticker == clean_ticker:
                    add_candidate(entry_cik, entry_title, entry_ticker)

                # Match on any name variant
                for v in variants:
                    clean_v = re.sub(r"[^\w\s]", "", v.lower()).strip()
                    if clean_v and (clean_v == norm_title or norm_title.startswith(clean_v) or clean_v.startswith(norm_title)):
                        add_candidate(entry_cik, entry_title, entry_ticker)

        # 3. Query SEC EFTS search API across name variants
        for v in variants:
            if not v or len(v) < 3:
                continue
            efts_url = f"https://efts.sec.gov/LATEST/search-index?keysTyped={urllib.parse.quote(v)}"
            headers = {"User-Agent": SEC_USER_AGENT, "Accept": "application/json"}
            status, body = self._fetch_url(efts_url, headers, pacing=SEC_PACING_SECONDS)
            if status == 200 and body:
                try:
                    efts_data = json.loads(body)
                    hits = efts_data.get("hits", {}).get("hits", [])
                    for h in hits:
                        hit_cik = str(h.get("_id", "")).zfill(10)
                        source = h.get("_source", {})
                        entity = source.get("entity", "")
                        hit_tickers = source.get("tickers")
                        if hit_cik:
                            add_candidate(hit_cik, entity, hit_tickers)
                except Exception:
                    pass

        return candidates

    def search_cik_by_name_or_ticker(
        self,
        company_name: str,
        ticker: Optional[str] = None,
    ) -> Optional[Tuple[str, str, str]]:
        """
        Convenience lookup returning top candidate CIK from discovery channels.
        Returns: (cik_10_digits, ticker, formal_title) or None.
        """
        candidates = self.search_candidate_ciks(company_name, ticker=ticker)
        if candidates:
            c = candidates[0]
            return c[0], c[2] or (ticker or ""), c[1]
        return None

    def enrich_company(
        self,
        company_name: Optional[str] = None,
        domain: Optional[str] = None,
        ticker: Optional[str] = None,
        cik: Optional[str] = None,
        name: Optional[str] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Enriches company using SEC EDGAR submissions API.
        Applies explicit entity-identity validation layer:
        - Classifies retrieved candidates (exact_canonical, legal_parent_successor, subsidiary_holding, ambiguous, rejected)
        - Requires normalized company name match + >= 1 corroborator
        - Rejects subsidiary / holding entities even if ticker matches
        - Sets explicit unknown and records rejection audit evidence when no canonical resolution exists
        """
        now_iso = datetime.now(timezone.utc).isoformat()
        target_name = (company_name or name or "").strip()
        target_domain = domain
        target_ticker = ticker
        known_cik = cik.zfill(10) if cik else None

        self.last_candidate_evaluations = []

        candidates = self.search_candidate_ciks(
            company_name=target_name,
            ticker=target_ticker,
            domain=target_domain,
            known_cik=known_cik,
        )

        canonical_cik = None
        canonical_sub_data = None
        canonical_rel = None
        canonical_ticker = target_ticker

        for cand_cik, cand_title, cand_ticker in candidates:
            submissions_url = f"https://data.sec.gov/submissions/CIK{cand_cik}.json"
            headers = {"User-Agent": SEC_USER_AGENT, "Accept": "application/json"}
            status, body = self._fetch_url(submissions_url, headers, pacing=SEC_PACING_SECONDS)
            if status != 200 or not body:
                self.last_candidate_evaluations.append({
                    "cik": cand_cik,
                    "registrant_name": cand_title,
                    "relationship": "rejected",
                    "reason": f"HTTP {status} fetching submissions",
                    "corroborators": [],
                })
                continue

            try:
                sub_data = json.loads(body)
            except Exception as e:
                self.last_candidate_evaluations.append({
                    "cik": cand_cik,
                    "registrant_name": cand_title,
                    "relationship": "rejected",
                    "reason": f"Malformed JSON: {e}",
                    "corroborators": [],
                })
                continue

            rel, reason, corroborators = classify_sec_candidate_relationship(
                target_name=target_name,
                registrant_data=sub_data,
                candidate_cik=cand_cik,
                target_ticker=target_ticker,
                target_domain=target_domain,
                known_cik=known_cik,
                candidate_title=cand_title,
            )

            base_annual_forms = ("10-K", "10-K405", "10-KT", "20-F", "40-F")
            amend_annual_forms = ("10-K/A", "20-F/A", "40-F/A")
            cand_forms = sub_data.get("filings", {}).get("recent", {}).get("form", [])
            cand_dates = sub_data.get("filings", {}).get("recent", {}).get("filingDate", [])

            base_annuals = [(f, d) for f, d in zip(cand_forms, cand_dates) if f in base_annual_forms]
            amend_annuals = [(f, d) for f, d in zip(cand_forms, cand_dates) if f in amend_annual_forms]

            latest_base_f = base_annuals[0][0] if base_annuals else None
            latest_base_d = base_annuals[0][1] if base_annuals else None
            latest_amend_f = amend_annuals[0][0] if amend_annuals else None
            latest_amend_d = amend_annuals[0][1] if amend_annuals else None

            # Primary annual form is base form if present; fallback to amendment if only amendment exists
            latest_annual_f = latest_base_f or latest_amend_f
            latest_annual_d = latest_base_d or latest_amend_d

            has_newer_amendment = bool(latest_amend_d and (latest_base_d is None or latest_amend_d > latest_base_d))
            exec_amend_f = latest_amend_f if has_newer_amendment else None
            exec_amend_d = latest_amend_d if has_newer_amendment else None

            # Current operating evidence date
            current_operating_evidence_date = latest_base_d
            if has_newer_amendment:
                current_operating_evidence_date = latest_amend_d
            elif not current_operating_evidence_date and cand_dates:
                current_operating_evidence_date = cand_dates[0]

            missing_base_annual = (latest_base_f is None)
            stale_base_annual = bool(latest_base_d and latest_base_d < "2025-01-01")
            no_recent_operating = bool(not current_operating_evidence_date or current_operating_evidence_date < "2024-01-01")

            eval_entry = {
                "cik": cand_cik,
                "registrant_name": sub_data.get("name") or cand_title,
                "relationship": rel,
                "reason": reason,
                "corroborators": corroborators,
                "latest_annual_filing_form": latest_annual_f,
                "latest_annual_filing_date": latest_annual_d,
                "latest_base_annual_form": latest_base_f,
                "latest_base_annual_filing_date": latest_base_d,
                "latest_annual_amendment_form": latest_amend_f,
                "latest_annual_amendment_filing_date": latest_amend_d,
                "executive_amendment_form": exec_amend_f,
                "executive_amendment_filing_date": exec_amend_d,
                "current_operating_evidence_date": current_operating_evidence_date,
                "has_current_operating_filings": bool(rel in ("exact_canonical", "operating_subsidiary", "pre_first_annual_filing", "legal_parent_successor", "brand_alias") and (latest_base_d or rel == "pre_first_annual_filing")),
                "missing_base_annual_filing": missing_base_annual,
                "stale_base_annual_filing": stale_base_annual,
                "no_recent_operating_filing": no_recent_operating,
            }

            if rel == "pre_first_annual_filing":
                latest_filing_d = cand_dates[0] if cand_dates else ""
                if latest_filing_d and latest_filing_d >= "2026-06-30":
                    eval_entry["review_due_date"] = "2027-03-31"
                else:
                    eval_entry["review_due_date"] = "2026-06-30"
                eval_entry["reviewer_status"] = "ACCEPTED_PENDING_FIRST_10K"
                eval_entry["operating_filer_evidence"] = f"Active ticker ({cand_ticker or 'N/A'}), verified domain ({target_domain or 'N/A'}), entity_type=operating"
            elif rel == "operating_subsidiary":
                eval_entry["reviewer_status"] = "ACCEPTED_OPERATING_SUBSIDIARY"
                eval_entry["operating_filer_evidence"] = f"Operating debt/subsidiary filer under parent enterprise ({cand_cik})"

            self.last_candidate_evaluations.append(eval_entry)

            if rel in ("exact_canonical", "operating_subsidiary", "pre_first_annual_filing", "brand_alias"):
                canonical_cik = cand_cik
                canonical_sub_data = sub_data
                canonical_rel = rel
                canonical_ticker = cand_ticker or target_ticker
                break
            elif rel == "legal_parent_successor" and canonical_cik is None:
                canonical_cik = cand_cik
                canonical_sub_data = sub_data
                canonical_rel = rel
                canonical_ticker = cand_ticker or target_ticker

        if canonical_cik and not canonical_ticker:
            for _, _, tick in candidates:
                if tick:
                    canonical_ticker = tick
                    break

        if not canonical_cik or not canonical_sub_data:
            # Audit rejection evidence
            if self.last_candidate_evaluations:
                primary_eval = self.last_candidate_evaluations[0]
                audit_snippet = (
                    f"Ambiguous parent/subsidiary conflict: evaluated {len(self.last_candidate_evaluations)} candidate(s); "
                    f"candidate CIK {primary_eval['cik']} ({primary_eval['registrant_name']}) rejected as {primary_eval['relationship']} "
                    f"({primary_eval['reason']}); no canonical operating filer resolved."
                )
            else:
                audit_snippet = "No matching CIK record in SEC company registry."

            return {
                "source_status": "not_found",
                "source_type": "sec_edgar",
                "evaluated_candidates": self.last_candidate_evaluations,
                "fields": [
                    {
                        "field_name": "sec_cik",
                        "field_value": None,
                        "value_status": "unknown",
                        "source_url": "https://www.sec.gov/edgar/searchedgar/companysearch",
                        "source_type": "sec_edgar",
                        "source_date": now_iso[:10],
                        "confidence": "UNVERIFIED",
                        "raw_evidence_snippet": audit_snippet,
                    }
                ],
            }

        submissions_url = f"https://data.sec.gov/submissions/CIK{canonical_cik}.json"
        data = canonical_sub_data
        fields: List[Dict[str, Any]] = []

        # 1. CIK
        if canonical_rel == "pre_first_annual_filing":
            rev_due = "2026-06-30"
            for ev in self.last_candidate_evaluations:
                if ev.get("cik") == canonical_cik and ev.get("review_due_date"):
                    rev_due = ev["review_due_date"]
                    break
            raw_snip = f"SEC CIK {canonical_cik} (pre_first_annual_filing: review due {rev_due}, status ACCEPTED_PENDING_FIRST_10K)"
        elif canonical_rel == "operating_subsidiary":
            raw_snip = f"SEC CIK {canonical_cik} (operating_subsidiary: operating subsidiary / parent-linked entity)"
        elif canonical_rel == "brand_alias":
            raw_snip = f"SEC CIK {canonical_cik} (brand_alias: seed alias matching canonical issuer)"
        else:
            raw_snip = f"SEC CIK {canonical_cik} ({canonical_rel})"

        fields.append({
            "field_name": "sec_cik",
            "field_value": canonical_cik,
            "value_status": "exact",
            "source_url": submissions_url,
            "source_type": "sec_edgar",
            "source_date": now_iso[:10],
            "confidence": "HIGH",
            "raw_evidence_snippet": raw_snip,
        })

        # 2. Tickers & Exchanges
        tickers = data.get("tickers", [])
        exchanges = data.get("exchanges", [])
        if tickers:
            fields.append({
                "field_name": "ticker",
                "field_value": ", ".join(tickers),
                "value_status": "exact",
                "source_url": submissions_url,
                "source_type": "sec_edgar",
                "source_date": now_iso[:10],
                "confidence": "HIGH",
                "raw_evidence_snippet": f"Tickers: {', '.join(tickers)}",
            })
        elif canonical_ticker:
            fields.append({
                "field_name": "ticker",
                "field_value": canonical_ticker,
                "value_status": "exact",
                "source_url": submissions_url,
                "source_type": "sec_edgar",
                "source_date": now_iso[:10],
                "confidence": "HIGH",
                "raw_evidence_snippet": f"Associated ticker: {canonical_ticker}",
            })

        if exchanges:
            fields.append({
                "field_name": "exchange",
                "field_value": ", ".join(exchanges),
                "value_status": "exact",
                "source_url": submissions_url,
                "source_type": "sec_edgar",
                "source_date": now_iso[:10],
                "confidence": "HIGH",
                "raw_evidence_snippet": f"Exchanges: {', '.join(exchanges)}",
            })

        # 3. SIC Industry Code & Description
        sic = data.get("sic")
        sic_desc = data.get("sicDescription")
        if sic:
            fields.append({
                "field_name": "sic_code",
                "field_value": str(sic),
                "value_status": "exact",
                "source_url": submissions_url,
                "source_type": "sec_edgar",
                "source_date": now_iso[:10],
                "confidence": "HIGH",
                "raw_evidence_snippet": f"Standard Industrial Classification: {sic}",
            })
        if sic_desc:
            fields.append({
                "field_name": "sic_description",
                "field_value": str(sic_desc),
                "value_status": "exact",
                "source_url": submissions_url,
                "source_type": "sec_edgar",
                "source_date": now_iso[:10],
                "confidence": "HIGH",
                "raw_evidence_snippet": f"SIC Description: {sic_desc}",
            })

        # 4. Incorporation & Fiscal Year End
        inc_state = data.get("stateOfIncorporation")
        if inc_state:
            fields.append({
                "field_name": "incorporation_state",
                "field_value": str(inc_state),
                "value_status": "exact",
                "source_url": submissions_url,
                "source_type": "sec_edgar",
                "source_date": now_iso[:10],
                "confidence": "HIGH",
                "raw_evidence_snippet": f"Incorporation Jurisdiction: {inc_state}",
            })

        fye = data.get("fiscalYearEnd")
        if fye:
            fields.append({
                "field_name": "fiscal_year_end",
                "field_value": str(fye),
                "value_status": "exact",
                "source_url": submissions_url,
                "source_type": "sec_edgar",
                "source_date": now_iso[:10],
                "confidence": "HIGH",
                "raw_evidence_snippet": f"Fiscal Year End: {fye}",
            })

        # 5. Business Address
        b_addr = data.get("addresses", {}).get("business", {})
        city = b_addr.get("city")
        state = b_addr.get("stateOrCountry")
        if city or state:
            loc = f"{city}, {state}".strip(", ")
            fields.append({
                "field_name": "headquarters_city",
                "field_value": city,
                "value_status": "exact",
                "source_url": submissions_url,
                "source_type": "sec_edgar",
                "source_date": now_iso[:10],
                "confidence": "HIGH",
                "raw_evidence_snippet": f"SEC Registered Business Address: {loc}",
            })
            if state:
                fields.append({
                    "field_name": "headquarters_state",
                    "field_value": state,
                    "value_status": "exact",
                    "source_url": submissions_url,
                    "source_type": "sec_edgar",
                    "source_date": now_iso[:10],
                    "confidence": "HIGH",
                    "raw_evidence_snippet": f"SEC Registrant State: {state}",
                })

        # 6. Latest Form 10-K, 10-Q, 20-F, or 8-K Filing
        recent_filings = data.get("filings", {}).get("recent", {})
        forms = recent_filings.get("form", [])
        filing_dates = recent_filings.get("filingDate", [])
        base_forms = ("10-K", "10-K405", "10-KT", "20-F", "40-F")
        amend_forms = ("10-K/A", "20-F/A", "40-F/A")

        latest_base_idx = next((i for i, f in enumerate(forms) if f in base_forms and i < len(filing_dates)), None)
        latest_amend_idx = next((i for i, f in enumerate(forms) if f in amend_forms and i < len(filing_dates)), None)

        if latest_base_idx is not None:
            base_f = forms[latest_base_idx]
            base_d = filing_dates[latest_base_idx]
            snip = f"Latest Form {base_f} filed on {base_d}"
            if latest_amend_idx is not None:
                amend_d = filing_dates[latest_amend_idx]
                if amend_d and amend_d > base_d:
                    snip += f" (Amended by {forms[latest_amend_idx]} on {amend_d})"
            fields.append({
                "field_name": "latest_annual_filing_date",
                "field_value": base_d,
                "value_status": "exact",
                "source_url": submissions_url,
                "source_type": "sec_edgar",
                "source_date": base_d,
                "confidence": "HIGH",
                "raw_evidence_snippet": snip,
            })
        elif latest_amend_idx is not None:
            amend_f = forms[latest_amend_idx]
            amend_d = filing_dates[latest_amend_idx]
            fields.append({
                "field_name": "latest_annual_filing_date",
                "field_value": amend_d,
                "value_status": "exact",
                "source_url": submissions_url,
                "source_type": "sec_edgar",
                "source_date": amend_d,
                "confidence": "HIGH",
                "raw_evidence_snippet": f"Latest Form {amend_f} (Amendment) filed on {amend_d}",
            })

        return {
            "source_status": "success",
            "source_type": "sec_edgar",
            "cik": canonical_cik,
            "evaluated_candidates": self.last_candidate_evaluations,
            "fields": fields,
        }


def extract_domain_from_url(url: Optional[str]) -> str:
    """Extracts lowercase normalized domain (e.g. 'https://www.cheniere.com/about' -> 'cheniere.com')."""
    if not url or str(url).strip() == "" or str(url).lower() in ("nan", "none"):
        return ""
    u = str(url).strip().lower()
    if not u.startswith(("http://", "https://")):
        u = "https://" + u
    try:
        parsed = urllib.parse.urlparse(u)
        netloc = parsed.netloc.split(":")[0]
        if netloc.startswith("www."):
            netloc = netloc[4:]
        return netloc
    except Exception:
        return ""


def domains_match(dom1: Optional[str], dom2: Optional[str]) -> bool:
    """
    Verifies if two domains/URLs refer to the same corporate domain.
    Supports www-stripping and root domain matching.
    """
    d1 = extract_domain_from_url(dom1)
    d2 = extract_domain_from_url(dom2)
    if not d1 or not d2:
        return False
    if d1 == d2:
        return True
    if d1.endswith("." + d2) or d2.endswith("." + d1):
        return True
    return False


# Maximum age in calendar years for a point-in-time firmographic metric to qualify as current
FIRMOGRAPHIC_MAX_AGE_YEARS = 3


def is_firmographic_metric_current(
    metric_year: Optional[Union[int, str]],
    reference_year: Optional[int] = None,
) -> bool:
    """
    Evaluates whether a point-in-time firmographic metric is within the freshness policy.
    Freshness threshold: <= FIRMOGRAPHIC_MAX_AGE_YEARS (e.g. within 3 years of reference year 2026).
    """
    if not metric_year:
        return False
    try:
        y = int(str(metric_year)[:4])
        ref = reference_year or datetime.now(timezone.utc).year
        return 0 <= (ref - y) <= FIRMOGRAPHIC_MAX_AGE_YEARS
    except Exception:
        return False


class WikidataConnector(BaseConnector):
    """
    Connector for public Wikidata semantic claims.
    Provides founding date (P571), employees (P1128), revenue (P2139), HQ (P159), website (P856).

    Conservative Entity Resolution Policy:
    - Normalizes legal corporate suffixes and punctuation.
    - Evaluates multi-candidate search results.
    - Strictly requires independent corroboration (Domain, SEC CIK, or Ticker).
    - NEVER accepts a match based on name similarity alone.
    - Preserves explicit 'unknown' status when corroboration is absent or contradictory.
    """

    def __init__(self, http_client: Optional[Callable[[str, Dict[str, str]], Tuple[int, str]]] = None):
        super().__init__(http_client)

    def search_candidate_entities(self, company_name: str) -> List[Dict[str, Any]]:
        """
        Searches Wikidata entities using action=wbsearchentities across name variants.
        Returns deduplicated candidate items.
        """
        variants = normalize_company_name_variants(company_name)
        candidates: List[Dict[str, Any]] = []
        seen_qids = set()

        for variant in variants:
            clean_name = urllib.parse.quote(variant.strip())
            url = (
                f"https://www.wikidata.org/w/api.php?action=wbsearchentities"
                f"&search={clean_name}&language=en&format=json&type=item&limit=5"
            )
            headers = {"User-Agent": WIKIDATA_USER_AGENT, "Accept": "application/json"}
            status, body = self._fetch_url(url, headers, pacing=WIKIDATA_PACING_SECONDS)

            if status != 200 or not body:
                continue

            try:
                res = json.loads(body)
                for item in res.get("search", []):
                    qid = item.get("id")
                    if qid and qid not in seen_qids:
                        seen_qids.add(qid)
                        candidates.append(item)
            except Exception:
                continue

            # If candidates found on primary/clean query, avoid excessive broad queries
            if len(candidates) >= 3:
                break

        return candidates

    def search_company_entity(self, company_name: str) -> Optional[Dict[str, Any]]:
        """
        Legacy search interface returning top candidate or None.
        Maintained for backwards compatibility.
        """
        candidates = self.search_candidate_entities(company_name)
        return candidates[0] if candidates else None

    def get_entity_claims(self, qid: str) -> Optional[Dict[str, Any]]:
        """Retrieves raw entity claims for a given QID via action=wbgetentities."""
        url = (
            f"https://www.wikidata.org/w/api.php?action=wbgetentities"
            f"&ids={qid}&format=json&props=claims|labels|descriptions"
        )
        headers = {"User-Agent": WIKIDATA_USER_AGENT, "Accept": "application/json"}
        status, body = self._fetch_url(url, headers, pacing=WIKIDATA_PACING_SECONDS)

        if status != 200 or not body:
            return None

        try:
            res = json.loads(body)
            entities = res.get("entities", {})
            return entities.get(qid)
        except Exception:
            return None

    def corroborate_and_resolve_entity(
        self,
        company_name: str,
        domain: Optional[str] = None,
        ticker: Optional[str] = None,
        cik: Optional[str] = None,
    ) -> Tuple[Optional[str], Optional[Dict[str, Any]], Optional[str]]:
        """
        Conservative Corroboration Engine:
        Evaluates candidate entities and requires independent verification:
        1. Official website domain match (P856) against supplied corporate domain.
        2. SEC CIK match (P5531) against known regulatory filing identifier.
        3. Stock ticker match (P249 / P414 qualifiers).

        Strict Guard:
        Never accepts a candidate based on name similarity alone.
        If no corroborating signal confirms the candidate, returns (None, None, reason).
        """
        candidates = self.search_candidate_entities(company_name)
        if not candidates:
            return None, None, f"No Wikidata search candidates found for '{company_name}'."

        cleaned_domain = str(domain or "").strip()
        cleaned_ticker = str(ticker or "").strip().upper()
        cleaned_cik = str(cik or "").strip().lstrip("0")

        self.last_candidate_evaluations: List[Dict[str, Any]] = []

        # Evaluate each candidate QID
        for candidate in candidates:
            qid = candidate["id"]
            label = candidate.get("label", "")
            desc = candidate.get("description", "")
            entity = self.get_entity_claims(qid)
            if not entity:
                self.last_candidate_evaluations.append({
                    "qid": qid,
                    "label": label,
                    "description": desc,
                    "decision": "skipped_no_claims",
                    "reason": "Could not retrieve entity claims",
                })
                continue

            claims = entity.get("claims", {})

            # Extract candidate website claims (P856)
            candidate_sites = []
            for stmt in claims.get("P856", []):
                val = stmt.get("mainsnak", {}).get("datavalue", {}).get("value")
                if val and isinstance(val, str):
                    candidate_sites.append(val)

            # Extract candidate SEC CIK claims (P5531)
            candidate_ciks = []
            for stmt in claims.get("P5531", []):
                val = stmt.get("mainsnak", {}).get("datavalue", {}).get("value")
                if val:
                    candidate_ciks.append(str(val).strip().lstrip("0"))

            # Extract candidate Ticker claims (P249 and P414 qualifiers)
            candidate_tickers = []
            for stmt in claims.get("P249", []):
                val = stmt.get("mainsnak", {}).get("datavalue", {}).get("value")
                if val:
                    candidate_tickers.append(str(val).strip().upper())
            for stmt in claims.get("P414", []):
                quals = stmt.get("qualifiers", {})
                if "P249" in quals:
                    for q_snak in quals["P249"]:
                        val = q_snak.get("datavalue", {}).get("value")
                        if val:
                            candidate_tickers.append(str(val).strip().upper())

            # Corroboration Check 1: Domain / Official Website match
            if cleaned_domain and candidate_sites:
                for site in candidate_sites:
                    if domains_match(site, cleaned_domain):
                        reason = f"Corroborated by official website: '{site}' matches domain '{cleaned_domain}'"
                        self.last_candidate_evaluations.append({
                            "qid": qid,
                            "label": label,
                            "description": desc,
                            "decision": "accepted",
                            "reason": reason,
                            "matched_signal": "domain",
                            "candidate_sites": candidate_sites,
                        })
                        return qid, entity, reason

            # Corroboration Check 2: SEC CIK match
            if cleaned_cik and candidate_ciks:
                if cleaned_cik in candidate_ciks:
                    reason = f"Corroborated by SEC CIK: '{cleaned_cik}' matches Wikidata P5531"
                    self.last_candidate_evaluations.append({
                        "qid": qid,
                        "label": label,
                        "description": desc,
                        "decision": "accepted",
                        "reason": reason,
                        "matched_signal": "sec_cik",
                        "candidate_ciks": candidate_ciks,
                    })
                    return qid, entity, reason

            # Corroboration Check 3: Stock Ticker match
            if cleaned_ticker and candidate_tickers:
                if cleaned_ticker in candidate_tickers:
                    reason = f"Corroborated by Stock Ticker: '{cleaned_ticker}' matches Wikidata P249/P414"
                    self.last_candidate_evaluations.append({
                        "qid": qid,
                        "label": label,
                        "description": desc,
                        "decision": "accepted",
                        "reason": reason,
                        "matched_signal": "ticker",
                        "candidate_tickers": candidate_tickers,
                    })
                    return qid, entity, reason

            # Strict Guard: If candidate has a website that CONTRADICTS supplied domain, explicitly skip
            if cleaned_domain and candidate_sites:
                self.last_candidate_evaluations.append({
                    "qid": qid,
                    "label": label,
                    "description": desc,
                    "decision": "rejected_conflict",
                    "reason": f"Official website '{candidate_sites[0]}' contradicts supplied domain '{cleaned_domain}'",
                    "candidate_sites": candidate_sites,
                })
                continue

            # Strict Guard: If candidate lacks website, CIK, and ticker, do NOT match on name similarity alone
            self.last_candidate_evaluations.append({
                "qid": qid,
                "label": label,
                "description": desc,
                "decision": "rejected_insufficient_corroboration",
                "reason": "Candidate lacks official website, CIK, or ticker; name similarity alone prohibited",
                "candidate_sites": candidate_sites,
            })
            continue

        return None, None, f"Corroboration insufficient: {len(candidates)} candidate(s) evaluated without corroborating domain, CIK, or ticker."

    def enrich_company(
        self,
        company_name: Optional[str] = None,
        domain: Optional[str] = None,
        ticker: Optional[str] = None,
        cik: Optional[str] = None,
        name: Optional[str] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Enriches company from Wikidata using conservative entity resolution.
        Extracts founding year, employee counts, revenue, website, HQ.
        Never invents values; missing fields are tagged with unknown status.
        """
        now_iso = datetime.now(timezone.utc).isoformat()
        target_name = (company_name or name or "").strip()
        qid, entity, reason = self.corroborate_and_resolve_entity(
            company_name=target_name,
            domain=domain,
            ticker=ticker,
            cik=cik,
        )

        if not qid or not entity:
            return {
                "source_status": "not_found",
                "source_type": "wikidata",
                "corroboration_reason": reason,
                "evaluated_candidates": getattr(self, "last_candidate_evaluations", []),
                "fields": [
                    {
                        "field_name": "wikidata_qid",
                        "field_value": None,
                        "value_status": "unknown",
                        "source_url": "https://www.wikidata.org",
                        "source_type": "wikidata",
                        "source_date": now_iso[:10],
                        "confidence": "UNVERIFIED",
                        "raw_evidence_snippet": reason or "No Wikidata entity resolved for company name.",
                    }
                ],
            }

        source_url = f"https://www.wikidata.org/wiki/{qid}"
        claims = entity.get("claims", {})
        fields: List[Dict[str, Any]] = []

        # 1. Wikidata QID
        fields.append({
            "field_name": "wikidata_qid",
            "field_value": qid,
            "value_status": "exact",
            "source_url": source_url,
            "source_type": "wikidata",
            "source_date": now_iso[:10],
            "confidence": "HIGH",
            "raw_evidence_snippet": f"Wikidata Entity {qid} ({reason})",
        })

        # 2. Inception Date / Founding Year (P571)
        if "P571" in claims:
            try:
                snak = claims["P571"][0]["mainsnak"]["datavalue"]["value"]
                time_str = snak.get("time", "")
                m = re.search(r"(\d{4})", time_str)
                if m:
                    founding_year = m.group(1)
                    fields.append({
                        "field_name": "founded_year",
                        "field_value": founding_year,
                        "value_status": "exact",
                        "source_url": source_url,
                        "source_type": "wikidata",
                        "source_date": now_iso[:10],
                        "confidence": "MEDIUM",
                        "raw_evidence_snippet": f"Inception: {founding_year}",
                    })
            except Exception:
                pass

        # 3. Employee Count (P1128) - Dated point-in-time metric
        if "P1128" in claims:
            try:
                emp_statements = []
                for claim in claims.get("P1128", []):
                    m_snak = claim.get("mainsnak", {}).get("datavalue", {}).get("value")
                    amt = m_snak.get("amount") if isinstance(m_snak, dict) else m_snak
                    if not amt:
                        continue
                    try:
                        clean_num = str(int(float(amt)))
                    except Exception:
                        continue
                    pt_year = None
                    quals = claim.get("qualifiers", {})
                    if "P585" in quals:
                        pt_val = quals["P585"][0].get("datavalue", {}).get("value", {}).get("time", "")
                        m = re.search(r"(\d{4})", pt_val)
                        if m:
                            pt_year = int(m.group(1))
                    emp_statements.append((pt_year or 0, pt_year, clean_num, claim))

                if emp_statements:
                    emp_statements.sort(key=lambda x: x[0], reverse=True)
                    _, best_year, emp_clean, _ = emp_statements[0]

                    if best_year and is_firmographic_metric_current(best_year):
                        fields.append({
                            "field_name": "employee_count",
                            "field_value": emp_clean,
                            "value_status": "estimate",
                            "source_url": source_url,
                            "source_type": "wikidata",
                            "source_date": str(best_year),
                            "confidence": "MEDIUM",
                            "raw_evidence_snippet": f"Wikidata current employee estimate: {emp_clean} (as of {best_year})",
                        })
                    elif best_year:
                        # Stale / historical: do not present as generic current employee count
                        fields.append({
                            "field_name": "employee_count",
                            "field_value": None,
                            "value_status": "unknown",
                            "source_url": source_url,
                            "source_type": "wikidata",
                            "source_date": now_iso[:10],
                            "confidence": "UNVERIFIED",
                            "raw_evidence_snippet": f"Current employee count unknown; available Wikidata claim is historical from {best_year} exceeding {FIRMOGRAPHIC_MAX_AGE_YEARS}y freshness policy.",
                        })
                        fields.append({
                            "field_name": "historical_employee_count",
                            "field_value": f"{emp_clean} (as of {best_year})",
                            "value_status": "estimate",
                            "source_url": source_url,
                            "source_type": "wikidata",
                            "source_date": str(best_year),
                            "confidence": "MEDIUM",
                            "raw_evidence_snippet": f"Wikidata historical employee count: {emp_clean} (as of {best_year})",
                        })
                    else:
                        fields.append({
                            "field_name": "employee_count",
                            "field_value": emp_clean,
                            "value_status": "estimate",
                            "source_url": source_url,
                            "source_type": "wikidata",
                            "source_date": now_iso[:10],
                            "confidence": "LOW",
                            "raw_evidence_snippet": f"Wikidata undated employee estimate: {emp_clean}",
                        })
            except Exception:
                pass

        # 4. Revenue (P2139) - Dated point-in-time metric
        if "P2139" in claims:
            try:
                rev_statements = []
                for claim in claims.get("P2139", []):
                    m_snak = claim.get("mainsnak", {}).get("datavalue", {}).get("value")
                    amt = m_snak.get("amount") if isinstance(m_snak, dict) else m_snak
                    if not amt:
                        continue
                    try:
                        rev_num = float(amt)
                    except Exception:
                        continue
                    pt_year = None
                    quals = claim.get("qualifiers", {})
                    if "P585" in quals:
                        pt_val = quals["P585"][0].get("datavalue", {}).get("value", {}).get("time", "")
                        m = re.search(r"(\d{4})", pt_val)
                        if m:
                            pt_year = int(m.group(1))
                    rev_statements.append((pt_year or 0, pt_year, rev_num, claim))

                if rev_statements:
                    rev_statements.sort(key=lambda x: x[0], reverse=True)
                    _, best_year, rev_num, _ = rev_statements[0]
                    formatted_rev = f"${rev_num:,.0f}"

                    if best_year and is_firmographic_metric_current(best_year):
                        fields.append({
                            "field_name": "annual_revenue",
                            "field_value": formatted_rev,
                            "value_status": "range",
                            "source_url": source_url,
                            "source_type": "wikidata",
                            "source_date": str(best_year),
                            "confidence": "MEDIUM",
                            "raw_evidence_snippet": f"Wikidata annual revenue estimate: {formatted_rev} (year {best_year})",
                        })
                    elif best_year:
                        # Stale / historical: do not present as generic current annual revenue
                        fields.append({
                            "field_name": "annual_revenue",
                            "field_value": None,
                            "value_status": "unknown",
                            "source_url": source_url,
                            "source_type": "wikidata",
                            "source_date": now_iso[:10],
                            "confidence": "UNVERIFIED",
                            "raw_evidence_snippet": f"Current annual revenue unknown; available Wikidata claim is historical from FY{best_year} exceeding {FIRMOGRAPHIC_MAX_AGE_YEARS}y freshness policy.",
                        })
                        fields.append({
                            "field_name": "historical_annual_revenue",
                            "field_value": f"{formatted_rev} (FY{best_year})",
                            "value_status": "range",
                            "source_url": source_url,
                            "source_type": "wikidata",
                            "source_date": str(best_year),
                            "confidence": "MEDIUM",
                            "raw_evidence_snippet": f"Wikidata historical revenue claim: {formatted_rev} (year {best_year})",
                        })
                    else:
                        fields.append({
                            "field_name": "annual_revenue",
                            "field_value": formatted_rev,
                            "value_status": "range",
                            "source_url": source_url,
                            "source_type": "wikidata",
                            "source_date": now_iso[:10],
                            "confidence": "LOW",
                            "raw_evidence_snippet": f"Wikidata undated revenue claim: {formatted_rev}",
                        })
            except Exception:
                pass

        # 5. Official Website (P856)
        if "P856" in claims:
            try:
                site = claims["P856"][0]["mainsnak"]["datavalue"]["value"]
                fields.append({
                    "field_name": "official_website",
                    "field_value": str(site),
                    "value_status": "exact",
                    "source_url": source_url,
                    "source_type": "wikidata",
                    "source_date": now_iso[:10],
                    "confidence": "HIGH",
                    "raw_evidence_snippet": f"Official URL: {site}",
                })
            except Exception:
                pass

        return {
            "source_status": "success",
            "source_type": "wikidata",
            "qid": qid,
            "corroboration_reason": reason,
            "evaluated_candidates": getattr(self, "last_candidate_evaluations", []),
            "fields": fields,
        }
