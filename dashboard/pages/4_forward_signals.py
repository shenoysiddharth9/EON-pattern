"""
Page 4: Forward Signals ("What You Are Building")
Searchable cards grouped by company and publisher, displaying the persistent 6 reported vs 4 extracted discrepancy.
"""

import streamlit as st
import pandas as pd
from dashboard.components import (
    render_disclaimer,
    render_badge,
    render_download_button,
)
from dashboard.data_loader import load_scope_data

scope = st.session_state.get("selected_scope", "Baseline Reports")
data = load_scope_data(scope)
signals_df = data.get("signals", pd.DataFrame())
companies_df = data.get("companies", pd.DataFrame())

st.title("📡 Forward Signals (\"What You Are Building\")")
render_disclaimer()

# Document Discrepancy Callout
st.markdown(
    """
    <div style="background-color: #fef2f2; border-left: 5px solid #ef4444; padding: 14px 20px; border-radius: 6px; margin-bottom: 22px;">
        <div style="font-weight: 700; color: #991b1b; font-size: 0.95rem; margin-bottom: 4px;">
            🚨 DOCUMENT DISCREPANCY DETECTED ACROSS ALL PATTERN REPORTS
        </div>
        <div style="font-size: 0.88rem; color: #7f1d1d; line-height: 1.45;">
            In every analyzed EON Pattern Report, the statistical summary page (Page 8 or 10) explicitly states:<br>
            <em>"Press: 6 accounts of what they are building or hiring for."</em><br>
            However, on Page 2 under the section <strong>"WHAT YOU ARE BUILDING"</strong>, exactly <strong>4 physical cards</strong> are rendered.
            The extractor strictly preserves the 4 extracted cards and logs the 2 unaccounted background signals as a discrepancy issue (<code>forward_signals_count_matches = FALSE</code>).
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

if signals_df.empty:
    st.warning("No forward signals found in the selected scope.")
    st.stop()

# Reconciliation Metric Cards
col_m1, col_m2, col_m3, col_m4 = st.columns(4)

with col_m1:
    tot_rep = companies_df["forward_signals_reported_count"].sum() if not companies_df.empty else len(companies_df) * 6
    st.metric("Total Reported Signals", int(tot_rep))

with col_m2:
    st.metric("Total Extracted Cards", len(signals_df))

with col_m3:
    unaccounted = int(tot_rep) - len(signals_df)
    st.metric("Unaccounted Signals", unaccounted, delta="-2 per company", delta_color="inverse")

with col_m4:
    st.markdown("##### Count Matches")
    st.markdown(render_badge("FALSE (DISCREPANCY)", "red"), unsafe_allow_html=True)
    st.caption("Preserves 4 physical cards")

st.markdown("---")

# Filters
f1, f2 = st.columns(2)
with f1:
    comp_opts = ["All Companies"] + sorted(signals_df["company_name"].dropna().unique().tolist())
    selected_comp = st.selectbox("Filter by Organization:", options=comp_opts, index=0)

with f2:
    publishers = ["All Publishers"] + sorted(signals_df["reported_by"].dropna().unique().tolist())
    selected_pub = st.selectbox("Filter by Publisher / Outlet:", options=publishers, index=0)

search_term = st.text_input(
    "Search Headline or Implication Text:",
    placeholder="e.g. data center, expansion, refinery, pipeline, chemicals...",
)

filtered = signals_df.copy()
if selected_comp != "All Companies":
    filtered = filtered[filtered["company_name"] == selected_comp]
if selected_pub != "All Publishers":
    filtered = filtered[filtered["reported_by"] == selected_pub]
if search_term:
    q = search_term.strip().lower()
    filtered = filtered[
        filtered["headline"].astype(str).str.lower().str.contains(q)
        | filtered["implication_text"].astype(str).str.lower().str.contains(q)
    ]

st.caption(f"Displaying **{len(filtered)}** of **{len(signals_df)}** extracted forward signals.")

# Display Cards Grouped by Company
grouped = filtered.groupby("company_name")

for comp_name, group in grouped:
    st.markdown(f"### 🏢 {comp_name} ({len(group)} extracted signals)")
    for _, row in group.iterrows():
        st.markdown(
            f"""
            <div style="background-color: #ffffff; border: 1px solid #e2e8f0; border-radius: 8px; padding: 16px 20px; margin-bottom: 14px; box-shadow: 0 1px 2px rgba(0,0,0,0.04);">
                <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 8px;">
                    <div>
                        <span style="background-color: #eff6ff; color: #1e40af; padding: 2px 8px; border-radius: 12px; font-weight: 700; font-size: 0.76rem; border: 1px solid #bfdbfe;">SIGNAL {row.get('signal_index')}</span>
                        &nbsp; <span style="font-size: 0.8rem; color: #64748b;">Page {row.get('page_number')} &nbsp;|&nbsp; ID: <code>{row.get('signal_id')}</code></span>
                    </div>
                    <div>
                        {render_badge(str(row.get('reported_by')), 'blue')}
                    </div>
                </div>
                <div style="font-size: 1.05rem; font-weight: 700; color: #1e293b; margin-bottom: 8px;">
                    {row.get('headline')}
                </div>
                <div style="background-color: #f8fafc; border-left: 3px solid #cbd5e1; padding: 8px 12px; font-size: 0.86rem; color: #475569; font-style: italic;">
                    "{row.get('implication_text')}"
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

st.markdown("---")
render_download_button(filtered, f"forward_signals_{len(filtered)}.csv", "Download Forward Signals (CSV)")
