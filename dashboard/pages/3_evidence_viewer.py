"""
Page 3: Field Evidence & Provenance Viewer
Filterable audit table showing field name, native value, standardized value, evidence quote,
page number, confidence, validation status, and analyst-assignment flag with color coding.
"""

import streamlit as st
import pandas as pd
from dashboard.components import (
    render_disclaimer,
    render_badge,
    render_download_button,
    style_validation_status,
    style_confidence,
)
from dashboard.data_loader import load_scope_data

scope = st.session_state.get("selected_scope", "Baseline Reports")
data = load_scope_data(scope)
evidence_df = data.get("evidence", pd.DataFrame())

st.title("🔍 Field Evidence & Provenance Viewer")
render_disclaimer()

if evidence_df.empty:
    st.warning("No field evidence records found in the selected scope.")
    st.stop()

# Filters Header
st.markdown("##### Filter Audit Dataset")
f1, f2, f3, f4 = st.columns(4)

with f1:
    companies_available = sorted(evidence_df["company_name"].dropna().unique().tolist())
    selected_companies = st.multiselect(
        "Filter Companies:",
        options=companies_available,
        default=companies_available,
    )

with f2:
    statuses_available = sorted(evidence_df["validation_status"].dropna().unique().tolist())
    selected_statuses = st.multiselect(
        "Validation Status:",
        options=statuses_available,
        default=statuses_available,
    )

with f3:
    confidences_available = sorted(evidence_df["confidence"].dropna().unique().tolist())
    selected_confidences = st.multiselect(
        "Confidence Level:",
        options=confidences_available,
        default=confidences_available,
    )

with f4:
    analyst_filter = st.selectbox(
        "Analyst Assigned:",
        options=["All", "Analyst Assigned Only (True)", "Automated Only (False)"],
        index=0,
    )

search_term = st.text_input(
    "Search Field Name or Source Evidence Quote:",
    placeholder="e.g. people_employed, citations, 10-K, paints, Houston...",
)

# Apply Filters
filtered = evidence_df.copy()

if selected_companies:
    filtered = filtered[filtered["company_name"].isin(selected_companies)]

if selected_statuses:
    filtered = filtered[filtered["validation_status"].isin(selected_statuses)]

if selected_confidences:
    filtered = filtered[filtered["confidence"].isin(selected_confidences)]

if analyst_filter == "Analyst Assigned Only (True)":
    filtered = filtered[filtered["is_analyst_assigned"].astype(str).str.upper() == "TRUE"]
elif analyst_filter == "Automated Only (False)":
    filtered = filtered[filtered["is_analyst_assigned"].astype(str).str.upper() != "TRUE"]

if search_term:
    term = search_term.strip().lower()
    mask = (
        filtered["field_name"].astype(str).str.lower().str.contains(term)
        | filtered["source_evidence"].astype(str).str.lower().str.contains(term)
        | filtered["standardized_value"].astype(str).str.lower().str.contains(term)
    )
    filtered = filtered[mask]

st.caption(f"Showing **{len(filtered)}** of **{len(evidence_df)}** extracted evidence records.")

# Table display columns
display_cols = [
    "company_name",
    "field_name",
    "report_native_value",
    "standardized_value",
    "source_evidence",
    "page_number",
    "confidence",
    "validation_status",
    "is_analyst_assigned",
    "source_type",
]

available_cols = [c for c in display_cols if c in filtered.columns]
sub_df = filtered[available_cols].copy()

# Render styled dataframe
styled_df = sub_df.style.map(
    style_validation_status, subset=["validation_status"] if "validation_status" in sub_df.columns else []
).map(
    style_confidence, subset=["confidence"] if "confidence" in sub_df.columns else []
)

st.dataframe(
    styled_df,
    use_container_width=True,
    hide_index=True,
    height=500,
)

col_d1, col_d2 = st.columns([2, 1])
with col_d1:
    render_download_button(filtered, f"field_evidence_filtered_{len(filtered)}.csv", "Download Filtered Evidence (CSV)")

# Expandable Single-Record Inspector
with st.expander("🔎 Deep Evidence Record Inspector (Select row details)"):
    if not filtered.empty:
        record_idx = st.selectbox(
            "Select evidence record to inspect:",
            options=range(len(filtered)),
            format_func=lambda i: f"[{filtered.iloc[i]['company_name']}] {filtered.iloc[i]['field_name']} -> {filtered.iloc[i]['standardized_value']} (P.{filtered.iloc[i].get('page_number')})",
        )
        rec = filtered.iloc[record_idx]
        c1, c2 = st.columns(2)
        with c1:
            st.markdown(f"**Company:** `{rec.get('company_name')}` (`{rec.get('company_id')}`)")
            st.markdown(f"**Field Name:** `{rec.get('field_name')}`")
            st.markdown(f"**Report Native Value:** `{rec.get('report_native_value')}`")
            st.markdown(f"**Standardized Value:** `{rec.get('standardized_value')}`")
            st.markdown(f"**Page Number:** `{rec.get('page_number')}`")
            st.markdown(f"**Confidence:** `{rec.get('confidence')}`")
            st.markdown(f"**Validation Status:** `{rec.get('validation_status')}`")
        with c2:
            st.markdown(f"**Analyst Assigned:** `{rec.get('is_analyst_assigned')}`")
            st.markdown(f"**Source Type:** `{rec.get('source_type')}`")
            st.markdown(f"**Derivation Method:** `{rec.get('derivation_method') or 'None'}`")
            st.markdown(f"**Derivation Components:** `{rec.get('derivation_components') or 'None'}`")
            st.markdown(f"**Value Context:** `{rec.get('value_context') or 'None'}`")
            st.markdown(f"**Source PDF:** `{rec.get('source_pdf_filename')}`")
        st.markdown("**Verbatim Source Evidence:**")
        st.code(str(rec.get("source_evidence")), language="text")
