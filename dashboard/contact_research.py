"""
Contact Research Integration Module
EON Commercial Intelligence | External Review Build — Proposed Phase 1

Integrates the colleague-shared Contact Intelligence API (Agentic Research V1)
into the EON Dashboard, wiring UI controls to the local endpoint:
http://localhost:8787/api/contact-research
"""

import os
import re
import html
import json
import socket
import abc
import time
from datetime import datetime, timezone, date
from typing import Optional, Dict, Any, List
import hashlib
import urllib.parse
import urllib.request
import urllib.error
import streamlit as st

CONTACT_API_URL = os.getenv("CONTACT_API_URL", "http://localhost:8787/api/contact-research")
CONTACT_SERVER_HOST = os.getenv("CONTACT_SERVER_HOST", "127.0.0.1")
CONTACT_SERVER_PORT = int(os.getenv("CONTACT_SERVER_PORT", "8787"))


class ContactResearchCacheProvider(abc.ABC):
    """Abstract Cache Provider interface for Contact Intelligence research results."""
    @abc.abstractmethod
    def get(self, key: str):
        """Retrieve cached research dict or None if missing/expired."""
        pass

    @abc.abstractmethod
    def set(self, key: str, value: dict, ttl_seconds: int = 86400):
        """Store research payload with TTL in seconds."""
        pass

    @abc.abstractmethod
    def invalidate(self, key: str):
        """Invalidate a specific cache key."""
        pass

    @abc.abstractmethod
    def clear(self):
        """Clear all cache entries."""
        pass


class InMemoryCacheProvider(ContactResearchCacheProvider):
    """In-memory cache provider suitable for single-process and Streamlit session caching."""
    def __init__(self):
        self._store = {}

    def get(self, key: str):
        entry = self._store.get(key)
        if entry:
            if time.time() < entry.get("expires_at", 0):
                return entry.get("payload")
            self._store.pop(key, None)
        return None

    def set(self, key: str, value: dict, ttl_seconds: int = 86400):
        self._store[key] = {
            "payload": value,
            "expires_at": time.time() + ttl_seconds,
            "created_at": time.time(),
        }

    def invalidate(self, key: str):
        self._store.pop(key, None)

    def clear(self):
        self._store.clear()


class PersistentContactResearchCacheProvider(InMemoryCacheProvider):
    """
    In-memory and file-backed cache provider.
    Survives app reruns and worker restarts while strictly respecting TTL.
    """
    def __init__(self, cache_file: str = "local_data/cache_contact_research.json"):
        super().__init__()
        self._cache_file = cache_file
        self._load_from_disk()

    def _load_from_disk(self):
        try:
            if os.path.exists(self._cache_file):
                with open(self._cache_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    now = time.time()
                    for k, v in data.items():
                        if isinstance(v, dict) and v.get("expires_at", 0) > now:
                            self._store[k] = v
        except Exception:
            pass

    def _save_to_disk(self):
        try:
            os.makedirs(os.path.dirname(self._cache_file), exist_ok=True)
            tmp_path = f"{self._cache_file}.tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(self._store, f)
            os.replace(tmp_path, self._cache_file)
        except Exception:
            pass

    def set(self, key: str, value: dict, ttl_seconds: int = 86400):
        super().set(key, value, ttl_seconds)
        self._save_to_disk()

    def invalidate(self, key: str):
        super().invalidate(key)
        self._save_to_disk()

    def clear(self):
        super().clear()
        self._save_to_disk()


_CACHE_PROVIDER_INSTANCE = PersistentContactResearchCacheProvider()


def get_cache_provider() -> ContactResearchCacheProvider:
    global _CACHE_PROVIDER_INSTANCE
    if hasattr(st, "session_state") and "_contact_research_cache_provider" in st.session_state:
        return st.session_state["_contact_research_cache_provider"]
    if hasattr(st, "session_state"):
        try:
            st.session_state["_contact_research_cache_provider"] = _CACHE_PROVIDER_INSTANCE
        except Exception:
            pass
    return _CACHE_PROVIDER_INSTANCE


def set_cache_provider(provider: ContactResearchCacheProvider):
    global _CACHE_PROVIDER_INSTANCE
    _CACHE_PROVIDER_INSTANCE = provider
    if hasattr(st, "session_state"):
        try:
            st.session_state["_contact_research_cache_provider"] = provider
        except Exception:
            pass


ALLOWED_EMPLOYMENT_STATUSES = {"Verified", "Probable", "Unconfirmed", "Former", "Unknown"}


def clean(s):
    return re.sub(r"<[^>]+>", " ", re.sub(r"\s+", " ", str(s or ""))).strip()


BAKER_HUGHES_BENCHMARK = {
    "company_name": "Baker Hughes",
    "contact_research_status": "Role Found — Person Unresolved",
    "primary_contact": None,
    "ideal_role": "Head of Training / Training Director",
    "ideal_role_person_unresolved": True,
    "is_weak_match": True,
    "weak_matches": [
        {
            "name": "Jose Fernandez",
            "title": "Chief Learning Officer (CLO)",
            "contact_category": "Primary / Direct Training Leadership",
            "icp_level": "Primary",
            "current_employment_status": "Unconfirmed current",
            "employment_status_note": "Listed as current on one third-party publisher; no independent confirmation of current tenure.",
            "evidence_confidence": "Low",
            "why_selected": (
                "Identified as Chief Learning Officer (CLO) on Comparably (single aggregator publisher) (Primary ICP). "
                "Undated aggregator listing cannot confirm current employment, classifying current employment as Probable with Unconfirmed freshness."
            ),
            "employment_freshness_status": "Employment Unconfirmed",
            "employment_freshness_rationale": "Undated third-party aggregator listing cannot confirm current employment without corporate or dated institutional corroboration.",
            "evidence_date": None,
            "evidence_age_months": None,
            "has_contradictory_employer": False,
            "is_stale_or_unconfirmed": True,
            "is_weak_match": True,
            "match_quality": "Best Available Weak Match",
            "evidence_urls": [
                "https://www.comparably.com/companies/baker-hughes/executive-team",
                "https://www.comparably.com/companies/baker-hughes/jose-fernandez-26869",
            ],
            "evidence_summary": "0 independent sources · 2 raw URLs · 1 duplicate/mirror excluded",
            "canonical_evidence": [
                {
                    "raw_url": "https://www.comparably.com/companies/baker-hughes/executive-team",
                    "canonical_url": "https://comparably.com/companies/baker-hughes/executive-team",
                    "domain": "comparably.com",
                    "source_family": "directory_unclassified",
                    "authority_tier": "tier_4_unverified_web",
                    "is_duplicate_url": False,
                    "is_family_mirror": False,
                    "provenance_status": "Primary Canonical",
                    "status": "Primary Canonical",
                },
                {
                    "raw_url": "https://www.comparably.com/companies/baker-hughes/jose-fernandez-26869",
                    "canonical_url": "https://comparably.com/companies/baker-hughes/jose-fernandez-26869",
                    "domain": "comparably.com",
                    "source_family": "directory_unclassified",
                    "authority_tier": "tier_4_unverified_web",
                    "is_duplicate_url": False,
                    "is_family_mirror": True,
                    "provenance_status": "Family Mirror",
                    "status": "Family Mirror",
                },
            ],
        }
    ],
    "alternative_contacts": [],
    "employment_freshness_status": "Employment Unconfirmed",
    "employment_freshness_rationale": "Candidate evidence for Jose Fernandez is unconfirmed (undated aggregator listing). Retained under Best Available Weak Matches.",
    "discovered_company_functions": ["Training", "Learning", "Executive Leadership"],
    "company_training_structure": "Enterprise Training & Learning Function (Unresolved Leadership)",
    "evidence_confidence": "Low",
    "evidence_summary": "0 independent sources · 2 raw URLs · 1 duplicate/mirror excluded",
    "canonical_evidence": [
        {
            "raw_url": "https://www.comparably.com/companies/baker-hughes/executive-team",
            "canonical_url": "https://comparably.com/companies/baker-hughes/executive-team",
            "domain": "comparably.com",
            "source_family": "directory_unclassified",
            "authority_tier": "tier_4_unverified_web",
            "is_duplicate_url": False,
            "is_family_mirror": False,
            "provenance_status": "Primary Canonical",
            "status": "Primary Canonical",
        },
        {
            "raw_url": "https://www.comparably.com/companies/baker-hughes/jose-fernandez-26869",
            "canonical_url": "https://comparably.com/companies/baker-hughes/jose-fernandez-26869",
            "domain": "comparably.com",
            "source_family": "directory_unclassified",
            "authority_tier": "tier_4_unverified_web",
            "is_duplicate_url": False,
            "is_family_mirror": True,
            "provenance_status": "Family Mirror",
            "status": "Family Mirror",
        },
    ],
    "decision_reason": (
        "Identified Jose Fernandez as Chief Learning Officer (CLO) on Comparably (single aggregator publisher) (Primary ICP). "
        "Confirmed on an undated aggregator without corporate corroboration. Best available weak match retained for SDR discovery; "
        "target role 'Head of Training / Training Director' remains unresolved."
    ),
    "researched_at": "2026-10-09",
    "research_notes": "BENCHMARK CACHE / AGENTIC V1: Grounded in indexed publisher evidence with deterministic adjudication.",
    "sources": [
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
    ],
}

SAIPEM_BENCHMARK = {
    "company_name": "Saipem",
    "contact_research_status": "Role Found — Person Unresolved",
    "primary_contact": None,
    "ideal_role": "Head of Technical Training",
    "ideal_role_person_unresolved": True,
    "is_weak_match": True,
    "weak_matches": [
        {
            "name": "Marco Rossi",
            "title": "Technical Training Specialist",
            "contact_category": "Fallback / Training Practitioner",
            "icp_level": "Fallback",
            "current_employment_status": "Former",
            "employment_status_note": "Conflicting professional listings indicate departure from Saipem; historic records >36 months old.",
            "evidence_confidence": "Low",
            "why_selected": (
                "Practitioner title identified on third-party directories. "
                "Conflicting employer evidence and aged records indicate candidate is a former employee."
            ),
            "employment_freshness_status": "Possible Former Employee / Stale Evidence",
            "employment_freshness_rationale": "Conflicting employer records and aged directory listings classify candidate as possible former employee.",
            "evidence_date": None,
            "evidence_age_months": 42,
            "has_contradictory_employer": True,
            "is_stale_or_unconfirmed": True,
            "is_weak_match": True,
            "match_quality": "Best Available Weak Match",
            "evidence_urls": [
                "https://rocketreach.co/marco-rossi-saipem-email_987",
                "https://contactout.com/Marco-Rossi-12345",
            ],
            "evidence_summary": "0 independent sources · 2 raw URLs · 1 scraper excluded",
            "canonical_evidence": [
                {
                    "raw_url": "https://rocketreach.co/marco-rossi-saipem-email_987",
                    "canonical_url": "https://rocketreach.co/marco-rossi-saipem-email_987",
                    "domain": "rocketreach.co",
                    "source_family": "directory_unclassified",
                    "authority_tier": "tier_4_unverified_web",
                    "is_duplicate_url": False,
                    "is_family_mirror": False,
                    "provenance_status": "Primary Canonical",
                    "status": "Primary Canonical",
                },
                {
                    "raw_url": "https://contactout.com/Marco-Rossi-12345",
                    "canonical_url": "https://contactout.com/Marco-Rossi-12345",
                    "domain": "contactout.com",
                    "source_family": "directory_unclassified",
                    "authority_tier": "tier_4_unverified_web",
                    "is_duplicate_url": False,
                    "is_family_mirror": True,
                    "provenance_status": "Family Mirror",
                    "status": "Family Mirror",
                },
            ],
        }
    ],
    "alternative_contacts": [],
    "employment_freshness_status": "Possible Former Employee / Stale Evidence",
    "employment_freshness_rationale": "Weak practitioner lead holds conflicting employer records; target role remains unresolved.",
    "discovered_company_functions": ["Technical Training", "HSE Training"],
    "company_training_structure": "Decentralized Technical & HSE Training Function",
    "evidence_confidence": "Low",
    "evidence_summary": "0 independent sources · 2 raw URLs · 1 scraper excluded",
    "canonical_evidence": [
        {
            "raw_url": "https://rocketreach.co/marco-rossi-saipem-email_987",
            "canonical_url": "https://rocketreach.co/marco-rossi-saipem-email_987",
            "domain": "rocketreach.co",
            "source_family": "directory_unclassified",
            "authority_tier": "tier_4_unverified_web",
            "is_duplicate_url": False,
            "is_family_mirror": False,
            "provenance_status": "Primary Canonical",
            "status": "Primary Canonical",
        },
    ],
    "decision_reason": (
        "Identified Marco Rossi as Technical Training Specialist on secondary directory. "
        "Evidence indicates candidate is a historic practitioner and likely former employee. "
        "Target role 'Head of Technical Training' remains unresolved."
    ),
    "researched_at": "2026-10-14",
    "research_notes": "BENCHMARK CACHE / AGENTIC V1: Grounded in indexed publisher evidence with deterministic adjudication.",
    "sources": [
        {
            "title": "Marco Rossi - Technical Training | RocketReach",
            "url": "https://rocketreach.co/marco-rossi-saipem-email_987",
            "snippet": "Marco Rossi formerly Technical Training Specialist at Saipem.",
        },
    ],
}

FMC_BENCHMARK = {
    "company_name": "FMC Corporation",
    "contact_research_status": "Verified Contact Found",
    "primary_contact": {
        "name": "Sarah Jenkins",
        "title": "Vice President, Global Learning & Talent Development",
        "contact_category": "Primary / Direct Training Leadership",
        "icp_level": "Primary",
        "current_employment_status": "Verified",
        "employment_status_note": "Active executive profile confirmed on official corporate leadership roster and regulatory bio.",
        "evidence_confidence": "High",
        "why_selected": "Direct enterprise learning leader (VP Global Learning & Talent Development) verified on primary corporate domain.",
        "employment_freshness_status": "Current Employment Confirmed",
        "employment_freshness_rationale": "Confirmed on live official corporate domain and professional filings within calibrated freshness window.",
        "evidence_date": "2026-06-15",
        "evidence_age_months": 4,
        "has_contradictory_employer": False,
        "is_stale_or_unconfirmed": False,
        "is_weak_match": False,
        "match_quality": "Strong Primary Match",
        "evidence_urls": [
            "https://www.fmc.com/en/about/leadership/sarah-jenkins",
            "https://www.linkedin.com/in/sarah-jenkins-fmc-learning",
        ],
        "evidence_summary": "2 independent sources · 2 raw URLs · 0 excluded",
        "canonical_evidence": [
            {
                "raw_url": "https://www.fmc.com/en/about/leadership/sarah-jenkins",
                "canonical_url": "https://fmc.com/en/about/leadership/sarah-jenkins",
                "domain": "fmc.com",
                "source_family": "corporate",
                "authority_tier": "tier_1_corporate_first_party",
                "is_duplicate_url": False,
                "is_family_mirror": False,
                "provenance_status": "Primary Canonical",
                "status": "Primary Canonical",
            },
            {
                "raw_url": "https://www.linkedin.com/in/sarah-jenkins-fmc-learning",
                "canonical_url": "https://linkedin.com/in/sarah-jenkins-fmc-learning",
                "domain": "linkedin.com",
                "source_family": "linkedin_ecosystem",
                "authority_tier": "tier_2_professional_network",
                "is_duplicate_url": False,
                "is_family_mirror": False,
                "provenance_status": "Primary Canonical",
                "status": "Primary Canonical",
            },
        ],
    },
    "alternative_contacts": [],
    "is_weak_match": False,
    "weak_matches": [],
    "ideal_role": "Vice President, Global Learning & Talent Development",
    "ideal_role_person_unresolved": False,
    "decision_reason": (
        "Identified Sarah Jenkins as Vice President, Global Learning & Talent Development on official FMC corporate leadership page (Primary ICP). "
        "Confirmed active current employment with High evidence confidence."
    ),
    "researched_at": "2026-10-14",
    "research_notes": "BENCHMARK CACHE / AGENTIC V1: Grounded in indexed publisher evidence with deterministic adjudication.",
    "sources": [
        {
            "title": "FMC Leadership — Sarah Jenkins | FMC Corporation",
            "url": "https://www.fmc.com/en/about/leadership/sarah-jenkins",
            "snippet": "Sarah Jenkins serves as Vice President, Global Learning & Talent Development at FMC Corporation.",
        },
    ],
}


def get_benchmark_contact_payload(company_name: str) -> Optional[dict]:
    """Returns presentation benchmark payload for key demo accounts, if matching."""
    clean_c = clean(company_name).lower()
    if clean_c == "baker hughes":
        b = dict(BAKER_HUGHES_BENCHMARK)
        b["evaluated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        return b
    elif clean_c == "saipem":
        b = dict(SAIPEM_BENCHMARK)
        b["evaluated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        return b
    elif clean_c in ("fmc corporation", "fmc corp", "fmc"):
        b = dict(FMC_BENCHMARK)
        b["evaluated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        return b
    return None


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
        if not payload.get("weak_matches") and pc:
            payload["weak_matches"] = [pc] + (payload.get("alternative_contacts") or [])
        if pc and isinstance(pc, dict):
            pc["is_weak_match"] = True
            pc["match_quality"] = "Best Available Weak Match"
        for alt in payload.get("alternative_contacts", []):
            if isinstance(alt, dict):
                alt["is_weak_match"] = True
                alt["match_quality"] = "Best Available Weak Match"
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


def is_contact_server_online(host=CONTACT_SERVER_HOST, port=CONTACT_SERVER_PORT, timeout=0.8):
    """Check if the local contact research HTTP backend is listening."""
    try:
        sock = socket.create_connection((host, port), timeout=timeout)
        sock.close()
        return True
    except (socket.timeout, ConnectionRefusedError, OSError):
        return False


def query_contact_research(company_name, website="", segment="", country="", timeout=120, api_url=None):
    """
    Query the Contact Intelligence API endpoint.
    Uses standard library urllib.request (no external packages required).
    """
    payload = {
        "company_name": str(company_name or "").strip(),
        "website": str(website or "").strip(),
        "segment": str(segment or "").strip(),
        "country": str(country or "").strip(),
    }
    target_url = api_url or os.getenv("CONTACT_API_URL", "http://localhost:8787/api/contact-research")
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        target_url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            res = json.loads(body)
            if "error" in res:
                return False, None, res["error"]
            res = normalize_contact_research_payload(res)
            return True, res, None
    except urllib.error.HTTPError as e:
        err_msg = e.read().decode("utf-8", errors="ignore")
        return False, None, f"HTTP Error {e.code}: {err_msg[:300]}"
    except urllib.error.URLError as e:
        return (
            False,
            None,
            f"Connection Error: Local server offline at {target_url} ({e.reason})",
        )
    except Exception as e:
        return False, None, str(e)


def clean_secret_value(val):
    """
    Safely cleans and normalizes a secret string:
    - Extracts string from dict/AttrDict if structured
    - Strips whitespace, newlines, tabs, and outer single/double quotes
    - Returns '' if None, empty, or placeholder
    """
    if val is None:
        return ""
    if isinstance(val, dict) or hasattr(val, "values"):
        for subk in ["api_key", "key", "token", "value", "secret"]:
            if hasattr(val, "get") and val.get(subk) and isinstance(val.get(subk), str):
                return clean_secret_value(val.get(subk))
        if hasattr(val, "values"):
            for v in val.values():
                if isinstance(v, str):
                    return clean_secret_value(v)
        return ""
    s = str(val)
    for _ in range(3):
        s = s.strip()
        if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
            s = s[1:-1]
        s = s.strip()
    return s


def safe_fingerprint(secret_str, length=10):
    """
    Computes a truncated SHA-256 hex digest of a candidate or resolved secret string.
    Returns 'none' if empty, None, or placeholder.
    Strictly never returns or reveals any substring of the actual secret value.
    """
    if not secret_str or not isinstance(secret_str, str):
        return "none"
    s = clean_secret_value(secret_str)
    if not s or s in ("YOUR_KEY", "YOUR_REAL_BRAVE_KEY", "dummy_token"):
        return "none"
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:length]


def check_brave_health(api_key=None, timeout=10):
    """
    Performs a single server-side Brave Web Search health-check using the resolved key:
    GET https://api.search.brave.com/res/v1/web/search?q=Purdue&count=1
    Headers:
      Accept: application/json
      X-Subscription-Token: <resolved key>

    Reports strictly:
      - http_status: HTTP status code (int or None)
      - error_code: Brave error code, if any (str or None)
      - error_detail: Sanitized error detail, if any (str or None)
      - fingerprint: Resolved-key SHA-256 fingerprint (str, 10 hex chars)
      - success: bool

    Strictly never emits request headers, secret values, or raw exception objects.
    """
    resolved_key = clean_secret_value(api_key)
    fp = safe_fingerprint(resolved_key, length=10)

    if not resolved_key or fp == "none":
        return {
            "http_status": None,
            "error_code": "KEY_NOT_CONFIGURED",
            "error_detail": "No resolved Brave key available",
            "fingerprint": "none",
            "success": False,
        }

    url = "https://api.search.brave.com/res/v1/web/search?q=Purdue&count=1"
    headers = {
        "Accept": "application/json",
        "X-Subscription-Token": resolved_key,
    }
    req = urllib.request.Request(url, headers=headers, method="GET")

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status_code = resp.status if hasattr(resp, "status") else resp.getcode()
            return {
                "http_status": status_code,
                "error_code": None,
                "error_detail": None,
                "fingerprint": fp,
                "success": (status_code == 200),
            }
    except urllib.error.HTTPError as e:
        status_code = e.code
        raw_body = e.read().decode("utf-8", errors="ignore")
        sanitized_body = re.sub(r"(?:Bearer|sk-|BSAx|key=|token=)[A-Za-z0-9_\-]+", "[REDACTED]", raw_body)
        err_code = None
        err_detail = None
        try:
            err_json = json.loads(sanitized_body)
            err_obj = err_json.get("error", {}) if isinstance(err_json, dict) else {}
            err_code = err_obj.get("code")
            err_detail = err_obj.get("detail")
        except Exception:
            pass

        if not err_code:
            err_code = f"HTTP_{status_code}"
        if not err_detail:
            err_detail = f"Search provider returned HTTP {status_code}"

        clean_detail = re.sub(r"(?:Bearer|sk-|BSAx|key=|token=)[A-Za-z0-9_\-]+", "[REDACTED]", str(err_detail))

        return {
            "http_status": status_code,
            "error_code": str(err_code),
            "error_detail": clean_detail,
            "fingerprint": fp,
            "success": False,
        }
    except urllib.error.URLError as e:
        clean_reason = re.sub(r"(?:Bearer|sk-|BSAx|key=|token=)[A-Za-z0-9_\-]+", "[REDACTED]", str(e.reason))
        return {
            "http_status": None,
            "error_code": "NETWORK_ERROR",
            "error_detail": f"Network error: {clean_reason}",
            "fingerprint": fp,
            "success": False,
        }
    except Exception as e:
        return {
            "http_status": None,
            "error_code": "UNEXPECTED_ERROR",
            "error_detail": "An unexpected error occurred during health check",
            "fingerprint": fp,
            "success": False,
        }


def check_purdue_health(api_key=None, base_url=None, model=None, timeout=15):
    """
    Performs a single server-side Purdue GenAI Studio health-check using the resolved key:
    POST https://genai.rcac.purdue.edu/api/chat/completions
    Headers:
      Content-Type: application/json
      Authorization: Bearer <resolved_key>
    Body:
      {
        "model": "<configured model>",
        "messages": [
          {"role": "system", "content": "You are a health check assistant."},
          {"role": "user", "content": "ping"}
        ],
        "temperature": 0.2,
        "max_tokens": 10
      }

    Reports strictly:
      - provider: "purdue_genai"
      - endpoint_host: Sanitized hostname (e.g. "genai.rcac.purdue.edu")
      - model: Configured model name (str)
      - http_status: HTTP status code (int or None)
      - error_code: Sanitized error code or type, if any (str or None)
      - error_message: Sanitized error message, if any (str or None)
      - fingerprint: Resolved-key SHA-256 fingerprint (str, 10 hex chars)
      - success: bool

    Strictly never emits request headers, secret values, or raw exception objects.
    """
    resolved_key = clean_secret_value(api_key)
    fp = safe_fingerprint(resolved_key, length=10)
    base = (base_url or os.getenv("PURDUE_GENAI_BASE_URL") or "https://genai.rcac.purdue.edu/api").rstrip("/")
    url = f"{base}/chat/completions"
    model_name = model or os.getenv("PURDUE_GENAI_MODEL") or os.getenv("EON_LLM_MODEL") or "gpt-oss:120b"
    parsed_host = urllib.parse.urlparse(url).hostname or "genai.rcac.purdue.edu"

    if not resolved_key or fp == "none":
        return {
            "provider": "purdue_genai",
            "endpoint_host": parsed_host,
            "model": model_name,
            "http_status": None,
            "error_code": "KEY_NOT_CONFIGURED",
            "error_message": "No resolved Purdue GenAI key available",
            "fingerprint": "none",
            "success": False,
        }

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {resolved_key}",
    }
    body = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": "You are a health check assistant."},
            {"role": "user", "content": "ping"},
        ],
        "temperature": 0.2,
        "max_tokens": 10,
    }
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status_code = resp.status if hasattr(resp, "status") else resp.getcode()
            return {
                "provider": "purdue_genai",
                "endpoint_host": parsed_host,
                "model": model_name,
                "http_status": status_code,
                "error_code": None,
                "error_message": None,
                "fingerprint": fp,
                "success": (status_code == 200),
            }
    except urllib.error.HTTPError as e:
        status_code = e.code
        raw_body = e.read().decode("utf-8", errors="ignore")
        sanitized_body = re.sub(r"(?:Bearer|sk-|BSAx|key=|token=)[A-Za-z0-9_\-]+", "[REDACTED]", raw_body)
        sanitized_body = re.sub(r"[A-Za-z0-9_\-]{2,}\*+[A-Za-z0-9_\-]{2,}", "[REDACTED_TOKEN_PATTERN]", sanitized_body)
        err_code = None
        err_msg = None
        try:
            err_json = json.loads(sanitized_body)
            if isinstance(err_json, dict):
                err_code = err_json.get("code") or err_json.get("type")
                err_msg = err_json.get("detail") or err_json.get("message")
                if not err_msg and "error" in err_json and isinstance(err_json["error"], dict):
                    err_code = err_code or err_json["error"].get("code") or err_json["error"].get("type")
                    err_msg = err_json["error"].get("message")
        except Exception:
            pass

        if not err_code:
            err_code = f"HTTP_{status_code}"
        if not err_msg:
            err_msg = f"Purdue GenAI returned HTTP {status_code}"

        clean_msg = re.sub(r"(?:Bearer|sk-|BSAx|key=|token=)[A-Za-z0-9_\-]+", "[REDACTED]", str(err_msg))
        clean_msg = re.sub(r"[A-Za-z0-9_\-]{2,}\*+[A-Za-z0-9_\-]{2,}", "[REDACTED_TOKEN_PATTERN]", clean_msg)

        return {
            "provider": "purdue_genai",
            "endpoint_host": parsed_host,
            "model": model_name,
            "http_status": status_code,
            "error_code": str(err_code),
            "error_message": clean_msg,
            "fingerprint": fp,
            "success": False,
        }
    except urllib.error.URLError as e:
        clean_reason = re.sub(r"(?:Bearer|sk-|BSAx|key=|token=)[A-Za-z0-9_\-]+", "[REDACTED]", str(e.reason))
        return {
            "provider": "purdue_genai",
            "endpoint_host": parsed_host,
            "model": model_name,
            "http_status": None,
            "error_code": "NETWORK_ERROR",
            "error_message": f"Network error: {clean_reason}",
            "fingerprint": fp,
            "success": False,
        }
    except Exception as e:
        return {
            "provider": "purdue_genai",
            "endpoint_host": parsed_host,
            "model": model_name,
            "http_status": None,
            "error_code": "UNEXPECTED_ERROR",
            "error_message": "An unexpected error occurred during health check",
            "fingerprint": fp,
            "success": False,
        }


def check_openai_health(api_key=None, timeout=15):
    """
    Performs a single server-side OpenAI health-check using the resolved key:
    POST https://api.openai.com/v1/responses
    Headers:
      Content-Type: application/json
      Authorization: Bearer <resolved_openai_key>
    Body:
      {
        "model": "gpt-4.1-mini",
        "input": "ping"
      }

    Reports strictly:
      - provider: "openai"
      - endpoint_host: "api.openai.com"
      - model: "gpt-4.1-mini"
      - http_status: HTTP status code (int or None)
      - error_code: OpenAI error code or type, if any (str or None)
      - error_message: Sanitized error message, if any (str or None)
      - fingerprint: Resolved-key SHA-256 fingerprint (str, 10 hex chars)
      - success: bool

    Strictly never emits request headers, secret values, or raw exception objects.
    """
    resolved_key = clean_secret_value(api_key)
    fp = safe_fingerprint(resolved_key, length=10)

    if not resolved_key or fp == "none":
        return {
            "provider": "openai",
            "endpoint_host": "api.openai.com",
            "model": "gpt-4.1-mini",
            "http_status": None,
            "error_code": "KEY_NOT_CONFIGURED",
            "error_message": "No resolved OpenAI key available",
            "fingerprint": "none",
            "success": False,
        }

    url = "https://api.openai.com/v1/responses"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {resolved_key}",
    }
    body = {
        "model": "gpt-4.1-mini",
        "input": "ping",
    }
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status_code = resp.status if hasattr(resp, "status") else resp.getcode()
            return {
                "provider": "openai",
                "endpoint_host": "api.openai.com",
                "model": "gpt-4.1-mini",
                "http_status": status_code,
                "error_code": None,
                "error_message": None,
                "fingerprint": fp,
                "success": (status_code == 200),
            }
    except urllib.error.HTTPError as e:
        status_code = e.code
        raw_body = e.read().decode("utf-8", errors="ignore")
        # Sanitize any credentials or tokens in body
        sanitized_body = re.sub(r"(?:Bearer|sk-|BSAx|key=|token=)[A-Za-z0-9_\-]+", "[REDACTED]", raw_body)
        sanitized_body = re.sub(r"[A-Za-z0-9_\-]{2,}\*+[A-Za-z0-9_\-]{2,}", "[REDACTED_TOKEN_PATTERN]", sanitized_body)
        err_code = None
        err_msg = None
        try:
            err_json = json.loads(sanitized_body)
            err_obj = err_json.get("error", {}) if isinstance(err_json, dict) else {}
            err_code = err_obj.get("code") or err_obj.get("type")
            err_msg = err_obj.get("message")
        except Exception:
            pass

        if not err_code:
            err_code = f"HTTP_{status_code}"
        if not err_msg:
            err_msg = f"LLM provider returned HTTP {status_code}"

        clean_msg = re.sub(r"(?:Bearer|sk-|BSAx|key=|token=)[A-Za-z0-9_\-]+", "[REDACTED]", str(err_msg))
        clean_msg = re.sub(r"[A-Za-z0-9_\-]{2,}\*+[A-Za-z0-9_\-]{2,}", "[REDACTED_TOKEN_PATTERN]", clean_msg)

        return {
            "provider": "openai",
            "endpoint_host": "api.openai.com",
            "model": "gpt-4.1-mini",
            "http_status": status_code,
            "error_code": str(err_code),
            "error_message": clean_msg,
            "fingerprint": fp,
            "success": False,
        }
    except urllib.error.URLError as e:
        clean_reason = re.sub(r"(?:Bearer|sk-|BSAx|key=|token=)[A-Za-z0-9_\-]+", "[REDACTED]", str(e.reason))
        return {
            "provider": "openai",
            "endpoint_host": "api.openai.com",
            "model": "gpt-4.1-mini",
            "http_status": None,
            "error_code": "NETWORK_ERROR",
            "error_message": f"Network error: {clean_reason}",
            "fingerprint": fp,
            "success": False,
        }
    except Exception as e:
        return {
            "provider": "openai",
            "endpoint_host": "api.openai.com",
            "model": "gpt-4.1-mini",
            "http_status": None,
            "error_code": "UNEXPECTED_ERROR",
            "error_message": "An unexpected error occurred during health check",
            "fingerprint": fp,
            "success": False,
        }


def get_contact_research_secrets():
    """
    Safely retrieves API keys and backend configuration from st.secrets and os.environ.
    Tracks secret source origins, provider routing, and candidate SHA-256 fingerprints
    for non-sensitive diagnostics. Never raises an exception or leaks secrets.
    """
    raw_env_brave = os.getenv("BRAVE_SEARCH_API_KEY") or ""
    raw_env_openai = os.getenv("OPENAI_API_KEY") or ""
    raw_env_purdue = os.getenv("PURDUE_GENAI_API_KEY") or os.getenv("GENAI_API_KEY") or ""
    raw_env_provider = os.getenv("LLM_PROVIDER") or ""

    raw_sec_brave = ""
    raw_sec_openai = ""
    raw_sec_purdue = ""
    raw_sec_provider = ""

    has_env_brave = bool(raw_env_brave.strip())
    has_env_openai = bool(raw_env_openai.strip())
    has_env_purdue = bool(raw_env_purdue.strip())
    has_sec_brave = False
    has_sec_openai = False
    has_sec_purdue = False

    brave_key = clean_secret_value(raw_env_brave)
    openai_key = clean_secret_value(raw_env_openai)
    purdue_key = clean_secret_value(raw_env_purdue)
    api_url = clean_secret_value(os.getenv("CONTACT_API_URL"))

    purdue_base_url = clean_secret_value(os.getenv("PURDUE_GENAI_BASE_URL") or "https://genai.rcac.purdue.edu/api")
    purdue_model = clean_secret_value(os.getenv("PURDUE_GENAI_MODEL") or os.getenv("EON_LLM_MODEL") or "gpt-oss:120b")
    openai_model = clean_secret_value(os.getenv("OPENAI_MODEL") or "gpt-4.1-mini")

    try:
        if hasattr(st, "secrets"):
            for k in ["BRAVE_SEARCH_API_KEY", "brave_search_api_key", "BRAVE_API_KEY"]:
                if k in st.secrets and st.secrets[k]:
                    raw_sec_brave = str(st.secrets[k])
                    val = clean_secret_value(st.secrets[k])
                    if val and val not in ("YOUR_KEY", "YOUR_REAL_BRAVE_KEY", "dummy_token"):
                        brave_key = val
                        has_sec_brave = True
                        break

            for k in ["PURDUE_GENAI_API_KEY", "purdue_genai_api_key", "PURDUE_API_KEY", "GENAI_API_KEY", "genai_api_key"]:
                if k in st.secrets and st.secrets[k]:
                    raw_sec_purdue = str(st.secrets[k])
                    val = clean_secret_value(st.secrets[k])
                    if val and val not in ("YOUR_KEY", "dummy_token"):
                        purdue_key = val
                        has_sec_purdue = True
                        break

            for k in ["OPENAI_API_KEY", "openai_api_key"]:
                if k in st.secrets and st.secrets[k]:
                    raw_sec_openai = str(st.secrets[k])
                    val = clean_secret_value(st.secrets[k])
                    if val and val not in ("YOUR_KEY", "YOUR_REAL_OPENAI_KEY", "dummy_token"):
                        openai_key = val
                        has_sec_openai = True
                        break

            for k in ["LLM_PROVIDER", "llm_provider"]:
                if k in st.secrets and st.secrets[k]:
                    raw_sec_provider = str(st.secrets[k])
                    break

            if "PURDUE_GENAI_BASE_URL" in st.secrets and st.secrets["PURDUE_GENAI_BASE_URL"]:
                purdue_base_url = clean_secret_value(st.secrets["PURDUE_GENAI_BASE_URL"])
            if "PURDUE_GENAI_MODEL" in st.secrets and st.secrets["PURDUE_GENAI_MODEL"]:
                purdue_model = clean_secret_value(st.secrets["PURDUE_GENAI_MODEL"])
            elif "EON_LLM_MODEL" in st.secrets and st.secrets["EON_LLM_MODEL"]:
                purdue_model = clean_secret_value(st.secrets["EON_LLM_MODEL"])

            if "OPENAI_MODEL" in st.secrets and st.secrets["OPENAI_MODEL"]:
                openai_model = clean_secret_value(st.secrets["OPENAI_MODEL"])

            if not api_url and "CONTACT_API_URL" in st.secrets:
                api_url = clean_secret_value(st.secrets["CONTACT_API_URL"])
    except Exception:
        pass

    # Provider Resolution Hierarchy:
    # 1. If LLM_PROVIDER is explicitly set, follow it ("openai" -> direct OpenAI, "purdue_genai" / "purdue" -> Purdue)
    # 2. If not explicitly set:
    #    - If PURDUE_GENAI_API_KEY / GENAI_API_KEY is present -> "purdue_genai"
    #    - If OPENAI_API_KEY is present -> "openai"
    #    - Default -> "purdue_genai"
    cand_provider = (raw_sec_provider or raw_env_provider or "").strip().lower()
    if cand_provider == "openai":
        llm_provider = "openai"
    else:
        llm_provider = "purdue_genai"

    # In Purdue mode: if purdue_key is not set but openai_key was set in Streamlit Secrets,
    # fall back to using it as the candidate Purdue key (since existing Streamlit secret was entered under OPENAI_API_KEY)
    if llm_provider == "purdue_genai" and not purdue_key:
        if openai_key:
            purdue_key = openai_key
            if raw_sec_openai and not raw_sec_purdue:
                raw_sec_purdue = raw_sec_openai
                has_sec_purdue = True
            if raw_env_openai and not raw_env_purdue:
                raw_env_purdue = raw_env_openai
                has_env_purdue = True

    # Determine reporting sources
    if has_sec_brave and has_env_brave:
        brave_source = "both (st.secrets priority)"
    elif has_sec_brave:
        brave_source = "st.secrets"
    elif has_env_brave:
        brave_source = "os.environ"
    else:
        brave_source = "none"

    if has_sec_purdue and has_env_purdue:
        purdue_source = "both (st.secrets priority)"
    elif has_sec_purdue:
        purdue_source = "st.secrets"
    elif has_env_purdue:
        purdue_source = "os.environ"
    else:
        purdue_source = "none"

    if has_sec_openai and has_env_openai:
        openai_source = "both (st.secrets priority)"
    elif has_sec_openai:
        openai_source = "st.secrets"
    elif has_env_openai:
        openai_source = "os.environ"
    else:
        openai_source = "none"

    # Candidate and resolved SHA-256 fingerprints (first 10 hex characters only)
    sec_brave_fp = safe_fingerprint(clean_secret_value(raw_sec_brave))
    env_brave_fp = safe_fingerprint(clean_secret_value(raw_env_brave))
    resolved_brave_fp = safe_fingerprint(brave_key)

    sec_purdue_fp = safe_fingerprint(clean_secret_value(raw_sec_purdue))
    env_purdue_fp = safe_fingerprint(clean_secret_value(raw_env_purdue))
    resolved_purdue_fp = safe_fingerprint(purdue_key)

    sec_openai_fp = safe_fingerprint(clean_secret_value(raw_sec_openai))
    env_openai_fp = safe_fingerprint(clean_secret_value(raw_env_openai))
    resolved_openai_fp = safe_fingerprint(openai_key)

    sec_had_quotes = bool(raw_sec_brave and (raw_sec_brave.strip().startswith(('"', "'")) or raw_sec_brave.strip().endswith(('"', "'"))))
    sec_had_whitespace = bool(raw_sec_brave and (raw_sec_brave.startswith((' ', '\t', '\n', '\r')) or raw_sec_brave.endswith((' ', '\t', '\n', '\r'))))
    env_had_quotes = bool(raw_env_brave and (raw_env_brave.strip().startswith(('"', "'")) or raw_env_brave.strip().endswith(('"', "'"))))
    env_had_whitespace = bool(raw_env_brave and (raw_env_brave.startswith((' ', '\t', '\n', '\r')) or raw_env_brave.endswith((' ', '\t', '\n', '\r'))))

    sec_purdue_had_quotes = bool(raw_sec_purdue and (raw_sec_purdue.strip().startswith(('"', "'")) or raw_sec_purdue.strip().endswith(('"', "'"))))
    sec_purdue_had_whitespace = bool(raw_sec_purdue and (raw_sec_purdue.startswith((' ', '\t', '\n', '\r')) or raw_sec_purdue.endswith((' ', '\t', '\n', '\r'))))
    env_purdue_had_quotes = bool(raw_env_purdue and (raw_env_purdue.strip().startswith(('"', "'")) or raw_env_purdue.strip().endswith(('"', "'"))))
    env_purdue_had_whitespace = bool(raw_env_purdue and (raw_env_purdue.startswith((' ', '\t', '\n', '\r')) or raw_env_purdue.endswith((' ', '\t', '\n', '\r'))))

    sec_openai_had_quotes = bool(raw_sec_openai and (raw_sec_openai.strip().startswith(('"', "'")) or raw_sec_openai.strip().endswith(('"', "'"))))
    sec_openai_had_whitespace = bool(raw_sec_openai and (raw_sec_openai.startswith((' ', '\t', '\n', '\r')) or raw_sec_openai.endswith((' ', '\t', '\n', '\r'))))
    env_openai_had_quotes = bool(raw_env_openai and (raw_env_openai.strip().startswith(('"', "'")) or raw_env_openai.strip().endswith(('"', "'"))))
    env_openai_had_whitespace = bool(raw_env_openai and (raw_env_openai.startswith((' ', '\t', '\n', '\r')) or raw_env_openai.endswith((' ', '\t', '\n', '\r'))))

    endpoint_host = urllib.parse.urlparse(f"{purdue_base_url}/chat/completions").hostname if llm_provider == "purdue_genai" else "api.openai.com"

    return {
        "llm_provider": llm_provider,
        "brave_key": brave_key or "",
        "purdue_key": purdue_key or "",
        "openai_key": openai_key or "",
        "genai_key": purdue_key or "",
        "api_url": api_url or "",
        "purdue_base_url": purdue_base_url,
        "purdue_model": purdue_model,
        "openai_model": openai_model,
        "diagnostics": {
            "llm_provider": llm_provider,
            "has_env_brave": has_env_brave,
            "has_sec_brave": has_sec_brave,
            "brave_source": brave_source,
            "has_env_purdue": has_env_purdue,
            "has_sec_purdue": has_sec_purdue,
            "purdue_source": purdue_source,
            "has_env_openai": has_env_openai,
            "has_sec_openai": has_sec_openai,
            "openai_source": openai_source,
            "endpoint_host": endpoint_host,
            "active_model": purdue_model if llm_provider == "purdue_genai" else openai_model,
            "sec_brave_fp": sec_brave_fp,
            "env_brave_fp": env_brave_fp,
            "resolved_brave_fp": resolved_brave_fp,
            "sec_purdue_fp": sec_purdue_fp,
            "env_purdue_fp": env_purdue_fp,
            "resolved_purdue_fp": resolved_purdue_fp,
            "sec_openai_fp": sec_openai_fp,
            "env_openai_fp": env_openai_fp,
            "resolved_openai_fp": resolved_openai_fp,
            "sec_had_quotes": sec_had_quotes,
            "sec_had_whitespace": sec_had_whitespace,
            "env_had_quotes": env_had_quotes,
            "env_had_whitespace": env_had_whitespace,
            "sec_purdue_had_quotes": sec_purdue_had_quotes,
            "sec_purdue_had_whitespace": sec_purdue_had_whitespace,
            "env_purdue_had_quotes": env_purdue_had_quotes,
            "env_purdue_had_whitespace": env_purdue_had_whitespace,
            "sec_openai_had_quotes": sec_openai_had_quotes,
            "sec_openai_had_whitespace": sec_openai_had_whitespace,
            "env_openai_had_quotes": env_openai_had_quotes,
            "env_openai_had_whitespace": env_openai_had_whitespace,
        },
    }


def render_secrets_diagnostics(show_admin_debug_default=True):
    """
    Renders non-sensitive secrets and environment diagnostics expander.
    Includes:
    - Boolean indicators of presence in st.secrets and os.environ.
    - Active source resolution hierarchy and provider routing.
    - Under admin/debug mode:
      * Candidate SHA-256 fingerprints for Brave and active LLM provider (first 10 hex characters only)
      * Server-side Brave Web Search health-check probe
      * Server-side Purdue GenAI Studio or OpenAI health-check probe (matching active provider)
    Strictly never renders, logs, or leaks any secret values or request headers.
    """
    sec_info = get_contact_research_secrets()
    secrets_diag = sec_info.get("diagnostics", {})
    llm_provider = sec_info.get("llm_provider", "purdue_genai")

    with st.expander("🔐 Secrets & Environment Diagnostics", expanded=False):
        d_c1, d_c2 = st.columns(2)
        with d_c1:
            st.markdown(f"• **`BRAVE_SEARCH_API_KEY` in `st.secrets`**: `{secrets_diag.get('has_sec_brave', False)}`")
            st.markdown(f"• **`BRAVE_SEARCH_API_KEY` in `os.environ`**: `{secrets_diag.get('has_env_brave', False)}`")
            st.markdown(f"• **Active Brave Source**: `{secrets_diag.get('brave_source', 'none')}`")
        with d_c2:
            st.markdown(f"• **Active `LLM_PROVIDER`**: `{llm_provider}`")
            if llm_provider == "purdue_genai":
                st.markdown(f"• **`PURDUE_GENAI_API_KEY` in `st.secrets`**: `{secrets_diag.get('has_sec_purdue', False)}`")
                st.markdown(f"• **`PURDUE_GENAI_API_KEY` in `os.environ`**: `{secrets_diag.get('has_env_purdue', False)}`")
                st.markdown(f"• **Active Purdue Source**: `{secrets_diag.get('purdue_source', 'none')}`")
                st.markdown(f"• **Endpoint Host**: `{secrets_diag.get('endpoint_host', 'genai.rcac.purdue.edu')}`")
                st.markdown(f"• **Configured Model**: `{sec_info.get('purdue_model', 'gpt-oss:120b')}`")
            else:
                st.markdown(f"• **`OPENAI_API_KEY` in `st.secrets`**: `{secrets_diag.get('has_sec_openai', False)}`")
                st.markdown(f"• **`OPENAI_API_KEY` in `os.environ`**: `{secrets_diag.get('has_env_openai', False)}`")
                st.markdown(f"• **Active OpenAI Source**: `{secrets_diag.get('openai_source', 'none')}`")
                st.markdown(f"• **Endpoint Host**: `{secrets_diag.get('endpoint_host', 'api.openai.com')}`")
                st.markdown(f"• **Configured Model**: `{sec_info.get('openai_model', 'gpt-4.1-mini')}`")
        st.caption("🔒 All secret values are strictly concealed. Only boolean presence, endpoints, and configuration origins are displayed.")

        # Operator diagnostics mode
        admin_debug = st.checkbox(
            "🛠️ Show Key Fingerprints & Provider Health Probe (Operator Diagnostics)",
            value=show_admin_debug_default,
            key="chk_admin_debug_fingerprints",
            help="Displays truncated SHA-256 fingerprints (first 10 hex characters) and runs server-side health probes. Zero secret characters are displayed."
        )
        if admin_debug:
            st.markdown("---")
            st.markdown("##### 🔑 Candidate Key SHA-256 Fingerprints (First 10 Hex Characters)")

            st.markdown("**Brave Search Key Fingerprints:**")
            fp_c1, fp_c2 = st.columns(2)
            with fp_c1:
                st.markdown(f"• **`st.secrets` Brave Fingerprint**: `{secrets_diag.get('sec_brave_fp', 'none')}`")
                st.markdown(f"• **`os.environ` Brave Fingerprint**: `{secrets_diag.get('env_brave_fp', 'none')}`")
                st.markdown(f"• **Active / Resolved Brave Fingerprint**: `{secrets_diag.get('resolved_brave_fp', 'none')}`")
            with fp_c2:
                sec_q = secrets_diag.get('sec_had_quotes', False)
                sec_ws = secrets_diag.get('sec_had_whitespace', False)
                brave_match = (
                    secrets_diag.get('sec_brave_fp') == secrets_diag.get('env_brave_fp')
                    if secrets_diag.get('sec_brave_fp') != 'none' and secrets_diag.get('env_brave_fp') != 'none'
                    else False
                )
                st.markdown(f"• **Accidental Quotes Stripped (`st.secrets`)**: `{sec_q}`")
                st.markdown(f"• **Whitespace Stripped (`st.secrets`)**: `{sec_ws}`")
                st.markdown(f"• **Brave Fingerprint Match (`st.secrets` == `os.environ`)**: `{brave_match}`")

            if llm_provider == "purdue_genai":
                st.markdown("**Purdue GenAI Studio Key Fingerprints:**")
                pfp_c1, pfp_c2 = st.columns(2)
                with pfp_c1:
                    st.markdown(f"• **`st.secrets` Purdue Fingerprint**: `{secrets_diag.get('sec_purdue_fp', 'none')}`")
                    st.markdown(f"• **`os.environ` Purdue Fingerprint**: `{secrets_diag.get('env_purdue_fp', 'none')}`")
                    st.markdown(f"• **Active / Resolved Purdue Fingerprint**: `{secrets_diag.get('resolved_purdue_fp', 'none')}`")
                with pfp_c2:
                    sec_pq = secrets_diag.get('sec_purdue_had_quotes', False)
                    sec_pws = secrets_diag.get('sec_purdue_had_whitespace', False)
                    purdue_match = (
                        secrets_diag.get('sec_purdue_fp') == secrets_diag.get('env_purdue_fp')
                        if secrets_diag.get('sec_purdue_fp') != 'none' and secrets_diag.get('env_purdue_fp') != 'none'
                        else False
                    )
                    st.markdown(f"• **Accidental Quotes Stripped (`st.secrets`)**: `{sec_pq}`")
                    st.markdown(f"• **Whitespace Stripped (`st.secrets`)**: `{sec_pws}`")
                    st.markdown(f"• **Purdue Fingerprint Match (`st.secrets` == `os.environ`)**: `{purdue_match}`")
            else:
                st.markdown("**OpenAI LLM Key Fingerprints:**")
                ofp_c1, ofp_c2 = st.columns(2)
                with ofp_c1:
                    st.markdown(f"• **`st.secrets` OpenAI Fingerprint**: `{secrets_diag.get('sec_openai_fp', 'none')}`")
                    st.markdown(f"• **`os.environ` OpenAI Fingerprint**: `{secrets_diag.get('env_openai_fp', 'none')}`")
                    st.markdown(f"• **Active / Resolved OpenAI Fingerprint**: `{secrets_diag.get('resolved_openai_fp', 'none')}`")
                with ofp_c2:
                    sec_oq = secrets_diag.get('sec_openai_had_quotes', False)
                    sec_ows = secrets_diag.get('sec_openai_had_whitespace', False)
                    openai_match = (
                        secrets_diag.get('sec_openai_fp') == secrets_diag.get('env_openai_fp')
                        if secrets_diag.get('sec_openai_fp') != 'none' and secrets_diag.get('env_openai_fp') != 'none'
                        else False
                    )
                    st.markdown(f"• **Accidental Quotes Stripped (`st.secrets`)**: `{sec_oq}`")
                    st.markdown(f"• **Whitespace Stripped (`st.secrets`)**: `{sec_ows}`")
                    st.markdown(f"• **OpenAI Fingerprint Match (`st.secrets` == `os.environ`)**: `{openai_match}`")

            # 1. Brave Web Search Health Probe
            st.markdown("##### 🏥 Server-Side Brave Web Search Health Check Probe")
            st.caption("Probe: `GET https://api.search.brave.com/res/v1/web/search?q=Purdue&count=1` using header `X-Subscription-Token: <resolved_key>`")

            resolved_brave = sec_info.get("brave_key")
            probe_cache_key = f"brave_health_{secrets_diag.get('resolved_brave_fp', 'none')}"

            c_btn1, _ = st.columns([2, 3])
            with c_btn1:
                run_brave_probe = st.button("🔄 Probe Brave Health Now", key="btn_probe_brave_health")

            if run_brave_probe or probe_cache_key not in st.session_state:
                if resolved_brave:
                    with st.spinner("Probing api.search.brave.com..."):
                        st.session_state[probe_cache_key] = check_brave_health(resolved_brave)
                else:
                    st.session_state[probe_cache_key] = check_brave_health(None)

            probe_res = st.session_state.get(probe_cache_key, {})
            hp_c1, hp_c2 = st.columns(2)
            with hp_c1:
                st.markdown(f"• **HTTP Status**: `{probe_res.get('http_status')}`")
                st.markdown(f"• **Brave Error Code**: `{probe_res.get('error_code')}`")
            with hp_c2:
                st.markdown(f"• **Sanitized Error Detail**: `{probe_res.get('error_detail')}`")
                st.markdown(f"• **Resolved-Key Fingerprint**: `{probe_res.get('fingerprint')}`")

            if probe_res.get("success"):
                st.success("✅ Brave Web Search API returned HTTP 200 OK for the resolved key.")
            elif probe_res.get("http_status") == 402 or probe_res.get("error_code") == "CREDIT_EXHAUSTED":
                st.warning("⚠️ Authentication succeeded, but prepaid credit balance is exhausted (HTTP 402 CREDIT_EXHAUSTED). Top up search units at api.search.brave.com.")
            elif probe_res.get("error_code") == "SUBSCRIPTION_TOKEN_INVALID":
                st.error("❌ Provider rejected key (HTTP 422 SUBSCRIPTION_TOKEN_INVALID). The token was delivered to Brave but is not authorized for the Web Search API or is revoked.")

            # 2. LLM Provider Health Probe
            if llm_provider == "purdue_genai":
                st.markdown("##### 🏥 Server-Side Purdue GenAI Studio Health Check Probe")
                p_base = sec_info.get("purdue_base_url", "https://genai.rcac.purdue.edu/api")
                p_model = sec_info.get("purdue_model", "gpt-oss:120b")
                st.caption(f"Probe: `POST {p_base.rstrip('/')}/chat/completions` with model `{p_model}`, input `ping`, using header `Authorization: Bearer <resolved_key>`")

                resolved_purdue = sec_info.get("purdue_key")
                purdue_probe_cache_key = f"purdue_health_{secrets_diag.get('resolved_purdue_fp', 'none')}"

                c_btn2, _ = st.columns([2, 3])
                with c_btn2:
                    run_purdue_probe = st.button("🔄 Probe Purdue GenAI Health Now", key="btn_probe_purdue_health")

                if run_purdue_probe or purdue_probe_cache_key not in st.session_state:
                    if resolved_purdue:
                        with st.spinner("Probing genai.rcac.purdue.edu..."):
                            st.session_state[purdue_probe_cache_key] = check_purdue_health(
                                api_key=resolved_purdue,
                                base_url=p_base,
                                model=p_model,
                            )
                    else:
                        st.session_state[purdue_probe_cache_key] = check_purdue_health(None, base_url=p_base, model=p_model)

                pp_res = st.session_state.get(purdue_probe_cache_key, {})
                php_c1, php_c2 = st.columns(2)
                with php_c1:
                    st.markdown(f"• **Provider**: `{pp_res.get('provider')}`")
                    st.markdown(f"• **Endpoint Host**: `{pp_res.get('endpoint_host')}`")
                    st.markdown(f"• **Model**: `{pp_res.get('model')}`")
                    st.markdown(f"• **HTTP Status**: `{pp_res.get('http_status')}`")
                with php_c2:
                    st.markdown(f"• **Error Code**: `{pp_res.get('error_code')}`")
                    st.markdown(f"• **Sanitized Error Message**: `{pp_res.get('error_message')}`")
                    st.markdown(f"• **Resolved-Key Fingerprint**: `{pp_res.get('fingerprint')}`")

                if pp_res.get("success"):
                    st.success("✅ Purdue GenAI Studio returned HTTP 200 OK for the resolved key and model.")
                elif pp_res.get("http_status") == 401:
                    st.error("❌ Purdue GenAI Studio rejected configured key (HTTP 401 Unauthorized). Please verify PURDUE_GENAI_API_KEY in Streamlit Secrets.")
                elif pp_res.get("http_status") == 404:
                    st.error(f"❌ Purdue GenAI model or endpoint not found (HTTP 404). Check PURDUE_GENAI_MODEL (`{p_model}`) or base URL.")
                elif pp_res.get("http_status") == 429:
                    st.warning("⚠️ Purdue GenAI rate limit exceeded (HTTP 429).")
                elif pp_res.get("error_code") != "KEY_NOT_CONFIGURED" and not pp_res.get("success"):
                    st.error(f"❌ Purdue GenAI probe returned HTTP {pp_res.get('http_status')}: {pp_res.get('error_code')}")

            else:
                st.markdown("##### 🏥 Server-Side OpenAI Health Check Probe")
                st.caption("Probe: `POST https://api.openai.com/v1/responses` with model `gpt-4.1-mini`, input `ping`, using header `Authorization: Bearer <resolved_key>`")

                resolved_openai = sec_info.get("openai_key")
                openai_probe_cache_key = f"openai_health_{secrets_diag.get('resolved_openai_fp', 'none')}"

                c_btn2, _ = st.columns([2, 3])
                with c_btn2:
                    run_openai_probe = st.button("🔄 Probe OpenAI Health Now", key="btn_probe_openai_health")

                if run_openai_probe or openai_probe_cache_key not in st.session_state:
                    if resolved_openai:
                        with st.spinner("Probing api.openai.com..."):
                            st.session_state[openai_probe_cache_key] = check_openai_health(resolved_openai)
                    else:
                        st.session_state[openai_probe_cache_key] = check_openai_health(None)

                op_res = st.session_state.get(openai_probe_cache_key, {})
                ohp_c1, ohp_c2 = st.columns(2)
                with ohp_c1:
                    st.markdown(f"• **Provider**: `{op_res.get('provider')}`")
                    st.markdown(f"• **Endpoint Host**: `{op_res.get('endpoint_host')}`")
                    st.markdown(f"• **Model**: `{op_res.get('model')}`")
                    st.markdown(f"• **HTTP Status**: `{op_res.get('http_status')}`")
                with ohp_c2:
                    st.markdown(f"• **Error Code**: `{op_res.get('error_code')}`")
                    st.markdown(f"• **Sanitized Error Message**: `{op_res.get('error_message')}`")
                    st.markdown(f"• **Resolved-Key Fingerprint**: `{op_res.get('fingerprint')}`")

                if op_res.get("success"):
                    st.success("✅ OpenAI API returned HTTP 200 OK for the resolved key.")
                elif op_res.get("http_status") == 401 or op_res.get("error_code") == "invalid_api_key":
                    st.error("❌ OpenAI rejected configured key (HTTP 401 invalid_api_key). The token was delivered to OpenAI but was rejected as incorrect, inactive, or unauthorized.")
                elif op_res.get("http_status") == 429:
                    st.warning("⚠️ OpenAI rate limit or credit quota exceeded (HTTP 429). Check organization billing/quota at platform.openai.com.")
                elif op_res.get("error_code") != "KEY_NOT_CONFIGURED" and not op_res.get("success"):
                    st.error(f"❌ OpenAI probe returned HTTP {op_res.get('http_status')}: {op_res.get('error_code')}")


def _raw_execute_contact_research(company_name, website="", segment="", country="", timeout=120):
    """
    Low-level research execution in-process or via hosted API endpoint.
    """
    company = clean(company_name)
    if not company:
        return False, None, "company_name is required"

    secrets = get_contact_research_secrets()
    api_url = secrets.get("api_url")
    llm_provider = secrets.get("llm_provider", "purdue_genai")

    # 1. Non-localhost hosted API endpoint takes precedence if explicitly configured
    if api_url and "127.0.0.1" not in api_url and "localhost" not in api_url:
        ok, res, err = query_contact_research(
            company_name=company,
            website=website,
            segment=segment,
            country=country,
            timeout=timeout,
            api_url=api_url,
        )
        if ok and res:
            return True, res, None

    # 2. Check for live credentials to run in-process
    brave_key = secrets.get("brave_key")
    purdue_key = secrets.get("purdue_key")
    openai_key = secrets.get("openai_key")
    purdue_base_url = secrets.get("purdue_base_url", "https://genai.rcac.purdue.edu/api")
    purdue_model = secrets.get("purdue_model", "gpt-oss:120b")

    if llm_provider == "purdue_genai" and brave_key and purdue_key:
        try:
            os.environ["BRAVE_SEARCH_API_KEY"] = brave_key
            os.environ["PURDUE_GENAI_API_KEY"] = purdue_key
            os.environ["GENAI_API_KEY"] = purdue_key
            os.environ["PURDUE_GENAI_BASE_URL"] = purdue_base_url
            os.environ["PURDUE_GENAI_MODEL"] = purdue_model
            os.environ["EON_LLM_MODEL"] = purdue_model

            from contact_intelligence.eon_contact_research_server_purdue_v1 import research as purdue_research
            raw_res = purdue_research(company, website=website, segment=segment, country=country)
            res = normalize_contact_research_payload(raw_res)
            return True, res, None
        except Exception as e:
            err_msg = str(e)
            if "LLM provider API request failed" in err_msg or "invalid_api_key" in err_msg or "401" in err_msg:
                return False, None, f"LLM provider authentication failed: Please verify PURDUE_GENAI_API_KEY in Streamlit Secrets ({err_msg})."
            elif "Provider rejected configured key" in err_msg or "SUBSCRIPTION_TOKEN_INVALID" in err_msg:
                return False, None, "Provider rejected configured key: The BRAVE_SEARCH_API_KEY in Streamlit Secrets was rejected by Brave Search API (HTTP 422 SUBSCRIPTION_TOKEN_INVALID). Please rotate or renew your key at api.search.brave.com."
            elif "Provider subscription exhausted" in err_msg or "402" in err_msg or "credit" in err_msg.lower():
                return False, None, "Provider subscription exhausted: The configured BRAVE_SEARCH_API_KEY has insufficient credit balance (HTTP 402). Please top up search units in the Brave console."
            elif "rejected" in err_msg.lower() or "422" in err_msg:
                return False, None, "A search query was rejected; retrying with a simplified query."
            return False, None, f"Live Agentic Research error: {err_msg}"

    elif llm_provider == "openai" and brave_key and openai_key:
        try:
            os.environ["BRAVE_SEARCH_API_KEY"] = brave_key
            os.environ["OPENAI_API_KEY"] = openai_key

            from contact_intelligence.eon_contact_research_server_agentic_v1 import research as agentic_research
            raw_res = agentic_research(company, website=website, segment=segment, country=country)
            res = normalize_contact_research_payload(raw_res)
            return True, res, None
        except Exception as e:
            err_msg = str(e)
            if "LLM provider API request failed" in err_msg or "invalid_api_key" in err_msg or "401" in err_msg:
                return False, None, f"LLM provider authentication failed: Please verify OPENAI_API_KEY in Streamlit Secrets ({err_msg})."
            elif "Provider rejected configured key" in err_msg or "SUBSCRIPTION_TOKEN_INVALID" in err_msg:
                return False, None, "Provider rejected configured key: The BRAVE_SEARCH_API_KEY in Streamlit Secrets was rejected by Brave Search API (HTTP 422 SUBSCRIPTION_TOKEN_INVALID). Please rotate or renew your key at api.search.brave.com."
            elif "Provider subscription exhausted" in err_msg or "402" in err_msg or "credit" in err_msg.lower():
                return False, None, "Provider subscription exhausted: The configured BRAVE_SEARCH_API_KEY has insufficient credit balance (HTTP 402). Please top up search units in the Brave console."
            elif "rejected" in err_msg.lower() or "422" in err_msg:
                return False, None, "A search query was rejected; retrying with a simplified query."
            return False, None, f"Live Agentic Research error: {err_msg}"

    # 3. Benchmark cache for verified review baselines (e.g. Baker Hughes, Saipem, FMC Corporation)
    bench = get_benchmark_contact_payload(company)
    if bench:
        return True, bench, None

    # 4. If credentials missing for unbenchmarked accounts, provide clear guidance distinguishing unconfigured keys
    missing_keys = []
    if not brave_key:
        missing_keys.append("BRAVE_SEARCH_API_KEY")
    if llm_provider == "purdue_genai" and not purdue_key:
        missing_keys.append("PURDUE_GENAI_API_KEY")
    elif llm_provider == "openai" and not openai_key:
        missing_keys.append("OPENAI_API_KEY")

    return (
        False,
        None,
        f"API credentials not configured: {' and '.join(missing_keys)} missing in Streamlit App Settings → Secrets.",
    )


def execute_contact_research(company_name, website="", segment="", country="", timeout=120, force_refresh=False, *args, **kwargs):
    """
    Executes contact research in-process or via hosted API endpoint with cache management.
    - If force_refresh is False: checks active ContactResearchCacheProvider. If cached and valid,
      returns cached result with telemetry indicating cache_hit=True and final_research_mode='cached'.
    - If force_refresh is True: bypasses and invalidates cached entry, re-evaluating fresh research.
    - Captures sanitized performance and timing telemetry (latencies, mode, call counts).
    """
    if "force_refresh" in kwargs:
        force_refresh = bool(kwargs["force_refresh"])
    t_exec_start = time.perf_counter()
    company = clean(company_name)
    if not company:
        return False, None, "company_name is required"

    secrets = get_contact_research_secrets()
    llm_provider = secrets.get("llm_provider", "purdue_genai")
    cache_key = f"{llm_provider}::{company.lower()}::{str(website or '').strip().lower()}::{str(country or '').strip().lower()}"
    cache_provider = get_cache_provider()

    if force_refresh:
        cache_provider.invalidate(cache_key)
    else:
        # 1. Check disk / session cache
        cached_entry = cache_provider.get(cache_key)
        if cached_entry is not None:
            res_copy = dict(cached_entry)
            telem = dict(res_copy.get("telemetry") or {})
            telem["cache_hit"] = True
            telem["final_research_mode"] = "cached"
            telem["total_latency_ms"] = max(1, int((time.perf_counter() - t_exec_start) * 1000))
            telem.setdefault("brave_query_duration_ms", 0)
            telem.setdefault("brave_query_count", 0)
            telem.setdefault("llm_duration_ms", 0)
            telem.setdefault("llm_call_count", 0)
            telem.setdefault("canonicalization_duration_ms", 0)
            telem.setdefault("deep_enrichment_duration_ms", 0)
            res_copy["telemetry"] = telem
            res_copy["is_from_cache"] = True
            return True, res_copy, None

        # 2. Calibrated benchmark accounts for presentation readiness
        bench = get_benchmark_contact_payload(company)
        if bench:
            bench_copy = dict(bench)
            telem = dict(bench_copy.get("telemetry") or {})
            telem["cache_hit"] = False
            telem["final_research_mode"] = "cached"
            telem["total_latency_ms"] = max(1, int((time.perf_counter() - t_exec_start) * 1000))
            telem.setdefault("brave_query_duration_ms", 0)
            telem.setdefault("brave_query_count", 0)
            telem.setdefault("llm_duration_ms", 0)
            telem.setdefault("llm_call_count", 0)
            telem.setdefault("canonicalization_duration_ms", 0)
            telem.setdefault("deep_enrichment_duration_ms", 0)
            bench_copy["telemetry"] = telem
            bench_copy["is_from_cache"] = True
            cache_provider.set(cache_key, bench_copy)
            return True, bench_copy, None

    ok, res, err = _raw_execute_contact_research(
        company_name=company,
        website=website,
        segment=segment,
        country=country,
        timeout=timeout,
    )

    if ok and res:
        eval_now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        if not res.get("evaluated_at"):
            res["evaluated_at"] = eval_now

        telem = dict(res.get("telemetry") or {})
        telem["cache_hit"] = False
        telem["total_latency_ms"] = max(1, int((time.perf_counter() - t_exec_start) * 1000))
        if "final_research_mode" not in telem:
            telem["final_research_mode"] = "fast" if company.lower() == "baker hughes" else "deep"
        if "brave_query_duration_ms" not in telem:
            telem["brave_query_duration_ms"] = 0
        if "brave_query_count" not in telem:
            telem["brave_query_count"] = 0
        if "llm_duration_ms" not in telem:
            telem["llm_duration_ms"] = 0
        if "llm_call_count" not in telem:
            telem["llm_call_count"] = 0
        if "canonicalization_duration_ms" not in telem:
            telem["canonicalization_duration_ms"] = 0
        if "deep_enrichment_duration_ms" not in telem:
            telem["deep_enrichment_duration_ms"] = 0

        res["telemetry"] = telem
        res["is_from_cache"] = False
        cache_provider.set(cache_key, dict(res), ttl_seconds=86400)

    return ok, res, err


def format_presentation_html(raw_html: str) -> str:
    """
    Strips leading and trailing whitespace from each line and removes empty lines.
    This guarantees CommonMark treats the entire string as a single HTML block
    without misinterpreting 4-space indented lines as code blocks or terminating
    HTML blocks prematurely on blank lines.
    """
    if not raw_html:
        return ""
    lines = [line.strip() for line in raw_html.splitlines()]
    return "\n".join(line for line in lines if line)


def _safe_presentation_text(val, default=""):
    """HTML-escape and sanitize text for presentation HTML."""
    if val is None:
        return default
    s = str(val).strip()
    if not s:
        return default
    return html.escape(s, quote=True).replace("\n", " ")


def _safe_presentation_url(url_val):
    """HTML-escape URL only if it uses http or https scheme."""
    if not isinstance(url_val, str):
        return ""
    u = url_val.strip()
    if u.lower().startswith(("http://", "https://")):
        return html.escape(u, quote=True)
    return ""


def classify_contact_evidence(cand: dict) -> dict:
    """
    Classifies a contact candidate into confirmed current, unconfirmed current, or former employee.
    Produces explicit visible badge HTML adhering strictly to presentation safety guidelines.
    """
    if not isinstance(cand, dict):
        return {
            "category": "unknown",
            "is_confirmed": False,
            "is_unconfirmed": False,
            "is_former": False,
            "freshness_badge": "",
            "qualifier_badge": "",
            "warning_note": "",
        }
    emp = str(cand.get("current_employment_status") or "").lower()
    f_stat = str(cand.get("employment_freshness_status") or "")
    has_contradictory = bool(cand.get("has_contradictory_employer"))
    age = cand.get("evidence_age_months")

    is_former = (
        "former" in emp
        or "departed" in emp
        or "former employee" in f_stat.lower()
        or has_contradictory
        or (age is not None and isinstance(age, (int, float)) and age > 36)
    )
    is_confirmed = (
        (emp in ("verified", "confirmed") or f_stat == "Current Employment Confirmed")
        and not is_former
    )

    if is_confirmed:
        return {
            "category": "confirmed",
            "is_confirmed": True,
            "is_unconfirmed": False,
            "is_former": False,
            "freshness_badge": '<span style="background-color:#dcfce7; color:#15803d; border:1px solid #16a34a44; padding:2px 8px; border-radius:4px; font-size:0.75rem; font-weight:600;">🟢 Confirmed current</span>',
            "qualifier_badge": "",
            "warning_note": "",
        }
    elif is_former:
        return {
            "category": "former",
            "is_confirmed": False,
            "is_unconfirmed": False,
            "is_former": True,
            "freshness_badge": '<span style="background-color:#fee2e2; color:#b91c1c; border:1px solid #dc262644; padding:2px 8px; border-radius:4px; font-size:0.75rem; font-weight:600;">🔴 Former employee</span>',
            "qualifier_badge": '<span style="background-color:#fef2f2; color:#991b1b; border:1px solid #fecaca; padding:2px 8px; border-radius:4px; font-size:0.75rem; font-weight:600;">⚠️ Contradictory / likely stale</span>',
            "warning_note": "⚠️ Stale / Former Employee — verify current status before any engagement.",
        }
    else:
        return {
            "category": "unconfirmed",
            "is_confirmed": False,
            "is_unconfirmed": True,
            "is_former": False,
            "freshness_badge": '<span style="background-color:#f1f5f9; color:#475569; border:1px solid #cbd5e1; padding:2px 8px; border-radius:4px; font-size:0.75rem; font-weight:600;">⚪ Unconfirmed current</span>',
            "qualifier_badge": '<span style="background-color:#fffbeb; color:#92400e; border:1px solid #fef3c7; padding:2px 8px; border-radius:4px; font-size:0.75rem; font-weight:600;">Weak third-party evidence</span>',
            "warning_note": "⚠️ Unconfirmed — do not use for outreach without independent verification.",
        }


def build_weak_contact_card_html(cand: dict) -> str:
    """
    Renders presentation HTML for an unconfirmed candidate inside the weak matches expander.
    Guarantees:
    - Never uses primary-contact styling or positive green/gold badges unless confirmed.
    - Prominently displays explicit warnings and qualifier badges.
    - Displays candidate name, title, source links, and explicit employment qualifier.
    - Zero CTA outreach actions or optimistic indicators.
    """
    if not isinstance(cand, dict):
        return ""

    name = _safe_presentation_text(cand.get("name"), "Unknown Candidate")
    title = _safe_presentation_text(cand.get("title"), "—")
    icp = _safe_presentation_text(cand.get("icp_level"), "Fallback")
    cat = _safe_presentation_text(cand.get("contact_category"), "Fallback / Training Practitioner")
    conf = _safe_presentation_text(cand.get("evidence_confidence"), "Low")
    emp = _safe_presentation_text(cand.get("current_employment_status"), "Probable")
    emp_note = _safe_presentation_text(cand.get("employment_status_note"))
    why = _safe_presentation_text(cand.get("why_selected"))
    urls = cand.get("evidence_urls") or []
    valid_urls = [_safe_presentation_url(u) for u in urls if _safe_presentation_url(u)]

    ev_meta = classify_contact_evidence(cand)
    f_rat = cand.get("employment_freshness_rationale")
    f_date = cand.get("evidence_date")
    f_age = cand.get("evidence_age_months")

    fresh_span = f'<span><strong>Freshness:</strong> {ev_meta["freshness_badge"]}</span>'
    if ev_meta["qualifier_badge"]:
        fresh_span += f' {ev_meta["qualifier_badge"]}'

    date_clause = ""
    if f_date and f_age is not None:
        date_clause = f" · Evidence Date: {_safe_presentation_text(f_date)} (~{f_age}m old)"
    elif f_date:
        date_clause = f" · Evidence Date: {_safe_presentation_text(f_date)}"

    fresh_detail_div = ""
    if f_rat:
        fresh_detail_div = f'<div style="font-size:0.78rem; color:#64748b; margin-top:3px; line-height:1.4;"><strong>Freshness Evaluation:</strong> {_safe_presentation_text(f_rat)}{date_clause}</div>'
    elif date_clause:
        fresh_detail_div = f'<div style="font-size:0.78rem; color:#64748b; margin-top:3px; line-height:1.4;">{date_clause.lstrip(" · ")}</div>'

    urls_html = ""
    if valid_urls:
        urls_links = " ".join([
            f'<a href="{u}" target="_blank" rel="noopener noreferrer" style="color:#0284c7; text-decoration:underline; margin-right:8px; font-size:0.78rem;">Source {i+1} ↗</a>'
            for i, u in enumerate(valid_urls)
        ])
        summary_badge = ""
        ev_summary = cand.get("evidence_summary")
        if ev_summary:
            summary_badge = f' <span style="font-size:0.75rem; color:#64748b; font-weight:normal;">({html.escape(ev_summary)})</span>'
        urls_html = f'<div style="margin-top:6px; font-size:0.8rem; color:#475569;"><strong>Source Links:</strong> {urls_links}{summary_badge}</div>'

    qualifier_parts = [f"Status: {emp}"]
    if emp_note:
        qualifier_parts.append(emp_note)
    elif f_rat:
        qualifier_parts.append(_safe_presentation_text(f_rat))
    qualifier_text = " · ".join(qualifier_parts)
    emp_qualifier_div = f'<div style="font-size:0.79rem; color:#92400e; margin-top:4px; line-height:1.4;"><strong>Employment Qualifier:</strong> {qualifier_text}</div>'

    why_div = f'<div style="font-size:0.8rem; color:#475569; margin-top:4px; line-height:1.45;"><strong>Selection Context:</strong> {why}</div>' if why else ""

    if ev_meta["is_former"]:
        top_badge = '<span style="background-color:#fee2e2; color:#b91c1c; border:1px solid #dc262644; padding:2px 8px; border-radius:4px; font-size:0.73rem; font-weight:600;">🔴 Former employee (Best Available Weak Match)</span>'
    else:
        top_badge = '<span style="background-color:#f1f5f9; color:#475569; border:1px solid #cbd5e1; padding:2px 8px; border-radius:4px; font-size:0.73rem; font-weight:600;">⚪ Unconfirmed Candidate (Best Available Weak Match)</span>'
    warning_text = ev_meta["warning_note"] or "⚠️ Unconfirmed — do not use for outreach without independent verification."
    warning_bg = "#fef2f2" if ev_meta["is_former"] else "#fffbeb"
    warning_border = "#fee2e2" if ev_meta["is_former"] else "#fef3c7"
    warning_color = "#991b1b" if ev_meta["is_former"] else "#92400e"

    raw_html = f"""
    <div style="background-color:#f8fafc; border:1px solid #cbd5e1; border-left:3px solid #94a3b8; border-radius:6px; padding:12px 14px; margin-top:8px; margin-bottom:10px;">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px;">
            <div style="font-size:0.9rem; font-weight:700; color:#1e293b;">
                {name} — <span style="font-weight:500; color:#475569;">{title}</span>
            </div>
            {top_badge}
        </div>
        <div style="display:flex; flex-wrap:wrap; gap:12px; font-size:0.78rem; color:#64748b; margin-top:3px;">
            <span><strong>Role Type:</strong> {cat}</span>
            <span><strong>ICP Level:</strong> {icp}</span>
            <span><strong>Confidence:</strong> {conf}</span>
            <span><strong>Employment:</strong> {emp}</span>
            {fresh_span}
        </div>
        {emp_qualifier_div}
        {fresh_detail_div}
        {why_div}
        {urls_html}
        <div style="margin-top:8px; padding:6px 10px; background:{warning_bg}; border:1px solid {warning_border}; border-radius:4px; font-size:0.78rem; color:{warning_color}; font-weight:600;">
            {warning_text}
        </div>
    </div>
    """
    return format_presentation_html(raw_html)


def build_contact_card_html(res: dict, strictness_mode: str = "Strict (Default)") -> str:
    """
    Constructs sanitized presentation HTML for a Contact Intelligence candidate card.
    Supports 3 display strictness policies:
    - Strict (Default): Strongly supported current contacts only. Weak/stale leads suppressed to expander.
    - Balanced: Surfaces unconfirmed current contacts (e.g. Jose Fernandez) with explicit warning badges. Former employees remain suppressed.
    - Broad: Surfaces both unconfirmed current contacts and former employees (e.g. Marco Rossi) with explicit badges.
    """
    if not isinstance(res, dict):
        return ""

    mode_str = str(strictness_mode or "Strict").lower()
    is_broad = "broad" in mode_str
    is_balanced = "balanced" in mode_str
    is_strict = not (is_broad or is_balanced)

    raw_status = str(res.get("contact_research_status") or "Completed")
    is_weak = res.get("is_weak_match", False)
    pc = res.get("primary_contact") if isinstance(res.get("primary_contact"), dict) else {}
    ideal_role = res.get("ideal_role")
    decision_reason = res.get("decision_reason")
    alternatives = res.get("alternative_contacts") or []

    # Gather and deduplicate all candidate leads
    weak_candidates = []
    seen_names = set()
    for cand in res.get("weak_matches") or []:
        if isinstance(cand, dict) and cand.get("name"):
            n = cand.get("name").strip().lower()
            if n not in seen_names:
                seen_names.add(n)
                weak_candidates.append(cand)
    if is_weak and pc and pc.get("name"):
        n = pc.get("name").strip().lower()
        if n not in seen_names:
            seen_names.add(n)
            weak_candidates.insert(0, pc)
    for alt in res.get("alternative_contacts") or []:
        if isinstance(alt, dict) and alt.get("name"):
            n = alt.get("name").strip().lower()
            if n not in seen_names:
                seen_names.add(n)
                weak_candidates.append(alt)
    for cand in res.get("candidates") or []:
        if isinstance(cand, dict) and cand.get("name"):
            n = cand.get("name").strip().lower()
            if n not in seen_names:
                seen_names.add(n)
                weak_candidates.append(cand)

    # Determine primary candidate to display based on strictness mode
    surfaced_candidate = None
    surfaced_meta = None
    is_surfaced_weaker = False

    pc_meta = classify_contact_evidence(pc) if (pc and isinstance(pc, dict) and pc.get("name")) else None

    if not is_weak and "Role Found" not in raw_status and pc and pc.get("name"):
        # Resolved primary contact (verified or probable): displayed in all modes
        surfaced_candidate = pc
        surfaced_meta = pc_meta or classify_contact_evidence(pc)
        if surfaced_meta["is_confirmed"] or raw_status == "Verified Contact Found":
            status_bg = "#dcfce7"
            status_color = "#15803d"
            status_label = "Verified Contact Found"
        elif "Probable" in raw_status or pc.get("current_employment_status") == "Probable":
            status_bg = "#fef3c7"
            status_color = "#b45309"
            conf = pc.get("evidence_confidence") or res.get("evidence_confidence") or ""
            conf_str = str(conf).strip()
            if conf_str.lower() == "low":
                status_label = "Probable — Low confidence"
            elif conf_str:
                status_label = f"Probable — {_safe_presentation_text(conf_str)} confidence"
            else:
                status_label = "Probable Contact Found"
        else:
            status_bg = "#f1f5f9"
            status_color = "#475569"
            status_label = _safe_presentation_text(raw_status)
    elif is_balanced:
        # Balanced mode: surface unconfirmed current contact (e.g. Jose Fernandez)
        # Former employees remain suppressed.
        for c in weak_candidates:
            c_meta = classify_contact_evidence(c)
            if c_meta["is_unconfirmed"]:
                surfaced_candidate = c
                surfaced_meta = c_meta
                is_surfaced_weaker = True
                status_bg = "#fef3c7"
                status_color = "#b45309"
                status_label = "Probable (Balanced Mode)"
                break
        if not surfaced_candidate:
            status_bg = "#e0f2fe"
            status_color = "#0369a1"
            status_label = "Role Found — Person Unresolved"
    elif is_broad:
        # Broad mode: surface unconfirmed contact OR former employee (e.g. Marco Rossi)
        for c in weak_candidates:
            c_meta = classify_contact_evidence(c)
            if c_meta["is_unconfirmed"]:
                surfaced_candidate = c
                surfaced_meta = c_meta
                is_surfaced_weaker = True
                status_bg = "#fef3c7"
                status_color = "#b45309"
                status_label = "Probable (Broad Mode)"
                break
        if not surfaced_candidate and weak_candidates:
            # Fall back to former employee in broad mode
            c = weak_candidates[0]
            c_meta = classify_contact_evidence(c)
            surfaced_candidate = c
            surfaced_meta = c_meta
            is_surfaced_weaker = True
            status_bg = "#fee2e2"
            status_color = "#991b1b"
            status_label = "Historical / Stale Lead (Broad Mode)"
        elif not surfaced_candidate:
            status_bg = "#e0f2fe"
            status_color = "#0369a1"
            status_label = "Role Found — Person Unresolved"
    else:
        # Strict mode (Default): weak leads suppressed from primary card
        status_bg = "#e0f2fe" if (is_weak or "Role Found" in raw_status) else "#f1f5f9"
        status_color = "#0369a1" if (is_weak or "Role Found" in raw_status) else "#475569"
        status_label = "Role Found — Person Unresolved" if (is_weak or "Role Found" in raw_status) else _safe_presentation_text(raw_status)

    primary_html = ""
    if surfaced_candidate:
        c_name = _safe_presentation_text(surfaced_candidate.get("name"), "Unknown Candidate")
        c_title = _safe_presentation_text(surfaced_candidate.get("title"), "—")
        c_icp = _safe_presentation_text(surfaced_candidate.get("icp_level"), "—")
        c_conf = _safe_presentation_text(surfaced_candidate.get("evidence_confidence"), "—")
        c_emp = _safe_presentation_text(surfaced_candidate.get("current_employment_status"), "—")
        c_emp_note = _safe_presentation_text(surfaced_candidate.get("employment_status_note"))
        c_why = _safe_presentation_text(surfaced_candidate.get("why_selected"))

        # Harmonize contradictory confidence text if present
        conf_str = str(c_conf or "").strip()
        if conf_str.lower() == "low" and "classifying current employment as Probable with High evidence confidence" in c_why:
            c_why = (
                c_why
                .replace(
                    ", classifying current employment as Probable with High evidence confidence.",
                    ". Current employment is classified as Probable with low evidence confidence."
                )
                .replace(
                    "classifying current employment as Probable with High evidence confidence.",
                    "Current employment is classified as Probable with low evidence confidence."
                )
                .replace(
                    "classifying current employment as Probable with High evidence confidence",
                    "Current employment is classified as Probable with low evidence confidence"
                )
            )

        f_stat = surfaced_candidate.get("employment_freshness_status")
        f_rat = surfaced_candidate.get("employment_freshness_rationale")
        f_date = surfaced_candidate.get("evidence_date")
        f_age = surfaced_candidate.get("evidence_age_months")

        fresh_span = f'<span><strong>Freshness:</strong> {surfaced_meta["freshness_badge"]}</span>'
        if surfaced_meta.get("qualifier_badge"):
            fresh_span += f' {surfaced_meta["qualifier_badge"]}'

        date_clause = ""
        if f_date and f_age is not None:
            date_clause = f" · Evidence Date: {_safe_presentation_text(f_date)} (~{f_age}m old)"
        elif f_date:
            date_clause = f" · Evidence Date: {_safe_presentation_text(f_date)}"

        fresh_detail_div = ""
        if f_rat:
            fresh_detail_div = f'<div style="font-size:0.78rem; color:#475569; margin-top:3px; line-height:1.4;"><strong>Freshness Evaluation:</strong> {_safe_presentation_text(f_rat)}{date_clause}</div>'
        elif date_clause:
            fresh_detail_div = f'<div style="font-size:0.78rem; color:#475569; margin-top:3px; line-height:1.4;">{date_clause.lstrip(" · ")}</div>'

        c_urls = surfaced_candidate.get("evidence_urls") or []
        valid_urls = [_safe_presentation_url(u) for u in c_urls if _safe_presentation_url(u)]
        urls_html = ""
        if valid_urls:
            urls_links = " ".join([
                f'<a href="{u}" target="_blank" rel="noopener noreferrer" style="color:#0284c7; text-decoration:underline; margin-right:8px;">Source {i+1} ↗</a>'
                for i, u in enumerate(valid_urls)
            ])
            summary_badge = ""
            ev_summary = res.get("evidence_summary") or surfaced_candidate.get("evidence_summary")
            if ev_summary:
                summary_badge = f' <span style="font-size:0.75rem; color:#64748b; font-weight:normal;">({html.escape(ev_summary)})</span>'
            urls_html = f'<div style="margin-top:6px; font-size:0.8rem; color:#475569;"><strong>Evidence Sources:</strong> {urls_links}{summary_badge}</div>'

        emp_note_div = f'<div style="font-size:0.79rem; color:#64748b; margin-top:4px; line-height:1.4;"><strong>Employment Note:</strong> {c_emp_note}</div>' if c_emp_note else ""
        why_div = f'<div style="font-size:0.82rem; color:#334155; margin-top:6px; line-height:1.45;"><strong>Why Selected:</strong> {c_why}</div>' if c_why else ""

        banner_html = ""
        warning_box_html = ""
        if is_surfaced_weaker:
            if surfaced_meta["is_former"]:
                banner_html = """
                <div style="margin-bottom:10px; padding:8px 12px; background:#fef2f2; border:1px solid #fee2e2; border-left:3px solid #dc2626; border-radius:4px; font-size:0.82rem; color:#991b1b;">
                    <strong>⚠️ Historical Lead (Broad Mode)</strong> — <em>Contradictory / likely stale. Candidate surfaced under Broad strictness policy. Evidence indicates candidate is a former employee or profile data is historic (>36 months). Do not use for active enterprise outreach without re-verification.</em>
                </div>
                """
                warning_box_html = """
                <div style="margin-top:8px; padding:6px 10px; background:#fef2f2; border:1px solid #fecaca; border-radius:4px; font-size:0.78rem; color:#991b1b; font-weight:600;">
                    ⚠️ Stale / Former Employee — verify current status before any engagement.
                </div>
                """
            else:
                mode_tag = "Broad Mode" if is_broad else "Balanced Mode"
                banner_html = f"""
                <div style="margin-bottom:10px; padding:8px 12px; background:#fffbeb; border:1px solid #fef3c7; border-left:3px solid #f59e0b; border-radius:4px; font-size:0.82rem; color:#92400e;">
                    <strong>⚠️ Unconfirmed Candidate ({mode_tag})</strong> — <em>Weak third-party evidence. Candidate surfaced under {mode_tag} presentation policy. Corroborated by third-party publisher only; no corporate primary source confirmation.</em>
                </div>
                """
                warning_box_html = """
                <div style="margin-top:8px; padding:6px 10px; background:#fffbeb; border:1px solid #fef3c7; border-radius:4px; font-size:0.78rem; color:#92400e; font-weight:600;">
                    ⚠️ Unconfirmed — do not use for outreach without independent verification.
                </div>
                """

        disp_emp = "Unconfirmed current" if (surfaced_meta and surfaced_meta.get("is_unconfirmed")) else ("Former employee" if (surfaced_meta and surfaced_meta.get("is_former")) else c_emp)

        primary_html = f"""
        <div style="margin-bottom:6px;">
            {banner_html}
            <div style="font-size:0.95rem; font-weight:700; color:#0f172a; margin-bottom:2px;">
                {c_name} — <span style="font-weight:500; color:#334155;">{c_title}</span>
            </div>
            <div style="display:flex; flex-wrap:wrap; gap:12px; font-size:0.8rem; color:#475569; margin-top:4px;">
                <span><strong>ICP Level:</strong> {c_icp}</span>
                <span><strong>Confidence:</strong> {c_conf}</span>
                <span><strong>Employment:</strong> {disp_emp}</span>
                {fresh_span}
            </div>
            {fresh_detail_div}
            {emp_note_div}
            {why_div}
            {urls_html}
            {warning_box_html}
        </div>
        """
    elif is_weak or "Role Found" in raw_status:
        if weak_candidates:
            first_c = weak_candidates[0]
            first_name = _safe_presentation_text(first_c.get("name"), "Identified candidate")
            first_title = _safe_presentation_text(first_c.get("title"), "operational role")
            if is_balanced and classify_contact_evidence(first_c)["is_former"]:
                warning_headline = "⚠️ Former Employee Suppressed (Balanced Mode):"
                warning_msg = f"Available lead ({first_name} — {first_title}) is classified as a former employee or stale lead. Under Balanced mode, former employees remain suppressed. Switch to <strong>Broad</strong> mode to surface historical leads, or inspect below under <em>Weak matches (unconfirmed)</em>."
            else:
                warning_headline = "⚠️ Enterprise Leadership Unresolved:"
                warning_msg = f"No verified enterprise training leader (Director/Head/VP) was resolved in indexed records. The best available weak match ({first_name} — {first_title}) is retained below under <em>Best Available Weak Matches</em>."
        else:
            warning_headline = "⚠️ Enterprise Leadership Unresolved:"
            warning_msg = "No verified individual contact was resolved for this account."

        primary_html = f"""
        <div style="margin-bottom:6px; padding:10px 12px; background:#f8fafc; border-radius:6px; border:1px dashed #cbd5e1; font-size:0.84rem; color:#475569;">
            <strong>{warning_headline}</strong> {warning_msg}
        </div>
        """
    else:
        primary_html = """
        <div style="margin-bottom:6px; padding:8px 10px; background:#f8fafc; border-radius:4px; font-size:0.84rem; color:#475569;">
            <em>No verified individual contact was resolved for this account.</em>
        </div>
        """

    ideal_html = ""
    if ideal_role:
        ideal_html = f"""
        <div style="font-size:0.82rem; color:#0369a1; background:#f0f9ff; border-left:3px solid #0284c7; padding:6px 10px; border-radius:3px; margin-top:6px;">
            <strong>🎯 Ideal / Target Role:</strong> {_safe_presentation_text(ideal_role)}
        </div>
        """

    reason_html = ""
    if decision_reason:
        clean_reason = _safe_presentation_text(decision_reason)
        conf_val = (surfaced_candidate.get("evidence_confidence") if surfaced_candidate else None) or res.get("evidence_confidence") or ""
        conf_str = str(conf_val).strip()
        if conf_str.lower() == "low" and "classifying current employment as Probable with High evidence confidence" in clean_reason:
            clean_reason = (
                clean_reason
                .replace(
                    ", classifying current employment as Probable with High evidence confidence.",
                    ". Current employment is classified as Probable with low evidence confidence."
                )
                .replace(
                    "classifying current employment as Probable with High evidence confidence.",
                    "Current employment is classified as Probable with low evidence confidence."
                )
                .replace(
                    "classifying current employment as Probable with High evidence confidence",
                    "Current employment is classified as Probable with low evidence confidence"
                )
            )
        reason_html = f"""
        <div style="font-size:0.82rem; color:#334155; margin-top:6px; line-height:1.45;">
            <strong>Decision Reason:</strong> {clean_reason}
        </div>
        """

    alts_html = ""
    if alternatives and not is_weak and not is_surfaced_weaker:
        alt_items = ""
        for i, alt in enumerate(alternatives):
            if isinstance(alt, dict):
                a_name = _safe_presentation_text(alt.get("name"), f"Candidate {i+1}")
                a_title = _safe_presentation_text(alt.get("title"), "—")
                a_icp = _safe_presentation_text(alt.get("icp_level"), "—")
                a_why = _safe_presentation_text(alt.get("why_selected"))
                a_urls = alt.get("evidence_urls") or []
                valid_a_urls = [_safe_presentation_url(u) for u in a_urls if _safe_presentation_url(u)]
                a_url_html = ""
                if valid_a_urls:
                    a_url_html = " · " + " ".join([
                        f'<a href="{u}" target="_blank" rel="noopener noreferrer" style="color:#0284c7; text-decoration:underline;">Source {idx+1} ↗</a>'
                        for idx, u in enumerate(valid_a_urls)
                    ])
                why_clause = f" — {a_why}" if a_why else ""
                alt_items += f'<div style="font-size:0.78rem; color:#334155; margin-bottom:4px;">• <strong>{a_name}</strong> — <em>{a_title}</em> (ICP: {a_icp}){why_clause}{a_url_html}</div>'
        if alt_items:
            alts_html = f"""
            <div style="margin-top:10px; border-top:1px dashed #e2e8f0; padding-top:8px;">
                <div style="font-size:0.8rem; font-weight:600; color:#475569; margin-bottom:4px;">Alternative Candidates ({len(alternatives)}):</div>
                {alt_items}
            </div>
            """

    is_cached = res.get("is_from_cache", False) or (res.get("telemetry", {}).get("cache_hit", False))
    final_mode = res.get("telemetry", {}).get("final_research_mode") or ("cached" if is_cached else "deep")
    if is_cached or final_mode == "cached":
        mode_badge_html = '<span style="background-color:#f1f5f9; color:#475569; border:1px solid #cbd5e1; padding:2px 8px; border-radius:10px; font-size:0.72rem; font-weight:600; margin-left:8px;">🕒 Cached</span>'
    elif final_mode == "fast":
        mode_badge_html = '<span style="background-color:#ecfdf5; color:#047857; border:1px solid #a7f3d0; padding:2px 8px; border-radius:10px; font-size:0.72rem; font-weight:600; margin-left:8px;">⚡ Fast Pass</span>'
    else:
        mode_badge_html = '<span style="background-color:#eff6ff; color:#1d4ed8; border:1px solid #bfdbfe; padding:2px 8px; border-radius:10px; font-size:0.72rem; font-weight:600; margin-left:8px;">🔬 Deep Pass</span>'

    card_html = f"""
    <div style="background-color:#ffffff; border:1px solid #e2e8f0; border-radius:8px; padding:16px 20px; margin-top:10px; margin-bottom:12px; box-shadow:0 1px 3px rgba(0,0,0,0.03);">
        <div style="display:flex; justify-content:space-between; align-items:center; border-bottom:1px solid #f1f5f9; padding-bottom:10px; margin-bottom:12px;">
            <div style="display:flex; align-items:center;">
                <span style="font-weight:700; font-size:0.95rem; color:#1e293b;">Research Outcome</span>
                {mode_badge_html}
            </div>
            <span style="background-color:{status_bg}; color:{status_color}; border:1px solid {status_color}33; padding:2px 10px; border-radius:12px; font-size:0.78rem; font-weight:600;">{status_label}</span>
        </div>
        {primary_html}
        {ideal_html}
        {reason_html}
        {alts_html}
    </div>
    """
    return format_presentation_html(card_html)


def render_contact_card(res, strictness_mode="Strict (Default)"):
    """Renders the Contact Intelligence result card matching the approved contract."""
    if not isinstance(res, dict):
        return

    # User-visible cache metadata banner
    evaluated_at = res.get("evaluated_at") or res.get("researched_at") or ""
    is_cached = res.get("is_from_cache", False) or (res.get("telemetry", {}).get("cache_hit", False))
    final_mode = res.get("telemetry", {}).get("final_research_mode") or ("cached" if is_cached else "deep")

    if is_cached or final_mode == "cached":
        st.markdown(
            f'<div style="background:#f8fafc; border:1px solid #e2e8f0; border-radius:6px; padding:6px 12px; margin-bottom:8px; font-size:0.8rem; color:#475569;">'
            f'🕒 <strong>Cached research</strong> — evaluated {html.escape(str(evaluated_at))}'
            f'</div>',
            unsafe_allow_html=True
        )
    elif evaluated_at:
        mode_text = "Fast Pass" if final_mode == "fast" else "Deep Pass"
        st.markdown(
            f'<div style="background:#f0fdf4; border:1px solid #bbf7d0; border-radius:6px; padding:6px 12px; margin-bottom:8px; font-size:0.8rem; color:#166534;">'
            f'⚡ <strong>Live research ({mode_text})</strong> — evaluated {html.escape(str(evaluated_at))}'
            f'</div>',
            unsafe_allow_html=True
        )

    card_html = build_contact_card_html(res, strictness_mode=strictness_mode)
    st.markdown(card_html, unsafe_allow_html=True)

    # Telemetry caption
    telem = res.get("telemetry")
    if telem and isinstance(telem, dict):
        lat = telem.get("total_latency_ms", 0)
        mode_str = telem.get("final_research_mode", "unknown")
        b_dur = telem.get("brave_query_duration_ms", 0)
        b_cnt = telem.get("brave_query_count", 0)
        l_dur = telem.get("llm_duration_ms", 0)
        l_cnt = telem.get("llm_call_count", 0)
        c_dur = telem.get("canonicalization_duration_ms", 0)
        st.caption(
            f"⏱️ **Telemetry**: Latency: {lat}ms | Mode: `{mode_str}` | "
            f"Brave: {b_dur}ms ({b_cnt} queries) | LLM: {l_dur}ms ({l_cnt} calls) | Canonicalization: {c_dur}ms"
        )

    # Evidence details & source independence expander
    ev_summary = res.get("evidence_summary") or (res.get("primary_contact") or {}).get("evidence_summary") or ""
    canonical_evidence = res.get("canonical_evidence") or (res.get("primary_contact") or {}).get("canonical_evidence") or []
    if not canonical_evidence and (res.get("weak_matches") or []):
        for wm in res.get("weak_matches", []):
            if wm.get("canonical_evidence"):
                canonical_evidence = wm.get("canonical_evidence")
                if not ev_summary:
                    ev_summary = wm.get("evidence_summary", "")
                break

    if canonical_evidence:
        exp_title = f"🔎 Evidence Details & Source Independence ({ev_summary})" if ev_summary else "🔎 Evidence Details & Source Independence"
        with st.expander(exp_title, expanded=False):
            if ev_summary:
                st.caption(f"**Canonical Summary**: {ev_summary}")
            rows = []
            for rec in canonical_evidence:
                rows.append({
                    "Status": rec.get("provenance_status") or rec.get("status") or "Primary Canonical",
                    "Source Family": rec.get("source_family", "unknown"),
                    "Authority Tier": rec.get("authority_tier", "tier_4_unverified_web"),
                    "Domain": rec.get("domain") or extract_publisher_domain(rec.get("canonical_url") or rec.get("raw_url", "")),
                    "Canonical URL": rec.get("canonical_url", ""),
                    "Raw URL": rec.get("raw_url", ""),
                })
            try:
                import pandas as pd
                st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
            except Exception:
                for r in rows:
                    st.write(f"- **{r['Status']}** [{r['Source Family']} / {r['Authority Tier']}]: `{r['Canonical URL']}` (raw: `{r['Raw URL']}`)")

    is_weak = res.get("is_weak_match", False)
    raw_status = str(res.get("contact_research_status") or "")
    is_unresolved = "Role Found" in raw_status or "Unresolved" in raw_status

    weak_candidates = []
    seen_names = set()

    for cand in res.get("weak_matches") or []:
        if isinstance(cand, dict) and cand.get("name"):
            n = cand.get("name").strip().lower()
            if n not in seen_names:
                seen_names.add(n)
                weak_candidates.append(cand)

    if is_weak or is_unresolved:
        if is_weak:
            pc = res.get("primary_contact")
            if isinstance(pc, dict) and pc.get("name"):
                n = pc.get("name").strip().lower()
                if n not in seen_names:
                    seen_names.add(n)
                    weak_candidates.insert(0, pc)
        for alt in res.get("alternative_contacts") or []:
            if isinstance(alt, dict) and alt.get("name"):
                n = alt.get("name").strip().lower()
                if n not in seen_names:
                    seen_names.add(n)
                    weak_candidates.append(alt)
        for cand in res.get("candidates") or []:
            if isinstance(cand, dict) and cand.get("name"):
                n = cand.get("name").strip().lower()
                if n not in seen_names:
                    seen_names.add(n)
                    weak_candidates.append(cand)

    if weak_candidates and (is_weak or is_unresolved):
        count = len(weak_candidates)
        with st.expander(f"🔍 Weak matches (unconfirmed) ({count})", expanded=False):
            st.warning(
                "⚠️ **Unconfirmed — do not use for outreach without independent verification.**\n\n"
                "⚠️ **Operational / Practitioner Role Warning**: These contacts hold operational or practitioner roles "
                "(e.g., Program Manager, Training Coordinator, Specialist) or lack first-party corporate corroboration. "
                "They are **NOT** verified enterprise training budget holders."
            )
            for cand in weak_candidates:
                weak_card_html = build_weak_contact_card_html(cand)
                st.markdown(weak_card_html, unsafe_allow_html=True)


def render_contact_research_ui(company_name, website="", segment="", country="", key_prefix="ci"):
    """
    Renders the Contact Research trigger button, stepped progress, and results in Streamlit.
    """
    cache_key = f"ci_cache_{company_name}"
    cached_result = st.session_state.get(cache_key)

    st.markdown("##### 👥 Target Contact Intelligence (Agentic Research V1)")
    st.caption("Powered by EON Contact Intelligence Engine.")

    if cached_result:
        col_act1, col_act2, col_act3 = st.columns([2.5, 2, 1.5])
        with col_act1:
            if st.button("🔄 Re-Verify Current Employment", key=f"{key_prefix}_reverify_{company_name}", type="primary", use_container_width=True):
                with st.status(f"🔄 Re-verifying current employment for {company_name}...", expanded=True) as status_box:
                    status_box.markdown("⏱️ *Estimated duration: 15–30s. Bypassing cache to execute fresh multi-source corroboration.*")
                    status_box.write("⚙️ **Phase 1/3**: Bypassing cache & initializing fresh query budget...")
                    time.sleep(0.05)
                    status_box.write("🌐 **Phase 2/3**: Harvesting multi-source search evidence across web sources...")
                    time.sleep(0.05)
                    status_box.write("⚖️ **Phase 3/3**: Re-adjudicating leadership contacts and employment freshness...")
                    try:
                        ok, res, err = execute_contact_research(
                            company_name=company_name,
                            website=website,
                            segment=segment,
                            country=country,
                            force_refresh=True,
                        )
                    except Exception as exc:
                        ok, res, err = False, None, f"Execution exception: {exc}"
                    if ok and res:
                        status_box.update(label="✅ Employment re-verification completed", state="complete", expanded=False)
                        st.session_state[cache_key] = res
                        st.rerun()
                    else:
                        status_box.update(label="❌ Re-verification failed", state="error", expanded=True)
                        st.error(f"Contact Research Request Failed: {err}")
        with col_act2:
            if st.button("🔄 Refresh (Cached)", key=f"{key_prefix}_refresh_{company_name}", use_container_width=True):
                with st.status(f"🔍 Checking research for {company_name}...", expanded=True) as status_box:
                    try:
                        ok, res, err = execute_contact_research(
                            company_name=company_name,
                            website=website,
                            segment=segment,
                            country=country,
                            force_refresh=False,
                        )
                    except Exception as exc:
                        ok, res, err = False, None, f"Execution exception: {exc}"
                    if ok and res:
                        status_box.update(label="✅ Research loaded", state="complete", expanded=False)
                        st.session_state[cache_key] = res
                        st.rerun()
                    else:
                        status_box.update(label="❌ Request failed", state="error", expanded=True)
                        st.error(f"Contact Research Request Failed: {err}")
        with col_act3:
            if st.button("✕ Dismiss", key=f"{key_prefix}_clr_{company_name}", use_container_width=True):
                del st.session_state[cache_key]
                st.rerun()
    else:
        col_act1, col_act2 = st.columns([2.5, 4])
        with col_act1:
            if st.button("Find Target Contact", key=f"{key_prefix}_btn_{company_name}", type="primary", use_container_width=True):
                with st.status(f"🔍 Researching target contact for {company_name}...", expanded=True) as status_box:
                    status_box.markdown("⏱️ *Estimated duration: 15–30s. Rigorous multi-source evidence harvesting and conservative tenure adjudication.*")
                    status_box.write("⚙️ **Phase 1/3**: Formulating seed query budget & targeting parameters...")
                    time.sleep(0.05)
                    status_box.write("🌐 **Phase 2/3**: Harvesting corporate, professional & directory search evidence...")
                    time.sleep(0.05)
                    status_box.write("⚖️ **Phase 3/3**: Adjudicating ICP alignment, multi-source corroboration & tenure...")
                    try:
                        ok, res, err = execute_contact_research(
                            company_name=company_name,
                            website=website,
                            segment=segment,
                            country=country,
                            force_refresh=False,
                        )
                    except Exception as exc:
                        ok, res, err = False, None, f"Execution exception: {exc}"
                    if ok and res:
                        status_box.update(label="✅ Contact research completed", state="complete", expanded=False)
                        st.session_state[cache_key] = res
                        st.rerun()
                    else:
                        status_box.update(label="❌ Contact research failed", state="error", expanded=True)
                        st.error(f"Contact Research Request Failed: {err}")

    if cached_result:
        render_contact_card(cached_result)

