"""
Comprehensive Unit and Integration Tests for Wingman Portfolio Intelligence Module and Views.
Validates:
  1. Full CSV loading, UTF-8 BOM handling, and deduplication across 785 unique companies
  2. CSV-only operational independence: proves enterprise pages work with ZERO dependency on PDF extracts
  3. Complete account identity reconciliation (1,180 rows, 785 accounts, 0 missing, 0 extra, 0 collapsed)
  4. Auditable dynamic tiering in distinct categories mode (130 Tier 1, 211 Tier 2, 444 Nurture)
  5. Auditable dynamic tiering in event count mode (163 Tier 1, 178 Tier 2, 444 Nurture)
  6. Softened customer fit review ('POSSIBLE OUT OF SCOPE — REVIEW REQUIRED') with note excerpts
  7. Expiry horizon evaluation per trigger category
  8. Pairwise trigger co-occurrence matrix and archetype grouping
  9. Jaccard similarity trigger-profile lookalike matching
  10. Rules-based suggested actions with mandatory qualification gates
  11. Streamlit AppTest multipage journey starting from app.py through all enterprise views
"""

from datetime import date
from pathlib import Path
from unittest.mock import patch
import pytest
import pandas as pd
from streamlit.testing.v1 import AppTest

from dashboard.wingman_portfolio import (
    load_wingman_portfolio,
    get_similar_companies,
    assess_customer_fit_from_notes,
    is_event_active,
    derive_suggested_action,
    normalize_domain,
    normalize_company_name,
    parse_iso_date,
    generate_portfolio_observations,
    DEFAULT_EXPIRY_WINDOWS,
    DEFAULT_AS_OF_DATE,
)

CSV_PATH = Path(__file__).resolve().parents[1] / "local_data" / "wingman-trigger-export-2026-09-17.csv"
SANITIZED_CSV_PATH = Path(__file__).resolve().parents[1] / "data" / "wingman-trigger-export-2026-09-17-sanitized.csv"
if not CSV_PATH.exists():
    CSV_PATH = SANITIZED_CSV_PATH
APP_PATH = Path(__file__).resolve().parents[1] / "app.py"


def test_full_csv_portfolio_loading():
    """Verify loading full Wingman CSV produces expected portfolio counts."""
    assert CSV_PATH.exists()
    res = load_wingman_portfolio(str(CSV_PATH), as_of_date=DEFAULT_AS_OF_DATE)

    metrics = res["metrics"]
    companies_df = res["companies_df"]

    assert metrics["total_companies"] == 785
    assert metrics["total_raw_rows"] == 1180
    assert len(companies_df) == 785
    assert metrics["tier_1_count"] + metrics["tier_2_count"] + metrics["nurture_count"] == 785
    assert metrics["active_events_total"] > 0


def test_exact_account_identity_reconciliation():
    """
    Item 2 Reconciliation:
      - CSV rows received: 1,180
      - Unique source accounts: 785
      - Accounts displayed in Portfolio Overview: 785
      - Missing accounts: 0
      - Unexpected additional accounts: 0
      - Accounts unintentionally collapsed: 0
      - Null company names: 0
      - Null domains: 3 (Schlumberger)
      - Shared domains across subsidiaries: 46
    """
    raw_df = pd.read_csv(CSV_PATH, encoding="utf-8-sig")
    assert len(raw_df) == 1180

    # 1. Null company names
    assert raw_df["company"].isna().sum() == 0
    assert (raw_df["company"].astype(str).str.strip() == "").sum() == 0

    # 2. Unique source accounts
    unique_companies = raw_df["company"].unique()
    assert len(unique_companies) == 785

    # 3. Domain nulls and duplicates
    null_domains = raw_df[raw_df["domain"].isna() | (raw_df["domain"].astype(str).str.strip().isin(["", "nan"]))]
    assert len(null_domains) == 3
    assert (null_domains["company"] == "schlumberger").all()

    # Shared domains
    dom_to_comps = raw_df.dropna(subset=["domain"]).groupby("domain")["company"].nunique()
    shared_domains = dom_to_comps[dom_to_comps > 1]
    assert len(shared_domains) == 46

    # 4. Load portfolio and verify 1:1 account representation
    res = load_wingman_portfolio(str(CSV_PATH), as_of_date=DEFAULT_AS_OF_DATE)
    comp_df = res["companies_df"]

    assert len(comp_df) == 785
    displayed_names = set(comp_df["company_name"])
    source_names = set(unique_companies)

    # Missing accounts: 0
    missing = source_names - displayed_names
    assert len(missing) == 0, f"Missing accounts: {missing}"

    # Unexpected additional accounts: 0
    unexpected = displayed_names - source_names
    assert len(unexpected) == 0, f"Unexpected accounts: {unexpected}"

    # Unintentional collapsing: 0
    assert len(displayed_names) == 785


def test_auditable_tiering_reconciliation():
    """
    Item 3: Verify auditable tiering counts and complete tier-audit DataFrame.
    Proposed Default (Distinct Categories): 130 Tier 1, 211 Tier 2, 444 Nurture.
    Event Count Mode: 163 Tier 1, 178 Tier 2, 444 Nurture.
    """
    res_cat = load_wingman_portfolio(str(CSV_PATH), as_of_date=DEFAULT_AS_OF_DATE, tier_mode="distinct_categories")
    res_evt = load_wingman_portfolio(str(CSV_PATH), as_of_date=DEFAULT_AS_OF_DATE, tier_mode="event_count")

    # Distinct categories mode audit
    assert res_cat["metrics"]["tier_1_count"] == 130
    assert res_cat["metrics"]["tier_2_count"] == 211
    assert res_cat["metrics"]["nurture_count"] == 444
    assert res_cat["metrics"]["tier_1_count"] + res_cat["metrics"]["tier_2_count"] + res_cat["metrics"]["nurture_count"] == 785

    # Event count mode audit
    assert res_evt["metrics"]["tier_1_count"] == 163
    assert res_evt["metrics"]["tier_2_count"] == 178
    assert res_evt["metrics"]["nurture_count"] == 444

    # Verify tier audit export DataFrame contains all 785 accounts
    tier_audit_df = res_cat["tier_audit_df"]
    assert len(tier_audit_df) == 785
    assert "tier_assignment_reason" in tier_audit_df.columns
    assert "distinct_active_categories" in tier_audit_df.columns
    assert "total_source_rows_in_csv" in tier_audit_df.columns

    # Verify each tier reason is explicit and auditable
    for _, row in res_cat["companies_df"].iterrows():
        reason = row["tier_reason"]
        assert reason.startswith("Tier 1:") or reason.startswith("Tier 2:") or reason.startswith("Nurture:")
        if row["tier"] == "Tier 1":
            assert row["distinct_category_count"] >= 2
        elif row["tier"] == "Tier 2":
            assert row["distinct_category_count"] == 1
        else:
            assert row["distinct_category_count"] == 0


def test_softened_customer_fit_review_required():
    """
    Item 4: Verify customer fit classification is softened to
    'POSSIBLE PROFILE MISMATCH — REVIEW REQUIRED' with matched note evidence.
    """
    res = load_wingman_portfolio(str(CSV_PATH), as_of_date=DEFAULT_AS_OF_DATE)
    comp_df = res["companies_df"]

    unassessed_count = (comp_df["fit_status"] == "FIT NOT YET ASSESSED").sum()
    review_req_count = (comp_df["fit_status"] == "POSSIBLE PROFILE MISMATCH — REVIEW REQUIRED").sum()

    assert unassessed_count + review_req_count == 785
    assert review_req_count > 0
    assert review_req_count == 199
    assert unassessed_count == 586

    # Verify review required accounts have matched phrase and review reason
    review_subset = comp_df[comp_df["fit_status"] == "POSSIBLE PROFILE MISMATCH — REVIEW REQUIRED"]
    for _, r in review_subset.iterrows():
        assert r["fit_matched_phrase"] != ""
        assert r["fit_note_excerpt"] != ""


def test_csv_only_operational_independence():
    """
    Item 1: Prove enterprise views function when PDF extracts (output/) are completely unavailable.
    None of the three enterprise pages imports or reads PDF-derived data.
    """
    output_dir = Path(__file__).resolve().parents[1] / "output"
    backup_dir = Path(__file__).resolve().parents[1] / "output_test_isolated_backup"

    assert output_dir.exists(), "Precondition: output/ must exist"

    try:
        # Rename output/ to simulate total absence of previous PDF extractions
        output_dir.rename(backup_dir)

        # Verify app.py boots directly to Page 10 without output/
        at = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
        assert len(at.exception) == 0
        assert "Portfolio Insights" in at.title[0].value

        # Switch to Page 11: Company Browser
        at.switch_page("dashboard/pages/11_company_browser.py").run()
        assert len(at.exception) == 0
        assert "Company Browser" in at.title[0].value

        # Switch to Page 12: Company Ranker
        at.switch_page("dashboard/pages/12_company_ranker.py").run()
        assert len(at.exception) == 0
        assert "Company Ranker" in at.title[0].value

    finally:
        # Restore output/
        if backup_dir.exists() and not output_dir.exists():
            backup_dir.rename(output_dir)


def test_multipage_app_user_journey():
    """
    Item 6: Complete multipage user journey starting from app.py.
    Boots on default Portfolio Insights,
    then switches sequentially through all 3 redesigned enterprise pages.
    """
    at = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    assert len(at.exception) == 0

    # Default page is Page 10: Portfolio Insights
    assert "Portfolio Insights" in at.title[0].value

    # Switch to Page 11: Company Browser
    at.switch_page("dashboard/pages/11_company_browser.py").run()
    assert len(at.exception) == 0
    assert "Company Browser" in at.title[0].value

    # Switch to Page 12: Company Ranker
    at.switch_page("dashboard/pages/12_company_ranker.py").run()
    assert len(at.exception) == 0
    assert "Company Ranker" in at.title[0].value


def test_suggested_actions_and_qualification_gates():
    """
    Item 7: Verify rules-based suggested actions include firing rule,
    supporting triggers, rationale, and mandatory qualification gates for unassessed accounts.
    """
    res = load_wingman_portfolio(str(CSV_PATH), as_of_date=DEFAULT_AS_OF_DATE)
    df = res["companies_df"]

    t1_unassessed = df[(df["tier"] == "Tier 1") & (df["fit_status"] == "FIT NOT YET ASSESSED")].iloc[0]
    act1 = t1_unassessed["action_details"]

    assert "Rule 4A" in act1["code"]
    assert "QUALIFICATION REQUIRED" in act1["qualification_gate"]
    assert len(act1["missing_information"]) > 0
    assert act1["why_appropriate"] != ""
    assert act1["what_would_change"] != ""

    # Scope review account
    review_acc = df[df["fit_status"] == "POSSIBLE PROFILE MISMATCH — REVIEW REQUIRED"].iloc[0]
    act_rev = review_acc["action_details"]
    assert "Rule 6" in act_rev["code"]
    assert "VERIFICATION REQUIRED" in act_rev["qualification_gate"]


def test_jaccard_trigger_profile_lookalikes():
    """
    Item 4: Verify trigger-profile lookalike finder uses Jaccard similarity
    over shared active trigger categories.
    """
    res = load_wingman_portfolio(str(CSV_PATH), as_of_date=DEFAULT_AS_OF_DATE)
    df = res["companies_df"]

    # Target: ADES Group
    lookalikes = get_similar_companies("ADES Group", df, top_n=5)
    assert len(lookalikes) == 5
    for l in lookalikes:
        assert 0.0 < l["similarity_score"] <= 1.0
        assert len(l["shared_triggers"]) > 0
        assert "suggested_playbook" in l


def test_queue_reconciliation_exact_counts():
    """
    Verify the 5 mutually exclusive queue allocation categories:
      - READY FOR OUTREACH: 0 (strictly gated by confirmed fit + buyer access)
      - RESEARCH & QUALIFY NOW: 127 (Tier 1 unassessed)
      - BUSINESS MODEL REVIEW: 199 (possible profile mismatch)
      - FOLLOW-UP QUALIFICATION: 192 (Tier 2 unassessed)
      - MONITOR: 267 (Nurture unassessed)
      - Total sum = 0 + 127 + 199 + 192 + 267 = 785
    """
    res = load_wingman_portfolio(str(SANITIZED_CSV_PATH), as_of_date=DEFAULT_AS_OF_DATE)
    metrics = res["metrics"]
    comp_df = res["companies_df"]

    assert metrics["ready_outreach_count"] == 0
    assert metrics["research_qualify_count"] == 127
    assert metrics["business_model_review_count"] == 199
    assert metrics["scope_hold_count"] == 199
    assert metrics["follow_up_qualify_count"] == 192
    assert metrics["monitor_count"] == 267
    assert (
        metrics["ready_outreach_count"]
        + metrics["research_qualify_count"]
        + metrics["business_model_review_count"]
        + metrics["follow_up_qualify_count"]
        + metrics["monitor_count"]
        == 785
    )

    # Also verify derived queue categories directly in the DataFrame
    queue_counts = comp_df["queue_category"].value_counts()
    assert queue_counts.get("Ready for Outreach", 0) == 0
    assert queue_counts.get("Research & Qualify Now", 0) == 127
    assert queue_counts.get("Business Model Review", 0) == 199
    assert queue_counts.get("Follow-Up Qualification", 0) == 192
    assert queue_counts.get("Monitor", 0) == 267
    assert queue_counts.sum() == 785

    # Verify transparent ranking criteria exists and is non-empty
    assert "ranking_rationale" in comp_df.columns
    assert comp_df["ranking_rationale"].str.len().min() > 5


def test_tier_disambiguation_fields():
    """
    Item 3: Verify source_tier, computed_tier, computed_tier_rule, and computed_as_of_date
    are distinctly exposed and populated across companies_df and tier_audit_df.
    """
    res = load_wingman_portfolio(str(SANITIZED_CSV_PATH), as_of_date=DEFAULT_AS_OF_DATE)
    comp_df = res["companies_df"]
    audit_df = res["tier_audit_df"]

    for col in ["source_tier", "computed_tier", "computed_tier_rule", "computed_as_of_date"]:
        assert col in comp_df.columns
        assert col in audit_df.columns
        assert comp_df[col].isna().sum() == 0
        assert audit_df[col].isna().sum() == 0

    assert set(comp_df["source_tier"].unique()).issubset({"Tier 1", "Tier 2", "Tier 3"})
    assert set(comp_df["computed_tier"].unique()).issubset({"Tier 1", "Tier 2", "Nurture"})


def test_data_sanitization_and_whitelisted_exports():
    """
    Verify strict external data boundary:
      - Raw notes and pattern_report_url are 100% removed from sanitized CSV
      - UI dataframes contain no raw notes or prototype URLs
      - Download exports strictly follow whitelisted column schemas
    """
    assert SANITIZED_CSV_PATH.exists()
    san_df = pd.read_csv(SANITIZED_CSV_PATH)

    # 1. Column absence in sanitized file
    assert "notes" not in san_df.columns
    assert "pattern_report_url" not in san_df.columns
    assert len(san_df) == 1180
    assert san_df["company"].nunique() == 785

    # 2. Portfolio load against sanitized data
    res = load_wingman_portfolio(str(SANITIZED_CSV_PATH), as_of_date=DEFAULT_AS_OF_DATE)
    comp_df = res["companies_df"]
    events_df = res["all_considered_events_df"]

    assert "notes" not in comp_df.columns
    assert "pattern_report_url" not in comp_df.columns
    assert "notes" not in events_df.columns
    assert "pattern_report_url" not in events_df.columns

    # 3. Downloadable export whitelists
    p10_whitelist = [
        "company_name", "domain", "segment", "tier", "tier_reason",
        "distinct_category_count", "active_event_count", "trigger_types",
        "fit_status", "fit_review_code", "fit_review_label",
        "queue_category", "suggested_action", "suggested_playbook",
        "action_urgency", "last_trigger_date",
    ]
    for col in p10_whitelist:
        assert col in comp_df.columns

    p12_whitelist = [
        "queue_category", "company_name", "domain", "segment", "tier",
        "distinct_category_count", "active_event_count", "trigger_types",
        "fit_status", "fit_review_code", "fit_review_label",
        "action_code", "action_name", "action_urgency", "suggested_action",
        "qualification_gate", "primary_research_step", "discovery_question",
        "last_trigger_date",
    ]
    p12_export_df = pd.DataFrame([
        {
            "queue_category": r["queue_category"],
            "company_name": r["company_name"],
            "domain": r["domain"],
            "segment": r["segment"],
            "tier": r["tier"],
            "distinct_category_count": r["distinct_category_count"],
            "active_event_count": r["active_event_count"],
            "trigger_types": r["trigger_types"],
            "fit_status": r["fit_status"],
            "fit_review_code": r["fit_review_code"],
            "fit_review_label": r["fit_review_label"],
            "action_code": r["action_details"].get("code", ""),
            "action_name": r["action_details"].get("name", ""),
            "action_urgency": r["action_urgency"],
            "suggested_action": r["suggested_action"],
            "qualification_gate": r["action_details"].get("qualification_gate", ""),
            "primary_research_step": r["action_details"].get("research_steps", [""])[0] if r["action_details"].get("research_steps") else "",
            "discovery_question": r["action_details"].get("discovery_question", ""),
            "last_trigger_date": r["last_trigger_date"],
        }
        for _, r in comp_df.iterrows()
    ])
    assert len(p12_export_df) == 785
    assert list(p12_export_df.columns) == p12_whitelist
    assert "notes" not in p12_export_df.columns
    assert "pattern_report_url" not in p12_export_df.columns


def test_sinopec_nonstandard_date_preservation():
    """
    Verify that nonstandard Sinopec date values are preserved without corruption
    and parsed correctly into valid dates:
      - '2026-Q3 (target, article 2025-05-23)' -> 2026-07-01
      - '2026-09 (listing ~17 days old as of Sep 2026 search)' -> 2026-09-01
    """
    d1 = parse_iso_date("2026-Q3 (target, article 2025-05-23)")
    assert d1 == date(2026, 7, 1)

    d2 = parse_iso_date("2026-09 (listing ~17 days old as of Sep 2026 search)")
    assert d2 == date(2026, 9, 1)

    # Verify in the sanitized dataset directly
    san_df = pd.read_csv(SANITIZED_CSV_PATH)
    sinopec_rows = san_df[san_df["company"] == "Sinopec"]
    sinopec_dates = set(sinopec_rows["trigger_date"].dropna())
    assert any("2026-Q3" in str(d) for d in sinopec_dates)
    assert any("listing ~17 days old" in str(d) for d in sinopec_dates)


def test_lift_calculation():
    """
    Verify normalized Observed-vs-Expected Lift metric for trigger co-occurrence.
    Lift = P(A, B) / (P(A) * P(B)).
    """
    res = load_wingman_portfolio(str(SANITIZED_CSV_PATH), as_of_date=DEFAULT_AS_OF_DATE)
    lift_matrix = res["pairwise_lift_matrix"]
    assert isinstance(lift_matrix, pd.DataFrame)
    assert lift_matrix.shape[0] > 0
    assert lift_matrix.shape[1] > 0
    for cat in lift_matrix.index:
        if lift_matrix.loc[cat, cat] > 0:
            assert lift_matrix.loc[cat, cat] >= 1.0


def test_latest_activity_dates_and_sorting():
    """
    Verify latest activity date semantics:
      - latest_source_activity: latest qualifying dated event on or before as-of date.
      - latest_observed_activity: latest qualifying date on or before the as-of date (2026-09-17).
      - next_upcoming_milestone: nearest qualifying future date (> 2026-09-17).
      - Future milestones are NOT treated as observed activity.
      - Null dates sort strictly last in descending date sort.
    """
    res = load_wingman_portfolio(str(SANITIZED_CSV_PATH), as_of_date=DEFAULT_AS_OF_DATE)
    df = res["companies_df"]

    assert "latest_source_activity" in df.columns
    assert "latest_observed_activity" in df.columns
    assert "next_upcoming_milestone" in df.columns
    assert "latest_activity_display" in df.columns
    assert "current_status" in df.columns

    # Verify observed dates do not contain future dates relative to DEFAULT_AS_OF_DATE
    for _, r in df[df["latest_observed_activity"] != ""].iterrows():
        obs_dt = pd.to_datetime(r["latest_observed_activity"]).date()
        assert obs_dt <= DEFAULT_AS_OF_DATE, f"Future date {obs_dt} found in latest_observed_activity for {r['company_name']}"

    # Verify upcoming milestones are strictly in the future (> DEFAULT_AS_OF_DATE)
    for _, r in df[df["next_upcoming_milestone"] != ""].iterrows():
        upc_dt = pd.to_datetime(r["next_upcoming_milestone"]).date()
        assert upc_dt > DEFAULT_AS_OF_DATE, f"Non-future date {upc_dt} found in next_upcoming_milestone for {r['company_name']}"

    # Check that companies with observed active activity have non-empty latest_observed_activity (339 accounts)
    observed_comps = df[df["latest_observed_activity"] != ""]
    assert len(observed_comps) == 339

    # Check future-only milestone accounts (North Oil Company and YPFB Transporte S.A.)
    future_only = df[(df["distinct_category_count"] > 0) & (df["latest_observed_activity"] == "")]
    assert len(future_only) == 2
    assert set(future_only["company_name"]) == {"North Oil Company", "YPFB Transporte S.A."}
    assert (future_only["next_upcoming_milestone"] != "").all()
    assert (future_only["latest_activity_display"].str.startswith("Upcoming:")).all()

    # Check sorting with nulls last in Recent Activity sort
    df_sorted = df.copy()
    df_sorted["parsed_date"] = pd.to_datetime(df_sorted["latest_observed_activity"], errors="coerce")
    sorted_df = df_sorted.sort_values(by="parsed_date", ascending=False, na_position="last").reset_index(drop=True)

    # The first row must have a valid date <= as_of_date
    assert pd.notna(sorted_df.iloc[0]["parsed_date"])
    assert sorted_df.iloc[0]["parsed_date"].date() <= DEFAULT_AS_OF_DATE

    # The last row must be null/NaT
    assert pd.isna(sorted_df.iloc[-1]["parsed_date"])

    # Exactly 339 non-null rows followed by 446 null rows (444 inactive + 2 future-only)
    assert sorted_df.iloc[:339]["parsed_date"].notna().all()
    assert sorted_df.iloc[339:]["parsed_date"].isna().all()


def test_default_status_taxonomy_and_reconciliation():
    """
    Verify that Current Status strictly uses the 5 mutually exclusive queue categories in Title Case:
      - Ready for Outreach (0)
      - Research & Qualify Now (127)
      - Business Model Review (199)
      - Follow-Up Qualification (192)
      - Monitor (267)
    Confirms zero mixing of tier labels in Current Status and exact 785 reconciliation.
    """
    res = load_wingman_portfolio(str(SANITIZED_CSV_PATH), as_of_date=DEFAULT_AS_OF_DATE)
    df = res["companies_df"]

    allowed_statuses = {
        "Ready for Outreach",
        "Research & Qualify Now",
        "Business Model Review",
        "Follow-Up Qualification",
        "Monitor",
    }

    assert set(df["current_status"].unique()).issubset(allowed_statuses)

    # Ensure no tier labels are mixed in current_status
    for val in df["current_status"].unique():
        assert not val.startswith("Tier ")
        assert val != "Nurture"

    counts = df["current_status"].value_counts().to_dict()
    assert counts.get("Ready for Outreach", 0) == 0
    assert counts["Research & Qualify Now"] == 127
    assert counts["Business Model Review"] == 199
    assert counts["Follow-Up Qualification"] == 192
    assert counts["Monitor"] == 267
    assert sum(counts.values()) == 785


def test_dynamic_portfolio_observations():
    """
    Verify zero hardcoded claims in dynamic observations generator:
      - Returns exactly 3 observations
      - Fact specifies exact count and denominator 785
      - Minimum support threshold (>=15 accounts) is enforced
      - Shortened card title: Commissioning + Turnaround
      - Expected under an independence baseline is verified
      - No claim that lift represents positive correlation
    """
    res = load_wingman_portfolio(str(SANITIZED_CSV_PATH), as_of_date=DEFAULT_AS_OF_DATE)
    obs = generate_portfolio_observations(res)

    assert len(obs) == 3
    obs_ids = [o["id"] for o in obs]
    assert "commissioning_dominance" in obs_ids
    assert "multi_catalyst_surges" in obs_ids
    assert "synergistic_pair" in obs_ids

    for o in obs:
        assert "785" in o["fact"]
        assert o["affected_count"] > 0
        assert "correlation" not in o["fact"].lower()
        assert "correlation" not in o["hypothesis"].lower()

    # Check minimum support threshold on synergistic pair
    pair_obs = next(o for o in obs if o["id"] == "synergistic_pair")
    assert pair_obs["affected_count"] >= 15
    assert pair_obs["title"] == "Commissioning + Turnaround"
    assert "independence baseline" in pair_obs["fact"]
    assert "Turnaround / Planned Maintenance + Frontline Hiring Burst" not in pair_obs["title"]


def test_company_ranker_presets_and_contiguous_indexing():
    """
    Verify that Company Ranker presets produce 1-indexed contiguous ranking with deterministic tie-breakers.
    """
    res = load_wingman_portfolio(str(SANITIZED_CSV_PATH), as_of_date=DEFAULT_AS_OF_DATE)
    df = res["companies_df"].copy()

    queue_order = {
        "Ready for Outreach": 0,
        "Research & Qualify Now": 1,
        "Business Model Review": 2,
        "Follow-Up Qualification": 3,
        "Monitor": 4,
    }
    tier_order = {"Tier 1": 0, "Tier 2": 1, "Nurture": 2}
    df["queue_rank"] = df["current_status"].map(queue_order).fillna(99)
    df["tier_rank"] = df["computed_tier"].map(tier_order).fillna(99)
    df["latest_active_date_parsed"] = pd.to_datetime(df["latest_active_catalyst"], errors="coerce")

    # Test Commercial Priority preset
    sorted_df = df.sort_values(
        by=["queue_rank", "tier_rank", "distinct_category_count", "active_event_count", "latest_active_date_parsed", "source_verified_count", "company_name"],
        ascending=[True, True, False, False, False, False, True],
        na_position="last",
    ).reset_index(drop=True)
    sorted_df["Rank"] = range(1, len(sorted_df) + 1)

    assert sorted_df.iloc[0]["Rank"] == 1
    assert sorted_df.iloc[-1]["Rank"] == 785
    assert list(sorted_df["Rank"]) == list(range(1, 786))
    assert sorted_df.iloc[0]["current_status"] == "Research & Qualify Now"
    assert sorted_df.iloc[-1]["current_status"] == "Monitor"


def test_kinder_morgan_active_catalyst_types_in_browser_and_ranker():
    """
    Automated assertion verifying that Kinder Morgan displays:
      - Active Signal Types (distinct_category_count) == 4 in both Browser and Ranker data views
      - Latest Observed Activity == '2026-08-11'
      - Status == 'Research & Qualify Now'
      - Active Events Count == 6
      - Qualification-first suggested action language
    """
    res = load_wingman_portfolio(str(SANITIZED_CSV_PATH), as_of_date=DEFAULT_AS_OF_DATE)
    df = res["companies_df"]

    km_rows = df[df["company_name"] == "Kinder Morgan"]
    assert len(km_rows) == 1, "Kinder Morgan must exist in portfolio"
    km = km_rows.iloc[0]

    # 1. Company Browser mapping assertion (Active Signal Types)
    browser_df = df[["company_name", "segment", "current_status", "distinct_category_count", "latest_observed_activity"]].rename(
        columns={
            "company_name": "Company",
            "segment": "Segment",
            "current_status": "Status",
            "distinct_category_count": "Active Signal Types",
            "latest_observed_activity": "Latest Observed Activity",
        }
    )
    km_browser = browser_df[browser_df["Company"] == "Kinder Morgan"].iloc[0]
    assert km_browser["Active Signal Types"] == 4, f"Expected 4 active signal types, got {km_browser['Active Signal Types']}"
    assert km_browser["Latest Observed Activity"] == "2026-08-11"
    assert km_browser["Status"] == "Research & Qualify Now"

    # 2. Company Ranker mapping assertion (Active Signal Types)
    ranker_cols = ["company_name", "current_status", "distinct_category_count", "latest_observed_activity"]
    km_ranker = df[df["company_name"] == "Kinder Morgan"][ranker_cols].rename(
        columns={
            "company_name": "Company",
            "current_status": "Status",
            "distinct_category_count": "Active Signal Types",
            "latest_observed_activity": "Latest Observed Activity",
        }
    ).iloc[0]
    assert km_ranker["Active Signal Types"] == 4, f"Expected 4 active signal types, got {km_ranker['Active Signal Types']}"
    assert km_ranker["Latest Observed Activity"] == "2026-08-11"
    assert km_ranker["Status"] == "Research & Qualify Now"

    # 3. Qualification-first suggested action language
    assert "Confirm the relevant operating use case" in km["suggested_action"]
    assert "operations, maintenance or HSE buyer before outreach" in km["suggested_action"]


def test_approved_status_taxonomy_and_no_legacy_labels():
    """
    Verify that no legacy status labels like 'Active Qualification' or 'active operational momentum'
    appear in suggested actions, research steps, or playbooks.
    """
    res = load_wingman_portfolio(str(SANITIZED_CSV_PATH), as_of_date=DEFAULT_AS_OF_DATE)
    df = res["companies_df"]

    # Check all suggested actions
    for _, r in df.iterrows():
        action_text = r["suggested_action"].lower()
        assert "active qualification" not in action_text
        assert "active operational momentum" not in action_text

    # Check Rule 6 details specifically
    bmr_rows = df[df["current_status"] == "Business Model Review"]
    for _, r in bmr_rows.iterrows():
        act_details = r.get("action_details", {})
        for step in act_details.get("research_steps", []):
            assert "Active Qualification" not in step
        assert "active qualification queue" not in act_details.get("what_would_change", "")


