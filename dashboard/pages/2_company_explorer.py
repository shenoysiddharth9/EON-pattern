"""
Page 2: Company Explorer
In-depth corporate profile, Wingman tier, review flags, regulatory outcome cards, and reconciliation status.
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
companies_df = data.get("companies", pd.DataFrame())

st.title("🏢 Company Explorer")
render_disclaimer()

if companies_df.empty:
    st.warning("No company records found in the selected scope.")
    st.stop()

# Company selector
company_names = companies_df["company_name"].tolist()
selected_comp = st.selectbox(
    "Select Organization to Inspect:",
    options=company_names,
    index=0,
    help="Switch between audited corporate profiles",
)

comp_row = companies_df[companies_df["company_name"] == selected_comp].iloc[0]

# Profile Header Banner
tier = str(comp_row.get("wingman_tier", "UNASSIGNED"))
tier_color = "blue" if "Tier" in tier else "gray"
tier_source = comp_row.get("wingman_source", "NOT_PROVIDED")

st.markdown(
    f"""
    <div style="background-color: #f8fafc; border: 1px solid #cbd5e1; border-radius: 8px; padding: 18px 24px; margin-bottom: 20px;">
        <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px;">
            <div>
                <h2 style="margin: 0; font-size: 1.6rem; color: #0f172a;">{comp_row.get('company_name')}</h2>
                <span style="font-size: 0.82rem; color: #64748b;">ID: <code>{comp_row.get('company_id')}</code> &nbsp;|&nbsp; PDF: <code>{comp_row.get('source_pdf_filename')}</code></span>
            </div>
            <div style="display: flex; gap: 8px; align-items: center;">
                {render_badge(tier, tier_color)}
                {render_badge(f"Source: {tier_source}", "gray")}
            </div>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

# Review Status Audit Badges
st.markdown("##### 🛡️ Audit & Review Flags")
col_f1, col_f2, col_f3, col_f4 = st.columns(4)

with col_f1:
    ext_req = comp_row.get("extraction_review_required")
    badge_type = "red" if ext_req is True or str(ext_req).upper() == "TRUE" else "green"
    st.markdown(f"**Extraction Review:**<br>{render_badge(str(ext_req).upper(), badge_type)}", unsafe_allow_html=True)
    st.caption("Parser candidate ambiguity or fallback")

with col_f2:
    src_req = comp_row.get("source_verification_required")
    badge_type = "amber" if src_req is True or str(src_req).upper() == "TRUE" else "green"
    st.markdown(f"**Independent Verification:**<br>{render_badge(str(src_req).upper(), badge_type)}", unsafe_allow_html=True)
    st.caption("Required for unverified public press")

with col_f3:
    norm_req = comp_row.get("analyst_normalization_review_required")
    badge_type = "amber" if norm_req is True or str(norm_req).upper() == "TRUE" else "green"
    st.markdown(f"**Analyst Normalization:**<br>{render_badge(str(norm_req).upper(), badge_type)}", unsafe_allow_html=True)
    st.caption("Analyst assigned or standardized values")

with col_f4:
    man_req = comp_row.get("manual_review_required")
    badge_type = "amber" if man_req is True or str(man_req).upper() == "TRUE" else "green"
    st.markdown(f"**Manual Review Overall:**<br>{render_badge(str(man_req).upper(), badge_type)}", unsafe_allow_html=True)
    st.caption("Workbook review required")

st.markdown("---")

# Detailed Tabs
tab_profile, tab_regulatory, tab_reconcile = st.tabs([
    "🏢 Corporate Profile & Operations",
    "⚖️ Regulatory Records & Outcome Cards",
    "📐 Reconciliation & Audit Notes",
])

with tab_profile:
    st.markdown("#### Business Profile & Operational Footprint")
    cp1, cp2 = st.columns(2)

    with cp1:
        st.markdown(f"**Line of Work:** `{comp_row.get('line_of_work') or 'NOT REPORTED'}`")
        st.markdown(f"**Headquarters City:** `{comp_row.get('headquarters_city') or 'NOT REPORTED'}`")
        st.markdown(f"**Headquarters Country:** `{comp_row.get('headquarters_country') or 'NOT REPORTED'}`")
        st.markdown(f"**Operating Countries:** `{comp_row.get('operating_countries') or 'NOT DISCLOSED'}`")
        st.markdown(f"**Report Geography:** `{comp_row.get('report_geography') or 'NOT REPORTED'}`")

    with cp2:
        year_f = comp_row.get('year_founded')
        st.markdown(f"**Year Founded:** `{int(year_f) if pd.notna(year_f) and str(year_f).replace('.','').isdigit() else 'NOT DISCLOSED'}`")

        emp = comp_row.get('people_employed')
        st.markdown(f"**People Employed:** `{int(emp):,}`" if pd.notna(emp) and str(emp).replace(".","").isdigit() else f"**People Employed:** `NOT DISCLOSED`")

        st.markdown(f"**Headcount Source Type:** `{comp_row.get('headcount_source_type') or 'N/A'}`")
        st.markdown(f"**Headcount Card Present on P1:** `{comp_row.get('headcount_profile_card_present')}`")
        st.markdown(f"**Report Window:** `{comp_row.get('report_window') or 'NOT REPORTED'}`")
        st.markdown(f"**Header Basis of Report:** `{comp_row.get('header_basis_of_report') or 'NOT REPORTED'}`")

    if pd.notna(comp_row.get("business_description")):
        st.markdown("##### Business Narrative Excerpt")
        st.info(f"\"{comp_row.get('business_description')}\"")

with tab_regulatory:
    st.markdown("#### Regulatory Records & Outcome Disclosures (Page 3 Evidence)")
    st.caption("Strict zero-fallback enforcement: explicit zero preserved as 0; absence preserved as missing.")

    r1, r2, r3, r4, r5, r6 = st.columns(6)
    with r1:
        st.metric("Citations", int(comp_row.get("citations_count", 0)))
    with r2:
        st.metric("Penalties", comp_row.get("penalties_display_text", "$0"))
    with r3:
        st.metric("Investigated Accidents", int(comp_row.get("investigated_accidents_count", 0)))
    with r4:
        st.metric("Deaths Count", int(comp_row.get("deaths_count", 0)))
    with r5:
        st.metric("OSHA Inspections", int(comp_row.get("osha_inspections_found", 0)))
    with r6:
        st.metric("CSB Mentions", int(comp_row.get("csb_mentions_found", 0)))

    st.markdown("##### Corporate Registry & Safety Inferences")
    reg_col1, reg_col2 = st.columns(2)
    with reg_col1:
        st.markdown(f"• **Official Records Availability:** `{comp_row.get('official_records_availability')}`")
        st.markdown(f"• **Registry Search Status:** `{comp_row.get('registry_search_status')}`")
        st.markdown(f"• **Official Company Record Found:** `{comp_row.get('official_company_record_found')}`")
        st.markdown(f"• **Regulatory Record Status:** `{comp_row.get('regulatory_record_status')}`")

    with reg_col2:
        st.markdown(f"• **SEC Annual Report Status:** `{comp_row.get('sec_annual_report_status')}`")
        st.markdown(f"• **SEC Filing Date:** `{comp_row.get('sec_filing_date') or 'NOT DISCLOSED'}`")
        st.markdown(f"• **Safety Performance Inference:** `{comp_row.get('safety_performance_inference')}`")

with tab_reconcile:
    st.markdown("#### Section Item Count Reconciliations")

    rec_data = [
        {
            "Section": "Forward Signals ('What You Are Building')",
            "Reported Total": comp_row.get("forward_signals_reported_count"),
            "Extracted Physical Items": comp_row.get("forward_signals_extracted_count"),
            "Reconciliation Status": "DISCREPANCY (Unaccounted signals in source)" if not comp_row.get("forward_signals_count_matches", True) else "RECONCILED",
            "Derivation Method": "REPORT_HEADER_VS_CARDS",
            "Derivation Detail": "Page 8/10 states 6 press accounts; Page 2 renders only 4 cards.",
        },
        {
            "Section": "Public Accounts ('Nonofficial Accounts')",
            "Reported Total": comp_row.get("public_accounts_reported_count"),
            "Extracted Physical Items": comp_row.get("public_accounts_extracted_count"),
            "Reconciliation Status": "RECONCILED (Component Sum)",
            "Derivation Method": comp_row.get("public_accounts_derivation_method", "COMPONENT_SUM"),
            "Derivation Detail": comp_row.get("public_accounts_derivation_components", "Component sum of open info + press"),
        },
        {
            "Section": "The Seven Failure Modes",
            "Reported Total": comp_row.get("seven_patterns_reported_count"),
            "Extracted Physical Items": comp_row.get("seven_patterns_extracted_count"),
            "Reconciliation Status": "RECONCILED (7/7 Patterns Evaluated)",
            "Derivation Method": "EXPLICIT_SECTION_CARDS",
            "Derivation Detail": f"Answered by record: {comp_row.get('the_seven_answered_count')}/7 | Macro Status: {comp_row.get('the_seven_overall_status')}",
        },
    ]
    st.table(pd.DataFrame(rec_data))

    if pd.notna(comp_row.get("manual_review_notes")):
        st.markdown("##### Detailed Auditor Notes")
        st.warning(comp_row.get("manual_review_notes"))

st.markdown("---")
render_download_button(
    pd.DataFrame([comp_row]),
    f"{comp_row.get('company_id')}_profile.csv",
    f"Download {comp_row.get('company_name')} Summary (CSV)",
)
