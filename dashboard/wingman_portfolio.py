"""
Wingman Portfolio Intelligence and Dynamic Tiering Engine.
Core processing module for full-universe portfolio operations:
- Ingestion of Wingman Trigger Export CSV (1,180 rows, 785 unique companies)
- Sanitized review data support with zero raw notes or prototype URLs
- Exact account identity resolution (company name + domain compound key, 0 collapsed)
- Event deduplication and temporal active window evaluation
- Auditable dynamic tier calculation (Proposed Default: distinct categories mode vs event-count mode)
- Normalized Observed-vs-Expected Lift calculation for trigger co-occurrence
- Re-structured queue semantics: RESEARCH & QUALIFY NOW, SCOPE REVIEW HOLD, READY FOR OUTREACH (0), MONITOR
- Decoupled 3D Decision Framework (Timing x Customer Fit x Buyer Accessibility)
- Softened fit review: 'POSSIBLE OUT OF SCOPE — REVIEW REQUIRED' with standardized review reason codes
- Operational archetype cohorts framed as Commercial Hypotheses & Discovery Questions
- Ranked Trigger-Profile Lookalikes with explicit subset-overlap transparency
- Transparent rules-based research steps and discovery questions, with locked outreach previews
"""

import os
import re
from datetime import date, datetime
import ipaddress
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Set, Tuple
import urllib.parse

import pandas as pd
import numpy as np

# Configurable default expiry horizons (in days)
DEFAULT_EXPIRY_WINDOWS = {
    "new_leader": {"past_days": 90, "future_days": 0, "label": "New Leader (90d past)"},
    "hiring_burst": {"past_days": 90, "future_days": 60, "label": "Hiring Burst (90d past / 60d fwd)"},
    "turnaround": {"past_days": 180, "future_days": 365, "label": "Turnaround (180d past / 365d fwd)"},
    "audit_cycle": {"past_days": 180, "future_days": 180, "label": "Audit Cycle (180d past / 180d fwd)"},
    "project_fid_commissioning": {"past_days": 365, "future_days": 540, "label": "Commissioning / FID (365d past / 540d fwd)"},
    "ma_acquisition": {"past_days": 365, "future_days": 180, "label": "M&A / Asset Acq (365d past / 180d fwd)"},
    "incident_regulator": {"past_days": 365, "future_days": 0, "label": "Regulatory / CSB (365d past)"},
    "crew_change": {"past_days": 365, "future_days": 365, "label": "Crew Change / Aging (365d past / 365d fwd)"},
}

DEFAULT_AS_OF_DATE = date(2026, 9, 17)

TRIGGER_DISPLAY_LABELS = {
    "project_fid_commissioning": "Project Commissioning / FID",
    "ma_acquisition": "M&A / Asset Acquisition",
    "hiring_burst": "Frontline Hiring Burst",
    "turnaround": "Turnaround / Planned Maintenance",
    "new_leader": "Executive Leadership Change",
    "incident_regulator": "Regulatory Finding / Incident",
    "audit_cycle": "Audit / Compliance Cycle",
    "crew_change": "Workforce / Crew Change Transition",
}

VALID_TRIGGER_TYPES = list(TRIGGER_DISPLAY_LABELS.keys())

def normalize_domain(domain: Any) -> str:
    """Standardizes domain strings for deduplication."""
    if not domain or pd.isna(domain):
        return ""
    d = str(domain).strip().lower()
    d = re.sub(r"^https?://", "", d)
    d = re.sub(r"^www\.", "", d)
    d = d.split("/")[0].split(":")[0]
    return d

def normalize_company_name(name: Any) -> str:
    """Cleans company name for display and normalized grouping."""
    if not name or pd.isna(name):
        return ""
    s = str(name).strip()
    s = re.sub(r"\s+", " ", s)
    return s

def parse_iso_date(val: Any) -> Optional[date]:
    """
    Parse YYYY-MM-DD, YYYY-MM, or YYYY-Qn to date.
    Preserves nonstandard Sinopec dates by extracting the valid date prefix:
      '2026-Q3 (target, article 2025-05-23)' -> 2026-07-01
      '2026-09 (listing ~17 days old as of Sep 2026 search)' -> 2026-09-01
    """
    if val is None or pd.isna(val):
        return None
    s = str(val).strip()
    if not s or s.lower() == "nan":
        return None
    # YYYY-MM-DD
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass
    # YYYY-Qn
    m = re.match(r"^(\d{4})-[qQ]([1-4])", s)
    if m:
        try:
            q_month = {1: 1, 2: 4, 3: 7, 4: 10}[int(m.group(2))]
            return date(int(m.group(1)), q_month, 1)
        except (ValueError, KeyError):
            pass
    # YYYY-MM
    m = re.match(r"^(\d{4})-(\d{2})", s)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), 1)
        except ValueError:
            pass
    return None

def is_safe_evidence_url(url: Any) -> bool:
    """
    Evidence-Link Safety and Local-Network URL Blocking.
    Validates that a URL is syntactically safe for client-side hyperlink rendering.
    Performs purely syntactic validation without outbound DNS resolution.
    Because the dashboard does not fetch these URLs, this is link-rendering protection
    rather than active server-side request forgery (SSRF) prevention.
    Note: Any future server-side fetching would require outbound DNS resolution
    and redirect validation.
    Rejects:
      - Non-http/https schemes (e.g., file:, javascript:, data:, mailto:, about:)
      - Local filesystem paths (/..., C:\\..., ..)
      - Credential-bearing URLs (containing '@' in authority/userinfo)
      - Obvious local/internal hostnames (localhost, *.localhost, *.local, *.internal, etc.)
      - Literal non-public IP addresses (IPv4 & IPv6 private, loopback, link-local, reserved, multicast, unspecified)
      - IPv4-mapped IPv6 addresses (e.g., ::ffff:127.0.0.1)
      - Deceptive representations (octal, hex, or decimal integer IP formats)
      - Hostnames without domain separation (e.g. intranet, host)
    """
    if not url or pd.isna(url):
        return False
    u_str = str(url).strip()
    if not u_str:
        return False

    # Block dangerous prefixes immediately
    u_lower = u_str.lower()
    for bad_prefix in ("file:", "javascript:", "data:", "mailto:", "about:", "/", "\\", "."):
        if u_lower.startswith(bad_prefix):
            return False

    try:
        parsed = urllib.parse.urlsplit(u_str)
    except Exception:
        return False

    # 1. Scheme check: strictly http and https
    if parsed.scheme.lower() not in ("http", "https"):
        return False

    # 2. Credential-bearing check: reject if username/password or '@' in netloc
    if parsed.username or parsed.password or "@" in parsed.netloc:
        return False

    # 3. Hostname check
    hostname = parsed.hostname
    if not hostname:
        return False

    hostname_lower = hostname.lower().strip(".")
    if not hostname_lower:
        return False

    # Block forbidden local and internal hostnames
    forbidden_exact = {
        "localhost", "broadcasthost", "localdomain", "loopback",
        "ip6-localhost", "ip6-loopback"
    }
    if hostname_lower in forbidden_exact:
        return False

    forbidden_suffixes = (
        ".localhost", ".local", ".internal", ".localdomain", ".lan", ".home", ".corp"
    )
    if any(hostname_lower.endswith(sfx) for sfx in forbidden_suffixes):
        return False

    # Check for deceptive numeric/hex/octal IP formats (e.g. 0x7f000001, 2130706433, 017700000001)
    if re.fullmatch(r"0x[0-9a-fA-F]+", hostname_lower) or re.fullmatch(r"\d+", hostname_lower):
        return False
    parts = hostname_lower.split(".")
    for part in parts:
        if part.startswith("0x") or (len(part) > 1 and part.startswith("0") and part.isdigit()):
            return False

    # 4. Check for IP address literal (IPv4 or IPv6)
    try:
        ip = ipaddress.ip_address(hostname_lower)
        if (
            ip.is_loopback
            or ip.is_private
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            return False
        if isinstance(ip, ipaddress.IPv4Address):
            if ip in ipaddress.IPv4Network("100.64.0.0/10") or ip == ipaddress.IPv4Address("255.255.255.255"):
                return False
        if isinstance(ip, ipaddress.IPv6Address):
            if ip.ipv4_mapped:
                mapped_v4 = ip.ipv4_mapped
                if (
                    mapped_v4.is_loopback
                    or mapped_v4.is_private
                    or mapped_v4.is_link_local
                    or mapped_v4.is_reserved
                    or mapped_v4.is_unspecified
                ):
                    return False
        return True
    except ValueError:
        pass

    # Hostname domain structure check: must have at least one dot separating domain and TLD
    if "." not in hostname_lower:
        return False

    # DNS character validation
    if not re.fullmatch(r"[a-z0-9]([a-z0-9\-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9\-]*[a-z0-9])?)+", hostname_lower):
        return False

    return True


def is_usable_url(url: Any) -> bool:
    """Checks whether a source URL is usable and syntactically safe evidence."""
    return is_safe_evidence_url(url)

def standardize_segment(val: Any) -> str:
    """Standardizes industry segment labels using clean title casing."""
    if not val or pd.isna(val):
        return "Unknown"
    s = str(val).strip()
    s_lower = s.lower()
    
    if s_lower in ["oil and gas", "oil & gas", "oil & energy"]:
        return "Oil & Gas"
    if s_lower in ["chemicals & petrochemicals", "chemical manufacturing"]:
        return "Chemicals & Petrochemicals"
    if s_lower in ["var", "imported"]:
        return "Diversified Industrial / Unspecified"
    if s_lower == "information technology & services":
        return "Information Technology"
    if s_lower in ["higher education", "education administration programs"]:
        return "Education & Training"
    if s_lower == "paper & forest products":
        return "Forest Products"
    if s_lower == "machinery":
        return "Machinery & Equipment"
    if s_lower == "maritime":
        return "Maritime & Shipping"
    if s_lower == "financial services":
        return "Financial Services"
    if s_lower == "government administration":
        return "Government Administration"
    if s_lower == "luxury goods & jewelry":
        return "Consumer / Specialty Goods"
    if s_lower == "marketing & advertising":
        return "Marketing & Communications"
    if s_lower == "retail":
        return "Retail Distribution"
    if s_lower == "construction":
        return "Construction & Civil Works"
        
    return s.title()

REVIEW_QUESTIONS = {
    "ACADEMIC_INCUBATOR": "Does this organization operate pilot process plants or industrial spinouts with physical operating procedures?",
    "TRAINING_PROVIDER": "Does this training organization own/operate industrial process facilities or license external operational procedure technology for workforce simulation?",
    "NON_OPERATOR_DISTRIBUTOR": "Does this distributor manage bulk terminal storage, gas processing plants, or physical fluid transfer operations requiring formal procedure qualification?",
    "SERVICE_CONTRACTOR": "Does this contractor operate client-owned process plant assets, offshore platforms, or drilling vessels requiring frontline procedure execution?",
    "CONSULTING_FIRM": "Does this advisory firm deliver owner's engineering or hands-on operating procedure implementation for industrial plant sites?",
    "HOLDING_COMPANY": "Which operating corporate entity or plant subsidiary holds direct ownership and operational control of the physical assets?",
    "GENERAL_NON_OPERATOR": "Does this company have direct operational control over high-hazard industrial process equipment?",
    "STANDARD_UNASSESSED": "Standard operator profile unassessed. Confirm operational plant assets during SDR discovery.",
}

def assess_customer_fit_from_record(row_or_notes: Any) -> Dict[str, Any]:
    """
    Decouples Customer Fit from Segment.
    Strictly defaults to 'FIT NOT YET ASSESSED'.
    Detects potential non-operator flags and marks 'POSSIBLE PROFILE MISMATCH — REVIEW REQUIRED'.
    Works with both raw notes or pre-sanitized profile_review / fit_review columns.
    """
    # Check if input is a DataFrame row with pre-sanitized profile_review or fit_review fields
    if hasattr(row_or_notes, "get"):
        has_profile_flag = bool(row_or_notes.get("profile_review_required", False) or row_or_notes.get("fit_review_required", False))
        if has_profile_flag:
            code = str(row_or_notes.get("profile_review_code") or row_or_notes.get("fit_review_code") or "REVIEW_REQUIRED")
            label = str(row_or_notes.get("profile_review_label") or row_or_notes.get("fit_review_label") or "Business profile requires human verification")
            kw = str(row_or_notes.get("profile_matched_keyword") or label)
            q = str(row_or_notes.get("profile_review_question") or REVIEW_QUESTIONS.get(code, "Does company operate physical process facilities?"))
            return {
                "status": "POSSIBLE PROFILE MISMATCH — REVIEW REQUIRED",
                "is_review_task": True,
                "review_code": code,
                "review_label": label,
                "matched_keyword": kw,
                "review_question": q,
                "matched_phrase": label,
                "explanation": "Profile requires human verification before commercial routing. This flag does not establish that the account is out of scope.",
            }
        notes = row_or_notes.get("notes", "")
    else:
        notes = row_or_notes

    if not notes or pd.isna(notes):
        return {
            "status": "FIT NOT YET ASSESSED",
            "is_review_task": False,
            "review_code": "STANDARD_UNASSESSED",
            "review_label": "Operational profile unassessed (standard operator candidate)",
            "matched_keyword": "",
            "review_question": REVIEW_QUESTIONS["STANDARD_UNASSESSED"],
            "matched_phrase": "",
            "explanation": "No prior operator assessment conducted. Requires qualification before commercial outreach.",
        }
    
    n_lower = str(notes).lower()
    
    review_keywords = [
        ("tech office", "Academic incubator / technology transfer office", "ACADEMIC_INCUBATOR"),
        ("technology transfer", "Academic incubator / technology transfer office", "ACADEMIC_INCUBATOR"),
        ("incubator", "Academic incubator / technology transfer office", "ACADEMIC_INCUBATOR"),
        ("university", "Academic incubator / technology transfer office", "ACADEMIC_INCUBATOR"),
        ("training center", "Third-party safety training center provider", "TRAINING_PROVIDER"),
        ("training provider", "Third-party safety training center provider", "TRAINING_PROVIDER"),
        ("training institute", "Third-party safety training center provider", "TRAINING_PROVIDER"),
        ("training academy", "Third-party safety training center provider", "TRAINING_PROVIDER"),
        ("not an o&g refiner", "Specialty product distributor / non-refining entity", "NON_OPERATOR_DISTRIBUTOR"),
        ("specialty resin", "Specialty product distributor / non-refining entity", "NON_OPERATOR_DISTRIBUTOR"),
        ("distributor", "Specialty product distributor / non-refining entity", "NON_OPERATOR_DISTRIBUTOR"),
        ("broker", "Specialty product distributor / non-refining entity", "NON_OPERATOR_DISTRIBUTOR"),
        ("service contractor", "Service contractor / non-plant asset operator", "SERVICE_CONTRACTOR"),
        ("civil works", "Service contractor / non-plant asset operator", "SERVICE_CONTRACTOR"),
        ("epc contractor", "Service contractor / non-plant asset operator", "SERVICE_CONTRACTOR"),
        ("consulting firm", "Consultancy / professional advisory service", "CONSULTING_FIRM"),
        ("consultancy", "Consultancy / professional advisory service", "CONSULTING_FIRM"),
        ("holding company only", "Holding company structure without direct operating assets", "HOLDING_COMPANY"),
        ("non-operator", "Service provider / non-operating facility", "GENERAL_NON_OPERATOR"),
        ("not an operator", "Service provider / non-operating facility", "GENERAL_NON_OPERATOR"),
        ("out of scope", "Service provider / non-operating facility", "GENERAL_NON_OPERATOR"),
    ]
    
    for kw, label, code in review_keywords:
        if kw in n_lower:
            return {
                "status": "POSSIBLE PROFILE MISMATCH — REVIEW REQUIRED",
                "is_review_task": True,
                "review_code": code,
                "review_label": label,
                "matched_keyword": kw,
                "review_question": REVIEW_QUESTIONS.get(code, "Does company operate physical process facilities?"),
                "matched_phrase": label,
                "explanation": "Profile requires human verification before commercial routing. This flag does not establish that the account is out of scope.",
            }
            
    return {
        "status": "FIT NOT YET ASSESSED",
        "is_review_task": False,
        "review_code": "STANDARD_UNASSESSED",
        "review_label": "Operational profile unassessed (standard operator candidate)",
        "matched_keyword": "",
        "review_question": REVIEW_QUESTIONS["STANDARD_UNASSESSED"],
        "matched_phrase": "",
        "explanation": "No prior operator assessment conducted. Requires qualification before commercial outreach.",
    }

assess_customer_fit_from_notes = assess_customer_fit_from_record

def is_event_active(
    event_date: Optional[date],
    trigger_type: str,
    as_of: date,
    expiry_windows: Dict[str, Dict[str, int]],
    custom_recency_days: Optional[int] = None,
) -> Tuple[bool, int, str]:
    """
    Evaluates whether an event is active as of a given reference date.
    Returns: (is_active, delta_days, window_description)
    """
    if event_date is None:
        return False, 0, "Missing event date"
        
    delta = (event_date - as_of).days  # positive if in future, negative if past
    
    if custom_recency_days is not None:
        days_ago = -delta
        is_act = (0 <= days_ago <= custom_recency_days)
        desc = f"Lookback <= {custom_recency_days} days"
        return is_act, delta, desc
        
    cfg = expiry_windows.get(
        trigger_type,
        {"past_days": 180, "future_days": 180, "label": "180d past / 180d fwd"}
    )
    past_days = cfg.get("past_days", 180)
    future_days = cfg.get("future_days", 180)
    label = cfg.get("label", f"{past_days}d past / {future_days}d fwd")
    
    is_act = (-past_days <= delta <= future_days)
    return is_act, delta, label

def derive_suggested_action(
    tier: str,
    fit_status: str,
    fit_details: Dict[str, Any],
    active_trigger_count: int,
    distinct_category_count: int,
    supporting_triggers: List[str],
    has_domain: bool,
    domain: str,
    company_name: str,
) -> Dict[str, Any]:
    """
    Determines transparent rules-based Suggested Action.
    Queue categories:
      - 'READY FOR OUTREACH': Only accounts with confirmed fit, sufficient evidence and buyer accessibility.
      - 'RESEARCH & QUALIFY NOW': Tier 1 accounts with fit unassessed.
      - 'SCOPE REVIEW HOLD': Possible out-of-scope accounts.
      - 'MONITOR': Nurture accounts (and Tier 2 unassessed / zero-trigger).
    """
    display_triggers = [TRIGGER_DISPLAY_LABELS.get(t, t) for t in supporting_triggers]
    triggers_str = ", ".join(display_triggers) if display_triggers else "None"
    
    # 1. Business Model Review (Profile Mismatch Indicator)
    if fit_status == "POSSIBLE PROFILE MISMATCH — REVIEW REQUIRED":
        review_q = fit_details.get("review_question") or REVIEW_QUESTIONS.get(fit_details.get("review_code", ""), "Does this organization own and operate physical process equipment?")
        return {
            "queue_category": "Business Model Review",
            "code": "Rule 6: Business Model Verification",
            "name": "Business Model Verification Task",
            "action": "Hold outbound. Verify whether the company operates relevant physical assets and whether EON’s use case applies before initiating contact.",
            "why_appropriate": (
                f"Review indicator: {fit_details.get('review_label', 'profile tag')}. "
                "Profile requires human verification before commercial routing. "
                "This flag does not establish that the account is out of scope. "
                "Contractor, distributor, holding company, or consultancy status is a verification signal to confirm whether the organization owns operating assets or executes physical procedure workflows."
            ),
            "research_steps": [
                f"Step 1: Check website ({domain or company_name}) to confirm physical operating assets.",
                "Step 2: Check LinkedIn to verify if company employs plant operators, chemical technicians, or HSE managers.",
                "Step 3: If confirmed as an operating facility, reclassify to Research & Qualify Now or Follow-Up Qualification. If verified non-operator, mark confirmed out of scope.",
            ],
            "discovery_question": review_q,
            "what_would_change": "Confirming operational plant facilities advances account to Research & Qualify Now or Follow-Up Qualification queue. Human confirmation of non-operator marks permanently out of scope.",
            "qualification_gate": "🛑 VERIFICATION REQUIRED: Verify physical operating assets and EON use-case applicability before outreach.",
            "missing_information": ["Operating asset confirmation vs non-operator profile"],
            "urgency": "Review Required",
            "badge_color": "orange",
        }
        
    # 2. Tier 1 Surging (Multiple Active Trigger Categories)
    if tier == "Tier 1":
        if fit_status == "FIT NOT YET ASSESSED":
            return {
                "queue_category": "Research & Qualify Now",
                "code": "Rule 4A: Surging Timing + Fit Unassessed",
                "name": "Rapid Operational Fit Scoping & Multi-Catalyst Blitz",
                "action": f"Multiple active signals detected ({distinct_category_count} types, {active_trigger_count} events). Confirm the relevant operating use case and identify the appropriate operations, maintenance or HSE buyer before outreach.",
                "why_appropriate": (
                    f"Account exhibits multiple simultaneous catalysts ({triggers_str}). "
                    "Commercial hypothesis: Accounts undergoing concurrent operational transformations face heightened procedure readiness needs. "
                    "However, ICP fit is unassessed. A 2-minute web/LinkedIn check to confirm facility operations unlocks high-conversion outreach."
                ),
                "research_steps": [
                    f"Step 1: Verify on {domain or 'corporate website'} whether {company_name} owns control rooms, operating plants, or terminals.",
                    "Step 2: Identify senior operations decision-makers (VP Operations, VP HSE, Plant Operations Director) on LinkedIn.",
                    "Step 3: Log verified operator fit in CRM to unlock commercial outreach template.",
                ],
                "discovery_question": f"Given {company_name}'s recent milestones in {triggers_str}, how is leadership harmonizing operating procedures and validating frontline competency?",
                "what_would_change": "Assessing strong fit moves this to READY FOR OUTREACH. Confirming non-operator moves to BUSINESS MODEL REVIEW.",
                "qualification_gate": "⚠️ QUALIFICATION REQUIRED: Confirm account operates physical plant facilities before deploying outreach.",
                "missing_information": ["ICP fit unverified (confirm physical plant operations)", "Target buyer contact / role title"],
                "urgency": "Immediate (This Week)",
                "badge_color": "red",
            }
        else:
            return {
                "queue_category": "Ready for Outreach",
                "code": "Rule 1: Surging Multi-Catalyst Strike",
                "name": "Multi-Thread Executive Sequence",
                "action": f"Deploy multi-touch executive campaign citing {distinct_category_count} operational milestones ({triggers_str}).",
                "why_appropriate": "High timing urgency and verified customer fit justify multi-threaded outreach to operations and safety leadership.",
                "research_steps": [
                    "Step 1: Review recent news links to reference specific facility names.",
                    "Step 2: Deploy executive email citing simultaneous milestones.",
                ],
                "discovery_question": f"How is your leadership team managing procedure standardization across {triggers_str}?",
                "what_would_change": "Decay of active triggers beyond expiry horizon would downgrade urgency to Tier 2.",
                "qualification_gate": "✅ QUALIFIED: Ready for commercial outreach.",
                "missing_information": [],
                "urgency": "Immediate (This Week)",
                "badge_color": "green",
            }
            
    # 3. Tier 2 Active (Single Milestone + Fit Unassessed)
    elif tier == "Tier 2":
        if fit_status == "FIT NOT YET ASSESSED":
            return {
                "queue_category": "Follow-Up Qualification",
                "code": "Rule 4B: Single Milestone + Fit Unassessed",
                "name": "Tier 2 Follow-Up Qualification & Milestone Discovery",
                "action": f"Active operational signal ({triggers_str}). Confirm the relevant operating use case and identify the appropriate operations, maintenance or HSE buyer before outreach.",
                "why_appropriate": (
                    f"Single operational milestone ({triggers_str}) indicates focused catalytic event. "
                    "Secondary qualification priority behind multi-catalyst Tier 1 surges. "
                    "ICP fit is unassessed; verify operating facilities before commercial pitch."
                ),
                "research_steps": [
                    f"Step 1: Check {domain or 'website'} to confirm operational plant or terminal facilities.",
                    "Step 2: Identify relevant operational or HSE lead for this milestone.",
                    "Step 3: If operator fit confirmed, queue for focused single-milestone discovery sequence.",
                ],
                "discovery_question": f"In connection with your upcoming {triggers_str} milestone, how is the operations team validating frontline procedure compliance?",
                "what_would_change": "Discovery of a second concurrent catalyst upgrades account to RESEARCH & QUALIFY NOW. Confirmed non-operator moves to BUSINESS MODEL REVIEW.",
                "qualification_gate": "⚠️ QUALIFICATION REQUIRED: Confirm operator status before outreach.",
                "missing_information": ["ICP fit unverified", "Direct operations buyer"],
                "urgency": "Follow-Up (Next 2 Weeks)",
                "badge_color": "blue",
            }
        else:
            return {
                "queue_category": "Ready for Outreach",
                "code": "Rule 2: Single Milestone Strike",
                "name": "Targeted Milestone Executive Outreach",
                "action": f"Deploy targeted outreach sequence referencing {triggers_str}.",
                "why_appropriate": "Single operational milestone and confirmed fit justify targeted outreach.",
                "research_steps": [
                    "Step 1: Reference specific facility and milestone.",
                    "Step 2: Deploy targeted sequence.",
                ],
                "discovery_question": f"How is your team preparing frontline procedures for the {triggers_str} milestone?",
                "what_would_change": "Decay of milestone beyond expiry moves to MONITOR.",
                "qualification_gate": "✅ QUALIFIED: Ready for commercial outreach.",
                "missing_information": [],
                "urgency": "Standard Outreach",
                "badge_color": "green",
            }
            
    # 4. Nurture (Zero Active Triggers)
    else:
        return {
            "queue_category": "Monitor",
            "code": "Rule 5: Zero Active Triggers",
            "name": "Automated Surveillance & Quarterly Nurture",
            "action": "Zero active qualifying triggers. Enroll in automated monitoring and quarterly industrial insights track.",
            "why_appropriate": "No active operational catalyst detected within current temporal window. Outbound selling without an event driver produces low conversion.",
            "research_steps": [
                "Step 1: Maintain in automated scan queue.",
                "Step 2: Rescan for upcoming turnaround or leadership announcements.",
            ],
            "discovery_question": "N/A — Monitored account.",
            "what_would_change": "Any newly detected capital project, leadership hire, turnaround, or M&A will promote account to Tier 1 or Tier 2.",
            "qualification_gate": "ℹ️ PASSIVE MONITORING: Do not initiate direct sales outreach.",
            "missing_information": ["Active operational catalyst", "Customer fit assessment"],
            "urgency": "Routine Surveillance",
            "badge_color": "gray",
        }

def load_wingman_portfolio(
    csv_path: Optional[Any] = None,
    as_of_date: Optional[date] = None,
    recency_days: Optional[int] = None,
    tier_mode: str = "distinct_categories",
    expiry_windows: Optional[Dict[str, Dict[str, int]]] = None,
    is_custom: bool = False,
    input_df: Optional[pd.DataFrame] = None,
) -> Dict[str, Any]:
    """
    Ingests the Wingman Trigger Export CSV (sanitized or raw) and computes dynamic portfolio state.
    Strictly independent: operates with zero imports or fallbacks from PDF-derived data.
    Supports in-memory DataFrames for session-scoped custom uploads.
    """
    if as_of_date is None:
        as_of_date = DEFAULT_AS_OF_DATE
    if expiry_windows is None:
        expiry_windows = DEFAULT_EXPIRY_WINDOWS
        
    project_root = Path(__file__).resolve().parents[1]
    
    if input_df is not None:
        raw_df = input_df.copy()
    elif isinstance(csv_path, pd.DataFrame):
        raw_df = csv_path.copy()
    else:
        if csv_path is None:
            # Check sanitized dataset first for external review build, fallback to local_data
            sanitized_path = project_root / "data" / "wingman-trigger-export-2026-09-17-sanitized.csv"
            raw_local_path = project_root / "local_data" / "wingman-trigger-export-2026-09-17.csv"
            
            if sanitized_path.exists():
                csv_path = str(sanitized_path)
            elif raw_local_path.exists():
                csv_path = str(raw_local_path)
            else:
                raise FileNotFoundError(f"Neither sanitized CSV ({sanitized_path}) nor raw CSV ({raw_local_path}) found.")

        p = Path(csv_path)
        if not p.exists():
            # Try resolving relative to current working directory
            p = Path("data/wingman-trigger-export-2026-09-17-sanitized.csv")
            if not p.exists():
                p = Path("local_data/wingman-trigger-export-2026-09-17.csv")
            if not p.exists():
                raise FileNotFoundError(f"Wingman CSV not found at {csv_path}")

        # Read with utf-8-sig BOM support
        raw_df = pd.read_csv(p, encoding="utf-8-sig")

    raw_df.columns = [c.strip() for c in raw_df.columns]
    
    # Ensure standard columns exist with defaults if missing in custom upload
    if "company" not in raw_df.columns:
        raw_df["company"] = ""
    if "domain" not in raw_df.columns:
        raw_df["domain"] = ""
    if "segment" not in raw_df.columns:
        raw_df["segment"] = "Diversified Industrial / Unspecified"
    if "source_tier" not in raw_df.columns and "tier" in raw_df.columns:
        raw_df["source_tier"] = raw_df["tier"]
    elif "source_tier" not in raw_df.columns:
        raw_df["source_tier"] = 3
    if "trigger_type" not in raw_df.columns:
        raw_df["trigger_type"] = ""
    if "trigger_date" not in raw_df.columns:
        raw_df["trigger_date"] = ""
    if "trigger_summary" not in raw_df.columns:
        raw_df["trigger_summary"] = ""
    if "trigger_source_url" not in raw_df.columns:
        raw_df["trigger_source_url"] = ""

    total_raw_rows = len(raw_df)
    
    # Standardize basic columns
    raw_df["clean_company"] = raw_df["company"].apply(normalize_company_name)
    raw_df["clean_domain"] = raw_df["domain"].apply(normalize_domain)
    raw_df["standardized_segment"] = raw_df["segment"].apply(standardize_segment)
    raw_df["parsed_trigger_date"] = raw_df["trigger_date"].apply(parse_iso_date)
    raw_df["trigger_type_clean"] = raw_df["trigger_type"].fillna("").astype(str).str.strip()
    raw_df["has_usable_url"] = raw_df["trigger_source_url"].apply(is_usable_url)
    
    # Event Deduplication Key: (company, trigger_type, summary_snippet, year_month)
    def make_event_dedup_key(row):
        t_type = row["trigger_type_clean"]
        if not t_type:
            return None
        c_name = row["clean_company"].lower()
        summ = str(row.get("trigger_summary", "")).strip().lower()[:40]
        dt = row["parsed_trigger_date"]
        ym = f"{dt.year}-{dt.month:02d}" if dt else "no-date"
        return f"{c_name}::{t_type}::{summ}::{ym}"
        
    raw_df["dedup_event_id"] = raw_df.apply(make_event_dedup_key, axis=1)
    
    # Account Identity Key: group by exact company string
    raw_df["domain_filled"] = raw_df["domain"].fillna("")
    company_groups = raw_df.groupby("company")
    unique_company_count = len(company_groups)
    
    null_domain_count = int(raw_df["domain"].isna().sum() + (raw_df["domain"].astype(str).str.strip().isin(["", "nan"])).sum())
    domain_to_comps = raw_df.dropna(subset=["domain"]).groupby("domain")["company"].nunique()
    shared_domain_count = int((domain_to_comps > 1).sum())
    
    companies_summary = []
    all_active_events = []
    all_considered_events = []
    tier_audit_rows = []
    
    for comp_name, group in company_groups:
        first_row = group.iloc[0]
        domain = first_row.get("domain", "")
        clean_dom = normalize_domain(domain)
        segment = first_row["standardized_segment"]
        scanned_at = first_row.get("scanned_at", "")
        
        # Disambiguate tiers: retained Wingman export tier is source_tier
        if "source_tier" in first_row and pd.notna(first_row["source_tier"]):
            try:
                source_tier_num = int(first_row["source_tier"])
            except ValueError:
                source_tier_num = 3
        elif "tier" in first_row and pd.notna(first_row["tier"]):
            try:
                source_tier_num = int(first_row["tier"])
            except ValueError:
                source_tier_num = 3
        else:
            source_tier_num = 3
        source_tier = f"Tier {source_tier_num}"
        raw_tier = source_tier_num
        
        # Fit assessment: check if pre-sanitized columns exist
        if "fit_review_required" in first_row:
            fit_details = assess_customer_fit_from_record(first_row)
        elif is_custom:
            # Custom upload without explicit profile review columns defaults to unassessed
            fit_details = assess_customer_fit_from_record("")
        else:
            all_notes = " | ".join([str(n) for n in group.get("notes", pd.Series()).dropna().unique() if str(n).strip()])
            fit_details = assess_customer_fit_from_record(all_notes)
            
        fit_status = fit_details["status"]
        
        # Collect and evaluate all source triggers considered
        valid_trigger_rows = group[group["trigger_type_clean"] != ""]
        
        active_events = []
        expired_events = []
        seen_event_keys = set()
        
        company_event_audits = []
        
        for _, erow in valid_trigger_rows.iterrows():
            dkey = erow["dedup_event_id"]
            if dkey in seen_event_keys:
                continue
            seen_event_keys.add(dkey)
            
            t_type = erow["trigger_type_clean"]
            t_date = erow["parsed_trigger_date"]
            usable_url = erow["has_usable_url"]
            
            is_recognized = t_type in VALID_TRIGGER_TYPES

            if is_recognized:
                is_active, delta_days, window_desc = is_event_active(
                    event_date=t_date,
                    trigger_type=t_type,
                    as_of=as_of_date,
                    expiry_windows=expiry_windows,
                    custom_recency_days=recency_days,
                )
                display_trigger = TRIGGER_DISPLAY_LABELS.get(t_type, t_type.replace("_", " ").title())
                status_str = "ACTIVE" if is_active else "EXPIRED"
            else:
                # Unrecognized / unknown trigger type: exclude from dynamic tiering & catalyst rankings
                is_active = False
                delta_days = (as_of_date - t_date).days if t_date else 99999
                window_desc = "Excluded from dynamic tiers (unrecognized trigger type)"
                display_trigger = f"Unclassified ({t_type})"
                status_str = "UNCLASSIFIED"
            
            evidence_status = "Evidence Link Available" if usable_url else "Unverified / Internal Scan Record"
            
            event_record = {
                "company": comp_name,
                "domain": clean_dom,
                "segment": segment,
                "trigger_type": t_type,
                "trigger_type_display": display_trigger,
                "raw_trigger_date": str(erow.get("trigger_date", "")),
                "parsed_date": t_date,
                "dedup_event_id": dkey,
                "delta_days": delta_days,
                "window_applied": window_desc,
                "temporal_status": status_str,
                "is_active": is_active,
                "trigger_summary": erow.get("trigger_summary", ""),
                "trigger_source_url": erow.get("trigger_source_url", ""),
                "has_usable_url": usable_url,
                "evidence_status": evidence_status,
            }
            
            company_event_audits.append(event_record)
            all_considered_events.append(event_record)
            
            if is_active:
                active_events.append(event_record)
                all_active_events.append(event_record)
            else:
                expired_events.append(event_record)
                
        # Calculate dynamic tier
        active_categories = sorted(list(set(e["trigger_type"] for e in active_events)))
        active_cat_count = len(active_categories)
        active_evt_count = len(active_events)
        
        active_display_labels = [TRIGGER_DISPLAY_LABELS.get(t, t) for t in active_categories]
        
        if tier_mode == "distinct_categories":
            if active_cat_count >= 2:
                dynamic_tier = "Tier 1"
                tier_reason = (
                    f"Tier 1: Evaluated via Proposed Default (Distinct Categories Mode) "
                    f"due to {active_cat_count} active distinct categories: [{', '.join(active_display_labels)}]."
                )
            elif active_cat_count == 1:
                dynamic_tier = "Tier 2"
                tier_reason = (
                    f"Tier 2: Evaluated via Proposed Default (Distinct Categories Mode) "
                    f"due to exactly 1 active category: [{active_display_labels[0]}]."
                )
            else:
                dynamic_tier = "Nurture"
                if company_event_audits:
                    tier_reason = (
                        f"Nurture: 0 active categories (all {len(company_event_audits)} considered source event(s) "
                        f"are expired relative to reference date {as_of_date})."
                    )
                else:
                    tier_reason = "Nurture: 0 qualifying operational triggers detected during scan."
        else:  # event_count mode
            if active_evt_count >= 2:
                dynamic_tier = "Tier 1"
                tier_reason = f"Tier 1: Evaluated via Event Count Mode due to {active_evt_count} active deduplicated events."
            elif active_evt_count == 1:
                dynamic_tier = "Tier 2"
                tier_reason = "Tier 2: Evaluated via Event Count Mode due to exactly 1 active deduplicated event."
            else:
                dynamic_tier = "Nurture"
                tier_reason = "Nurture: 0 active deduplicated events."
                
        # Date bounds: separate observed activity (<= as_of_date) from upcoming milestones (> as_of_date)
        all_source_dates = [e["parsed_date"] for e in company_event_audits if e.get("parsed_date") is not None]
        all_source_observed = [d for d in all_source_dates if d <= as_of_date]
        all_source_upcoming = [d for d in all_source_dates if d > as_of_date]
        latest_source_activity = str(max(all_source_observed)) if all_source_observed else ""
        latest_source_activity_date = max(all_source_observed) if all_source_observed else None
        next_source_milestone = str(min(all_source_upcoming)) if all_source_upcoming else ""
        next_source_milestone_date = min(all_source_upcoming) if all_source_upcoming else None
        first_source_activity = str(min(all_source_dates)) if all_source_dates else ""

        valid_dates = [e["parsed_date"] for e in active_events if e["parsed_date"] is not None]
        first_date = min(valid_dates) if valid_dates else None
        last_date = max(valid_dates) if valid_dates else None

        observed_active_dates = [d for d in valid_dates if d <= as_of_date]
        upcoming_active_dates = [d for d in valid_dates if d > as_of_date]

        latest_observed_activity_date = max(observed_active_dates) if observed_active_dates else None
        latest_observed_activity = str(latest_observed_activity_date) if latest_observed_activity_date else ""

        next_upcoming_milestone_date = min(upcoming_active_dates) if upcoming_active_dates else None
        next_upcoming_milestone = str(next_upcoming_milestone_date) if next_upcoming_milestone_date else ""

        # Display with Upcoming prefix for future dates
        if latest_observed_activity:
            latest_activity_display = latest_observed_activity
        elif next_upcoming_milestone:
            latest_activity_display = f"Upcoming: {next_upcoming_milestone}"
        else:
            latest_activity_display = "No current catalyst"

        latest_active_catalyst = latest_observed_activity if latest_observed_activity else (next_upcoming_milestone if next_upcoming_milestone else "")
        latest_active_catalyst_date = latest_observed_activity_date if latest_observed_activity_date else next_upcoming_milestone_date
        latest_active_catalyst_display = latest_activity_display
        
        source_verified_count = sum(1 for e in active_events if e["has_usable_url"])
        
        # Suggested Action & Queue Category
        action_data = derive_suggested_action(
            tier=dynamic_tier,
            fit_status=fit_status,
            fit_details=fit_details,
            active_trigger_count=active_evt_count,
            distinct_category_count=active_cat_count,
            supporting_triggers=active_categories,
            has_domain=bool(clean_dom),
            domain=domain,
            company_name=comp_name,
        )
        
        tier_mode_desc = (
            "Proposed Default: Distinct Categories (>=2 active categories = Tier 1)"
            if tier_mode == "distinct_categories"
            else "Alternative: Event Count Mode (>=2 active events = Tier 1)"
        )
        
        company_record = {
            "company_name": comp_name,
            "domain": domain if domain and str(domain).lower() != "nan" else "",
            "clean_domain": clean_dom,
            "segment": segment,
            "source_tier": source_tier,
            "computed_tier": dynamic_tier,
            "computed_tier_rule": tier_mode_desc,
            "computed_as_of_date": str(as_of_date),
            "tier": dynamic_tier,
            "raw_tier": source_tier,
            "tier_reason": tier_reason,
            "current_status": action_data["queue_category"],
            "queue_category": action_data["queue_category"],
            "distinct_category_count": active_cat_count,
            "active_event_count": active_evt_count,
            "total_considered_triggers": len(company_event_audits),
            "source_verified_count": source_verified_count,
            "trigger_types": ", ".join(active_display_labels) if active_display_labels else "None",
            "trigger_type_list": active_categories,
            "first_trigger_date": str(first_date) if first_date else "",
            "last_trigger_date": str(last_date) if last_date else "",
            "latest_source_activity": latest_source_activity,
            "latest_source_activity_date": latest_source_activity_date,
            "next_source_milestone": next_source_milestone,
            "next_source_milestone_date": next_source_milestone_date,
            "first_source_activity": first_source_activity,
            "latest_observed_activity": latest_observed_activity,
            "latest_observed_activity_date": latest_observed_activity_date,
            "next_upcoming_milestone": next_upcoming_milestone,
            "next_upcoming_milestone_date": next_upcoming_milestone_date,
            "latest_activity_display": latest_activity_display,
            "latest_active_catalyst": latest_observed_activity,
            "latest_active_catalyst_date": latest_observed_activity_date,
            "latest_active_catalyst_display": latest_activity_display,
            "fit_status": fit_status,
            "profile_review_required": fit_status == "POSSIBLE PROFILE MISMATCH — REVIEW REQUIRED",
            "profile_review_code": fit_details.get("review_code", "STANDARD_UNASSESSED"),
            "profile_review_label": fit_details.get("review_label", ""),
            "profile_matched_keyword": fit_details.get("matched_keyword", ""),
            "profile_review_question": fit_details.get("review_question", ""),
            "fit_review_code": fit_details.get("review_code", "STANDARD_UNASSESSED"),
            "fit_review_label": fit_details.get("review_label", ""),
            "fit_explanation": fit_details["explanation"],
            "fit_matched_phrase": fit_details.get("matched_phrase", ""),
            "fit_note_excerpt": fit_details.get("review_label", ""),
            "suggested_action": action_data["action"],
            "suggested_playbook": action_data["code"] + ": " + action_data["name"],
            "action_urgency": action_data["urgency"],
            "action_badge_color": action_data["badge_color"],
            "action_details": action_data,
            "scanned_at": scanned_at,
            "raw_row_count": len(group),
        }
        
        companies_summary.append(company_record)
        
        # Tier audit row for export
        tier_audit_rows.append({
            "company_name": comp_name,
            "domain": domain,
            "segment": segment,
            "source_tier": source_tier,
            "computed_tier": dynamic_tier,
            "computed_tier_rule": tier_mode_desc,
            "computed_as_of_date": str(as_of_date),
            "assigned_tier": dynamic_tier,
            "tiering_rule": tier_mode_desc,
            "tier_assignment_reason": tier_reason,
            "current_status": action_data["queue_category"],
            "queue_category": action_data["queue_category"],
            "distinct_active_categories": active_cat_count,
            "active_events_count": active_evt_count,
            "total_source_rows_in_csv": len(group),
            "active_categories_list": ", ".join(active_display_labels),
            "customer_fit_status": fit_status,
            "profile_review_code": fit_details.get("review_code", "STANDARD_UNASSESSED"),
            "profile_review_label": fit_details.get("review_label", ""),
            "profile_review_question": fit_details.get("review_question", ""),
            "fit_review_reason": fit_details.get("review_label", "Standard Unassessed"),
            "first_active_milestone_date": str(first_date) if first_date else "",
            "latest_active_milestone_date": str(last_date) if last_date else "",
            "latest_source_activity": latest_source_activity,
            "latest_active_catalyst": latest_active_catalyst,
            "source_urls_present_count": source_verified_count,
        })
        
    companies_df = pd.DataFrame(companies_summary)
    active_events_df = pd.DataFrame(all_active_events)
    all_considered_events_df = pd.DataFrame(all_considered_events)
    tier_audit_df = pd.DataFrame(tier_audit_rows)
    
    # Transparent deterministic ranking within and across queues:
    # 1. Queue Category rank (READY -> QUALIFY NOW -> BUSINESS MODEL REVIEW -> FOLLOW-UP -> MONITOR)
    # 2. Computed Tier rank (Tier 1 -> Tier 2 -> Nurture)
    # 3. Number of distinct active categories (descending)
    # 4. Total active events count (descending)
    # 5. Milestone recency (last_trigger_date descending)
    # 6. Evidence availability (source_verified_count descending)
    # 7. Profile review required flag (standard False first, review required True second)
    # 8. Company name (ascending alphabetical tie-breaker)
    queue_order = {
        "Ready for Outreach": 0,
        "READY FOR OUTREACH": 0,
        "Research & Qualify Now": 1,
        "RESEARCH & QUALIFY NOW": 1,
        "Business Model Review": 2,
        "BUSINESS MODEL REVIEW": 2,
        "Follow-Up Qualification": 3,
        "FOLLOW-UP QUALIFICATION": 3,
        "Monitor": 4,
        "MONITOR": 4,
    }
    tier_order = {"Tier 1": 0, "Tier 2": 1, "Nurture": 2}
    companies_df["queue_rank"] = companies_df["queue_category"].map(queue_order).fillna(99)
    companies_df["tier_rank"] = companies_df["tier"].map(tier_order).fillna(99)
    companies_df["profile_rank"] = companies_df["profile_review_required"].astype(int)
    
    companies_df = companies_df.sort_values(
        by=[
            "queue_rank",
            "tier_rank",
            "distinct_category_count",
            "active_event_count",
            "last_trigger_date",
            "source_verified_count",
            "profile_rank",
            "company_name",
        ],
        ascending=[True, True, False, False, False, False, True, True]
    ).reset_index(drop=True)
    
    def make_ranking_rationale(row):
        cats = row["distinct_category_count"]
        evts = row["active_event_count"]
        last_d = row["last_trigger_date"] if row["last_trigger_date"] else "None"
        urls = row["source_verified_count"]
        return f"{row['tier']} | {cats} active cat(s) | {evts} event(s) | Latest: {last_d} | Evidence: {urls} URL(s)"
        
    companies_df["ranking_rationale"] = companies_df.apply(make_ranking_rationale, axis=1)
    
    # Portfolio Metrics
    t1_count = int((companies_df["tier"] == "Tier 1").sum())
    t2_count = int((companies_df["tier"] == "Tier 2").sum())
    nurture_count = int((companies_df["tier"] == "Nurture").sum())
    total_companies = len(companies_df)
    
    # Five-Category Queue Allocation Metrics
    ready_outreach_count = int((companies_df["queue_category"].str.upper() == "READY FOR OUTREACH").sum())
    research_qualify_count = int((companies_df["queue_category"].str.upper() == "RESEARCH & QUALIFY NOW").sum())
    business_model_review_count = int((companies_df["queue_category"].str.upper() == "BUSINESS MODEL REVIEW").sum())
    follow_up_qualify_count = int((companies_df["queue_category"].str.upper() == "FOLLOW-UP QUALIFICATION").sum())
    monitor_count = int((companies_df["queue_category"].str.upper() == "MONITOR").sum())
    
    metrics = {
        "total_companies": total_companies,
        "total_raw_rows": total_raw_rows,
        "tier_1_count": t1_count,
        "tier_1_pct": round(100.0 * t1_count / total_companies, 1) if total_companies > 0 else 0,
        "tier_2_count": t2_count,
        "tier_2_pct": round(100.0 * t2_count / total_companies, 1) if total_companies > 0 else 0,
        "nurture_count": nurture_count,
        "nurture_pct": round(100.0 * nurture_count / total_companies, 1) if total_companies > 0 else 0,
        "active_events_total": len(all_active_events),
        "unassessed_fit_count": int((companies_df["fit_status"] == "FIT NOT YET ASSESSED").sum()),
        "review_required_fit_count": int((companies_df["fit_status"] == "POSSIBLE PROFILE MISMATCH — REVIEW REQUIRED").sum()),
        "ready_outreach_count": ready_outreach_count,
        "research_qualify_count": research_qualify_count,
        "business_model_review_count": business_model_review_count,
        "scope_hold_count": business_model_review_count,  # backward compatibility alias
        "scope_review_count": business_model_review_count, # backward compatibility alias
        "follow_up_qualify_count": follow_up_qualify_count,
        "monitor_count": monitor_count,
        "null_domain_count": null_domain_count,
        "shared_domain_count": shared_domain_count,
    }
    
    # Co-Occurrence Matrix & Lift Calculation
    all_categories = sorted(list(VALID_TRIGGER_TYPES))
    matrix_data = {c: {c2: 0 for c2 in all_categories} for c in all_categories}
    pair_counts = {}
    cat_prevalence = {c: 0 for c in all_categories}
    
    for _, row in companies_df.iterrows():
        types = sorted(row["trigger_type_list"])
        for t in types:
            if t in cat_prevalence:
                cat_prevalence[t] += 1
        for i in range(len(types)):
            t1 = types[i]
            if t1 in matrix_data:
                matrix_data[t1][t1] += 1
            for j in range(i + 1, len(types)):
                t2 = types[j]
                if t1 in matrix_data and t2 in matrix_data[t1]:
                    matrix_data[t1][t2] += 1
                    matrix_data[t2][t1] += 1
                pair_key = (t1, t2) if t1 < t2 else (t2, t1)
                pair_counts[pair_key] = pair_counts.get(pair_key, 0) + 1
                
    co_occurrence_df = pd.DataFrame(matrix_data)
    
    # Calculate Observed vs Expected Lift:
    # Expected(A, B) = (Count(A) * Count(B)) / Total_Companies
    # Lift = Observed / Expected
    top_combinations = []
    for (t1, t2), obs_count in sorted(pair_counts.items(), key=lambda x: x[1], reverse=True):
        cA = cat_prevalence.get(t1, 0)
        cB = cat_prevalence.get(t2, 0)
        expected = (cA * cB) / total_companies if total_companies > 0 else 1.0
        lift = round(obs_count / expected, 2) if expected > 0 else 1.0
        
        top_combinations.append({
            "pair": f"{t1} + {t2}",
            "pair_display": f"{TRIGGER_DISPLAY_LABELS.get(t1, t1)} + {TRIGGER_DISPLAY_LABELS.get(t2, t2)}",
            "count": obs_count,
            "observed_count": obs_count,
            "expected_count": round(expected, 1),
            "lift": lift,
            "pct_universe": round(100.0 * obs_count / total_companies, 1),
            "has_low_support": obs_count <= 5,
            "support_warning": "⚠️ Low Support (<=5 accounts): Exploratory pattern only; small sample" if obs_count <= 5 else "Robust Portfolio Support",
            "interpretation": "Above Independence Expectation" if lift > 1.0 else "At/Below Independence Expectation",
        })
        
    # Pairwise Lift Matrix DataFrame
    lift_matrix_data = {c: {c2: 0.0 for c2 in all_categories} for c in all_categories}
    for c1 in all_categories:
        for c2 in all_categories:
            if c1 == c2:
                cA = cat_prevalence.get(c1, 0)
                lift_matrix_data[c1][c2] = round(total_companies / cA, 2) if cA > 0 else 0.0
            else:
                pair_key = (c1, c2) if c1 < c2 else (c2, c1)
                obs_count = pair_counts.get(pair_key, 0)
                cA = cat_prevalence.get(c1, 0)
                cB = cat_prevalence.get(c2, 0)
                expected = (cA * cB) / total_companies if total_companies > 0 else 1.0
                lift_matrix_data[c1][c2] = round(obs_count / expected, 2) if expected > 0 else 0.0
    pairwise_lift_matrix = pd.DataFrame(lift_matrix_data)
        
    # Archetype Cohorts framed as Commercial Hypotheses & Discovery Questions
    archetype_definitions = {
        "Commissioning + Hiring": {
            "required_types": ["project_fid_commissioning", "hiring_burst"],
            "operational_need": "Capital projects approaching startup require simultaneous contractor onboarding and procedure qualification.",
            "commercial_hypothesis": "Operators staffing for commissioning milestones may benefit from digital procedure qualification workflows to accelerate time-to-competency.",
            "discovery_question": "How is your team qualifying newly hired technicians against site procedures ahead of facility startup?",
        },
        "M&A + Commissioning": {
            "required_types": ["ma_acquisition", "project_fid_commissioning"],
            "operational_need": "Acquired operating facilities undergoing capital expansion require unified operating standards and safety procedures.",
            "commercial_hypothesis": "Post-acquisition integration coupled with project delivery creates urgent demand for procedure harmonization across operating sites.",
            "discovery_question": "What is your approach to harmonizing operating procedures across newly acquired assets and ongoing capital expansion projects?",
        },
        "M&A + Hiring": {
            "required_types": ["ma_acquisition", "hiring_burst"],
            "operational_need": "Post-merger workforce integration and procedure alignment across newly acquired operating units.",
            "commercial_hypothesis": "Cross-training operators across newly acquired sites reduces procedure deviation risk during organizational transitions.",
            "discovery_question": "How are you ensuring consistent procedure compliance as teams integrate across acquired operations?",
        },
        "Turnaround + Audit/Regulator": {
            "required_types": ["turnaround", "incident_regulator"],
            "operational_need": "Maintenance turnarounds conducted under regulatory scrutiny (OSHA, CSB, SEMS).",
            "commercial_hypothesis": "Turnaround teams subject to regulatory compliance require audited digital verification of safety-critical permits and procedures.",
            "discovery_question": "How are safety-critical procedures digitally verified during your turnaround execution to satisfy regulatory compliance?",
        },
        "Turnaround + Hiring": {
            "required_types": ["turnaround", "hiring_burst"],
            "operational_need": "Major plant overhaul requiring massive temporary contractor ramp-up.",
            "commercial_hypothesis": "Pre-turnaround contractor training and digital permit verification reduce shutdown delays and contractor onboarding bottlenecks.",
            "discovery_question": "What digital workflows are you using to qualify contractor technicians prior to their arrival on site for the turnaround?",
        },
        "New Leader + Commissioning": {
            "required_types": ["new_leader", "project_fid_commissioning"],
            "operational_need": "New executive leadership managing high-profile project deliveries seeking operational readiness assurance.",
            "commercial_hypothesis": "Incoming leaders frequently seek rapid procedural modernization to de-risk high-visibility capital project startups.",
            "discovery_question": "As new leadership prepares for upcoming facility startup milestones, what initiatives are underway to de-risk frontline procedure execution?",
        },
    }
    
    archetypes = {}
    for arch_name, a_meta in archetype_definitions.items():
        matched_companies = []
        for _, row in companies_df.iterrows():
            tl = set(row["trigger_type_list"])
            if all(t in tl for t in a_meta["required_types"]):
                matched_companies.append({
                    "company_name": row["company_name"],
                    "domain": row["domain"],
                    "tier": row["tier"],
                    "segment": row["segment"],
                    "trigger_types": row["trigger_types"],
                    "queue_category": row["queue_category"],
                    "suggested_playbook": row["suggested_playbook"],
                })
        archetypes[arch_name] = {
            "meta": a_meta,
            "companies": matched_companies,
            "count": len(matched_companies),
        }
        
    return {
        "raw_df": raw_df,
        "companies_df": companies_df,
        "active_events_df": active_events_df,
        "all_considered_events_df": all_considered_events_df,
        "tier_audit_df": tier_audit_df,
        "co_occurrence_df": co_occurrence_df,
        "pairwise_lift_matrix": pairwise_lift_matrix,
        "top_combinations": top_combinations,
        "archetypes": archetypes,
        "metrics": metrics,
        "as_of_date": as_of_date,
        "tier_mode": tier_mode,
        "pair_counts": pair_counts,
        "cat_prevalence": cat_prevalence,
        "all_categories": all_categories,
    }


def generate_portfolio_observations(portfolio_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Dynamically generates portfolio observation cards with sample-size guardrails.
    Sample size tiers (treated as presentation guardrails, not statistical significance):
      - N < 10: Descriptive metrics only; suppress lift, co-occurrence conclusions,
        and strategic implication text.
      - 10 <= N <= 29: Exploratory patterns with exploratory badges and caveats.
      - N >= 30: Standard dashboard behavior (does not claim statistical significance).
    Always shows supporting numerator, denominator, and percentage.
    """
    companies_df = portfolio_data.get("companies_df", pd.DataFrame())
    top_combinations = portfolio_data.get("top_combinations", [])
    expiry_windows = portfolio_data.get("expiry_windows", DEFAULT_EXPIRY_WINDOWS)
    total = len(companies_df)
    if total == 0:
        return []

    observations = []

    # 1. Commissioning Dominance (Descriptive Fact)
    comm_count = int(sum(1 for tl in companies_df["trigger_type_list"] if "project_fid_commissioning" in tl))
    comm_pct = round(100.0 * comm_count / total, 1)

    comm_obs = {
        "id": "commissioning_dominance",
        "title": "Project Commissioning Dominance",
        "icon": "🏗️",
        "badge": f"{comm_count} of {total} Accounts ({comm_pct}%)",
        "fact": f"{comm_count} of {total} companies ({comm_pct}%) have active commissioning or FID milestones.",
        "filter_type": "catalyst",
        "filter_value": "Project Commissioning / FID",
        "affected_count": comm_count,
        "affected_pct": comm_pct,
    }
    if total < 10:
        # Suppress strategic implication text for N < 10
        comm_obs["hypothesis"] = None
    elif total < 30:
        comm_obs["hypothesis"] = (
            f"[Exploratory observation for N={total}]: Pre-startup readiness and contractor ramp-up may create procedure verification demand."
        )
    else:
        comm_obs["hypothesis"] = (
            "Pre-startup readiness and contractor ramp-up may create urgent procedure verification demand."
        )
    observations.append(comm_obs)

    # 2. Multiple Active Signals (Descriptive Fact)
    multi_count = int(sum(1 for c in companies_df["distinct_category_count"] if c >= 2))
    multi_pct = round(100.0 * multi_count / total, 1)

    multi_obs = {
        "id": "multi_catalyst_surges",
        "title": "Multiple Active Signals",
        "icon": "⚡",
        "badge": f"{multi_count} of {total} Accounts ({multi_pct}%)",
        "fact": f"{multi_count} of {total} companies ({multi_pct}%) have 2+ distinct active operational signal types.",
        "filter_type": "multi_catalyst",
        "filter_value": True,
        "affected_count": multi_count,
        "affected_pct": multi_pct,
    }
    if total < 10:
        # Suppress strategic implication text for N < 10
        multi_obs["hypothesis"] = None
    elif total < 30:
        multi_obs["hypothesis"] = (
            f"[Exploratory observation for N={total}]: Compounding operational triggers may increase site complexity and frontline risk."
        )
    else:
        multi_obs["hypothesis"] = (
            "Compounding operational triggers may increase site complexity, frontline risk, and software readiness."
        )
    observations.append(multi_obs)

    # 3. Top Supported Catalyst Pairing / Co-occurrence
    # For N < 10: Completely suppress lift and co-occurrence conclusions!
    if total >= 10:
        min_support = 15 if total >= 50 else max(2, int(total * 0.15))
        supported_combos = [c for c in top_combinations if c.get("count", 0) >= min_support]
        if supported_combos:
            best_pair = max(supported_combos, key=lambda x: x.get("lift", 0.0))
            p_name = best_pair["pair_display"]
            p_count = best_pair["count"]
            p_pct = best_pair["pct_universe"]
            p_lift = best_pair["lift"]

            is_exploratory = total < 30
            badge_str = (
                f"{p_count} of {total} Accounts (Exploratory · {p_lift}x baseline)"
                if is_exploratory
                else f"{p_count} of {total} Accounts ({p_lift}x baseline)"
            )
            hyp_str = (
                f"[Exploratory pattern for N={total}]: Concurrent project delivery and turnaround maintenance may indicate multi-facility procedure demand."
                if is_exploratory
                else "Concurrent project delivery and turnaround maintenance may require unified procedure controls."
            )

            pair_tuple = best_pair.get("pair", ())
            if "project_fid_commissioning" in pair_tuple and "turnaround" in pair_tuple:
                pair_title = "Commissioning + Turnaround"
            else:
                pair_title = p_name or "Commissioning + Turnaround"

            observations.append({
                "id": "synergistic_pair",
                "title": pair_title,
                "icon": "🔄",
                "badge": badge_str,
                "fact": f"Co-occurs in {p_count} of {total} companies ({p_pct}%), at {p_lift}x the frequency expected under an independence baseline.",
                "hypothesis": hyp_str,
                "filter_type": "catalyst_pair",
                "filter_value": best_pair["pair"],
                "affected_count": p_count,
                "affected_pct": p_pct,
            })

    return observations

def get_similar_companies(target_company: str, companies_df: pd.DataFrame, top_n: int = 6) -> List[Dict[str, Any]]:
    """
    Computes Jaccard similarity of trigger types between the target company and all other companies.
    Jaccard(A, B) = |Types(A) ∩ Types(B)| / |Types(A) ∪ Types(B)|.
    Provides complete transparency into:
      - Shared Catalysts
      - Benchmark-Only Catalysts (in benchmark, missing in peer)
      - Peer-Only Catalysts (in peer, missing in benchmark; explicitly clarifies when None)
    """
    target_row = companies_df[companies_df["company_name"] == target_company]
    if target_row.empty:
        return []
    
    t_types = set(target_row.iloc[0]["trigger_type_list"])
    if not t_types:
        return []
        
    scores = []
    for _, row in companies_df.iterrows():
        comp = row["company_name"]
        if comp == target_company:
            continue
        c_types = set(row["trigger_type_list"])
        if not c_types:
            continue
            
        shared = t_types & c_types
        benchmark_only = t_types - c_types
        peer_only = c_types - t_types
        
        union = len(t_types | c_types)
        sim = len(shared) / union if union > 0 else 0.0
        
        if sim > 0:
            scores.append({
                "company_name": comp,
                "domain": row["domain"],
                "source_tier": row.get("source_tier", 3),
                "computed_tier": row.get("computed_tier", row["tier"]),
                "tier": row["tier"],
                "segment": row["segment"],
                "similarity_score": round(sim, 2),
                "shared_triggers": [TRIGGER_DISPLAY_LABELS.get(t, t) for t in sorted(list(shared))],
                "benchmark_only_triggers": [TRIGGER_DISPLAY_LABELS.get(t, t) for t in sorted(list(benchmark_only))],
                "peer_only_triggers": [TRIGGER_DISPLAY_LABELS.get(t, t) for t in sorted(list(peer_only))],
                "suggested_playbook": row["suggested_playbook"],
                "queue_category": row["queue_category"],
            })
            
    scores = sorted(scores, key=lambda x: (x["similarity_score"], len(x["shared_triggers"])), reverse=True)
    return scores[:top_n]
