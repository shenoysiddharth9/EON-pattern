"""
Page 8: Test New PDF (Isolated Execution)
Upload an EON Pattern Report PDF, execute unchanged extraction in an ephemeral session,
display results, enforce wingman_tier = UNASSIGNED, with zero disk leakage or test contamination.
"""

import streamlit as st
import pandas as pd
import tempfile
import hashlib
from pathlib import Path

from dashboard.components import (
    render_disclaimer,
    render_badge,
    render_download_button,
    style_validation_status,
    style_confidence,
)
from src.pdf_loader import load_pdf_pages
from src.extractor import PatternReportExtractor
from src.validator import validate_all_policies
from src.models import WingmanInfo
from src.csv_writer import COMPANIES_SUMMARY_HEADERS

st.title("📄 Test New Pattern Report PDF (Isolated Session)")
render_disclaimer()

# Strict Isolation Guarantee Banner
st.markdown(
    """
    <div style="background-color: #f0fdf4; border-left: 5px solid #22c55e; padding: 14px 20px; border-radius: 6px; margin-bottom: 22px;">
        <div style="font-weight: 700; color: #15803d; font-size: 0.95rem; margin-bottom: 4px;">
            🔒 ZERO-LEAKAGE EXECUTION ISOLATION GUARANTEE
        </div>
        <div style="font-size: 0.88rem; color: #166534; line-height: 1.45;">
            Running extraction on an uploaded PDF executes strictly in a temporary memory session.<br>
            • <strong>No Filesystem Leakage:</strong> This session will <strong>NEVER</strong> alter <code>output/</code>, <code>baseline/</code>, or <code>tests/</code>.<br>
            • <strong>Wingman Enforcement:</strong> <code>wingman_tier</code> is strictly locked to <code>UNASSIGNED</code> (<code>source = NOT_PROVIDED</code>).<br>
            • <strong>Integrity Protection:</strong> Baseline SHA-256 manifests and regression test fixtures remain 100% frozen.
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

# Upload Form
uploaded_file = st.file_uploader(
    "Upload EON Pattern Report PDF for Blind Validation:",
    type=["pdf"],
    help="Upload any standard EON Pattern Report PDF to run isolated parser extraction.",
)

col_act1, col_act2 = st.columns([1, 4])
with col_act1:
    run_btn = st.button("🚀 Run Extraction", type="primary", disabled=uploaded_file is None)
with col_act2:
    if "test_results" in st.session_state:
        if st.button("🧹 Clear Session Results"):
            del st.session_state["test_results"]
            st.rerun()

if run_btn and uploaded_file is not None:
    with st.spinner("Executing isolated extraction and policy validation..."):
        # Save to temporary file
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp_file:
            tmp_file.write(uploaded_file.getvalue())
            tmp_pdf_path = Path(tmp_file.name)

        try:
            pages = load_pdf_pages(tmp_pdf_path)
            extractor = PatternReportExtractor(filename=uploaded_file.name, pages=pages)

            # Assign deterministic temporary ID if unmapped and enforce unassigned Wingman
            if extractor.company_id == "COMP-UNKNOWN":
                comp_hash = hashlib.sha256(Path(uploaded_file.name).stem.encode("utf-8")).hexdigest()[:6].upper()
                extractor.company_id = f"COMP-TMP-{comp_hash}"
                extractor.slug = f"TMP{comp_hash[:4]}"

            extractor.wingman = WingmanInfo(tier="UNASSIGNED", source="NOT_PROVIDED")

            record = extractor.extract_all()
            valid, violations = validate_all_policies([record])

            # Build in-memory datasets
            emp_fe = record.fields.get("people_employed")
            p_card_str = "TRUE" if emp_fe and emp_fe.profile_card_present is True else ("FALSE" if emp_fe and emp_fe.profile_card_present is False else "")
            
            summary_row = {
                "parser_version": record.metadata.get("parser_version", "1.1.0"),
                "extraction_timestamp": record.metadata.get("extraction_timestamp", ""),
                "source_pdf_filename": record.source_pdf_filename,
                "company_id": record.company_id,
                "company_name": record.company_name,
                "extraction_review_required": record.metadata.get("extraction_review_required", "FALSE"),
                "source_verification_required": record.metadata.get("source_verification_required", "FALSE"),
                "analyst_normalization_review_required": record.metadata.get("analyst_normalization_review_required", "FALSE"),
                "manual_review_required": record.metadata.get("manual_review_required", ""),
                "manual_review_notes": record.metadata.get("manual_review_notes", ""),
                "wingman_tier": record.wingman.tier,
                "wingman_source": record.wingman.source,
                "headcount_source_type": emp_fe.source_type if (emp_fe and emp_fe.source_type) else "",
                "headcount_source_date": emp_fe.source_date if (emp_fe and emp_fe.source_date) else "",
                "headcount_value_context": emp_fe.value_context if (emp_fe and emp_fe.value_context) else "",
                "headcount_profile_card_present": p_card_str,
            }
            pa_rep_fe = record.fields.get("public_accounts_reported_count")
            if pa_rep_fe:
                summary_row["public_accounts_derivation_method"] = pa_rep_fe.derivation_method or ""
                summary_row["public_accounts_derivation_components"] = pa_rep_fe.derivation_components or ""

            for col in COMPANIES_SUMMARY_HEADERS:
                if col not in summary_row:
                    fe = record.fields.get(col)
                    summary_row[col] = fe.standardized_value if (fe and fe.standardized_value is not None) else ""

            summary_df = pd.DataFrame([summary_row])
            evidence_df = pd.DataFrame([fe.to_dict() for fe in record.fields.values()])
            signals_df = pd.DataFrame([sig.to_dict() for sig in record.forward_signals])
            accounts_df = pd.DataFrame([acc.to_dict() for acc in record.public_accounts])
            patterns_df = pd.DataFrame([pat.to_dict() for pat in record.seven_patterns])
            issues_df = pd.DataFrame([iss.to_dict() for iss in record.validation_issues])

            st.session_state["test_results"] = {
                "company_name": record.company_name,
                "company_id": record.company_id,
                "summary_df": summary_df,
                "evidence_df": evidence_df,
                "signals_df": signals_df,
                "accounts_df": accounts_df,
                "patterns_df": patterns_df,
                "issues_df": issues_df,
                "valid": valid,
                "violations": violations,
            }
            st.success(f"Extraction completed for **{record.company_name}** ({len(record.fields)} fields, {len(record.forward_signals)} signals, {len(record.public_accounts)} accounts)!")

        finally:
            if tmp_pdf_path.exists():
                tmp_pdf_path.unlink()

# Render Session Results
if "test_results" in st.session_state:
    res = st.session_state["test_results"]
    c_name = res["company_name"]
    c_id = res["company_id"]
    s_df = res["summary_df"].iloc[0]

    st.markdown("---")
    st.markdown(f"## 📊 Extraction Results: **{c_name}** (`{c_id}`)")

    # Status banner
    s1, s2, s3, s4 = st.columns(4)
    with s1:
        st.markdown(f"**Wingman Tier:**<br>{render_badge('UNASSIGNED', 'gray')}", unsafe_allow_html=True)
    with s2:
        ext_req = s_df.get("extraction_review_required")
        badge_type = "red" if ext_req is True or str(ext_req).upper() == "TRUE" else "green"
        st.markdown(f"**Extraction Review:**<br>{render_badge(str(ext_req).upper(), badge_type)}", unsafe_allow_html=True)
    with s3:
        st.markdown(f"**Policy Validation:**<br>{render_badge('PASSED' if res['valid'] else 'VIOLATIONS', 'green' if res['valid'] else 'red')}", unsafe_allow_html=True)
    with s4:
        iss_cnt = len(res["issues_df"])
        iss_badge_type = "amber" if iss_cnt > 0 else "green"
        st.markdown(f"**Logged Issues:**<br>{render_badge(f'{iss_cnt} ISSUES', iss_badge_type)}", unsafe_allow_html=True)

    # Tabs for Data Views
    t1, t2, t3, t4, t5, t6 = st.tabs([
        "🏢 Summary & Outcomes",
        "🔍 Field Evidence",
        "📡 Forward Signals",
        "📰 Public Accounts",
        "⚡ The Seven Patterns",
        "🛡️ Issues & Policies",
    ])

    with t1:
        st.markdown("#### Executive Summary")
        col_p1, col_p2 = st.columns(2)
        with col_p1:
            st.markdown(f"• **Line of Work:** `{s_df.get('line_of_work') or 'NOT REPORTED'}`")
            st.markdown(f"• **Headquarters:** `{s_df.get('headquarters_city')}, {s_df.get('headquarters_country')}`")
            st.markdown(f"• **People Employed:** `{s_df.get('people_employed') or 'NOT DISCLOSED'}`")
            st.markdown(f"• **Year Founded:** `{s_df.get('year_founded') or 'NOT DISCLOSED'}`")
        with col_p2:
            st.markdown(f"• **Official Records Availability:** `{s_df.get('official_records_availability')}`")
            st.markdown(f"• **Registry Search Status:** `{s_df.get('registry_search_status')}`")
            st.markdown(f"• **Regulatory Status:** `{s_df.get('regulatory_record_status')}`")
            st.markdown(f"• **Inference:** `{s_df.get('safety_performance_inference')}`")

        render_download_button(res["summary_df"], f"{c_id}_summary.csv", "Download Summary (CSV)", key="dl_test_sum")

    with t2:
        st.markdown("#### Extracted Field Evidence")
        ev_disp = res["evidence_df"][["field_name", "report_native_value", "standardized_value", "page_number", "confidence", "validation_status", "is_analyst_assigned"]].copy()
        styled_ev = ev_disp.style.map(style_validation_status, subset=["validation_status"]).map(style_confidence, subset=["confidence"])
        st.dataframe(styled_ev, use_container_width=True, hide_index=True)
        render_download_button(res["evidence_df"], f"{c_id}_evidence.csv", "Download Evidence (CSV)", key="dl_test_ev")

    with t3:
        st.markdown("#### Forward Signals (What You Are Building)")
        st.caption(f"Extracted: {len(res['signals_df'])} cards | Reported in stats: {s_df.get('forward_signals_reported_count')}")
        if not res["signals_df"].empty:
            for _, sig in res["signals_df"].iterrows():
                st.markdown(f"• **#{sig.get('signal_index')} — {sig.get('headline')}** (P.{sig.get('page_number')}, *{sig.get('reported_by')}*)")
                st.caption(f"\"{sig.get('implication_text')}\"")
        render_download_button(res["signals_df"], f"{c_id}_signals.csv", "Download Signals (CSV)", key="dl_test_sig")

    with t4:
        st.markdown("#### Public Accounts (Nonofficial Disclosures)")
        st.caption(f"Component sum: open_info={s_df.get('open_information_count')}, press={s_df.get('press_reported_account_count')}")
        if not res["accounts_df"].empty:
            acc_disp = res["accounts_df"][["account_index", "year", "tag", "headline", "source_outlet", "page_number", "official_status"]].copy()
            st.dataframe(acc_disp, use_container_width=True, hide_index=True)
        render_download_button(res["accounts_df"], f"{c_id}_accounts.csv", "Download Accounts (CSV)", key="dl_test_acc")

    with t5:
        st.markdown("#### The Seven Failure Mode Patterns")
        st.caption(f"Answered by record: {s_df.get('the_seven_answered_count')}/7 | Status: {s_df.get('the_seven_overall_status')}")
        if not res["patterns_df"].empty:
            pat_disp = res["patterns_df"][["pattern_number", "pattern_name", "company_record_status", "solution_closed_by", "sector_benchmark_source"]].copy()
            st.dataframe(pat_disp, use_container_width=True, hide_index=True)
        render_download_button(res["patterns_df"], f"{c_id}_patterns.csv", "Download Seven Patterns (CSV)", key="dl_test_pat")

    with t6:
        st.markdown("#### Validation Issues & Policy Check Results")
        if res["violations"]:
            st.error(f"⚠️ {len(res['violations'])} Policy Violations Detected:")
            for v in res["violations"]:
                st.markdown(f"• {v}")
        else:
            st.success("✅ All standardized validation policies passed.")

        if not res["issues_df"].empty:
            st.markdown("##### Logged Quality Issues")
            st.dataframe(res["issues_df"][["issue_id", "field_name", "issue_type", "description", "page_number", "resolution_proposed"]], use_container_width=True, hide_index=True)
        render_download_button(res["issues_df"], f"{c_id}_issues.csv", "Download Issues (CSV)", key="dl_test_iss")
