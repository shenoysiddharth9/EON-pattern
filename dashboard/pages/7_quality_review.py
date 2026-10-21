"""
Page 7: Quality Review & Validation Issues
Detailed inventory of logged issues, document discrepancies, ambiguities, native text fragments, and proposed resolutions.
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
issues_df = data.get("issues", pd.DataFrame())
companies_df = data.get("companies", pd.DataFrame())

st.title("🛡️ Extractor Quality Review & Validation Issues")
render_disclaimer()

if issues_df.empty:
    st.success("No validation issues or discrepancies logged in the selected scope.")
    st.stop()

# Summary Metrics
c1, c2, c3, c4 = st.columns(4)
with c1:
    st.metric("Total Issues Logged", len(issues_df))
with c2:
    disc_count = len(issues_df[issues_df["issue_type"] == "DISCREPANCY"]) if "issue_type" in issues_df.columns else 0
    st.metric("Discrepancies", disc_count)
with c3:
    amb_count = len(issues_df[issues_df["issue_type"] == "AMBIGUITY"]) if "issue_type" in issues_df.columns else 0
    st.metric("Ambiguities", amb_count)
with c4:
    miss_count = len(issues_df[issues_df["issue_type"] == "MISSING_DATA"]) if "issue_type" in issues_df.columns else 0
    st.metric("Missing Data Notes", miss_count)

st.markdown("---")

# Filters
st.markdown("##### Filter Logged Issues")
f1, f2 = st.columns(2)
with f1:
    comp_opts = ["All Companies"] + sorted(issues_df["company_name"].dropna().unique().tolist())
    sel_comp = st.selectbox("Company Filter:", options=comp_opts, index=0)
with f2:
    types = ["All Types"] + sorted(issues_df["issue_type"].dropna().unique().tolist())
    sel_type = st.selectbox("Issue Type:", options=types, index=0)

filtered_issues = issues_df.copy()
if sel_comp != "All Companies":
    filtered_issues = filtered_issues[filtered_issues["company_name"] == sel_comp]
if sel_type != "All Types":
    filtered_issues = filtered_issues[filtered_issues["issue_type"] == sel_type]

st.caption(f"Displaying **{len(filtered_issues)}** of **{len(issues_df)}** logged quality issues.")

# Issues Table
display_cols = ["issue_id", "company_name", "field_name", "issue_type", "description", "page_number", "resolution_proposed"]
available_cols = [c for c in display_cols if c in filtered_issues.columns]
st.dataframe(filtered_issues[available_cols], use_container_width=True, hide_index=True)

col_d1, col_d2 = st.columns([2, 1])
with col_d1:
    render_download_button(filtered_issues, f"validation_issues_{len(filtered_issues)}.csv", "Download Validation Issues (CSV)")

st.markdown("---")

# Detailed Issue Cards with Native Fragments
st.markdown("##### 🔍 Deep Issue Evidence & Proposed Resolutions")

for _, iss in filtered_issues.iterrows():
    issue_type = str(iss.get("issue_type"))
    badge_color = "red" if issue_type == "DISCREPANCY" else "amber" if issue_type == "AMBIGUITY" else "gray"

    with st.expander(f"[{iss.get('company_name')}] {iss.get('issue_id')} — {iss.get('field_name')} ({issue_type})"):
        i_col1, i_col2 = st.columns(2)
        with i_col1:
            st.markdown(f"**Issue ID:** `<code>{iss.get('issue_id')}</code>`", unsafe_allow_html=True)
            st.markdown(f"**Company:** `{iss.get('company_name')}`")
            st.markdown(f"**Field:** `<code>{iss.get('field_name')}</code>`", unsafe_allow_html=True)
            st.markdown(f"**Issue Type:** {render_badge(issue_type, badge_color)}", unsafe_allow_html=True)
            st.markdown(f"**Report Page:** `{iss.get('page_number')}`")
        with i_col2:
            st.markdown(f"**Source PDF:** `{iss.get('source_pdf_filename')}`")
            st.markdown(f"**Description:** {iss.get('description')}")

        st.markdown("**Verbatim Report Native Fragment:**")
        st.code(str(iss.get("report_native_fragment") or "No text fragment captured"), language="text")

        st.markdown("**Proposed Auditor Resolution:**")
        st.info(str(iss.get("resolution_proposed") or "None"))

st.markdown("---")

# Auditor Review Checklists
st.markdown("### 📋 Auditor Review Checklists")
ch1, ch2, ch3 = st.columns(3)

with ch1:
    st.markdown("#### 1. Extraction Review")
    st.caption("Checks for ambiguous entity consensus or filename fallbacks.")
    for _, comp in companies_df.iterrows():
        val = comp.get("extraction_review_required")
        icon = "🔴" if val is True or str(val).upper() == "TRUE" else "🟢"
        st.markdown(f"{icon} **{comp.get('company_name')}**: `extraction_review_required = {val}`")

with ch2:
    st.markdown("#### 2. Independent Verification")
    st.caption("Checks third-party unverified public press claims.")
    for _, comp in companies_df.iterrows():
        val = comp.get("source_verification_required")
        icon = "🟡" if val is True or str(val).upper() == "TRUE" else "🟢"
        st.markdown(f"{icon} **{comp.get('company_name')}**: independent verification required: `{val}`")

with ch3:
    st.markdown("#### 3. Normalization Review")
    st.caption("Checks analyst-assigned classifications and derivations.")
    for _, comp in companies_df.iterrows():
        val = comp.get("analyst_normalization_review_required")
        icon = "🟡" if val is True or str(val).upper() == "TRUE" else "🟢"
        st.markdown(f"{icon} **{comp.get('company_name')}**: `analyst_normalization_review_required = {val}`")
