"""
Page 5: Public Accounts (Nonofficial Disclosures)
Filterable accounts table with year, tag, headline, outlet, page, official status,
raw evidence expanders, and permanent nonofficial content banner.
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
accounts_df = data.get("accounts", pd.DataFrame())
companies_df = data.get("companies", pd.DataFrame())

st.title("📰 Nonofficial Public Accounts")
render_disclaimer()

# Permanent Nonofficial Content Callout Banner
st.markdown(
    """
    <div style="background-color: #fefce8; border-left: 5px solid #eab308; padding: 14px 20px; border-radius: 6px; margin-bottom: 22px;">
        <div style="font-weight: 700; color: #854d0e; font-size: 0.95rem; margin-bottom: 4px;">
            ⚠️ NONOFFICIAL PUBLICLY WRITTEN ACCOUNTS (UNVERIFIED DISCLOSURES)
        </div>
        <div style="font-size: 0.88rem; color: #713f12; line-height: 1.45;">
            These accounts represent nonofficial, publicly written accounts comprising <strong>open-information accounts</strong> and <strong>press-reported accounts</strong>.<br>
            <strong>Official Status:</strong> <em>"Not verified, and not treated as a fact about your organisation."</em><br>
            All records mandate independent verification required. The reported total is a standardized component sum reconciliation.
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

if accounts_df.empty:
    st.warning("No public accounts found in the selected scope.")
    st.stop()

# Reconciliation Summary by Company
st.markdown("##### 📐 Component-Sum Derivation Breakdown")
recon_rows = []
for _, comp in companies_df.iterrows():
    cname = comp["company_name"]
    open_c = comp.get("open_information_count", 0)
    press_c = comp.get("press_reported_account_count", 0)
    rep_tot = comp.get("public_accounts_reported_count", 0)
    ext_tot = comp.get("public_accounts_extracted_count", 0)
    matches = comp.get("public_accounts_count_matches", True)

    recon_rows.append({
        "Company": cname,
        "Open Info Accounts": int(open_c) if pd.notna(open_c) else 0,
        "Press Accounts": int(press_c) if pd.notna(press_c) else 0,
        "Derived Total (Component Sum)": int(rep_tot) if pd.notna(rep_tot) else 0,
        "Physical Rows Extracted": int(ext_tot) if pd.notna(ext_tot) else 0,
        "Reconciliation Status": "MATCHED (100%)" if matches else "DISCREPANCY",
        "Derivation Method": comp.get("public_accounts_derivation_method", "COMPONENT_SUM"),
    })

st.dataframe(pd.DataFrame(recon_rows), use_container_width=True, hide_index=True)

st.markdown("---")

# Filters
st.markdown("##### Filter Public Accounts")
f1, f2, f3, f4 = st.columns(4)

with f1:
    comp_opts = ["All Companies"] + sorted(accounts_df["company_name"].dropna().unique().tolist())
    selected_comp = st.selectbox("Company:", options=comp_opts, index=0)

with f2:
    tag_opts = ["All Tags"] + sorted(accounts_df["tag"].dropna().unique().tolist())
    selected_tag = st.selectbox("Category Tag:", options=tag_opts, index=0)

with f3:
    outlet_opts = ["All Outlets"] + sorted(accounts_df["source_outlet"].dropna().unique().tolist())
    selected_outlet = st.selectbox("Source Outlet:", options=outlet_opts, index=0)

with f4:
    search_q = st.text_input("Search Headline / Keyword:", placeholder="e.g. fire, explosion, chemical...")

filtered = accounts_df.copy()
if selected_comp != "All Companies":
    filtered = filtered[filtered["company_name"] == selected_comp]
if selected_tag != "All Tags":
    filtered = filtered[filtered["tag"] == selected_tag]
if selected_outlet != "All Outlets":
    filtered = filtered[filtered["source_outlet"] == selected_outlet]
if search_q:
    q = search_q.strip().lower()
    filtered = filtered[
        filtered["headline"].astype(str).str.lower().str.contains(q)
        | filtered["description_snippet"].astype(str).str.lower().str.contains(q)
        | filtered["raw_evidence"].astype(str).str.lower().str.contains(q)
    ]

st.caption(f"Displaying **{len(filtered)}** of **{len(accounts_df)}** nonofficial accounts.")

# Display Table
tbl_cols = ["company_name", "account_index", "year", "tag", "headline", "source_outlet", "page_number", "official_status"]
available_tbl = [c for c in tbl_cols if c in filtered.columns]

display_table = filtered[available_tbl].copy()
if "year" in display_table.columns:
    display_table["year"] = display_table["year"].apply(
        lambda y: str(int(y)) if pd.notna(y) and str(y).replace(".","").isdigit() else "NOT STATED"
    )

st.dataframe(
    display_table,
    use_container_width=True,
    hide_index=True,
    height=420,
)

col_b1, col_b2 = st.columns([2, 1])
with col_b1:
    render_download_button(filtered, f"public_accounts_filtered_{len(filtered)}.csv", "Download Filtered Accounts (CSV)")

# Verbatim Raw Evidence Expanders
st.markdown("---")
st.markdown("##### 📜 Verbatim Raw Document Excerpts")
st.caption("Expand any item to inspect verbatim text parsed directly from the source PDF.")

for _, row in filtered.iterrows():
    header_label = f"[{row.get('company_name')}] #{row.get('account_index')} — {row.get('headline')} ({row.get('source_outlet') or 'Unspecified'})"
    with st.expander(header_label):
        c1, c2 = st.columns(2)
        with c1:
            st.markdown(f"**Year:** `{row.get('year') or 'Not stated'}`")
            st.markdown(f"**Category Tag:** `{row.get('tag')}`")
            st.markdown(f"**Source Outlet:** `{row.get('source_outlet')}`")
            st.markdown(f"**Page in Report:** `{row.get('page_number')}`")
        with c2:
            st.markdown(f"**Account ID:** `<code>{row.get('account_id')}</code>`", unsafe_allow_html=True)
            st.markdown(f"**Official Status:** `{row.get('official_status')}`")
            st.markdown(f"**Source PDF:** `{row.get('source_pdf_filename')}`")

        st.markdown("**Description Snippet:**")
        st.write(row.get("description_snippet") or "None")

        st.markdown("**Verbatim Raw Text from Document:**")
        st.code(str(row.get("raw_evidence")), language="text")
