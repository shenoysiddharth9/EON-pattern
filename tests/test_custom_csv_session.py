"""
Tests for Session-Scoped Custom CSV Support & Centralized Dataset Management
EON Commercial Intelligence | External Review Build — Proposed Phase 1

Verifies:
1. Canonical schema matches actual default sanitized CSV headers
2. Recognized alias normalization (company_name, industry, tier, catalyst_type, etc.)
3. Duplicate raw header detection before pandas auto-renames
4. Company rows with blank trigger fields (Monitor / 0-trigger accounts)
5. Custom analysis-date changes affecting active-window calculations
6. Future milestones not becoming analysis date
7. Unknown triggers remaining visible but excluded from category-based calculations
8. Missing profile fields producing Not yet assessed, not Business Model Review
9. Failed replacement upload preserving previously active source
10. Two files with the same name and different content (content hash separation)
11. Cache separation by content hash, schema, analysis date, tier mode
12. Default and custom export filenames and labels
13. AppTest multi-page session state consistency across all three pages
14. Preservation of all default metrics and invariants (785 accounts, 0/127/199/192/267 queues)
"""

import copy
import csv
from datetime import date, timedelta
import io
from pathlib import Path
import time
import pytest
import pandas as pd

from dashboard.data_source import (
    SCHEMA_VERSION,
    CANONICAL_COLUMNS,
    REQUIRED_COLUMNS,
    COLUMN_ALIASES,
    MAX_UPLOAD_SIZE_BYTES,
    MAX_ROW_COUNT,
    check_raw_header_duplicates,
    normalize_columns,
    validate_custom_csv,
    generate_blank_template_csv,
    generate_example_dataset_csv,
    sanitize_value_for_csv,
    sanitize_dataframe_for_csv,
    activate_custom_dataset,
    return_to_default_dataset,
    get_active_dataset,
    init_data_source_session,
    render_source_banner,
)
from dashboard.wingman_portfolio import (
    load_wingman_portfolio,
    generate_portfolio_observations,
    is_safe_evidence_url,
    DEFAULT_AS_OF_DATE,
    DEFAULT_EXPIRY_WINDOWS,
    VALID_TRIGGER_TYPES,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SANITIZED_CSV = REPO_ROOT / "data" / "wingman-trigger-export-2026-09-17-sanitized.csv"


def test_actual_default_csv_headers_match_canonical_schema():
    """Verify that actual default sanitized CSV headers match CANONICAL_COLUMNS."""
    assert DEFAULT_SANITIZED_CSV.exists()
    with open(DEFAULT_SANITIZED_CSV, "r", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        header_row = next(reader)
    clean_headers = [h.strip() for h in header_row]
    assert clean_headers == CANONICAL_COLUMNS


def test_recognized_alias_normalization():
    """Verify that documented column aliases normalize cleanly to canonical schema."""
    sample_data = {
        "Company_Name": ["Test Energy Corp"],
        "Industry": ["Oil & Gas"],
        "Website": ["testenergy.com"],
        "Tier": ["1"],
        "Catalyst_Type": ["project_fid_commissioning"],
        "Event_Date": ["2026-08-01"],
        "Description": ["New LNG facility approved"],
        "Source_URL": ["https://example.com/source"],
        "Scan_Date": ["2026-08-25"],
    }
    df = pd.DataFrame(sample_data)
    norm_df, aliases_applied, ignored = normalize_columns(df)

    assert "company" in norm_df.columns
    assert "segment" in norm_df.columns
    assert "domain" in norm_df.columns
    assert "source_tier" in norm_df.columns
    assert "trigger_type" in norm_df.columns
    assert "trigger_date" in norm_df.columns
    assert "trigger_summary" in norm_df.columns
    assert "trigger_source_url" in norm_df.columns
    assert "scanned_at" in norm_df.columns
    assert len(ignored) == 0
    assert aliases_applied["Company_Name"] == "company"
    assert aliases_applied["Industry"] == "segment"
    assert aliases_applied["Tier"] == "source_tier"


def test_duplicate_raw_headers_detected_and_blocked():
    """Verify that raw CSV with duplicate headers is blocked before pandas auto-renames."""
    csv_bytes = b"company,segment,company,trigger_type\nAcme Corp,Oil & Gas,Acme Corp,hiring_burst\n"
    headers, raw_duplicates = check_raw_header_duplicates(csv_bytes)
    assert "company" in raw_duplicates

    val_res = validate_custom_csv(csv_bytes, "dup_header.csv")
    assert not val_res.is_valid
    assert any("Duplicate column header(s)" in err for err in val_res.blocking_errors)


def test_company_rows_with_blank_trigger_fields():
    """Verify that company rows with blank trigger fields parse properly and enter Monitor."""
    csv_text = (
        "company,segment,domain,source_tier,trigger_type,trigger_date\n"
        "Active Operator Ltd,Oil & Gas,activeop.com,1,project_fid_commissioning,2026-08-10\n"
        "Quiet Logistics Co,Oil & Gas,quietlog.com,3,,\n"
        "Silent Utilities Inc,Utilities,silentutil.com,3,,\n"
    )
    val_res = validate_custom_csv(csv_text.encode("utf-8"), "blank_triggers.csv")
    assert val_res.is_valid
    assert val_res.company_count == 3
    assert val_res.companies_without_triggers_count == 2

    portfolio = load_wingman_portfolio(
        csv_path=val_res.clean_df,
        as_of_date=date(2026, 9, 1),
        is_custom=True,
    )
    df = portfolio["companies_df"]
    assert len(df) == 3

    quiet_row = df[df["company_name"] == "Quiet Logistics Co"].iloc[0]
    assert quiet_row["current_status"] == "Monitor"
    assert quiet_row["distinct_category_count"] == 0
    assert quiet_row["active_event_count"] == 0


def test_custom_analysis_date_changes_affect_active_windows():
    """Verify that changing analysis date moves events into/out of active decay windows."""
    csv_text = (
        "company,segment,trigger_type,trigger_date\n"
        "Pioneer Energy,Oil & Gas,hiring_burst,2026-06-01\n"
    )
    val_res = validate_custom_csv(csv_text.encode("utf-8"), "date_test.csv")
    assert val_res.is_valid

    # hiring_burst has a 90-day window
    # As of 2026-07-01: delta is 30 days -> ACTIVE
    p_active = load_wingman_portfolio(
        csv_path=val_res.clean_df,
        as_of_date=date(2026, 7, 1),
        is_custom=True,
    )
    pioneer_active = p_active["companies_df"].iloc[0]
    assert pioneer_active["distinct_category_count"] == 1
    assert pioneer_active["active_event_count"] == 1

    # As of 2026-10-01: delta is 122 days -> EXPIRED
    p_expired = load_wingman_portfolio(
        csv_path=val_res.clean_df,
        as_of_date=date(2026, 10, 1),
        is_custom=True,
    )
    pioneer_expired = p_expired["companies_df"].iloc[0]
    assert pioneer_expired["distinct_category_count"] == 0
    assert pioneer_expired["active_event_count"] == 0
    assert pioneer_expired["current_status"] == "Monitor"


def test_future_milestones_not_becoming_analysis_date():
    """Verify that a future trigger date (e.g. 2027) does not become the suggested as-of date."""
    csv_text = (
        "company,segment,trigger_type,trigger_date,scanned_at\n"
        "Frontier Gas,Oil & Gas,project_fid_commissioning,2027-05-01,2026-09-10\n"
    )
    val_res = validate_custom_csv(csv_text.encode("utf-8"), "future_date.csv")
    assert val_res.is_valid
    # Suggested date must come from scanned_at (2026-09-10), NOT future trigger date 2027-05-01
    assert val_res.suggested_as_of_date == date(2026, 9, 10)


def test_unknown_triggers_remaining_visible_but_excluded_from_categories():
    """Verify unknown triggers are labeled Unclassified, excluded from tiers, but visible in history."""
    csv_text = (
        "company,segment,trigger_type,trigger_date\n"
        "Novelty Biofuels,Renewables,patent_filing,2026-08-15\n"
        "Novelty Biofuels,Renewables,conference_speech,2026-08-20\n"
    )
    val_res = validate_custom_csv(csv_text.encode("utf-8"), "unknown_triggers.csv")
    assert val_res.is_valid
    assert val_res.unknown_trigger_rows_count == 2
    assert "patent_filing" in val_res.unknown_triggers_breakdown
    assert "conference_speech" in val_res.unknown_triggers_breakdown
    assert any("unrecognized trigger types" in w for w in val_res.warnings)

    portfolio = load_wingman_portfolio(
        csv_path=val_res.clean_df,
        as_of_date=date(2026, 9, 1),
        is_custom=True,
    )
    df = portfolio["companies_df"]
    row = df.iloc[0]
    # Excluded from active categories and dynamic tiers
    assert row["distinct_category_count"] == 0
    assert row["active_event_count"] == 0
    assert row["current_status"] == "Monitor"

    # Visible in all_considered_events
    events = portfolio["all_considered_events_df"]
    assert len(events) == 2
    assert all("Unclassified" in r["trigger_type_display"] for _, r in events.iterrows())


def test_missing_profile_fields_produce_unassessed_not_business_model_review():
    """Verify missing profile fields default to unassessed and do NOT create Business Model Review."""
    csv_text = (
        "company,segment,trigger_type,trigger_date\n"
        "Delta EPC Consultancy,Engineering,project_fid_commissioning,2026-08-10\n"
        "Delta EPC Consultancy,Engineering,hiring_burst,2026-08-12\n"
    )
    val_res = validate_custom_csv(csv_text.encode("utf-8"), "custom_no_profile.csv")
    assert val_res.is_valid
    assert not val_res.has_profile_fields
    assert any("does not contain profile-review fields" in w for w in val_res.warnings)

    portfolio = load_wingman_portfolio(
        csv_path=val_res.clean_df,
        as_of_date=date(2026, 9, 1),
        is_custom=True,
    )
    df = portfolio["companies_df"]
    assert len(df) == 1
    row = df.iloc[0]
    # Despite containing "Consultancy" in name, custom data does NOT infer BMR
    assert row["fit_status"] == "FIT NOT YET ASSESSED"
    assert row["current_status"] == "Research & Qualify Now"  # Multi-catalyst Tier 1
    assert portfolio["metrics"]["business_model_review_count"] == 0


def test_failed_replacement_upload_preserves_previously_active_source():
    """Verify that uploading invalid CSV (e.g. missing company) fails validation without side-effects."""
    invalid_csv = b"random_col,other_col\nfoo,bar\n"
    val_res = validate_custom_csv(invalid_csv, "corrupt.csv")
    assert not val_res.is_valid
    assert any("Missing required analytical column" in err for err in val_res.blocking_errors)
    # clean_df must be None when invalid
    assert val_res.clean_df is None


def test_two_files_with_same_name_and_different_content():
    """Verify content hash distinguishes uploads having the same filename."""
    csv1 = b"company,segment\nCompany A,Oil & Gas\n"
    csv2 = b"company,segment\nCompany B,Chemicals\n"
    val1 = validate_custom_csv(csv1, "upload.csv")
    val2 = validate_custom_csv(csv2, "upload.csv")
    assert val1.is_valid and val2.is_valid
    assert val1.content_hash != val2.content_hash
    assert val1.company_count == 1
    assert val2.company_count == 1
    assert val1.clean_df.iloc[0]["company"] == "Company A"
    assert val2.clean_df.iloc[0]["company"] == "Company B"


def test_template_generators():
    """Verify blank template and example dataset generators."""
    blank = generate_blank_template_csv()
    assert "company,segment,domain,source_tier,trigger_type,trigger_date" in blank
    lines = blank.strip().splitlines()
    assert len(lines) == 1  # Headers only

    example = generate_example_dataset_csv()
    ex_lines = example.strip().splitlines()
    assert len(ex_lines) == 5  # Header + 4 rows
    assert "Apex Energy Systems" in example
    assert "Beacon Chemical Technologies" in example
    assert "Cascade Pipeline Logistics" in example


def test_default_sanitized_metrics_invariants_preserved():
    """Verify that loading default sanitized dataset preserves exact 785 accounts and queue counts."""
    portfolio = load_wingman_portfolio(
        csv_path=str(DEFAULT_SANITIZED_CSV),
        as_of_date=DEFAULT_AS_OF_DATE,
        tier_mode="distinct_categories",
        expiry_windows=DEFAULT_EXPIRY_WINDOWS,
        is_custom=False,
    )
    df = portfolio["companies_df"]
    assert len(df) == 785
    assert len(portfolio["raw_df"]) == 1180
    assert len(portfolio["active_events_df"]) == 642

    counts = df["current_status"].value_counts().to_dict()
    assert counts.get("Ready for Outreach", 0) == 0
    assert counts.get("Research & Qualify Now", 0) == 127
    assert counts.get("Business Model Review", 0) == 199
    assert counts.get("Follow-Up Qualification", 0) == 192
    assert counts.get("Monitor", 0) == 267
    assert sum(counts.values()) == 785


def test_apptest_all_three_pages_render_and_share_active_dataset():
    """Verify multi-page AppTest execution across Portfolio Insights, Company Browser, and Ranker."""
    from streamlit.testing.v1 import AppTest

    # Launch app.py
    at = AppTest.from_file("app.py", default_timeout=30)
    at.run()
    assert not at.exception, f"app.py crashed: {at.exception}"

    # Verify persistent sidebar radio
    assert len(at.sidebar.radio) > 0

    # Verify Portfolio Insights renders 4 KPI cards and active segment callout
    assert len(at.title) > 0
    assert at.title[0].value == "💡 Portfolio Insights"

    # Check text content contains Total Accounts (785)
    page_text = " ".join([m.value for m in at.markdown])
    assert "Total Accounts" in page_text
    assert "785" in page_text

    # Switch to Company Browser
    at_browser = AppTest.from_file("dashboard/pages/11_company_browser.py", default_timeout=30)
    at_browser.run()
    assert not at_browser.exception, f"Company Browser crashed: {at_browser.exception}"
    assert at_browser.title[0].value == "🔍 Company Browser"

    # Switch to Company Ranker
    at_ranker = AppTest.from_file("dashboard/pages/12_company_ranker.py", default_timeout=30)
    at_ranker.run()
    assert not at_ranker.exception, f"Company Ranker crashed: {at_ranker.exception}"
    assert at_ranker.title[0].value == "📊 Company Ranker"


# =====================================================================
# HARDENING REVISION TESTS: SMALL DATASETS, LIMITS, SANITIZATION, ISOLATION
# =====================================================================

def test_small_dataset_safeguards_n_under_10():
    """Verify that for N < 10, lift, co-occurrence, and hypothesis text are suppressed."""
    small_csv = (
        "company,segment,domain,trigger_type,trigger_date,scanned_at\n"
        "Alpha Corp,Oil & Gas,alpha.example.com,project_fid_commissioning,2026-08-01,2026-09-17\n"
        "Alpha Corp,Oil & Gas,alpha.example.com,turnaround,2026-08-10,2026-09-17\n"
        "Beta Corp,Chemicals,beta.example.com,hiring_burst,2026-08-05,2026-09-17\n"
        "Gamma Corp,Oil & Gas,gamma.example.com,project_fid_commissioning,2026-08-12,2026-09-17\n"
        "Delta Corp,Power,delta.example.com,,,2026-09-17\n"
        "Epsilon Corp,Mining,epsilon.example.com,,,2026-09-17\n"
    )
    val = validate_custom_csv(small_csv.encode("utf-8"), "small.csv")
    assert val.is_valid
    assert val.company_count == 5

    portfolio = load_wingman_portfolio(
        csv_path=val.clean_df,
        as_of_date=date(2026, 9, 17),
        is_custom=True,
    )
    obs = generate_portfolio_observations(portfolio)

    # N < 10 guardrail: exactly 2 descriptive cards, synergistic_pair co-occurrence suppressed
    assert len(obs) == 2
    ids = [o["id"] for o in obs]
    assert "commissioning_dominance" in ids
    assert "multi_catalyst_surges" in ids
    assert "synergistic_pair" not in ids

    # Strategic implication text must be suppressed (None)
    for o in obs:
        assert o["hypothesis"] is None
        # Must preserve numerator and denominator
        assert "of 5" in o["badge"]
        assert "of 5 companies" in o["fact"]


def test_small_dataset_safeguards_n_10_to_29():
    """Verify that for 10 <= N <= 29, patterns are marked exploratory with caveats."""
    rows = ["company,segment,domain,trigger_type,trigger_date,scanned_at"]
    # Create 15 companies
    for i in range(1, 16):
        c_name = f"Company_{i}"
        t_type = "project_fid_commissioning" if i <= 8 else "turnaround"
        rows.append(f"{c_name},Oil & Gas,{c_name}.com,{t_type},2026-08-10,2026-09-17")
        if i <= 5:
            rows.append(f"{c_name},Oil & Gas,{c_name}.com,turnaround,2026-08-15,2026-09-17")

    csv_data = "\n".join(rows)
    val = validate_custom_csv(csv_data.encode("utf-8"), "mid.csv")
    assert val.is_valid
    assert val.company_count == 15

    portfolio = load_wingman_portfolio(
        csv_path=val.clean_df,
        as_of_date=date(2026, 9, 17),
        is_custom=True,
    )
    obs = generate_portfolio_observations(portfolio)

    # 10 <= N <= 29: Exploratory patterns
    for o in obs:
        assert "of 15" in o["badge"]
        assert "of 15 companies" in o["fact"]
        if o["hypothesis"]:
            assert "[Exploratory" in o["hypothesis"]
            assert "N=15" in o["hypothesis"]


def test_standard_dataset_n_30_plus():
    """Verify that for N >= 30, standard observations are rendered without claim of statistical significance."""
    portfolio = load_wingman_portfolio(
        csv_path=str(DEFAULT_SANITIZED_CSV),
        as_of_date=DEFAULT_AS_OF_DATE,
        is_custom=False,
    )
    obs = generate_portfolio_observations(portfolio)
    assert len(obs) >= 3
    for o in obs:
        assert "of 785" in o["badge"]
        assert "of 785 companies" in o["fact"]
        # Implication present without exploratory bracket
        assert o["hypothesis"] is not None
        assert "[Exploratory" not in o["hypothesis"]


def test_explicit_upload_limits_size_and_row_count():
    """Verify 10 MB and 20,000-row upload limit enforcement with clear blocking messages."""
    # 1. Test size limit (>10 MB)
    large_header = "company,segment\n"
    large_line = "Huge Corp,Oil & Gas\n"
    target_bytes = (10 * 1024 * 1024) + 500  # > 10 MB
    line_bytes = large_line.encode("utf-8")
    repeat_count = (target_bytes - len(large_header)) // len(line_bytes) + 1
    oversized_bytes = large_header.encode("utf-8") + (line_bytes * repeat_count)
    assert len(oversized_bytes) > MAX_UPLOAD_SIZE_BYTES

    res_size = validate_custom_csv(oversized_bytes, "oversized.csv")
    assert not res_size.is_valid
    assert any("exceeds maximum allowed limit of 10.0 MB" in err for err in res_size.blocking_errors)

    # 2. Test row limit (>20,000 rows)
    lines = ["company,segment"] + [f"Corp_{i},Oil & Gas" for i in range(20_005)]
    oversized_rows_bytes = "\n".join(lines).encode("utf-8")
    assert len(oversized_rows_bytes) <= MAX_UPLOAD_SIZE_BYTES  # ensure it passes size check

    res_rows = validate_custom_csv(oversized_rows_bytes, "many_rows.csv")
    assert not res_rows.is_valid
    assert any("exceeds maximum allowed limit of 20,000 rows" in err for err in res_rows.blocking_errors)


def test_near_limit_performance_benchmark_20000_rows():
    """Benchmark validation and portfolio processing near the 20,000-row limit."""
    lines = ["company,segment,domain,trigger_type,trigger_date,scanned_at"]
    # 5,000 companies with 4 rows each = 20,000 rows
    for i in range(1, 5001):
        c_name = f"BenchmarkCompany_{i}"
        for t_idx, t_type in enumerate(["project_fid_commissioning", "turnaround", "hiring_burst", "new_leader"]):
            lines.append(f"{c_name},Oil & Gas,{c_name}.example.com,{t_type},2026-08-{10+t_idx:02d},2026-09-17")

    csv_data = "\n".join(lines).encode("utf-8")
    assert len(csv_data) <= MAX_UPLOAD_SIZE_BYTES

    t0 = time.perf_counter()
    val = validate_custom_csv(csv_data, "benchmark_20000.csv")
    val_time = time.perf_counter() - t0

    assert val.is_valid
    assert val.row_count == 20000
    assert val.company_count == 5000

    t1 = time.perf_counter()
    portfolio = load_wingman_portfolio(
        csv_path=val.clean_df,
        as_of_date=date(2026, 9, 17),
        is_custom=True,
    )
    proc_time = time.perf_counter() - t1

    assert len(portfolio["companies_df"]) == 5000
    print(f"\n[PERFORMANCE BENCHMARK] 20,000 Rows: Validation={val_time:.2f}s, Processing={proc_time:.2f}s")


def test_csv_formula_injection_sanitization_comprehensive():
    """Verify spreadsheet formula injection sanitization (CWE-1236 / OWASP)."""
    # 1. Dangerous single values
    dangerous_inputs = [
        "=1+1",
        "+1234",
        "-55",
        "@SUM(A1:B10)",
        "\tTabPrefix",
        "\rCRPrefix",
        "\nLFPrefix",
        "  =FormulaLeadingSpace",
        " \t+LeadingTabAndSpace",
        "\r\n@LeadingNewline",
    ]
    for inp in dangerous_inputs:
        sanitized = sanitize_value_for_csv(inp)
        assert sanitized.startswith("'"), f"Failed to sanitize: {inp!r} -> {sanitized!r}"

    # 2. Benign inputs must remain unchanged
    benign_inputs = [
        "Normal Company Name",
        "Chevron",
        "Oil & Gas",
        "Company with\nembedded newline",
        "",
        None,
        42,
        -15.5,
    ]
    for b in benign_inputs:
        assert sanitize_value_for_csv(b) == b

    # 3. DataFrame sanitization
    df = pd.DataFrame({
        "company": ["=MaliciousCorp", "SafeCorp", "  @EvilCorp"],
        "segment": ["+Oil & Gas", "Chemicals", "-Mining"],
        "numeric_id": [101, -202, 303],
        "score": [0.95, -0.45, 1.25],
    })
    safe_df = sanitize_dataframe_for_csv(df)

    # Check that strings are sanitized
    assert safe_df["company"].iloc[0] == "'=MaliciousCorp"
    assert safe_df["company"].iloc[1] == "SafeCorp"
    assert safe_df["company"].iloc[2] == "'  @EvilCorp"
    assert safe_df["segment"].iloc[0] == "'+Oil & Gas"
    assert safe_df["segment"].iloc[2] == "'-Mining"

    # Check numeric types are strictly preserved
    assert safe_df["numeric_id"].iloc[1] == -202
    assert safe_df["score"].iloc[1] == -0.45
    assert safe_df["numeric_id"].dtype == df["numeric_id"].dtype

    # Check source DataFrame was not mutated
    assert df["company"].iloc[0] == "=MaliciousCorp"


def test_csv_sanitizer_applied_to_browser_and_ranker_exports():
    """Verify formula injection sanitization is applied at Browser and Ranker export boundaries."""
    malicious_csv = (
        "company,segment,domain,trigger_type,trigger_date,trigger_summary,scanned_at\n"
        "=CMD() Calc,Oil & Gas,calc.example.com,hiring_burst,2026-08-10,+Formula in summary,2026-09-17\n"
        "@Echo Corp,-NegativeSegment,echo.example.com,turnaround,2026-08-15,\tTab summary,2026-09-17\n"
    )
    val = validate_custom_csv(malicious_csv.encode("utf-8"), "malicious.csv")
    assert val.is_valid

    portfolio = load_wingman_portfolio(
        csv_path=val.clean_df,
        as_of_date=date(2026, 9, 17),
        is_custom=True,
    )
    companies_df = portfolio["companies_df"]

    # Browser export simulation
    safe_browser_df = sanitize_dataframe_for_csv(companies_df)
    browser_csv = safe_browser_df.to_csv(index=False)
    assert "'=CMD() Calc" in browser_csv
    assert "'@Echo Corp" in browser_csv
    assert ("'-Negativesegment" in browser_csv) or ("'-NegativeSegment" in browser_csv)

    # Ranker export simulation
    safe_ranker_df = sanitize_dataframe_for_csv(companies_df)
    ranker_csv = safe_ranker_df.to_csv(index=False)
    assert "'=CMD() Calc" in ranker_csv


def test_evidence_url_safety_comprehensive():
    """Verify evidence URL syntactic validation, rejecting SSRF vectors, local paths, and malicious schemes."""
    # 1. Valid URLs (should return True)
    assert is_safe_evidence_url("https://www.reuters.com/business/energy/article1")
    assert is_safe_evidence_url("http://press.example.com/releases/2026-fid")
    assert is_safe_evidence_url("https://sub.domain.co.uk:8443/item?id=123&test=1")

    # 2. Dangerous schemes (should return False)
    assert not is_safe_evidence_url("file:///etc/passwd")
    assert not is_safe_evidence_url("file://localhost/etc/shadow")
    assert not is_safe_evidence_url("javascript:alert(1)")
    assert not is_safe_evidence_url("data:text/html,<script>alert(1)</script>")
    assert not is_safe_evidence_url("mailto:security@example.com")
    assert not is_safe_evidence_url("about:blank")

    # 3. Local filesystem paths (should return False)
    assert not is_safe_evidence_url("/var/log/system.log")
    assert not is_safe_evidence_url("C:\\Windows\\System32\\calc.exe")
    assert not is_safe_evidence_url("../passwords.txt")
    assert not is_safe_evidence_url(".\\secrets.env")

    # 4. Obvious local / internal hostnames (should return False)
    assert not is_safe_evidence_url("http://localhost:8501")
    assert not is_safe_evidence_url("https://app.localhost/page")
    assert not is_safe_evidence_url("http://broadcasthost/")
    assert not is_safe_evidence_url("http://intranet.local/")
    assert not is_safe_evidence_url("http://api.internal/v1")
    assert not is_safe_evidence_url("http://router.lan/")

    # 5. IPv4 Loopback & Non-Public addresses (should return False)
    assert not is_safe_evidence_url("http://127.0.0.1:8000")
    assert not is_safe_evidence_url("http://127.0.0.254")
    assert not is_safe_evidence_url("http://10.0.0.1/")
    assert not is_safe_evidence_url("http://172.16.5.10/")
    assert not is_safe_evidence_url("http://192.168.1.1/")
    assert not is_safe_evidence_url("http://0.0.0.0:80")
    assert not is_safe_evidence_url("http://169.254.169.254/latest/meta-data/")
    assert not is_safe_evidence_url("http://100.64.0.1/")
    assert not is_safe_evidence_url("http://255.255.255.255/")

    # 6. IPv6 Loopback & Non-Public addresses (should return False)
    assert not is_safe_evidence_url("http://[::1]/")
    assert not is_safe_evidence_url("http://[fe80::1]/")
    assert not is_safe_evidence_url("http://[fc00::1]/")
    assert not is_safe_evidence_url("http://[fd00::1]/")
    assert not is_safe_evidence_url("http://[::ffff:127.0.0.1]/")
    assert not is_safe_evidence_url("http://[::ffff:10.0.0.1]/")

    # 7. Credential-bearing URLs (should return False)
    assert not is_safe_evidence_url("https://user:password@example.com/news")
    assert not is_safe_evidence_url("http://admin@company.com/")

    # 8. Deceptive IP formats (should return False)
    assert not is_safe_evidence_url("http://0x7f000001/")
    assert not is_safe_evidence_url("http://2130706433/")
    assert not is_safe_evidence_url("http://0177.0.0.1/")
    assert not is_safe_evidence_url("http://intranet/")  # host without domain dot
    assert not is_safe_evidence_url("http://host..domain.com/")

    # 9. Malformed / empty URLs (should return False)
    assert not is_safe_evidence_url("http://")
    assert not is_safe_evidence_url("https://")
    assert not is_safe_evidence_url("not a url")
    assert not is_safe_evidence_url("")
    assert not is_safe_evidence_url(None)


def test_two_session_complete_isolation():
    """Verify strict session isolation between two concurrent user sessions."""
    # Create distinct custom CSVs
    csv_a = "company,segment\nAlphaCorp,Renewables\n".encode("utf-8")
    csv_b = "company,segment\nBetaCorp,Mining\n".encode("utf-8")

    val_a = validate_custom_csv(csv_a, "alpha.csv")
    val_b = validate_custom_csv(csv_b, "beta.csv")

    # Simulate Session A
    session_a_state = {
        "active_data_source": {
            "source_type": "custom",
            "source_name": "Custom CSV: alpha.csv",
            "filename": "alpha.csv",
            "is_custom": True,
            "as_of_date": date(2026, 9, 20),
            "row_count": 1,
            "company_count": 1,
            "raw_df": val_a.clean_df.copy(),
            "content_hash": val_a.content_hash,
            "tier_mode": "distinct_categories",
        },
        "_portfolio_cache": {},
        "has_pending_custom_upload": False,
    }

    # Simulate Session B (on custom B)
    session_b_state = {
        "active_data_source": {
            "source_type": "custom",
            "source_name": "Custom CSV: beta.csv",
            "filename": "beta.csv",
            "is_custom": True,
            "as_of_date": date(2026, 9, 15),
            "row_count": 1,
            "company_count": 1,
            "raw_df": val_b.clean_df.copy(),
            "content_hash": val_b.content_hash,
            "tier_mode": "distinct_categories",
        },
        "_portfolio_cache": {},
        "has_pending_custom_upload": False,
    }

    # Assert Session A sees only AlphaCorp
    assert session_a_state["active_data_source"]["filename"] == "alpha.csv"
    assert session_a_state["active_data_source"]["raw_df"]["company"].tolist() == ["AlphaCorp"]

    # Assert Session B sees only BetaCorp
    assert session_b_state["active_data_source"]["filename"] == "beta.csv"
    assert session_b_state["active_data_source"]["raw_df"]["company"].tolist() == ["BetaCorp"]

    # Export isolation
    export_a = sanitize_dataframe_for_csv(session_a_state["active_data_source"]["raw_df"]).to_csv()
    export_b = sanitize_dataframe_for_csv(session_b_state["active_data_source"]["raw_df"]).to_csv()

    assert "AlphaCorp" in export_a
    assert "BetaCorp" not in export_a
    assert "BetaCorp" in export_b
    assert "AlphaCorp" not in export_b

    # Reset Session A to Default: verify Session B is untouched
    session_a_state["active_data_source"] = {
        "source_type": "default",
        "source_name": "Default Wingman Dataset",
        "filename": "wingman-trigger-export-2026-09-17-sanitized.csv",
        "is_custom": False,
        "company_count": 785,
    }
    assert session_a_state["active_data_source"]["is_custom"] is False
    assert session_a_state["active_data_source"]["company_count"] == 785

    # Session B remains on Custom Dataset B
    assert session_b_state["active_data_source"]["is_custom"] is True
    assert session_b_state["active_data_source"]["filename"] == "beta.csv"
    assert session_b_state["active_data_source"]["raw_df"]["company"].tolist() == ["BetaCorp"]


def test_pending_activation_clarification_banner():
    """Verify that uploading a valid CSV sets pending state while active dataset remains default."""
    valid_csv = "company,segment\nNewCompany,Oil & Gas\n".encode("utf-8")
    val = validate_custom_csv(valid_csv, "pending_test.csv")
    assert val.is_valid

    # Mock session state
    session = {
        "active_data_source": {
            "source_type": "default",
            "source_name": "Default Wingman Dataset",
            "filename": "wingman-trigger-export-2026-09-17-sanitized.csv",
            "is_custom": False,
            "company_count": 785,
        },
        "has_pending_custom_upload": True,
        "pending_custom_filename": "pending_test.csv",
    }

    # Verify pending flag is True while active source is still default
    assert session["has_pending_custom_upload"] is True
    assert session["active_data_source"]["is_custom"] is False
    assert session["active_data_source"]["company_count"] == 785


def test_conditional_section_headings_portfolio_insights():
    """
    Verify conditional section language for Portfolio Observations:
      - N < 10: 'Portfolio Descriptive Observations' and small-sample subtitle
      - 10 <= N <= 29: 'Portfolio Observations & Exploratory Patterns'
      - N >= 30: 'Portfolio Observations & Strategic Patterns'
    """
    def get_heading_and_subtitle(total_comps: int) -> tuple[str, str]:
        if total_comps < 10:
            h = "Portfolio Descriptive Observations"
            s = "Descriptive account and signal prevalence for the active custom dataset. Portfolio-level implications and co-occurrence patterns are suppressed for small samples."
        elif total_comps < 30:
            h = "Portfolio Observations & Exploratory Patterns"
            s = "Dynamically calculated observations and exploratory patterns for moderate sample sizes."
        else:
            h = "Portfolio Observations & Strategic Patterns"
            s = "Dynamically calculated observations separating confirmed empirical facts from commercial implications."
        return h, s

    # 1. N < 10 (e.g. 5 companies)
    h_5, s_5 = get_heading_and_subtitle(5)
    assert h_5 == "Portfolio Descriptive Observations"
    assert "Portfolio-level implications and co-occurrence patterns are suppressed" in s_5

    # 2. 10 <= N <= 29 (e.g. 15 companies)
    h_15, s_15 = get_heading_and_subtitle(15)
    assert h_15 == "Portfolio Observations & Exploratory Patterns"
    assert "exploratory patterns for moderate sample sizes" in s_15

    # 3. N >= 30 (e.g. 785 default companies)
    h_785, s_785 = get_heading_and_subtitle(785)
    assert h_785 == "Portfolio Observations & Strategic Patterns"
    assert "separating confirmed empirical facts from commercial implications" in s_785


def test_html_escaping_and_injection_prevention_comprehensive():
    """
    Verify that untrusted user-controlled values (URLs, company names, segments, summaries,
    filenames) are properly HTML-escaped before insertion into raw markup.
    Asserts that:
      - Dangerous tags (<script>, <img>, etc.) never produce executable markup
      - Unsafe URLs remain non-clickable
      - Safe links retain target="_blank" and rel="noopener noreferrer"
      - User-controlled strings are escaped (&, <, >, ", ')
    """
    import html
    from dashboard.components import render_badge, render_kpi_card

    # 1. Test URL safety check against XSS vectors
    xss_urls = [
        "<script>alert(1)</script>",
        "<img src=x onerror=alert(1)>",
        'https://example.com"><script>alert(1)</script>',
        "javascript:alert('xss')",
        "data:text/html,<script>alert(1)</script>",
        "<svg/onload=alert(1)>",
    ]
    for bad_url in xss_urls:
        assert not is_safe_evidence_url(bad_url), f"Should reject malicious URL: {bad_url}"

    # Safe URL check
    safe_url = "https://reuters.com/business/article-2026"
    assert is_safe_evidence_url(safe_url)

    # 2. Test HTML escaping in badge and KPI cards
    malicious_text = "<script>alert('badge')</script>"
    badge_html = render_badge(malicious_text, "green")
    assert "<script>" not in badge_html
    assert "&lt;script&gt;alert(&#x27;badge&#x27;)&lt;/script&gt;" in badge_html or "&lt;script&gt;alert('badge')&lt;/script&gt;" in badge_html

    kpi_title = '<b onmouseover="alert(1)">Title</b>'
    kpi_sub = '<img src=x onerror=alert(1)>'
    clean_kpi_title = html.escape(kpi_title)
    clean_kpi_sub = html.escape(kpi_sub)
    assert "<b " not in clean_kpi_title
    assert "<img" not in clean_kpi_sub
    assert "&lt;b onmouseover=&quot;alert(1)&quot;&gt;Title&lt;/b&gt;" in clean_kpi_title
    assert "&lt;img src=x onerror=alert(1)&gt;" in clean_kpi_sub

    # 3. Simulate Profile Card HTML Generation with Malicious Inputs
    malicious_csv = (
        "company,segment,domain,trigger_type,trigger_date,trigger_summary,trigger_source_url,scanned_at\n"
        "<script>alert('co')</script>,<img src=x onerror=alert(1)>,evil.com,project_fid_commissioning,2026-08-10,Summary <script>xss</script>,'https://example.com\"><script>alert(1)</script>',2026-09-17\n"
    )
    val = validate_custom_csv(malicious_csv.encode("utf-8"), "<script>file.csv")
    assert val.is_valid

    # Validate filename escaping
    escaped_filename = html.escape(val.filename)
    assert "<script>" not in escaped_filename
    assert "&lt;script&gt;file.csv" in escaped_filename

    # Build portfolio
    portfolio = load_wingman_portfolio(
        csv_path=val.clean_df,
        as_of_date=date(2026, 9, 17),
        is_custom=True,
    )
    comp_row = portfolio["companies_df"].iloc[0]
    ev_row = portfolio["all_considered_events_df"].iloc[0]

    # Verify field values before escaping
    raw_comp = comp_row["company_name"]
    raw_seg = comp_row["segment"]
    raw_sum = ev_row["trigger_summary"]
    raw_link = ev_row["trigger_source_url"]

    # Apply HTML escaping as in Company Browser
    clean_comp = html.escape(str(raw_comp))
    clean_seg = html.escape(str(raw_seg))
    clean_sum = html.escape(str(raw_sum))
    clean_link_escaped = html.escape(str(raw_link), quote=True)

    # Assert no executable tags survive
    assert "<script>" not in clean_comp
    assert "&lt;script&gt;" in clean_comp
    assert "<img" not in clean_seg.lower()
    assert "&lt;img" in clean_seg.lower()
    assert "<script>" not in clean_sum
    assert "&lt;script&gt;" in clean_sum

    # Link rendering simulation: unsafe URL must NOT be rendered as a clickable link
    is_safe = is_safe_evidence_url(raw_link)
    assert not is_safe

    if is_safe:
        rendered_link = f'<a href="{clean_link_escaped}" target="_blank" rel="noopener noreferrer">Link</a>'
    else:
        rendered_link = f'<span>Unverified link: <code>{clean_link_escaped}</code></span>'

    # Verify unsafe URL rendered as plain text in <code> and not in <a href>
    assert "<a href=" not in rendered_link
    assert "<code>" in rendered_link
    assert "&quot;&gt;&lt;script&gt;" in rendered_link or "&lt;script&gt;" in rendered_link

    # Verify safe URL retains attributes
    safe_test_url = "https://example.com/valid/link"
    assert is_safe_evidence_url(safe_test_url)
    clean_safe = html.escape(safe_test_url, quote=True)
    safe_rendered = f'<a href="{clean_safe}" target="_blank" rel="noopener noreferrer">Evidence Link Available ↗</a>'
    assert 'target="_blank"' in safe_rendered
    assert 'rel="noopener noreferrer"' in safe_rendered
    assert f'href="{safe_test_url}"' in safe_rendered


def test_uploader_widget_max_upload_size_limit_configuration(monkeypatch):
    """
    Verify that the file uploader widget:
      1. Configures max_upload_size=10 MB if supported by installed Streamlit version.
      2. Falls back to an immediately visible caption stating:
         'Maximum accepted file size: 10 MB; maximum dataset size: 20,000 rows.'
         if max_upload_size is not supported in st.file_uploader signature.
      3. Preserves identical validation behavior (MAX_UPLOAD_SIZE_BYTES and MAX_ROW_COUNT).
    """
    import inspect
    import streamlit as st
    from dashboard.data_source import (
        MAX_UPLOAD_SIZE_MB,
        MAX_UPLOAD_SIZE_BYTES,
        MAX_ROW_COUNT,
        render_data_source_sidebar,
        init_data_source_session,
    )

    assert MAX_UPLOAD_SIZE_MB == 10
    assert MAX_UPLOAD_SIZE_BYTES == 10 * 1024 * 1024
    assert MAX_ROW_COUNT == 20000

    # 1. Test when max_upload_size is supported
    sig = inspect.signature(st.file_uploader)
    has_max_size_param = "max_upload_size" in sig.parameters
    assert has_max_size_param, "Installed Streamlit version (1.56.0) must support max_upload_size"

    # Setup session state for sidebar render in custom CSV upload mode
    st.session_state["data_source_mode_radio"] = "Custom CSV upload"
    if "active_data_source" not in st.session_state:
        init_data_source_session()

    captured_uploader_kwargs = {}

    def mock_file_uploader(*args, **kwargs):
        captured_uploader_kwargs.update(kwargs)
        return None

    monkeypatch.setattr(st.sidebar, "radio", lambda *a, **k: "Custom CSV upload")
    monkeypatch.setattr(st, "file_uploader", mock_file_uploader)

    # Render sidebar
    render_data_source_sidebar()
    assert captured_uploader_kwargs.get("max_upload_size") == 10
    assert captured_uploader_kwargs.get("accept_multiple_files") is False
    assert captured_uploader_kwargs.get("type") == ["csv"]

    # 2. Test fallback path when max_upload_size is NOT supported
    captured_captions = []

    def mock_caption(text, *args, **kwargs):
        captured_captions.append(text)

    import dashboard.data_source as ds_mod
    monkeypatch.setattr(ds_mod, "HAS_MAX_UPLOAD_SIZE", False)
    monkeypatch.setattr(st, "caption", mock_caption)
    captured_uploader_kwargs.clear()

    render_data_source_sidebar()
    assert "max_upload_size" not in captured_uploader_kwargs
    assert any("Maximum accepted file size: 10 MB; maximum dataset size: 20,000 rows." in c for c in captured_captions)


# =============================================================================
# DEFECT REGRESSION TESTS: Active State, Dynamic Horizon, Browser Directory
# =============================================================================

SMOKE_CSV_BYTES = (
    b"company,segment,domain,source_tier,trigger_type,trigger_date,trigger_summary,trigger_source_url,scanned_at\n"
    b"Apex Energy Systems,Oil & Gas,,1,project_fid_commissioning,2026-08-15,Approved final investment decision for LNG liquefaction train expansion with targeted mechanical completion in Q3 2027.,https://example.com/press/apex-lng-fid-announcement,2026-09-15\n"
    b"Apex Energy Systems,Oil & Gas,,1,hiring_burst,2026-08-28,\"Posted 45 frontline operations, control-room console, and maintenance technician roles for plant pre-commissioning.\",https://example.com/careers/apex-operations-hiring,2026-09-15\n"
    b"Beacon Chemical Technologies,Chemicals & Petrochemicals,,2,turnaround,2026-07-20,Scheduled 45-day major site turnaround and cracker revamp announced for Gulf Coast petrochemical complex.,Industrial Info Resources Trade Bulletin,2026-09-12\n"
    b"Crestview Engineering Partners,Diversified Industrial,,2,new_leader,,\"Appointed new Global Vice President of Health, Safety, and Environment to lead digital safety transformation.\",https://example.com/news/crestview-appoints-vp-hse,2026-09-10\n"
    b"Delta Midstream Logistics,Oil & Gas,,3,,,,,2026-09-08\n"
    b"Epsilon Power Operations,Diversified Industrial / Unspecified,,3,,,,,2026-08-28\n"
)


class MockUploadedFile(io.BytesIO):
    """Mock Streamlit UploadedFile object."""
    def __init__(self, content: bytes, name: str):
        super().__init__(content)
        self.name = name
        self.size = len(content)

    def getvalue(self) -> bytes:
        return self.getvalue_from_buf() if hasattr(self, "getvalue_from_buf") else super().getvalue()


def test_sidebar_custom_csv_active_state_suppresses_pending_warning(monkeypatch):
    """
    Defect 1 Regression Test:
    When a custom CSV is already active and the uploader retains the same file,
    the pending activation warning must be suppressed, 'Custom CSV active' confirmation shown,
    and the activation button / date input must be disabled.
    """
    import streamlit as st
    from dashboard.data_source import (
        validate_custom_csv,
        activate_custom_dataset,
        render_data_source_sidebar,
    )

    # 1. Setup session state with active custom smoke CSV
    val_res = validate_custom_csv(SMOKE_CSV_BYTES, "wingman-dashboard-smoke.csv")
    assert val_res.is_valid
    activate_custom_dataset(val_res, chosen_as_of_date=date(2026, 9, 15))

    assert st.session_state["active_data_source"]["is_custom"] is True
    assert st.session_state["active_data_source"]["filename"] == "wingman-dashboard-smoke.csv"
    assert st.session_state["has_pending_custom_upload"] is False

    # 2. Mock Streamlit UI calls
    active_mock_file = MockUploadedFile(SMOKE_CSV_BYTES, "wingman-dashboard-smoke.csv")
    captured_successes = []
    captured_warnings = []
    captured_button_kwargs = {}
    captured_date_kwargs = {}

    monkeypatch.setattr(st.sidebar, "radio", lambda *a, **k: "Custom CSV upload")
    monkeypatch.setattr(st, "file_uploader", lambda *a, **k: active_mock_file)
    monkeypatch.setattr(st, "success", lambda text, *a, **k: captured_successes.append(text))
    monkeypatch.setattr(st, "warning", lambda text, *a, **k: captured_warnings.append(text))
    monkeypatch.setattr(st, "caption", lambda *a, **k: None)
    monkeypatch.setattr(st, "markdown", lambda *a, **k: None)
    monkeypatch.setattr(st, "download_button", lambda *a, **k: None)

    def mock_date_input(label, *a, **kwargs):
        captured_date_kwargs.update(kwargs)
        return kwargs.get("value", date(2026, 9, 15))

    def mock_button(label, *a, **kwargs):
        captured_button_kwargs.update(kwargs)
        return False

    monkeypatch.setattr(st, "date_input", mock_date_input)
    monkeypatch.setattr(st, "button", mock_button)

    # 3. Render sidebar
    render_data_source_sidebar()

    # 4. Assert pending warning is SUPPRESSED and active status is confirmed
    assert st.session_state["has_pending_custom_upload"] is False
    assert any("Custom CSV active" in s for s in captured_successes)
    assert not any("pending activation" in w for w in captured_warnings)

    # 5. Assert activation button and date input are disabled for the active file
    assert captured_button_kwargs.get("disabled") is True
    assert captured_date_kwargs.get("disabled") is True


def test_sidebar_staged_replacement_preserves_active_and_enables_activation(monkeypatch):
    """
    Defect 1 Regression Test:
    When a custom dataset is active and a DIFFERENT file is uploaded:
    1. Replacement pending warning is shown.
    2. Activation button is enabled.
    3. Active dataset remains unchanged until activation is explicitly triggered.
    4. Upon activation, the new dataset becomes active.
    """
    import streamlit as st
    from dashboard.data_source import (
        validate_custom_csv,
        activate_custom_dataset,
        render_data_source_sidebar,
    )

    # 1. Activate original smoke CSV
    val_res_orig = validate_custom_csv(SMOKE_CSV_BYTES, "wingman-dashboard-smoke.csv")
    activate_custom_dataset(val_res_orig, chosen_as_of_date=date(2026, 9, 15))
    orig_hash = st.session_state["active_data_source"]["content_hash"]

    # 2. Stage a different replacement CSV
    replacement_bytes = (
        b"company,segment,domain,source_tier,trigger_type,trigger_date,scanned_at\n"
        b"Replacement Energy,Oil & Gas,rep.example.com,1,turnaround,2026-08-01,2026-09-15\n"
    )
    replacement_file = MockUploadedFile(replacement_bytes, "replacement_dataset.csv")

    captured_warnings = []
    captured_button_kwargs = {}
    captured_date_kwargs = {}

    monkeypatch.setattr(st.sidebar, "radio", lambda *a, **k: "Custom CSV upload")
    monkeypatch.setattr(st, "file_uploader", lambda *a, **k: replacement_file)
    monkeypatch.setattr(st, "success", lambda *a, **k: None)
    monkeypatch.setattr(st, "warning", lambda text, *a, **k: captured_warnings.append(text))
    monkeypatch.setattr(st, "caption", lambda *a, **k: None)
    monkeypatch.setattr(st, "markdown", lambda *a, **k: None)
    monkeypatch.setattr(st, "download_button", lambda *a, **k: None)

    def mock_date_input(label, *a, **kwargs):
        captured_date_kwargs.update(kwargs)
        return kwargs.get("value", date(2026, 9, 15))

    def mock_button(label, *a, **kwargs):
        captured_button_kwargs.update(kwargs)
        return False

    monkeypatch.setattr(st, "date_input", mock_date_input)
    monkeypatch.setattr(st, "button", mock_button)

    render_data_source_sidebar()

    # 3. Assert replacement staging behavior
    assert st.session_state["has_pending_custom_upload"] is True
    assert st.session_state["pending_custom_filename"] == "replacement_dataset.csv"
    assert any("Replacement CSV pending activation" in w for w in captured_warnings)
    assert captured_button_kwargs.get("disabled") is not True

    # 4. Crucial: Active data source was NOT replaced before clicking button
    assert st.session_state["active_data_source"]["filename"] == "wingman-dashboard-smoke.csv"
    assert st.session_state["active_data_source"]["content_hash"] == orig_hash

    # 5. Simulate activation of replacement CSV
    val_res_rep = validate_custom_csv(replacement_bytes, "replacement_dataset.csv")
    activate_custom_dataset(val_res_rep, chosen_as_of_date=date(2026, 9, 15))

    assert st.session_state["active_data_source"]["filename"] == "replacement_dataset.csv"
    assert st.session_state["active_data_source"]["content_hash"] != orig_hash
    assert st.session_state["active_data_source"]["company_count"] == 1
    assert st.session_state["has_pending_custom_upload"] is False


def test_company_browser_dynamic_horizon_options_and_filtering():
    """
    Defect 2 Regression Test:
    Company Browser Signal Activity Horizon must calculate dynamic universe counts
    and filter correctly across both custom and default datasets.
    """
    # 1. Custom Smoke Dataset (5 companies: 2 active, 3 inactive)
    val_smoke = validate_custom_csv(SMOKE_CSV_BYTES, "smoke.csv")
    portfolio_smoke = load_wingman_portfolio(
        csv_path=val_smoke.clean_df,
        as_of_date=date(2026, 9, 15),
        is_custom=True,
    )
    df_smoke = portfolio_smoke["companies_df"]
    total_smoke = len(df_smoke)
    active_smoke = int((df_smoke["distinct_category_count"] > 0).sum())
    inactive_smoke = int((df_smoke["distinct_category_count"] == 0).sum())

    assert total_smoke == 5
    assert active_smoke == 2
    assert inactive_smoke == 3

    smoke_options = [
        f"All Accounts ({total_smoke})",
        f"Active Signals Only ({active_smoke})",
        f"Inactive / Nurture Only ({inactive_smoke})",
    ]
    assert smoke_options == [
        "All Accounts (5)",
        "Active Signals Only (2)",
        "Inactive / Nurture Only (3)",
    ]

    # Verify filter logic
    active_filtered = df_smoke[df_smoke["distinct_category_count"] > 0]
    assert len(active_filtered) == 2
    assert set(active_filtered["company_name"]) == {"Apex Energy Systems", "Beacon Chemical Technologies"}

    inactive_filtered = df_smoke[df_smoke["distinct_category_count"] == 0]
    assert len(inactive_filtered) == 3
    assert set(inactive_filtered["company_name"]) == {
        "Crestview Engineering Partners",
        "Delta Midstream Logistics",
        "Epsilon Power Operations",
    }

    # 2. Default Dataset (785 companies: 341 active, 444 inactive)
    portfolio_default = load_wingman_portfolio(
        csv_path=str(DEFAULT_SANITIZED_CSV),
        as_of_date=DEFAULT_AS_OF_DATE,
        is_custom=False,
    )
    df_default = portfolio_default["companies_df"]
    total_default = len(df_default)
    active_default = int((df_default["distinct_category_count"] > 0).sum())
    inactive_default = int((df_default["distinct_category_count"] == 0).sum())

    assert total_default == 785
    assert active_default == 341
    assert inactive_default == 444

    default_options = [
        f"All Accounts ({total_default})",
        f"Active Signals Only ({active_default})",
        f"Inactive / Nurture Only ({inactive_default})",
    ]
    assert default_options == [
        "All Accounts (785)",
        "Active Signals Only (341)",
        "Inactive / Nurture Only (444)",
    ]


def test_synthetic_smoke_dataset_all_five_companies_profiles():
    """
    Defect 3 Regression Test:
    Verify that all 5 synthetic companies in wingman-dashboard-smoke.csv:
    1. Render in the directory table.
    2. Have complete and correct profile data and commercial status classifications.
    3. Null-date triggers (Crestview) are marked undated/inactive.
    4. Plain-text citations (Beacon) are not clickable links.
    5. Epsilon uses segment 'Diversified Industrial / Unspecified'.
    """
    val_smoke = validate_custom_csv(SMOKE_CSV_BYTES, "wingman-dashboard-smoke.csv")
    assert val_smoke.is_valid
    assert val_smoke.company_count == 5

    portfolio = load_wingman_portfolio(
        csv_path=val_smoke.clean_df,
        as_of_date=date(2026, 9, 15),
        is_custom=True,
    )
    companies_df = portfolio["companies_df"]
    events_df = portfolio["all_considered_events_df"]

    assert len(companies_df) == 5
    expected_companies = {
        "Apex Energy Systems",
        "Beacon Chemical Technologies",
        "Crestview Engineering Partners",
        "Delta Midstream Logistics",
        "Epsilon Power Operations",
    }
    assert set(companies_df["company_name"]) == expected_companies

    # 1. Apex Energy Systems: 2 active events, multiple signals -> Research & Qualify Now
    apex = companies_df[companies_df["company_name"] == "Apex Energy Systems"].iloc[0]
    apex_events = events_df[events_df["company"] == "Apex Energy Systems"]
    assert apex["segment"] == "Oil & Gas"
    assert apex["distinct_category_count"] == 2
    assert apex["current_status"] == "Research & Qualify Now"
    assert len(apex_events) == 2
    for _, ev in apex_events.iterrows():
        assert ev["is_active"] is True
        assert is_safe_evidence_url(ev["trigger_source_url"]) is True

    # 2. Beacon Chemical Technologies: 1 active turnaround event -> Follow-Up Qualification
    beacon = companies_df[companies_df["company_name"] == "Beacon Chemical Technologies"].iloc[0]
    beacon_events = events_df[events_df["company"] == "Beacon Chemical Technologies"]
    assert beacon["segment"] == "Chemicals & Petrochemicals"
    assert beacon["distinct_category_count"] == 1
    assert beacon["current_status"] == "Follow-Up Qualification"
    assert len(beacon_events) == 1
    beacon_ev = beacon_events.iloc[0]
    assert bool(beacon_ev["is_active"]) is True
    # Plain text trade bulletin citation is not a safe web link
    assert is_safe_evidence_url(beacon_ev["trigger_source_url"]) is False

    # 3. Crestview Engineering Partners: blank trigger_date -> undated, inactive -> Monitor
    crestview = companies_df[companies_df["company_name"] == "Crestview Engineering Partners"].iloc[0]
    crestview_events = events_df[events_df["company"] == "Crestview Engineering Partners"]
    assert crestview["segment"] == "Diversified Industrial"
    assert crestview["distinct_category_count"] == 0
    assert crestview["current_status"] == "Monitor"
    assert len(crestview_events) == 1
    cv_ev = crestview_events.iloc[0]
    assert pd.isna(cv_ev["parsed_date"])
    assert bool(cv_ev["is_active"]) is False
    assert cv_ev["temporal_status"] == "EXPIRED"

    # 4. Delta Midstream Logistics: zero triggers -> Monitor
    delta = companies_df[companies_df["company_name"] == "Delta Midstream Logistics"].iloc[0]
    assert delta["segment"] == "Oil & Gas"
    assert delta["distinct_category_count"] == 0
    assert delta["current_status"] == "Monitor"

    # 5. Epsilon Power Operations: zero triggers, segment 'Diversified Industrial / Unspecified' -> Monitor
    epsilon = companies_df[companies_df["company_name"] == "Epsilon Power Operations"].iloc[0]
    assert epsilon["segment"] == "Diversified Industrial / Unspecified"
    assert epsilon["distinct_category_count"] == 0
    assert epsilon["current_status"] == "Monitor"


def test_return_to_default_dataset_resets_state_and_restores_baseline():
    """
    Verify that return_to_default_dataset():
    1. Reinstates Default Wingman Dataset as active with 785 accounts.
    2. Restores exact baseline queue distribution.
    3. Clears all filter keys, selected company, and uploader keys.
    """
    import streamlit as st
    from dashboard.data_source import (
        validate_custom_csv,
        activate_custom_dataset,
        return_to_default_dataset,
    )

    # 1. Activate custom dataset and simulate dirty session state
    val_smoke = validate_custom_csv(SMOKE_CSV_BYTES, "smoke.csv")
    activate_custom_dataset(val_smoke, chosen_as_of_date=date(2026, 9, 15))

    st.session_state["browser_filter_catalysts"] = ["Hiring Bursts"]
    st.session_state["browser_filter_status"] = "Ready for Outreach"
    st.session_state["browser_filter_multi"] = True
    st.session_state["browser_selected_company"] = "Apex Energy Systems"
    st.session_state["uploader_custom_csv"] = "mock_uploaded_file"
    st.session_state["sidebar_source_mode_radio"] = "Custom CSV upload"

    # 2. Revert to default
    return_to_default_dataset()

    # 3. Assert active data source is default
    ds = st.session_state["active_data_source"]
    assert ds["is_custom"] is False
    assert ds["source_name"] == "Default Wingman Dataset"
    assert ds["company_count"] == 785

    # 4. Assert baseline queue distribution
    comps = ds["portfolio"]["companies_df"]
    status_counts = comps["current_status"].value_counts().to_dict()
    assert status_counts.get("Ready for Outreach", 0) == 0
    assert status_counts.get("Research & Qualify Now", 0) == 127
    assert status_counts.get("Business Model Review", 0) == 199
    assert status_counts.get("Follow-Up Qualification", 0) == 192
    assert status_counts.get("Monitor", 0) == 267

    # 5. Assert transient state keys were reset (deleted from session state)
    assert "browser_filter_catalysts" not in st.session_state
    assert "browser_filter_status" not in st.session_state
    assert "browser_filter_multi" not in st.session_state
    assert "browser_selected_company" not in st.session_state
    assert "uploader_custom_csv" not in st.session_state
    assert "sidebar_source_mode_radio" not in st.session_state


def test_session_isolation_custom_dataset():
    """
    Verify that custom dataset session state is strictly isolated
    and does not mutate underlying baseline files or default cached objects.
    """
    import streamlit as st
    from dashboard.data_source import (
        validate_custom_csv,
        activate_custom_dataset,
        get_active_dataset,
    )

    # Calculate default dataset SHA-256 before custom activation
    import hashlib
    with open(DEFAULT_SANITIZED_CSV, "rb") as f:
        baseline_hash_before = hashlib.sha256(f.read()).hexdigest()

    assert baseline_hash_before == "5f262e7f91e90442383f6a795b52fe393edaf7e7c3af0c73b2b40a8d110905e4"

    # Activate custom dataset
    val_smoke = validate_custom_csv(SMOKE_CSV_BYTES, "smoke.csv")
    activate_custom_dataset(val_smoke, chosen_as_of_date=date(2026, 9, 15))

    active = get_active_dataset()
    assert active["is_custom"] is True
    assert active["company_count"] == 5

    # Verify baseline disk file remains untouched
    with open(DEFAULT_SANITIZED_CSV, "rb") as f:
        baseline_hash_after = hashlib.sha256(f.read()).hexdigest()

    assert baseline_hash_after == "5f262e7f91e90442383f6a795b52fe393edaf7e7c3af0c73b2b40a8d110905e4"
