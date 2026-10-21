"""
Centralized Data Source & Session Management for Wingman Dashboard
EON Commercial Intelligence | External Review Build — Proposed Phase 1

Provides session-scoped dataset management:
- Default sanitized Wingman dataset (785 companies)
- Validated custom CSV uploads (isolated to active browser session)
- Versioned schema v1.0.0 with canonical column mapping and alias normalization
- Pre-activation validation engine (blocking errors vs non-blocking warnings)
- Dual template downloads (blank CSV headers only + example dataset with sample rows)
- Source switching with clean state reset
- In-memory processing with zero disk writes, logs, or cross-session leakage
"""

import copy
import csv
import datetime
from datetime import date
import hashlib
import html
import inspect
import io
import ipaddress
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Set, Tuple
import urllib.parse

import pandas as pd
import streamlit as st

from dashboard.wingman_portfolio import (
    load_wingman_portfolio,
    DEFAULT_AS_OF_DATE,
    DEFAULT_EXPIRY_WINDOWS,
    TRIGGER_DISPLAY_LABELS,
    VALID_TRIGGER_TYPES,
    is_safe_evidence_url,
)

SCHEMA_VERSION = "1.0.0"

# Upload Limits (Hardening Guardrails)
# These conservative limits reduce the risk of excessive memory use and interface delays
# in concurrent sessions.
# Note: Measured performance on 20,000 rows (0.38s validation, 2.49s processing) represents
# a synthetic local benchmark, not a production performance guarantee. Actual performance
# depends on data density, company count, client device, and deployment resources.
MAX_UPLOAD_SIZE_MB = 10
MAX_UPLOAD_SIZE_BYTES = MAX_UPLOAD_SIZE_MB * 1024 * 1024  # 10 MB maximum upload size
MAX_ROW_COUNT = 20_000                     # 20,000 maximum row limit

# Check whether installed Streamlit version supports per-widget max_upload_size
HAS_MAX_UPLOAD_SIZE = "max_upload_size" in inspect.signature(st.file_uploader).parameters

# Canonical schema derived from data/wingman-trigger-export-2026-09-17-sanitized.csv
CANONICAL_COLUMNS = [
    "company",
    "segment",
    "domain",
    "source_tier",
    "trigger_type",
    "trigger_date",
    "trigger_summary",
    "trigger_source_url",
    "scanned_at",
    "profile_review_required",
    "profile_review_code",
    "profile_review_label",
    "profile_matched_keyword",
    "profile_review_question",
    "fit_review_required",
    "fit_review_code",
    "fit_review_label",
]

# Required analytical columns to construct the portfolio reliably
REQUIRED_COLUMNS = ["company", "segment"]

# Recognized field aliases mapped to canonical names
COLUMN_ALIASES = {
    # company
    "company_name": "company",
    "account_name": "company",
    "account": "company",
    "company name": "company",
    "organization": "company",
    "name": "company",
    # segment
    "industry": "segment",
    "vertical": "segment",
    "sector": "segment",
    # domain
    "website": "domain",
    "url": "domain",
    "company_domain": "domain",
    "web_domain": "domain",
    # source_tier
    "tier": "source_tier",
    "wingman_tier": "source_tier",
    "baseline_tier": "source_tier",
    "source tier": "source_tier",
    # trigger_type
    "catalyst_type": "trigger_type",
    "trigger": "trigger_type",
    "signal_type": "trigger_type",
    "catalyst": "trigger_type",
    "event_type": "trigger_type",
    "type": "trigger_type",
    # trigger_date
    "date": "trigger_date",
    "event_date": "trigger_date",
    "activity_date": "trigger_date",
    "catalyst_date": "trigger_date",
    # trigger_summary
    "summary": "trigger_summary",
    "description": "trigger_summary",
    "event_summary": "trigger_summary",
    "trigger description": "trigger_summary",
    # trigger_source_url
    "source_url": "trigger_source_url",
    "url_source": "trigger_source_url",
    "evidence_url": "trigger_source_url",
    "link": "trigger_source_url",
    "source_link": "trigger_source_url",
    # scanned_at
    "scan_date": "scanned_at",
    "as_of_date": "scanned_at",
    "scanned_date": "scanned_at",
    "ingestion_date": "scanned_at",
}

# Supported profile review columns (optional; if absent, defaults to unassessed)
SUPPORTED_PROFILE_COLUMNS = [
    "profile_review_required",
    "profile_review_code",
    "profile_review_label",
    "profile_matched_keyword",
    "profile_review_question",
    "fit_review_required",
    "fit_review_code",
    "fit_review_label",
]

# CSV Formula Injection Protection (CWE-1236 / OWASP)
DANGEROUS_FORMULA_CHARS = ("=", "+", "-", "@", "\t", "\r", "\n")


def sanitize_value_for_csv(val: Any) -> Any:
    """
    Sanitizes a single cell value against CSV / spreadsheet formula injection (CWE-1236 / OWASP).
    Checks =, +, -, @, tab (\\t), carriage return (\\r), and line feed (\\n).
    Detects formula characters even after leading whitespace or control characters.
    Leaves non-string / genuine numeric values untouched.
    """
    if val is None or pd.isna(val):
        return val
    if not isinstance(val, str):
        return val
    if not val:
        return val

    # Check raw string prefix
    if val[0] in DANGEROUS_FORMULA_CHARS:
        return "'" + val

    # Detect dangerous prefix after leading whitespace or control characters
    stripped = val.lstrip(" \t\r\n\x00\x0b\x0c")
    if stripped and stripped[0] in DANGEROUS_FORMULA_CHARS:
        return "'" + val

    return val


def sanitize_dataframe_for_csv(df: pd.DataFrame) -> pd.DataFrame:
    """
    Returns a sanitized copy of the DataFrame for safe CSV export.
    Sanitizes every string / object cell across all columns.
    Leaves genuine numeric types unchanged. Does not mutate the source DataFrame.
    Handles null values and non-string objects safely.
    """
    safe_df = df.copy()
    for col in safe_df.columns:
        col_series = safe_df[col]
        if (
            pd.api.types.is_object_dtype(col_series)
            or pd.api.types.is_string_dtype(col_series)
            or isinstance(col_series.dtype, pd.CategoricalDtype)
        ):
            safe_df[col] = col_series.apply(sanitize_value_for_csv)
    return safe_df


def check_raw_header_duplicates(raw_bytes: bytes) -> Tuple[List[str], List[str]]:
    """
    Parses the raw CSV header line before pandas automatically renames duplicates.
    Returns (headers, list_of_duplicate_headers).
    """
    try:
        text = raw_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = raw_bytes.decode("latin-1")
        except Exception:
            return [], []

    first_line = text.splitlines()[0] if text.splitlines() else ""
    reader = csv.reader([first_line])
    headers = []
    for row in reader:
        headers = [h.strip() for h in row if h is not None]
        break

    seen: Set[str] = set()
    duplicates: List[str] = []
    for h in headers:
        normalized_h = h.lower()
        if normalized_h in seen:
            if h not in duplicates:
                duplicates.append(h)
        else:
            seen.add(normalized_h)

    return headers, duplicates


def normalize_columns(df: pd.DataFrame) -> Tuple[pd.DataFrame, Dict[str, str], List[str]]:
    """
    Normalizes DataFrame column names using recognized aliases.
    Returns (normalized_df, alias_mapping_applied, ignored_unknown_columns).
    """
    normalized_df = df.copy()
    alias_map = {}
    ignored_cols = []
    new_cols = []

    for col in normalized_df.columns:
        c_clean = col.strip()
        c_lower = c_clean.lower()
        if c_lower in CANONICAL_COLUMNS:
            new_cols.append(c_lower)
            if c_clean != c_lower:
                alias_map[c_clean] = c_lower
        elif c_lower in COLUMN_ALIASES:
            canon = COLUMN_ALIASES[c_lower]
            new_cols.append(canon)
            alias_map[c_clean] = canon
        else:
            new_cols.append(c_clean)
            ignored_cols.append(c_clean)

    normalized_df.columns = new_cols
    return normalized_df, alias_map, ignored_cols


class ValidationResult:
    """Encapsulates validation results for uploaded custom CSV."""

    def __init__(self):
        self.is_valid: bool = False
        self.blocking_errors: List[str] = []
        self.warnings: List[str] = []
        self.row_count: int = 0
        self.company_count: int = 0
        self.companies_without_triggers_count: int = 0
        self.recognized_trigger_rows_count: int = 0
        self.unknown_trigger_rows_count: int = 0
        self.unknown_triggers_breakdown: Dict[str, int] = {}
        self.invalid_or_blank_dates_count: int = 0
        self.earliest_valid_date: Optional[date] = None
        self.latest_valid_date: Optional[date] = None
        self.suggested_as_of_date: date = date.today()
        self.missing_recommended_fields: List[str] = []
        self.ignored_columns: List[str] = []
        self.alias_mappings_applied: Dict[str, str] = {}
        self.has_profile_fields: bool = False
        self.duplicate_identity_notes: List[str] = []
        self.clean_df: Optional[pd.DataFrame] = None
        self.content_hash: str = ""
        self.filename: str = ""


def validate_custom_csv(raw_bytes: bytes, filename: str) -> ValidationResult:
    """
    Validates uploaded CSV bytes against versioned schema v1.0.0.
    Produces structured validation preview with blocking errors vs non-blocking warnings.
    """
    res = ValidationResult()
    res.filename = filename
    res.content_hash = hashlib.sha256(raw_bytes).hexdigest()

    # 0. Maximum upload size check (10 MB limit)
    if len(raw_bytes) > MAX_UPLOAD_SIZE_BYTES:
        size_mb = len(raw_bytes) / (1024 * 1024)
        res.blocking_errors.append(
            f"File size ({size_mb:.2f} MB) exceeds maximum allowed limit of 10.0 MB. Please upload a smaller CSV."
        )
        return res

    # 1. Empty file check
    if not raw_bytes or len(raw_bytes.strip()) == 0:
        res.blocking_errors.append("File is empty (0 bytes). Please upload a valid CSV file.")
        return res

    # 2. Raw header duplicate check
    headers, raw_duplicates = check_raw_header_duplicates(raw_bytes)
    if raw_duplicates:
        res.blocking_errors.append(
            f"Duplicate column header(s) detected in CSV: {', '.join(raw_duplicates)}. Each column name must be unique."
        )
        return res

    # 3. Decode & Parse CSV
    try:
        # Try UTF-8 with BOM support first, then Latin-1 fallback
        text_stream = io.StringIO(raw_bytes.decode("utf-8-sig"))
        df = pd.read_csv(text_stream)
    except UnicodeDecodeError:
        try:
            text_stream = io.StringIO(raw_bytes.decode("latin-1"))
            df = pd.read_csv(text_stream)
            res.warnings.append("File encoded as Latin-1. UTF-8 or UTF-8 with BOM is recommended.")
        except Exception as e:
            res.blocking_errors.append(f"Could not parse CSV encoding: {str(e)}")
            return res
    except Exception as e:
        res.blocking_errors.append(f"CSV parsing error: {str(e)}")
        return res

    if df.empty or len(df) == 0:
        res.blocking_errors.append("CSV contains headers but has 0 data rows.")
        return res

    # Maximum row count check (20,000 rows limit)
    if len(df) > MAX_ROW_COUNT:
        res.blocking_errors.append(
            f"Dataset contains {len(df):,} rows, which exceeds maximum allowed limit of {MAX_ROW_COUNT:,} rows. Please filter your data before uploading."
        )
        return res

    res.row_count = len(df)

    # 4. Normalize columns using canonical aliases
    norm_df, aliases_applied, ignored = normalize_columns(df)
    res.alias_mappings_applied = aliases_applied
    res.ignored_columns = ignored

    if ignored:
        res.warnings.append(
            f"Ignored {len(ignored)} unrecognized column(s): {', '.join(ignored)}. These will not affect analytical calculations."
        )

    # 5. Check required analytical columns
    missing_required = [c for c in REQUIRED_COLUMNS if c not in norm_df.columns]
    if missing_required:
        res.blocking_errors.append(
            f"Missing required analytical column(s): {', '.join(missing_required)}. The file must at minimum contain 'company' and 'segment'."
        )
        return res

    # 6. Check company identity
    norm_df["company"] = norm_df["company"].fillna("").astype(str).str.strip()
    valid_company_mask = norm_df["company"] != ""
    if not valid_company_mask.any():
        res.blocking_errors.append("No valid company names found. All 'company' entries are blank.")
        return res

    res.company_count = int(norm_df["company"].nunique())
    if res.company_count == 0:
        res.blocking_errors.append("No unique company identities found in the upload.")
        return res

    # 7. Check recommended optional columns
    recommended_cols = ["domain", "source_tier", "trigger_type", "trigger_date", "trigger_summary", "trigger_source_url", "scanned_at"]
    missing_rec = [c for c in recommended_cols if c not in norm_df.columns]
    res.missing_recommended_fields = missing_rec

    # Ensure missing recommended columns exist as empty strings/defaults
    for c in recommended_cols:
        if c not in norm_df.columns:
            if c == "source_tier":
                norm_df[c] = 3
            else:
                norm_df[c] = ""

    # Check profile review fields
    has_profile = any(c in norm_df.columns for c in SUPPORTED_PROFILE_COLUMNS)
    res.has_profile_fields = has_profile
    if not has_profile:
        res.warnings.append(
            "Custom file does not contain profile-review fields (e.g. profile_review_required). "
            "All accounts will default to 'Operational profile unassessed' and will not be routed to Business Model Review."
        )

    # 8. Trigger validation & classification
    norm_df["trigger_type_clean"] = norm_df["trigger_type"].fillna("").astype(str).str.strip()

    # Identify companies with no triggers
    comp_triggers = norm_df.groupby("company")["trigger_type_clean"].apply(lambda s: [x for x in s if x != ""])
    res.companies_without_triggers_count = int((comp_triggers.apply(len) == 0).sum())

    recognized_count = 0
    unknown_breakdown: Dict[str, int] = {}

    for _, row in norm_df.iterrows():
        t_val = row["trigger_type_clean"]
        if not t_val:
            continue
        if t_val in VALID_TRIGGER_TYPES:
            recognized_count += 1
        else:
            unknown_breakdown[t_val] = unknown_breakdown.get(t_val, 0) + 1

    res.recognized_trigger_rows_count = recognized_count
    res.unknown_trigger_rows_count = sum(unknown_breakdown.values())
    res.unknown_triggers_breakdown = unknown_breakdown

    if unknown_breakdown:
        items_desc = [f"'{k}' ({v} row{'s' if v > 1 else ''})" for k, v in sorted(unknown_breakdown.items(), key=lambda x: x[1], reverse=True)]
        res.warnings.append(
            f"{res.unknown_trigger_rows_count} row(s) contain unrecognized trigger types: {', '.join(items_desc)}. "
            "These will remain visible in event history as 'Unclassified' but are excluded from dynamic tier and catalyst rankings."
        )

    # 9. Date parsing & Analysis As-Of Date determination
    norm_df["trigger_date_clean"] = norm_df["trigger_date"].fillna("").astype(str).str.strip()
    valid_trigger_dates: List[date] = []
    invalid_or_blank_dates = 0

    for d_str in norm_df["trigger_date_clean"]:
        if not d_str:
            invalid_or_blank_dates += 1
            continue
        m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", d_str)
        if m:
            try:
                dt = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
                valid_trigger_dates.append(dt)
            except ValueError:
                invalid_or_blank_dates += 1
        else:
            invalid_or_blank_dates += 1

    res.invalid_or_blank_dates_count = invalid_or_blank_dates
    if valid_trigger_dates:
        res.earliest_valid_date = min(valid_trigger_dates)
        res.latest_valid_date = max(valid_trigger_dates)

    # Determine suggested as-of date: check scanned_at first; otherwise current date (NOT latest trigger date)
    suggested_date = date.today()
    if "scanned_at" in norm_df.columns:
        scanned_dates: List[date] = []
        for s in norm_df["scanned_at"].dropna():
            m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", str(s).strip())
            if m:
                try:
                    scanned_dates.append(date(int(m.group(1)), int(m.group(2)), int(m.group(3))))
                except ValueError:
                    pass
        if scanned_dates:
            suggested_date = max(scanned_dates)

    res.suggested_as_of_date = suggested_date

    # 10. Check shared domain identities
    if "domain" in norm_df.columns:
        dom_df = norm_df[norm_df["domain"].fillna("").astype(str).str.strip() != ""]
        if not dom_df.empty:
            shared = dom_df.groupby("domain")["company"].nunique()
            shared_doms = shared[shared > 1]
            if not shared_doms.empty:
                res.duplicate_identity_notes.append(
                    f"{len(shared_doms)} domain(s) are shared by multiple company names (e.g. {shared_doms.index[0]}: {shared_doms.iloc[0]} companies)."
                )

    # Mark as valid if no blocking errors
    res.is_valid = len(res.blocking_errors) == 0
    res.clean_df = norm_df
    return res


def generate_blank_template_csv() -> str:
    """Generates a blank CSV template containing schema headers only."""
    headers = [
        "company",
        "segment",
        "domain",
        "source_tier",
        "trigger_type",
        "trigger_date",
        "trigger_summary",
        "trigger_source_url",
        "scanned_at",
    ]
    return ",".join(headers) + "\n"


def generate_example_dataset_csv() -> str:
    """Generates an illustrative example CSV with valid sample records."""
    headers = [
        "company",
        "segment",
        "domain",
        "source_tier",
        "trigger_type",
        "trigger_date",
        "trigger_summary",
        "trigger_source_url",
        "scanned_at",
    ]
    rows = [
        [
            "Apex Energy Systems",
            "Oil & Gas",
            "apexenergy.example.com",
            "1",
            "project_fid_commissioning",
            "2026-08-15",
            "Approved final investment decision for LNG liquefaction train expansion",
            "https://example.com/news/apex-fid-lng",
            "2026-09-15",
        ],
        [
            "Apex Energy Systems",
            "Oil & Gas",
            "apexenergy.example.com",
            "1",
            "hiring_burst",
            "2026-08-28",
            "Posted 40+ frontline operator and maintenance technician positions",
            "https://example.com/careers/apex-plant-staffing",
            "2026-09-15",
        ],
        [
            "Beacon Chemical Technologies",
            "Chemicals",
            "beaconchem.example.com",
            "2",
            "turnaround",
            "2026-07-20",
            "Scheduled 45-day site turnaround for ethylene cracker revamp",
            "https://example.com/press/beacon-tar-2026",
            "2026-09-15",
        ],
        [
            "Cascade Pipeline Logistics",
            "Oil & Gas",
            "cascadepipe.example.com",
            "3",
            "",
            "",
            "",
            "",
            "2026-09-15",
        ],
    ]

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(headers)
    writer.writerows(rows)
    return output.getvalue()


def init_data_source_session():
    """Initializes session state with default sanitized Wingman dataset if not set."""
    if "active_data_source" not in st.session_state:
        # Load default sanitized dataset
        project_root = Path(__file__).resolve().parents[1]
        default_csv = project_root / "data" / "wingman-trigger-export-2026-09-17-sanitized.csv"

        portfolio = load_wingman_portfolio(
            csv_path=str(default_csv),
            as_of_date=DEFAULT_AS_OF_DATE,
            tier_mode="distinct_categories",
            expiry_windows=DEFAULT_EXPIRY_WINDOWS,
            is_custom=False,
        )

        st.session_state["active_data_source"] = {
            "source_type": "default",
            "source_name": "Default Wingman Dataset",
            "filename": "wingman-trigger-export-2026-09-17-sanitized.csv",
            "is_custom": False,
            "as_of_date": DEFAULT_AS_OF_DATE,
            "row_count": len(portfolio["raw_df"]),
            "company_count": len(portfolio["companies_df"]),
            "valid_trigger_count": len(portfolio["active_events_df"]),
            "content_hash": "default-sanitized-v1",
            "raw_df": portfolio["raw_df"].copy(),
            "portfolio": portfolio,
            "tier_mode": "distinct_categories",
            "recency_option": "Category-Specific Expiry Defaults (Recommended)",
        }
        st.session_state["_portfolio_cache"] = {}
        st.session_state["has_pending_custom_upload"] = False


def reset_page_state():
    """
    Clears all transient page filters, selections, and comparison state when switching datasets.
    """
    keys_to_clear = [
        "browser_search_term",
        "browser_selected_segments",
        "browser_selected_statuses",
        "browser_selected_signals",
        "browser_filter_signal_mode",
        "selected_company_browser",
        "comparison_companies",
        "ranker_selected_preset",
        "ranker_pri_col",
        "ranker_pri_order",
        "ranker_sec_col",
        "ranker_sec_order",
        # Explicit keys used across the dashboard pages:
        "browser_filter_catalysts",
        "browser_filter_status",
        "browser_filter_multi",
        "browser_selected_company",
        "browser_compare_companies",
        "browser_table_widget",
    ]
    for k in keys_to_clear:
        if k in st.session_state:
            del st.session_state[k]

    # Clear query parameters (e.g. ?company=)
    st.query_params.clear()


def activate_custom_dataset(val_result: ValidationResult, chosen_as_of_date: date):
    """
    Activates validated custom dataset into session state and recalculates portfolio.
    """
    reset_page_state()
    st.session_state["has_pending_custom_upload"] = False
    st.session_state.pop("pending_custom_filename", None)

    # Calculate portfolio from custom DataFrame
    portfolio = load_wingman_portfolio(
        csv_path=val_result.clean_df,
        as_of_date=chosen_as_of_date,
        tier_mode="distinct_categories",
        expiry_windows=DEFAULT_EXPIRY_WINDOWS,
        is_custom=True,
    )

    st.session_state["active_data_source"] = {
        "source_type": "custom",
        "source_name": f"Custom CSV: {val_result.filename}",
        "filename": val_result.filename,
        "is_custom": True,
        "as_of_date": chosen_as_of_date,
        "row_count": val_result.row_count,
        "company_count": len(portfolio["companies_df"]),
        "valid_trigger_count": len(portfolio["active_events_df"]),
        "content_hash": val_result.content_hash,
        "raw_df": val_result.clean_df.copy(),
        "portfolio": portfolio,
        "tier_mode": "distinct_categories",
        "recency_option": "Category-Specific Expiry Defaults (Recommended)",
    }
    st.session_state["_portfolio_cache"] = {}


def return_to_default_dataset():
    """Restores the default sanitized Wingman dataset and resets page state."""
    reset_page_state()
    st.session_state["has_pending_custom_upload"] = False
    st.session_state.pop("pending_custom_filename", None)
    st.session_state.pop("sidebar_source_mode_radio", None)
    st.session_state.pop("uploader_custom_csv", None)
    project_root = Path(__file__).resolve().parents[1]
    default_csv = project_root / "data" / "wingman-trigger-export-2026-09-17-sanitized.csv"

    portfolio = load_wingman_portfolio(
        csv_path=str(default_csv),
        as_of_date=DEFAULT_AS_OF_DATE,
        tier_mode="distinct_categories",
        expiry_windows=DEFAULT_EXPIRY_WINDOWS,
        is_custom=False,
    )

    st.session_state["active_data_source"] = {
        "source_type": "default",
        "source_name": "Default Wingman Dataset",
        "filename": "wingman-trigger-export-2026-09-17-sanitized.csv",
        "is_custom": False,
        "as_of_date": DEFAULT_AS_OF_DATE,
        "row_count": len(portfolio["raw_df"]),
        "company_count": len(portfolio["companies_df"]),
        "valid_trigger_count": len(portfolio["active_events_df"]),
        "content_hash": "default-sanitized-v1",
        "raw_df": portfolio["raw_df"].copy(),
        "portfolio": portfolio,
        "tier_mode": "distinct_categories",
        "recency_option": "Category-Specific Expiry Defaults (Recommended)",
    }
    st.session_state["_portfolio_cache"] = {}


def get_active_dataset(
    as_of_date: Optional[date] = None,
    tier_mode: Optional[str] = None,
    expiry_windows: Optional[Dict[str, int]] = None,
) -> Dict[str, Any]:
    """
    Centralized getter for the active dataset.
    Used by Portfolio Insights, Company Browser, and Company Ranker.
    If custom parameters are provided (e.g. from Analysis Settings),
    it recalculates and returns defensive copies without mutating other sessions.
    """
    init_data_source_session()
    current_ds = st.session_state["active_data_source"]

    target_date = as_of_date or current_ds["as_of_date"]
    target_tier_mode = tier_mode or current_ds.get("tier_mode", "distinct_categories")
    target_expiry = expiry_windows or DEFAULT_EXPIRY_WINDOWS
    is_custom = current_ds.get("is_custom", False)

    # Check cache
    cache = st.session_state.setdefault("_portfolio_cache", {})
    expiry_key = hashlib.sha256(str(target_expiry).encode("utf-8")).hexdigest()
    cache_key = (
        current_ds["content_hash"],
        SCHEMA_VERSION,
        str(target_date),
        str(target_tier_mode),
        expiry_key,
    )

    if cache_key in cache:
        portfolio = cache[cache_key]
    else:
        # Recompute portfolio defensively from raw_df
        portfolio = load_wingman_portfolio(
            csv_path=current_ds["raw_df"].copy(),
            as_of_date=target_date,
            tier_mode=target_tier_mode,
            expiry_windows=target_expiry,
            is_custom=is_custom,
        )
        cache[cache_key] = portfolio

    return {
        "source_type": current_ds["source_type"],
        "source_name": current_ds["source_name"],
        "filename": current_ds["filename"],
        "is_custom": current_ds["is_custom"],
        "as_of_date": target_date,
        "row_count": len(portfolio["raw_df"]),
        "company_count": len(portfolio["companies_df"]),
        "valid_trigger_count": len(portfolio["active_events_df"]),
        "portfolio": copy.deepcopy(portfolio),
    }


def render_source_banner():
    """Renders a visible banner on top of the page when custom data is active or pending activation."""
    init_data_source_session()
    ds = st.session_state.get("active_data_source", {})
    if ds.get("is_custom"):
        clean_filename = html.escape(str(ds.get('filename', '')))
        clean_as_of = html.escape(str(ds.get('as_of_date', '')))
        st.info(
            f"🟠 **Active Data Source**: Custom CSV — **{clean_filename}** | "
            f"**{ds['company_count']}** companies · **{ds['row_count']}** rows · "
            f"Analysis Date: **{clean_as_of}** | "
            f"*Session-isolated in-memory view.*"
        )
        if st.session_state.get("has_pending_custom_upload", False):
            pending_fn = html.escape(str(st.session_state.get("pending_custom_filename", "replacement file")))
            st.warning(
                f"⚠️ **Replacement CSV pending activation ({pending_fn}).** The dashboard is still showing the active custom dataset ({clean_filename})."
            )
    elif st.session_state.get("has_pending_custom_upload", False):
        st.warning(
            "⚠️ **Custom CSV pending activation.** The dashboard is still showing the Default Wingman Dataset."
        )


def render_data_source_sidebar():
    """
    Renders the persistent Data-Source selector, custom upload workflow,
    validation preview, and active source status in app.py sidebar.
    """
    init_data_source_session()
    current_ds = st.session_state["active_data_source"]

    st.sidebar.markdown(
        """
        <div style="font-size: 0.85rem; font-weight: 700; color: #1e3a8a; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 6px;">
            📁 Data Source
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Active source indicator card
    if current_ds["is_custom"]:
        clean_filename = html.escape(str(current_ds.get('filename', '')))
        clean_as_of = html.escape(str(current_ds.get('as_of_date', '')))
        st.sidebar.markdown(
            f"""
            <div style="background-color: #fff7ed; border: 1px solid #fdba74; border-radius: 6px; padding: 10px; margin-bottom: 12px; font-size: 0.82rem; color: #9a3412;">
                <div style="font-weight: 700; margin-bottom: 4px;">Data source: Custom CSV</div>
                <div><b>File:</b> {clean_filename}</div>
                <div><b>Analysis date:</b> {clean_as_of}</div>
                <div><b>Rows:</b> {current_ds['row_count']:,}</div>
                <div><b>Companies:</b> {current_ds['company_count']:,}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.sidebar.button("↩️ Return to Default Dataset", key="btn_return_default", use_container_width=True):
            return_to_default_dataset()
            st.rerun()
    else:
        clean_filename = html.escape(str(current_ds.get('filename', '')))
        clean_as_of = html.escape(str(current_ds.get('as_of_date', '')))
        st.sidebar.markdown(
            f"""
            <div style="background-color: #f0fdf4; border: 1px solid #bbf7d0; border-radius: 6px; padding: 10px; margin-bottom: 12px; font-size: 0.82rem; color: #166534;">
                <div style="font-weight: 700; margin-bottom: 4px;">Data source: Default Wingman Dataset</div>
                <div><b>File:</b> {clean_filename}</div>
                <div><b>Analysis date:</b> {clean_as_of}</div>
                <div><b>Rows:</b> {current_ds['row_count']:,}</div>
                <div><b>Companies:</b> {current_ds['company_count']:,}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    # Radio selector for workflow mode
    source_mode = st.sidebar.radio(
        "Source Mode:",
        options=["Default Wingman dataset", "Custom CSV upload"],
        index=1 if current_ds["is_custom"] else 0,
        key="sidebar_source_mode_radio",
        label_visibility="collapsed",
    )

    # If user selected Default mode while custom is active or pending, revert
    if source_mode == "Default Wingman dataset":
        if current_ds["is_custom"]:
            return_to_default_dataset()
            st.rerun()
        elif st.session_state.get("has_pending_custom_upload", False):
            st.session_state["has_pending_custom_upload"] = False
            st.session_state.pop("pending_custom_filename", None)

    # Custom upload workflow
    if source_mode == "Custom CSV upload":
        with st.sidebar.expander("📤 Upload Custom CSV", expanded=True):
            st.caption(
                "Uploaded data is temporary and applies only to your current dashboard session. "
                "It does not replace the default Wingman dataset."
            )

            # Template downloads
            st.markdown(
                "<div style='font-size: 0.8rem; font-weight: 600; margin-bottom: 4px;'>CSV Templates (Schema v1.0.0):</div>",
                unsafe_allow_html=True,
            )
            col_t1, col_t2 = st.columns(2)
            with col_t1:
                st.download_button(
                    "📄 Blank Template",
                    data=generate_blank_template_csv(),
                    file_name="wingman_template_blank.csv",
                    mime="text/csv",
                    key="btn_dl_blank_tpl",
                    use_container_width=True,
                )
            with col_t2:
                st.download_button(
                    "📋 Example CSV",
                    data=generate_example_dataset_csv(),
                    file_name="wingman_example_dataset.csv",
                    mime="text/csv",
                    key="btn_dl_example_csv",
                    use_container_width=True,
                )

            # Format guidance expander
            with st.expander("ℹ️ Accepted Format & Taxonomy", expanded=False):
                st.markdown(
                    """
                    **Required Columns:**
                    - `company`: Account / company name *(required)*
                    - `segment`: Industry / vertical classification *(required)*

                    **Recognized Aliases:**
                    - `company`: `company_name`, `account_name`, `organization`
                    - `segment`: `industry`, `vertical`, `sector`
                    - `source_tier`: `tier`, `wingman_tier`
                    - `trigger_source_url`: `source_url`, `evidence_url`, `url`
                    - `scanned_at`: `scan_date`, `as_of_date`

                    **Recognized Trigger Types:**
                    - `project_fid_commissioning`: Project Commissioning / FID
                    - `ma_acquisition`: M&A / Asset Acquisition
                    - `hiring_burst`: Frontline Hiring Burst
                    - `turnaround`: Turnaround / Planned Maintenance
                    - `new_leader`: Executive Leadership Change
                    - `incident_regulator`: Regulatory Finding / Incident
                    - `audit_cycle`: Audit / Compliance Cycle
                    - `crew_change`: Workforce / Crew Change Transition
                    *(Unrecognized triggers are labeled 'Unclassified' and excluded from dynamic tiers.)*
                    """
                )

            uploader_kwargs = {
                "label": "Choose a .csv file",
                "type": ["csv"],
                "key": "uploader_custom_csv",
                "accept_multiple_files": False,
            }
            if HAS_MAX_UPLOAD_SIZE:
                uploader_kwargs["max_upload_size"] = MAX_UPLOAD_SIZE_MB
            else:
                st.caption("Maximum accepted file size: 10 MB; maximum dataset size: 20,000 rows.")

            uploaded_file = st.file_uploader(**uploader_kwargs)

            if uploaded_file is not None:
                if isinstance(uploaded_file, list):
                    st.error("🛑 **Upload Blocked**")
                    st.markdown("• Multiple file upload is not permitted. Please upload a single .csv file.")
                    return

                raw_bytes = uploaded_file.getvalue()
                val_res = validate_custom_csv(raw_bytes, uploaded_file.name)

                if not val_res.is_valid:
                    st.session_state["has_pending_custom_upload"] = False
                    st.session_state.pop("pending_custom_filename", None)
                    st.error("🛑 **Upload Blocked**")
                    for err in val_res.blocking_errors:
                        st.markdown(f"• {err}")
                    st.caption("Active data source remains unchanged. Please fix errors and re-upload.")
                else:
                    is_active_file = current_ds.get("is_custom") and (val_res.content_hash == current_ds.get("content_hash"))
                    clean_earliest = html.escape(str(val_res.earliest_valid_date or 'None'))
                    clean_latest = html.escape(str(val_res.latest_valid_date or 'None'))

                    if is_active_file:
                        # Uploaded file is ALREADY active in this session
                        st.session_state["has_pending_custom_upload"] = False
                        st.session_state.pop("pending_custom_filename", None)
                        st.success("✅ **Custom CSV active**")
                        st.markdown(
                            f"""
                            <div style="font-size: 0.8rem; line-height: 1.45; background-color: #f8fafc; border: 1px solid #e2e8f0; border-radius: 4px; padding: 8px; margin-bottom: 8px;">
                                • <b>Rows Uploaded:</b> {val_res.row_count:,}<br/>
                                • <b>Unique Companies:</b> {val_res.company_count:,}<br/>
                                • <b>Accounts with No Triggers:</b> {val_res.companies_without_triggers_count:,}<br/>
                                • <b>Recognized Trigger Rows:</b> {val_res.recognized_trigger_rows_count:,}<br/>
                                • <b>Unclassified Trigger Rows:</b> {val_res.unknown_trigger_rows_count:,}<br/>
                                • <b>Blank / Invalid Dates:</b> {val_res.invalid_or_blank_dates_count:,}<br/>
                                • <b>Date Range:</b> {clean_earliest} to {clean_latest}
                            </div>
                            """,
                            unsafe_allow_html=True,
                        )

                        if val_res.warnings:
                            with st.expander(f"⚠️ Validation Warnings ({len(val_res.warnings)})", expanded=False):
                                for w in val_res.warnings:
                                    st.markdown(f"• {w}")

                        st.date_input(
                            "Analysis as-of date:",
                            value=current_ds["as_of_date"],
                            disabled=True,
                            help="Baseline date for evaluating active catalyst horizons and recency windows. Currently active in session.",
                            key="input_custom_as_of_date_active",
                        )

                        st.button(
                            "🚀 Use This Dataset",
                            type="primary",
                            disabled=True,
                            use_container_width=True,
                            key="btn_activate_custom",
                            help="This dataset is already active in your dashboard session.",
                        )
                        st.caption("ℹ️ This dataset is currently active. Choose a replacement CSV above or return to default dataset.")
                    else:
                        # Uploaded file is staged pending activation (new upload or replacement CSV)
                        st.session_state["has_pending_custom_upload"] = True
                        st.session_state["pending_custom_filename"] = uploaded_file.name

                        if current_ds.get("is_custom"):
                            st.warning(
                                f"⚠️ **Replacement CSV pending activation.** The dashboard is still showing the active custom dataset ({html.escape(current_ds['filename'])})."
                            )
                        else:
                            st.warning("⚠️ **Custom CSV pending activation.** The dashboard is still showing the Default Wingman Dataset.")

                        st.success("✅ **CSV Format Validated**")
                        st.markdown(
                            f"""
                            <div style="font-size: 0.8rem; line-height: 1.45; background-color: #f8fafc; border: 1px solid #e2e8f0; border-radius: 4px; padding: 8px; margin-bottom: 8px;">
                                • <b>Rows Uploaded:</b> {val_res.row_count:,}<br/>
                                • <b>Unique Companies:</b> {val_res.company_count:,}<br/>
                                • <b>Accounts with No Triggers:</b> {val_res.companies_without_triggers_count:,}<br/>
                                • <b>Recognized Trigger Rows:</b> {val_res.recognized_trigger_rows_count:,}<br/>
                                • <b>Unclassified Trigger Rows:</b> {val_res.unknown_trigger_rows_count:,}<br/>
                                • <b>Blank / Invalid Dates:</b> {val_res.invalid_or_blank_dates_count:,}<br/>
                                • <b>Date Range:</b> {clean_earliest} to {clean_latest}
                            </div>
                            """,
                            unsafe_allow_html=True,
                        )

                        if val_res.warnings:
                            with st.expander(f"⚠️ Validation Warnings ({len(val_res.warnings)})", expanded=False):
                                for w in val_res.warnings:
                                    st.markdown(f"• {w}")

                        chosen_date = st.date_input(
                            "Analysis as-of date:",
                            value=val_res.suggested_as_of_date,
                            help="Baseline date for evaluating active catalyst horizons and recency windows. Defaults to scanned_at or today.",
                            key="input_custom_as_of_date",
                        )

                        # Explicit activation button
                        if st.button("🚀 Use This Dataset", type="primary", use_container_width=True, key="btn_activate_custom"):
                            activate_custom_dataset(val_res, chosen_date)
                            st.rerun()
            else:
                st.session_state["has_pending_custom_upload"] = False
                st.session_state.pop("pending_custom_filename", None)

    st.sidebar.markdown("---")
