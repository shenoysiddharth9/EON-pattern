"""
Page 12: Company Ranker
EON Commercial Intelligence | External Review Build — Proposed Phase 1

Prioritize companies using transparent, user-selected criteria and presets:
- Clear separation between Eligibility Filters and Ranking Criteria
- 4 primary presets via selectbox:
    1. Commercial Priority (Standard Workflow: Qualify -> Review -> Follow-up -> Monitor)
    2. Signal Momentum (Distinct Categories -> Event Count -> Recency)
    3. Recent Activity (Latest observed date descending with nulls last)
    4. Business Model Review (Prioritize profile-review accounts by operational complexity)
- Collapsed Advanced ranking options expander:
    - Upcoming Milestones
    - Research Priority
    - Evidence Availability
    - Custom Ranking (compact sort controls visible only when selected)
- UI-optimized, concise Why Ranked rationale preventing table clipping
- Whitelisted CSV export containing Rank, Current Status, Metrics, Playbooks, and full audit rationale
- Methodology disclaimers and tie-breaker transparency
"""

from pathlib import Path
from datetime import date
import streamlit as st
import pandas as pd

from dashboard.components import render_disclaimer, render_badge
from dashboard.data_source import get_active_dataset, render_source_banner, sanitize_dataframe_for_csv
from dashboard.wingman_portfolio import (
    DEFAULT_EXPIRY_WINDOWS,
    DEFAULT_AS_OF_DATE,
    TRIGGER_DISPLAY_LABELS,
)

# Page header
st.title("📊 Company Ranker")
render_source_banner()
st.caption(
    "EON Commercial Intelligence | External Review Build — Proposed Phase 1 | "
    "Prioritize companies transparently using business presets or custom multi-criteria scoring."
)

# Load Centralized Portfolio Data (cached and session-isolated)
with st.spinner("Loading portfolio data..."):
    active_ds = get_active_dataset()
    portfolio = active_ds["portfolio"]

companies_df = portfolio["companies_df"].copy()
total_universe = len(companies_df)
reference_date = active_ds["as_of_date"]
is_custom = active_ds["is_custom"]

# Map Phase 4 Master DB enrichment status if available (read-only safe hook)
try:
    from dashboard.company_db import get_all_companies_dataframe, normalize_str
    master_df = get_all_companies_dataframe()
    enr_status_map = dict(zip(master_df["normalized_name"], master_df["enrichment_status"]))
except Exception:
    enr_status_map = {}

companies_df["enrichment_status"] = companies_df["company_name"].apply(
    lambda x: enr_status_map.get(normalize_str(x), "not_started")
)

# Date formatting helper for UI
def format_ui_date(d):
    if not d or pd.isna(d):
        return ""
    try:
        dt = pd.to_datetime(d)
        return f"{dt.strftime('%b')} {dt.day}"
    except Exception:
        return str(d)

# ==========================================
# SECTION 1: ELIGIBILITY FILTERS
# ==========================================
st.markdown("### 1️⃣ Define Eligible Universe (Pre-Ranking Filters)")
st.caption("Filter the portfolio to the eligible account cohort before calculating rank orders.")

with st.container():
    ef_col1, ef_col2, ef_col3 = st.columns(3)
    
    with ef_col1:
        status_filter_options = [
            "All Queues",
            "Ready for Outreach",
            "Research & Qualify Now",
            "Business Model Review",
            "Follow-Up Qualification",
            "Monitor",
        ]
        selected_status = st.selectbox(
            "Filter by Current Status:",
            options=status_filter_options,
            index=0,
            help="Limit eligible accounts to a specific operational queue.",
        )
        
        search_filter = st.text_input(
            "Search Name / Domain:",
            value="",
            placeholder="Filter eligible accounts...",
            help="Filter companies matching name or domain substring.",
        )

    with ef_col2:
        all_segments = sorted(companies_df["segment"].unique())
        selected_segments = st.multiselect(
            "Filter by Segment:",
            options=all_segments,
            default=[],
            placeholder="All Industry Segments",
            help="Limit eligible accounts to selected segments.",
        )
        
        min_cats_option = st.selectbox(
            "Minimum Active Signals:",
            options=[
                "All Accounts (>= 0 signals)",
                "Active Signals Only (>= 1 signal type)",
                "Multiple Signals Only (>= 2 signal types)",
            ],
            index=0,
            help="Filter accounts by minimum distinct active signal categories.",
        )

    with ef_col3:
        bmr_filter_option = st.selectbox(
            "Business Model Review Flag:",
            options=[
                "Include All Accounts",
                "Operating Entities Only (Exclude Review Required)",
                "Review Required Only (Scope Hold Cohort)",
            ],
            index=0,
            help="Filter based on whether the account is flagged for business model verification.",
        )
        enrichment_filter_option = st.selectbox(
            "Enrichment Status:",
            options=[
                "All Accounts",
                "Current Verified Only (Complete or Partial)",
                "Current Verified (Complete) Only",
                "Not Yet Enriched Only",
            ],
            index=0,
            help="Filter accounts by statutory & firmographic verification status.",
        )

# Apply eligibility filters
eligible_df = companies_df.copy()

if selected_status != "All Queues":
    eligible_df = eligible_df[eligible_df["current_status"].str.upper() == selected_status.upper()]

if search_filter.strip():
    q = search_filter.strip().lower()
    eligible_df = eligible_df[
        eligible_df["company_name"].str.lower().str.contains(q, na=False)
        | eligible_df["domain"].str.lower().str.contains(q, na=False)
    ]

if selected_segments:
    eligible_df = eligible_df[eligible_df["segment"].isin(selected_segments)]

if min_cats_option == "Active Signals Only (>= 1 signal type)":
    eligible_df = eligible_df[eligible_df["distinct_category_count"] >= 1]
elif min_cats_option == "Multiple Signals Only (>= 2 signal types)":
    eligible_df = eligible_df[eligible_df["distinct_category_count"] >= 2]

if bmr_filter_option == "Operating Entities Only (Exclude Review Required)":
    eligible_df = eligible_df[~eligible_df["profile_review_required"]]
elif bmr_filter_option == "Review Required Only (Scope Hold Cohort)":
    eligible_df = eligible_df[eligible_df["profile_review_required"]]

if enrichment_filter_option == "Current Verified Only (Complete or Partial)":
    eligible_df = eligible_df[eligible_df["enrichment_status"].isin(["complete", "partial"])]
elif enrichment_filter_option == "Current Verified (Complete) Only":
    eligible_df = eligible_df[eligible_df["enrichment_status"] == "complete"]
elif enrichment_filter_option == "Not Yet Enriched Only":
    eligible_df = eligible_df[eligible_df["enrichment_status"] == "not_started"]

eligible_count = len(eligible_df)

st.caption(
    f"🎯 **Eligible Universe**: **{eligible_count}** of **{total_universe}** accounts "
    f"({round(100.0 * eligible_count / total_universe, 1)}% of total portfolio)"
)

st.markdown("---")

# ==========================================
# SECTION 2: RANKING PRESETS & CRITERIA
# ==========================================
st.markdown("### 2️⃣ Select Ranking Criteria & Presets")

col_r1, col_r2 = st.columns([1.5, 1.5])
with col_r1:
    primary_preset = st.selectbox(
        "Ranking method:",
        options=[
            "Commercial Priority",
            "Signal Momentum",
            "Recent Activity",
            "Business Model Review",
        ],
        index=0,
        help="Select one of the four primary operational ranking presets.",
    )

selected_preset = primary_preset

# Defaults for custom sort criteria
pri_col = "distinct_category_count"
pri_order = "High to Low"
sec_col = "active_event_count"
sec_order = "High to Low"

# Collapsed Advanced ranking options section
with st.expander("⚙️ Advanced ranking options", expanded=False):
    advanced_option = st.radio(
        "Advanced Ranking Options:",
        options=[
            "None (Use primary Ranking method above)",
            "Upcoming Milestones",
            "Research Priority",
            "Evidence Availability",
            "Custom Ranking",
        ],
        index=0,
        help="Select an advanced method or custom criteria to override the primary ranking method.",
    )
    
    if advanced_option != "None (Use primary Ranking method above)":
        selected_preset = advanced_option

    # Show primary/secondary sort controls ONLY when Custom Ranking is selected
    if selected_preset == "Custom Ranking":
        st.markdown("##### 🎛️ Custom Sort Criteria")
        c_col1, c_col2, c_col3, c_col4 = st.columns(4)
        
        criterion_labels = {
            "distinct_category_count": "Active Signal Types",
            "active_event_count": "Active Events Count",
            "latest_observed_activity_date": "Latest Observed Date",
            "next_upcoming_milestone_date": "Upcoming Milestone Date",
            "source_verified_count": "Evidence Links Count",
            "queue_rank": "Queue Order",
            "computed_tier_rank": "Computed Tier",
            "company_name": "Company Name",
        }
        
        with c_col1:
            pri_col = st.selectbox(
                "Primary Sort Column:",
                options=list(criterion_labels.keys()),
                format_func=lambda k: criterion_labels[k],
                index=0,
            )
        with c_col2:
            pri_order = st.selectbox("Primary Order:", options=["High to Low", "Low to High"], index=0)
        
        with c_col3:
            sec_col = st.selectbox(
                "Secondary Sort Column:",
                options=["None"] + list(criterion_labels.keys()),
                format_func=lambda k: criterion_labels.get(k, "None"),
                index=2,
            )
        with c_col4:
            sec_order = st.selectbox("Secondary Order:", options=["High to Low", "Low to High"], index=0)

# Helper fields for deterministic ranking
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

eligible_df["queue_rank"] = eligible_df["current_status"].map(queue_order).fillna(99)
eligible_df["computed_tier_rank"] = eligible_df["computed_tier"].map(tier_order).fillna(99)
eligible_df["latest_observed_date_parsed"] = pd.to_datetime(eligible_df["latest_observed_activity"], errors="coerce")
eligible_df["next_milestone_date_parsed"] = pd.to_datetime(eligible_df["next_upcoming_milestone"], errors="coerce")

# Format helper for Custom Ranking Rationale (full for CSV, concise for UI)
def format_criterion_val_full(col_key, row):
    if col_key in ("distinct_category_count", "active_signal_types"):
        c = row.get("distinct_category_count", 0)
        return f"{c} active signal types"
    elif col_key == "active_event_count":
        e = row.get("active_event_count", 0)
        return f"{e} active events"
    elif col_key in ("latest_observed_activity_date", "latest_observed_date_parsed", "latest_observed_activity"):
        d = row.get("latest_observed_activity")
        return f"observed {d}" if d else "no observed activity"
    elif col_key in ("next_upcoming_milestone_date", "next_milestone_date_parsed", "next_upcoming_milestone"):
        d = row.get("next_upcoming_milestone")
        return f"upcoming {d}" if d else "no upcoming milestone"
    elif col_key == "source_verified_count":
        s = row.get("source_verified_count", 0)
        return f"{s} evidence links"
    elif col_key in ("queue_rank", "current_status"):
        return f"status: {row.get('current_status', '')}"
    elif col_key in ("computed_tier_rank", "computed_tier"):
        return f"tier: {row.get('computed_tier', '')}"
    elif col_key == "company_name":
        return f"{row.get('company_name', '')}"
    else:
        return f"{row.get(col_key, '')}"

def format_criterion_val_ui(col_key, row):
    if col_key in ("distinct_category_count", "active_signal_types"):
        c = row.get("distinct_category_count", 0)
        return f"{c} signal types"
    elif col_key == "active_event_count":
        e = row.get("active_event_count", 0)
        return f"{e} events"
    elif col_key in ("latest_observed_activity_date", "latest_observed_date_parsed", "latest_observed_activity"):
        d = row.get("latest_observed_activity")
        return f"observed {format_ui_date(d)}" if d else "no activity"
    elif col_key in ("next_upcoming_milestone_date", "next_milestone_date_parsed", "next_upcoming_milestone"):
        d = row.get("next_upcoming_milestone")
        return f"upcoming {format_ui_date(d)}" if d else "no milestone"
    elif col_key == "source_verified_count":
        s = row.get("source_verified_count", 0)
        return f"{s} links"
    elif col_key in ("queue_rank", "current_status"):
        return f"{row.get('current_status', '')}"
    elif col_key in ("computed_tier_rank", "computed_tier"):
        return f"{row.get('computed_tier', '')}"
    elif col_key == "company_name":
        return f"{row.get('company_name', '')}"
    else:
        return f"{row.get(col_key, '')}"

# Ranking logic execution & plain-language explanation
if selected_preset == "Commercial Priority":
    sort_by = [
        "queue_rank",
        "computed_tier_rank",
        "distinct_category_count",
        "active_event_count",
        "latest_observed_date_parsed",
        "source_verified_count",
        "company_name",
    ]
    sort_asc = [True, True, False, False, False, False, True]
    preset_explanation = (
        "Prioritizes accounts by commercial actionability: Research & Qualify Now targets first, "
        "followed by active signal volume, recency, and available evidence links."
    )
    def row_reason_ui(r):
        c = r['distinct_category_count']
        e = r['active_event_count']
        obs = r['latest_observed_activity']
        obs_fmt = format_ui_date(obs)
        if obs_fmt:
            return f"{c} signals · {e} events · {obs_fmt}"
        elif e > 0:
            return f"{c} signals · {e} events"
        else:
            return "No active signals · Monitor"

    def row_reason_full(r):
        c = r['distinct_category_count']
        e = r['active_event_count']
        obs = r['latest_observed_activity']
        if obs:
            return f"{c} active signal types · {e} events · observed {obs}"
        elif e > 0:
            return f"{c} active signal types · {e} active events"
        else:
            return "No active signals · Routine monitoring"

elif selected_preset == "Signal Momentum":
    sort_by = [
        "distinct_category_count",
        "active_event_count",
        "latest_observed_date_parsed",
        "company_name",
    ]
    sort_asc = [False, False, False, True]
    preset_explanation = (
        "Ranks companies by the velocity and diversity of simultaneous operational signals."
    )
    def row_reason_ui(r):
        c = r['distinct_category_count']
        e = r['active_event_count']
        obs = r['latest_observed_activity']
        obs_fmt = format_ui_date(obs)
        return f"{c} signals · {e} events · {obs_fmt}" if obs_fmt else f"{c} signals · {e} events"

    def row_reason_full(r):
        c = r['distinct_category_count']
        e = r['active_event_count']
        obs = r['latest_observed_activity']
        return f"{c} active signal types · {e} events · observed {obs}" if obs else f"{c} active signal types · {e} active events"

elif selected_preset == "Recent Activity":
    sort_by = [
        "latest_observed_date_parsed",
        "distinct_category_count",
        "company_name",
    ]
    sort_asc = [False, False, True]
    preset_explanation = (
        "Orders accounts by the recency of their latest observed operational activity on or before the as-of date, placing accounts without observed activity last."
    )
    def row_reason_ui(r):
        obs = r['latest_observed_activity']
        obs_fmt = format_ui_date(obs)
        c = r['distinct_category_count']
        return f"Observed {obs_fmt} · {c} signals" if obs_fmt else "No observed activity"

    def row_reason_full(r):
        obs = r['latest_observed_activity']
        c = r['distinct_category_count']
        e = r['active_event_count']
        return f"Observed {obs} · {c} active signal types · {e} events" if obs else "No observed activity"

elif selected_preset == "Upcoming Milestones":
    sort_by = [
        "next_milestone_date_parsed",
        "distinct_category_count",
        "company_name",
    ]
    sort_asc = [True, False, True]
    preset_explanation = (
        "Orders accounts by the proximity of their nearest upcoming operational milestone scheduled after the as-of date, placing accounts without upcoming milestones last."
    )
    def row_reason_ui(r):
        upc = r['next_upcoming_milestone']
        upc_fmt = format_ui_date(upc)
        c = r['distinct_category_count']
        return f"Upcoming {upc_fmt} · {c} signals" if upc_fmt else "No upcoming milestones"

    def row_reason_full(r):
        upc = r['next_upcoming_milestone']
        c = r['distinct_category_count']
        return f"Upcoming {upc} · {c} active signal types" if upc else "No upcoming milestones"

elif selected_preset == "Business Model Review":
    eligible_df["is_bmr"] = (eligible_df["current_status"].str.upper() == "BUSINESS MODEL REVIEW").astype(int)
    sort_by = [
        "is_bmr",
        "distinct_category_count",
        "active_event_count",
        "company_name",
    ]
    sort_asc = [False, False, False, True]
    preset_explanation = (
        "Surfaces accounts requiring business model or profile verification, ordered by signal volume."
    )
    def row_reason_ui(r):
        c = r['distinct_category_count']
        e = r['active_event_count']
        if "BUSINESS MODEL" in r['current_status'].upper():
            return f"Profile review · {c} signals · {e} events"
        return f"{r['current_status']} · {c} signals"

    def row_reason_full(r):
        c = r['distinct_category_count']
        e = r['active_event_count']
        if "BUSINESS MODEL" in r['current_status'].upper():
            return f"Profile review · {c} active signal types · {e} events"
        return f"{r['current_status']} · {c} active signal types"

elif selected_preset == "Research Priority":
    eligible_df["is_research_target"] = (eligible_df["current_status"].str.upper() == "RESEARCH & QUALIFY NOW").astype(int)
    sort_by = [
        "is_research_target",
        "distinct_category_count",
        "active_event_count",
        "source_verified_count",
        "company_name",
    ]
    sort_asc = [False, False, False, False, True]
    preset_explanation = (
        "Focuses exclusively on Tier 1 surge accounts requiring immediate physical facility and buyer qualification."
    )
    def row_reason_ui(r):
        c = r['distinct_category_count']
        e = r['active_event_count']
        if "RESEARCH" in r['current_status'].upper():
            return f"Tier 1 surge · {c} signals · {e} events"
        return f"{r['current_status']} · {c} signals"

    def row_reason_full(r):
        c = r['distinct_category_count']
        e = r['active_event_count']
        if "RESEARCH" in r['current_status'].upper():
            return f"Tier 1 surge · {c} active signal types · {e} events"
        return f"{r['current_status']} · {c} active signal types"

elif selected_preset == "Evidence Availability":
    sort_by = [
        "source_verified_count",
        "distinct_category_count",
        "active_event_count",
        "company_name",
    ]
    sort_asc = [False, False, False, True]
    preset_explanation = (
        "Ranks accounts by the availability of public source evidence links, followed by commercial status."
    )
    def row_reason_ui(r):
        return f"{r['source_verified_count']} links · {r['distinct_category_count']} signals"

    def row_reason_full(r):
        return f"{r['source_verified_count']} evidence links · {r['distinct_category_count']} active signal types"

else:  # Custom Ranking
    sort_by = [pri_col]
    sort_asc = [pri_order == "Low to High"]
    if sec_col != "None" and sec_col != pri_col:
        sort_by.append(sec_col)
        sort_asc.append(sec_order == "Low to High")
    sort_by.append("company_name")
    sort_asc.append(True)
    preset_explanation = "Ranks accounts according to your custom primary and secondary criteria."
    def row_reason_ui(r):
        pri_str = format_criterion_val_ui(pri_col, r)
        if sec_col != "None" and sec_col != pri_col:
            sec_str = format_criterion_val_ui(sec_col, r)
            return f"{pri_str} · {sec_str}"
        return f"{pri_str}"

    def row_reason_full(r):
        pri_str = format_criterion_val_full(pri_col, r)
        if sec_col != "None" and sec_col != pri_col:
            sec_str = format_criterion_val_full(sec_col, r)
            return f"Primary: {pri_str} · Secondary: {sec_str}"
        return f"Primary: {pri_str}"

# Display one-sentence plain-language explanation banner
st.info(f"ℹ️ {preset_explanation}")

st.markdown("---")

# ==========================================
# SECTION 3: PRIORITIZED RESULTS
# ==========================================
st.markdown(f"### 3️⃣ Prioritized Company Ranking (`{eligible_count}` Accounts)")

if eligible_df.empty:
    st.warning("⚠️ No accounts meet the selected eligibility criteria. Adjust filters above to populate rankings.")
else:
    # Deterministic multi-column sort with null dates strictly placed last
    ranked_df = eligible_df.sort_values(by=sort_by, ascending=sort_asc, na_position="last").reset_index(drop=True)
    ranked_df["Rank"] = range(1, len(ranked_df) + 1)
    
    # Generate human-readable ranking reasons: concise for UI, full for CSV
    ranked_df["Ranking reason (UI)"] = ranked_df.apply(row_reason_ui, axis=1)
    ranked_df["Ranking reason (CSV)"] = ranked_df.apply(row_reason_full, axis=1)
    
    # Format Latest Observed Activity
    ranked_df["Latest Observed Activity"] = ranked_df["latest_observed_activity"].apply(
        lambda x: str(x) if x else "No current catalyst"
    )
    
    # Enrichment status display label
    enr_label_map = {
        "complete": "🟢 Current Verified",
        "partial": "🟡 Partial Records",
        "stale": "⏱️ Historical Reference",
        "failed": "🔴 Unresolved",
        "not_started": "⚪ Not Yet Enriched",
    }
    ranked_df["Enrichment"] = ranked_df["enrichment_status"].apply(lambda s: enr_label_map.get(s, "⚪ Not Yet Enriched"))

    # Display columns: Rank, Company, Status, Enrichment, Active Signal Types, Latest Observed Activity, Why Ranked
    display_cols = [
        "Rank",
        "company_name",
        "current_status",
        "Enrichment",
        "distinct_category_count",
        "Latest Observed Activity",
        "Ranking reason (UI)",
    ]
    
    table_view = ranked_df[display_cols].rename(columns={
        "company_name": "Company",
        "current_status": "Status",
        "distinct_category_count": "Active Signal Types",
        "Latest Observed Activity": "Latest Observed Activity",
        "Ranking reason (UI)": "Why Ranked",
    })
    
    st.dataframe(
        table_view,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Rank": st.column_config.NumberColumn("Rank", width=65),
            "Company": st.column_config.TextColumn("Company", width=180),
            "Status": st.column_config.TextColumn("Status", width=160),
            "Enrichment": st.column_config.TextColumn("Enrichment", width=130),
            "Active Signal Types": st.column_config.NumberColumn("Active Signal Types", width=110, format="%d"),
            "Latest Observed Activity": st.column_config.TextColumn("Latest Observed Activity", width=130),
            "Why Ranked": st.column_config.TextColumn("Why Ranked", width=270),
        },
    )
    
    # Whitelisted CSV Export (retains full audit rationale & enrichment state)
    export_rank_cols = [
        "Rank",
        "company_name",
        "domain",
        "segment",
        "current_status",
        "enrichment_status",
        "computed_tier",
        "distinct_category_count",
        "active_event_count",
        "latest_observed_activity",
        "next_upcoming_milestone",
        "source_verified_count",
        "suggested_action",
        "Ranking reason (CSV)",
    ]
    
    export_ranked_df = ranked_df[export_rank_cols].rename(columns={
        "company_name": "Company Name",
        "domain": "Domain",
        "segment": "Segment",
        "current_status": "Status",
        "enrichment_status": "Enrichment Status",
        "computed_tier": "Computed Tier",
        "distinct_category_count": "Active Signal Types",
        "active_event_count": "Active Events Count",
        "latest_observed_activity": "Latest Observed Activity",
        "next_upcoming_milestone": "Next Upcoming Milestone",
        "source_verified_count": "Evidence Links Count",
        "suggested_action": "Suggested Next Step",
        "Ranking reason (CSV)": "Why Ranked",
    })
    
    clean_preset_key = selected_preset.lower().replace(" ", "_")
    safe_export_ranked_df = sanitize_dataframe_for_csv(export_ranked_df)
    ranked_csv = safe_export_ranked_df.to_csv(index=False).encode("utf-8")
    export_prefix = "custom_wingman" if is_custom else "wingman"
    export_label = (
        f"📥 Download Ranked Companies (CSV) — Custom Dataset ({len(ranked_df)} Row(s))"
        if is_custom
        else f"📥 Download Ranked Companies (CSV) — {len(ranked_df)} Row(s)"
    )
    st.download_button(
        label=export_label,
        data=ranked_csv,
        file_name=f"{export_prefix}_ranked_companies_{clean_preset_key}_{date.today().isoformat()}.csv",
        mime="text/csv",
        key="dl_ranked_companies_csv",
    )

st.markdown("---")

# ==========================================
# SECTION 4: ADVANCED RANKING METHODOLOGY & DISCLAIMER
# ==========================================
with st.expander("🔬 Advanced Ranking Methodology & Deterministic Rules", expanded=False):
    st.markdown(
        """
        ### Deterministic Ranking Principles
        1. **Pre-Filter Eligibility**: All filters (Status, Segment, Search) are evaluated *before* rank indices are computed.
        2. **Contiguous Indexing**: Ranks are indexed from `1` through `N` strictly within the active eligible subset.
        3. **Deterministic Tie-Breaking**: When companies share identical metric scores across all criteria, alphabetical ordering on `company_name` serves as the invariant tie-breaker.
        4. **Date Handling**: Null or missing dates are always sorted to the end of the ranking when sorting in descending order.
        5. **No Data Leakage**: Downloads use whitelisted columns and contain zero internal analyst notes or unverified URL references.
        """
    )
    render_disclaimer()
