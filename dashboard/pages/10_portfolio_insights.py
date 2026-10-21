"""
Page 10: Portfolio Insights
EON Commercial Intelligence | External Review Build — Proposed Phase 1

Understand what the CSV shows and what the patterns mean commercially:
- High-level portfolio KPI cards (5 non-zero cards)
- Dynamically calculated portfolio observations with exact counts and facts vs hypotheses
- Interactive routing from observations to Company Browser
- Responsive Altair visualizations (Catalyst Prevalence, Segment Distribution, Lift Combinations)
- Collapsible Advanced Analysis (Co-occurrence Heatmap, Archetype Cohorts, Lookalike Finder, Methodology)
"""

import html
from pathlib import Path
from datetime import date
import streamlit as st
import pandas as pd
import altair as alt

from dashboard.components import render_disclaimer, render_kpi_card, render_badge
from dashboard.data_source import get_active_dataset, render_source_banner
from dashboard.wingman_portfolio import (
    generate_portfolio_observations,
    get_similar_companies,
    DEFAULT_EXPIRY_WINDOWS,
    DEFAULT_AS_OF_DATE,
    TRIGGER_DISPLAY_LABELS,
)

# Page Configuration & Headers
st.title("💡 Portfolio Insights")
render_source_banner()
st.caption(
    "EON Commercial Intelligence | External Review Build — Proposed Phase 1 | "
    "Understand portfolio patterns, signal prevalence, and commercial implications."
)

# Fetch active dataset metadata
active_ds = get_active_dataset()
current_as_of = active_ds["as_of_date"]

# Sidebar Controls: Collapsed Analysis Settings
with st.sidebar.expander("⚙️ Analysis Settings", expanded=False):
    tier_mode_selection = st.radio(
        "Tier 1 Classification Rule:",
        options=[
            "Proposed Default: Distinct Categories (>=2 types = Tier 1)",
            "Alternative: Event Count Mode (>=2 events = Tier 1)",
        ],
        index=0,
        help="Proposed Default requires 2 or more distinct trigger categories. Alternative mode counts total deduplicated events.",
    )
    recency_option = st.selectbox(
        "Trigger Active Horizon Window:",
        options=[
            "Category-Specific Expiry Defaults (Recommended)",
            "Last 30 Days",
            "Last 90 Days",
            "Last 180 Days",
            "Last 365 Days",
            "All Historic Events",
        ],
        index=0,
        help="Controls the recency window for classifying an event as active. Category-Specific applies operational defaults.",
    )

# Compute portfolio state based on active dataset
expiry_windows = DEFAULT_EXPIRY_WINDOWS
tier_mode = "distinct_categories" if "Distinct Categories" in tier_mode_selection else "event_count"

# Check if non-default settings requested
if recency_option != "Category-Specific Expiry Defaults (Recommended)":
    days_map = {
        "Last 30 Days": 30,
        "Last 90 Days": 90,
        "Last 180 Days": 180,
        "Last 365 Days": 365,
        "All Historic Events": 99999,
    }
    d_val = days_map.get(recency_option, 90)
    expiry_windows = {cat: {"active_days": d_val, "decay_days": d_val * 2} for cat in DEFAULT_EXPIRY_WINDOWS}

portfolio_bundle = get_active_dataset(
    as_of_date=current_as_of,
    tier_mode=tier_mode,
    expiry_windows=expiry_windows,
)

portfolio = portfolio_bundle["portfolio"]
metrics = portfolio["metrics"]
companies_df = portfolio["companies_df"]
active_events_df = portfolio["active_events_df"]
cat_prevalence = portfolio["cat_prevalence"]
top_combinations = portfolio["top_combinations"]
archetypes = portfolio["archetypes"]


# 4 Hero KPI Cards
st.markdown("### 📊 Portfolio Health & Signal Overview")
kpi1, kpi2, kpi3, kpi4 = st.columns(4)

# Active catalyst accounts (companies with >= 1 active catalyst)
active_comps_count = int((companies_df["distinct_category_count"] > 0).sum())
active_comps_pct = round(100.0 * active_comps_count / metrics["total_companies"], 1)

# Multi-catalyst surges (>= 2 distinct categories)
multi_comps_count = int((companies_df["distinct_category_count"] >= 2).sum())
multi_comps_pct = round(100.0 * multi_comps_count / metrics["total_companies"], 1)

# Business Model Review count
bmr_count = metrics["business_model_review_count"]
bmr_pct = round(100.0 * bmr_count / metrics["total_companies"], 1)

# Top active catalyst and segment for chart section
top_cat_key = max(cat_prevalence, key=cat_prevalence.get) if cat_prevalence else "project_fid_commissioning"
top_cat_label = TRIGGER_DISPLAY_LABELS.get(top_cat_key, top_cat_key)
top_cat_count = cat_prevalence.get(top_cat_key, 0)

active_companies = companies_df[companies_df["distinct_category_count"] > 0]
top_segment = active_companies["segment"].value_counts().index[0] if not active_companies.empty else "Oil & Gas"
top_seg_count = active_companies["segment"].value_counts().iloc[0] if not active_companies.empty else 0

with kpi1:
    render_kpi_card(
        title="Total Accounts",
        value=f"{metrics['total_companies']:,}",
        subtitle="100% deduplicated accounts",
        badge_text="Full Universe",
        badge_type="green",
    )

with kpi2:
    render_kpi_card(
        title="Accounts with Active Signals",
        value=f"{active_comps_count:,}",
        subtitle=f"{active_comps_pct}% of portfolio",
        badge_text="Active Window",
        badge_type="blue",
    )

with kpi3:
    render_kpi_card(
        title="Multiple-Signal Accounts",
        value=f"{multi_comps_count:,}",
        subtitle=f"{multi_comps_pct}% with >=2 signal types",
        badge_text="Multiple Active Signals",
        badge_type="amber",
    )

with kpi4:
    render_kpi_card(
        title="Business Model Review",
        value=f"{bmr_count:,}",
        subtitle=f"{bmr_pct}% review required",
        badge_text="Profile Review Required",
        badge_type="gray",
    )

st.markdown("---")

total_comps = metrics["total_companies"]

# Dynamic Portfolio Observations Heading & Subtitle (Conditional on Sample Size)
if total_comps < 10:
    st.markdown("### 📌 Portfolio Descriptive Observations")
    st.caption(
        "Descriptive account and signal prevalence for the active custom dataset. "
        "Portfolio-level implications and co-occurrence patterns are suppressed for small samples."
    )
    st.info(
        f"ℹ️ **Descriptive Metrics Only (N = {total_comps}):** "
        f"With fewer than 10 accounts, portfolio-level commercial implications and co-occurrence patterns are suppressed to avoid over-generalizing from small samples. "
        f"The thresholds control presentation and over-generalization; they do not establish statistical significance by themselves."
    )
elif total_comps < 30:
    st.markdown("### 📌 Portfolio Observations & Exploratory Patterns")
    st.caption(
        "Dynamically calculated observations and exploratory patterns for moderate sample sizes."
    )
    st.warning(
        f"⚠️ **Low Sample Size (N = {total_comps}):** "
        f"Observations and patterns are exploratory and should be verified against account-specific context. "
        f"The thresholds control presentation and over-generalization; they do not establish statistical significance by themselves."
    )
else:
    st.markdown("### 📌 Portfolio Observations & Strategic Patterns")
    st.caption(
        "Dynamically calculated observations separating confirmed empirical facts from commercial implications."
    )

observations = generate_portfolio_observations(portfolio)

obs_cols = st.columns(len(observations))
for idx, obs in enumerate(observations):
    with obs_cols[idx]:
        with st.container():
            clean_title = html.escape(str(obs.get("title", "")))
            clean_badge = html.escape(str(obs.get("badge", "")))
            clean_fact = html.escape(str(obs.get("fact", "")))
            obs_icon = obs.get("icon", "📌")

            if obs.get("hypothesis"):
                clean_hyp = html.escape(str(obs["hypothesis"]))
                hyp_html = (
                    f'<div style="background-color: #f8fafc; border-left: 3px solid #3b82f6; padding: 6px 10px; font-size: 0.79rem; color: #475569; line-height: 1.3; margin-top: 8px;">'
                    f'<strong>Possible Implication:</strong> {clean_hyp}'
                    f'</div>'
                )
            else:
                hyp_html = ""

            card_html = (
                f'<div style="background-color: #ffffff; border: 1px solid #e5e7eb; border-radius: 8px; padding: 16px; margin-bottom: 12px; box-shadow: 0 1px 3px rgba(0,0,0,0.04); min-height: 160px; height: auto; display: flex; flex-direction: column; justify-content: space-between;">'
                '<div>'
                '<div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">'
                f'<span style="font-weight: 700; font-size: 0.95rem; color: #1e3a8a;">{obs_icon} {clean_title}</span>'
                f'<span style="background-color: #dbeafe; color: #1e40af; padding: 2px 7px; border-radius: 10px; font-size: 0.74rem; font-weight: 600; white-space: nowrap;">{clean_badge}</span>'
                '</div>'
                f'<div style="font-size: 0.83rem; color: #1f2937; line-height: 1.35; margin-bottom: 8px;"><strong>Fact:</strong> {clean_fact}</div>'
                '</div>'
                f'{hyp_html}'
                '</div>'
            )
            st.markdown(card_html, unsafe_allow_html=True)
            btn_label = f"🔍 Explore ({obs['affected_count']}) in Browser"
            if st.button(btn_label, key=f"btn_explore_obs_{obs['id']}", use_container_width=True):
                if obs["filter_type"] == "catalyst":
                    st.session_state["browser_filter_catalysts"] = [obs["filter_value"]]
                    st.session_state["browser_filter_status"] = "All Statuses"
                    st.session_state["browser_filter_multi"] = False
                elif obs["filter_type"] == "multi_catalyst":
                    st.session_state["browser_filter_multi"] = True
                    st.session_state["browser_filter_catalysts"] = []
                    st.session_state["browser_filter_status"] = "All Statuses"
                elif obs["filter_type"] == "status":
                    st.session_state["browser_filter_status"] = obs["filter_value"]
                    st.session_state["browser_filter_catalysts"] = []
                    st.session_state["browser_filter_multi"] = False
                elif obs["filter_type"] == "catalyst_pair":
                    pair_cats = [TRIGGER_DISPLAY_LABELS.get(p.strip(), p.strip()) for p in obs["filter_value"].split("+")]
                    st.session_state["browser_filter_catalysts"] = pair_cats
                    st.session_state["browser_filter_status"] = "All Statuses"
                    st.session_state["browser_filter_multi"] = False
                st.switch_page("dashboard/pages/11_company_browser.py")

st.markdown("---")

# =========================================================================
# Phase 4 Foundation: Master Database Universe & Firmographic Enrichment
# =========================================================================
st.markdown("### 🏛️ Master Company Database & Firmographic Enrichment (Phase 4 Foundation)")
st.caption(
    "DB-first architecture (scalable to 2,000+ accounts) with automated free-source enrichment. "
    "Primary statutory filings sourced from SEC EDGAR; secondary semantic estimates from Wikidata."
)

try:
    from dashboard.company_db import get_enrichment_summary_stats
    enr_stats = get_enrichment_summary_stats()
except Exception:
    enr_stats = {
        "total_companies": 0,
        "status_counts": {"complete": 0, "partial": 0, "not_started": 0, "stale": 0, "failed": 0},
        "enriched_count": 0,
        "coverage_pct": 0.0,
        "sec_edgar_complete": 0,
        "sec_edgar_partial": 0,
        "wikidata_complete": 0,
        "wikidata_partial": 0,
        "total_provenance_fields": 0,
        "value_status_counts": {"exact": 0, "estimate": 0, "range": 0, "unknown": 0},
        "source_type_counts": {},
    }

m1, m2, m3, m4, m5, m6 = st.columns(6)

with m1:
    render_kpi_card(
        title="Master Universe",
        value=str(enr_stats["total_companies"]),
        subtitle="SQLite master store",
        badge_text="DB-FIRST",
        badge_type="blue",
    )

with m2:
    cov_val = f"{enr_stats['coverage_pct']}%"
    cov_sub = f"{enr_stats['enriched_count']}/{enr_stats['total_companies']} accounts"
    render_kpi_card(
        title="Enrichment Coverage",
        value=cov_val,
        subtitle=cov_sub,
        badge_text=f"{enr_stats['status_counts'].get('complete', 0)} COMPLETE",
        badge_type="green" if enr_stats["coverage_pct"] > 50 else "amber",
    )

with m3:
    sec_tot = enr_stats["sec_edgar_complete"] + enr_stats["sec_edgar_partial"]
    render_kpi_card(
        title="SEC EDGAR",
        value=str(sec_tot),
        subtitle="Statutory public 10-K",
        badge_text="STATUTORY",
        badge_type="blue",
    )

with m4:
    wiki_tot = enr_stats["wikidata_complete"] + enr_stats["wikidata_partial"]
    render_kpi_card(
        title="Wikidata Semantic",
        value=str(wiki_tot),
        subtitle="Community estimates",
        badge_text="SECONDARY",
        badge_type="amber",
    )

with m5:
    render_kpi_card(
        title="Field Provenance",
        value=str(enr_stats["total_provenance_fields"]),
        subtitle="Granular audit records",
        badge_text="AUDITED",
        badge_type="purple",
    )

with m6:
    stale_cnt = enr_stats["status_counts"].get("stale", 0)
    failed_cnt = enr_stats["status_counts"].get("failed", 0)
    render_kpi_card(
        title="Stale / Failed",
        value=f"{stale_cnt} / {failed_cnt}",
        subtitle="Stale >90d / Error",
        badge_text="MONITORED",
        badge_type="green" if (stale_cnt == 0 and failed_cnt == 0) else "amber",
    )

col_enr1, col_enr2 = st.columns(2)

with col_enr1:
    st.markdown("#### Enrichment Lifecycle Status Distribution")
    st.caption("Operational status across all accounts in the master database.")

    status_data = [
        {"Status": "Current Verified (Complete)", "Code": "complete", "Count": enr_stats["status_counts"].get("complete", 0)},
        {"Status": "Partial Records (1-3 Fields)", "Code": "partial", "Count": enr_stats["status_counts"].get("partial", 0)},
        {"Status": "Not Yet Enriched", "Code": "not_started", "Count": enr_stats["status_counts"].get("not_started", 0)},
        {"Status": "Historical Reference (>90 Days Old)", "Code": "stale", "Count": enr_stats["status_counts"].get("stale", 0)},
        {"Status": "Unresolved (Connector Error)", "Code": "failed", "Count": enr_stats["status_counts"].get("failed", 0)},
    ]
    status_df = pd.DataFrame(status_data)

    chart_enr_status = (
        alt.Chart(status_df)
        .mark_bar(cornerRadiusTopRight=4, cornerRadiusBottomRight=4)
        .encode(
            y=alt.Y("Status:N", sort=["Current Verified (Complete)", "Partial Records (1-3 Fields)", "Not Yet Enriched", "Historical Reference (>90 Days Old)", "Unresolved (Connector Error)"], title=None),
            x=alt.X("Count:Q", title="Number of Accounts"),
            color=alt.Color(
                "Code:N",
                scale=alt.Scale(
                    domain=["complete", "partial", "not_started", "stale", "failed"],
                    range=["#10b981", "#f59e0b", "#94a3b8", "#ea580c", "#ef4444"],
                ),
                legend=None,
            ),
            tooltip=["Status", "Count"],
        )
        .properties(height=200)
    )
    st.altair_chart(chart_enr_status, use_container_width=True)

with col_enr2:
    st.markdown("#### Provenance Field Quality Breakdown")
    st.caption("Distribution of exact vs estimated values across enriched attributes.")

    val_data = [
        {"Quality": "Current Verified (Statutory Exact)", "Code": "exact", "Count": enr_stats["value_status_counts"].get("exact", 0)},
        {"Quality": "Historical Reference / Estimate", "Code": "estimate", "Count": enr_stats["value_status_counts"].get("estimate", 0)},
        {"Quality": "Historical Reference (Range)", "Code": "range", "Count": enr_stats["value_status_counts"].get("range", 0)},
        {"Quality": "No Current Verified Value", "Code": "unknown", "Count": enr_stats["value_status_counts"].get("unknown", 0)},
    ]
    val_df = pd.DataFrame(val_data)

    chart_val_status = (
        alt.Chart(val_df)
        .mark_bar(cornerRadiusTopRight=4, cornerRadiusBottomRight=4)
        .encode(
            y=alt.Y("Quality:N", sort=["Current Verified (Statutory Exact)", "Historical Reference / Estimate", "Historical Reference (Range)", "No Current Verified Value"], title=None),
            x=alt.X("Count:Q", title="Field Records"),
            color=alt.Color(
                "Code:N",
                scale=alt.Scale(
                    domain=["exact", "estimate", "range", "unknown"],
                    range=["#2563eb", "#0284c7", "#f59e0b", "#cbd5e1"],
                ),
                legend=None,
            ),
            tooltip=["Quality", "Count"],
        )
        .properties(height=200)
    )
    st.altair_chart(chart_val_status, use_container_width=True)

st.markdown("---")

# Portfolio Visualizations
st.markdown("### 📈 Visual Portfolio Analytics")

# Top Signal and Top Segment callouts in the chart section
c_top1, c_top2 = st.columns(2)
with c_top1:
    total_tot = metrics["total_companies"] if metrics["total_companies"] > 0 else 1
    act_pct = round(100.0 * top_seg_count / active_comps_count, 1) if active_comps_count > 0 else 0.0
    port_pct = round(100.0 * top_seg_count / total_tot, 1)
    st.info(f"🏭 **Top Active Segment**: **{top_segment}**: {top_seg_count} active accounts — {act_pct}% of actively signaled accounts; {port_pct}% of the full portfolio.")

viz_col1, viz_col2 = st.columns(2)

with viz_col1:
    st.markdown("#### Active Signal Prevalence (% of Accounts)")
    st.caption(f"Percentage of all {metrics['total_companies']} companies with at least one active signal in each operational category.")
    
    prev_rows = []
    for cat_k, cat_lbl in TRIGGER_DISPLAY_LABELS.items():
        cnt = cat_prevalence.get(cat_k, 0)
        pct = round(100.0 * cnt / metrics["total_companies"], 1)
        prev_rows.append({"Category": cat_lbl, "Count": cnt, "Percentage": pct})
    
    prev_df = pd.DataFrame(prev_rows).sort_values(by="Count", ascending=True)
    
    chart_prev = alt.Chart(prev_df).mark_bar(color="#2563eb", cornerRadiusEnd=3).encode(
        x=alt.X("Percentage:Q", title="% of Portfolio", scale=alt.Scale(domain=[0, max(prev_df["Percentage"]) + 5])),
        y=alt.Y("Category:N", sort="-x", title=""),
        tooltip=["Category", "Count", alt.Tooltip("Percentage:Q", format=".1f", title="% of Accounts")],
    ).properties(height=280)
    
    text_prev = chart_prev.mark_text(
        align="left",
        baseline="middle",
        dx=5,
        fontSize=11,
        color="#374151",
    ).encode(
        text=alt.Text("Percentage:Q", format=".1f")
    )
    
    st.altair_chart(chart_prev + text_prev, use_container_width=True)

with viz_col2:
    st.markdown("#### Active Accounts by Industry Segment")
    st.caption("Distribution of accounts with active operational signals across industry sectors.")
    
    seg_counts = active_companies["segment"].value_counts().reset_index()
    seg_counts.columns = ["Segment", "Active Accounts"]
    seg_counts = seg_counts.sort_values(by="Active Accounts", ascending=True)
    
    chart_seg = alt.Chart(seg_counts).mark_bar(color="#0891b2", cornerRadiusEnd=3).encode(
        x=alt.X("Active Accounts:Q", title="Number of Accounts"),
        y=alt.Y("Segment:N", sort="-x", title=""),
        tooltip=["Segment", "Active Accounts"],
    ).properties(height=280)
    
    text_seg = chart_seg.mark_text(
        align="left",
        baseline="middle",
        dx=5,
        fontSize=11,
        color="#374151",
    ).encode(
        text="Active Accounts:Q"
    )
    
    st.altair_chart(chart_seg + text_seg, use_container_width=True)

# Top Co-Occurring Signal Combinations (Top 5 by default)
st.markdown("#### 🔗 Top Co-Occurring Signal Combinations")
st.caption(
    "Lift compares observed co-occurrence with the frequency expected if the two catalyst types were independent. "
    "It is descriptive and does not establish causality or statistical dependence."
)

combo_rows = []
for c in top_combinations[:5]:
    combo_rows.append({
        "Catalyst Combination": c["pair_display"],
        "Observed Accounts": c["observed_count"],
        "% of Portfolio": f"{c['pct_universe']:.1f}%",
        "Lift Ratio": f"{c['lift']:.2f}x",
        "Support Status": "Adequate support (≥15 accounts)" if c["observed_count"] >= 15 else "Low support (<15 accounts) — exploratory",
    })

combo_df = pd.DataFrame(combo_rows)
st.dataframe(combo_df, use_container_width=True, hide_index=True)

st.info(
    "💡 **Analytical Caveat on Lift**: High lift values in combinations below the minimum support threshold (<15 accounts) "
    "represent exploratory patterns with small sample sizes, not statistically proven dependencies. "
    "Use high-support pairs (≥15 accounts) for broad campaign planning."
)

st.markdown("---")

# Collapsible Advanced Analysis & Methodology
with st.expander("🔬 Advanced Analysis & Methodology", expanded=False):
    st.markdown("### 🔗 Complete Pairwise Co-Occurrence & Lift Matrix")
    st.caption(
        "Complete portfolio co-occurrence table across all evaluated trigger pairs. "
        "Lift compares observed co-occurrence with the frequency expected if the two catalyst types were independent (minimum support threshold: ≥15 accounts)."
    )
    all_combo_rows = []
    for c in top_combinations:
        all_combo_rows.append({
            "Catalyst Combination": c["pair_display"],
            "Observed Accounts": c["observed_count"],
            "% of Portfolio": f"{c['pct_universe']:.1f}%",
            "Lift Ratio": f"{c['lift']:.2f}x",
            "Support Status": "Adequate support (≥15 accounts)" if c["observed_count"] >= 15 else "Low support (<15 accounts) — exploratory",
        })
    st.dataframe(pd.DataFrame(all_combo_rows), use_container_width=True, hide_index=True)
    st.markdown("---")

    st.markdown("### 🧪 Operational Archetype Cohorts")
    st.markdown(
        "Commercial cohorts built from compounding operational signals. "
        "Expand any archetype below to view its commercial rationale and inspect matching companies."
    )
    
    for arch_name, arch_info in archetypes.items():
        arch_meta = arch_info["meta"]
        m_comps = arch_info["companies"]
        arch_count = arch_info["count"]
        
        with st.expander(f"📁 {arch_name} ({arch_count} Accounts)", expanded=False):
            c_left, c_right = st.columns([3, 2])
            with c_left:
                st.markdown(f"**Operational Need**: {arch_meta['operational_need']}")
                st.markdown(f"**Commercial Hypothesis**: {arch_meta['commercial_hypothesis']}")
            with c_right:
                st.markdown(f"**Suggested Discovery Question**: *\"{arch_meta['discovery_question']}\"*")
            
            if m_comps:
                m_df = pd.DataFrame(m_comps)
                display_cols = ["company_name", "domain", "segment", "tier", "queue_category", "suggested_playbook"]
                st.dataframe(
                    m_df[display_cols].rename(columns={
                        "company_name": "Company",
                        "domain": "Domain",
                        "segment": "Segment",
                        "tier": "Computed Tier",
                        "queue_category": "Queue Category",
                        "suggested_playbook": "Suggested Playbook",
                    }),
                    use_container_width=True,
                    hide_index=True,
                )
                
                # Download cohort CSV
                cohort_csv = m_df[display_cols].to_csv(index=False).encode("utf-8")
                st.download_button(
                    label=f"📥 Download {arch_name} Accounts (CSV)",
                    data=cohort_csv,
                    file_name=f"{arch_name.lower().replace(' ', '_')}_accounts.csv",
                    mime="text/csv",
                    key=f"dl_arch_{arch_name}",
                )
            else:
                st.caption("No accounts currently match this archetype under the active horizon settings.")

    st.markdown("---")
    st.markdown("### 🔎 Lookalike Profile Finder")
    st.caption("Find companies with similar operational catalyst profiles using Jaccard trigger similarity.")
    
    benchmark_comp = st.selectbox(
        "Select a Benchmark Company:",
        options=sorted(companies_df[companies_df["distinct_category_count"] > 0]["company_name"].unique()),
        help="Choose a company with active catalysts to find lookalike operating peers.",
    )
    
    if benchmark_comp:
        sim_results = get_similar_companies(benchmark_comp, companies_df, top_n=6)
        if sim_results:
            sim_df = pd.DataFrame(sim_results)
            st.markdown(f"**Top Lookalike Accounts for {benchmark_comp}:**")
            st.dataframe(
                sim_df[[
                    "company_name", "domain", "segment", "computed_tier", "queue_category",
                    "similarity_score", "shared_triggers", "benchmark_only_triggers", "peer_only_triggers"
                ]].rename(columns={
                    "company_name": "Company",
                    "domain": "Domain",
                    "segment": "Segment",
                    "computed_tier": "Computed Tier",
                    "queue_category": "Queue Category",
                    "similarity_score": "Similarity Score",
                    "shared_triggers": "Shared Catalysts",
                    "benchmark_only_triggers": "Benchmark Only",
                    "peer_only_triggers": "Peer Only",
                }),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.caption("No lookalike accounts found for the selected benchmark company.")

    st.markdown("---")
    st.markdown("### 📐 Methodology & Operational Rules")
    st.markdown(
        """
        - **Deduplication Standard**: Scanned trigger rows are grouped by normalized company identity and deduplicated by event date and trigger type.
        - **Horizon Enforcement**: Operational catalysts expire after category-specific windows (90d for leadership/hiring, 180d for TAR/audits/incidents, 365d for commissioning, 540d for M&A).
        - **Status Taxonomy**: Accounts are classified into 5 mutually exclusive queues based on confirmed catalyst activity and customer profile verification.
        - **Zero Raw Analyst Notes**: External views consume only sanitized category codes, deduplicated event counts, and structured timestamps.
        """
    )
    render_disclaimer()
