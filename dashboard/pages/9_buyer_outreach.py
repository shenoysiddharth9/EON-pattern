"""
Page 9: Buyer & Outreach Recommendation Hub
Consultative B2B account prioritization, target buyer identification,
duplicate-clustered project triggers, consultative discovery topics for The Seven,
and tailored outreach briefs with strict 4-tier provenance tagging.
"""

import streamlit as st
import pandas as pd
from dashboard.components import (
    render_disclaimer,
    render_badge,
    render_download_button,
    render_kpi_card,
)
from dashboard.data_loader import load_scope_data
from datetime import date, datetime, timezone
from dashboard.recommendations import (
    METHODOLOGY_VERSION,
    DEFAULT_PRESET_NAME,
    DEFAULT_WEIGHTS,
    DEFAULT_EON_SCOPE,
    APPROVED_PRODUCT_POSITIONING,
    classify_sector_from_line_of_work,
    is_in_default_eon_scope,
    get_scope_label,
    calculate_account_fit,
    calculate_trigger_relevance,
    cluster_forward_signals,
    calculate_contactability,
    derive_priority_and_readiness,
    load_canonical_seven_patterns,
    generate_tailored_outreach_brief,
    validate_crm_schema,
    validate_contact_schema,
    generate_privacy_safe_export,
    normalize_company_name,
    abbreviate_monetary_values,
)
from dashboard.wingman_triggers import (
    parse_wingman_trigger_export,
    match_company_to_wingman_records,
    cluster_wingman_events,
    calculate_wingman_trigger_relevance,
    derive_recommended_action_wingman,
)
from dashboard.identity_registry import (
    AccountIdentityRegistry,
    parse_identity_crosswalk,
)


# Page Header
st.title("🎯 Buyer & Outreach Recommendation")
render_disclaimer()

# Collapsed Methodological Guardrail Notice (Moved closer to top)
with st.expander("ℹ️ Consultative Methodology & Transparent Heuristic Boundaries", expanded=False):
    st.markdown(
        """
        <div style="font-size: 0.88rem; color: #334155; line-height: 1.5;">
            • <strong>Non-Predictive Heuristic:</strong> Account prioritization scores are transparent heuristic indicators based on publicly extracted project activity and operational scale. They must <strong>NOT</strong> be presented as statistically predictive likelihood-to-close algorithms.<br>
            • <strong>Public Silence is NOT a Deficiency:</strong> The status <code>YOUR RECORD IS SILENT</code> across The Seven indicates an absence of public regulatory records. It is <strong>never</strong> scored as an operational vulnerability, but explored via consultative discovery questions.<br>
            • <strong>Zero Points for Missing Data:</strong> Undisclosed headcount or footprint contributes strictly zero points (no midpoint inflation). Both raw points and normalized 0–100 scores are reported.<br>
            • <strong>Temporal Urgency Separation:</strong> Because the source forward-signals schema contains no verified publication or milestone dates, <code>temporal_urgency</code> remains explicitly <code>UNKNOWN</code>.
        </div>
        """,
        unsafe_allow_html=True,
    )

# Load Active Extraction Data
scope = st.session_state.get("selected_scope", "Baseline Reports")
data = load_scope_data(scope)
companies_df = data.get("companies", pd.DataFrame())
signals_df = data.get("signals", pd.DataFrame())
patterns_df = data.get("patterns", pd.DataFrame())

if companies_df.empty:
    st.warning("No company records found in the active scope.")
    st.stop()

canonical_patterns = load_canonical_seven_patterns(patterns_df)

# Session State for Ingested Data (CRM, Contacts & Wingman Triggers)
if "uploaded_crm_df" not in st.session_state:
    st.session_state["uploaded_crm_df"] = None
if "uploaded_contacts_df" not in st.session_state:
    st.session_state["uploaded_contacts_df"] = None
if "uploaded_identity_registry" not in st.session_state:
    st.session_state["uploaded_identity_registry"] = None
if "uploaded_wingman_records" not in st.session_state:
    st.session_state["uploaded_wingman_records"] = None
if "uploaded_wingman_metadata" not in st.session_state:
    st.session_state["uploaded_wingman_metadata"] = None
if "uploaded_wingman_multi_domains" not in st.session_state:
    st.session_state["uploaded_wingman_multi_domains"] = {}
if "analysis_as_of_date" not in st.session_state:
    st.session_state["analysis_as_of_date"] = date.today()
if "scoring_weights" not in st.session_state:
    st.session_state["scoring_weights"] = DEFAULT_WEIGHTS.copy()

# Advanced Scoring Controls Expander (Collapsed by default, all 4 dimensions visible)
with st.expander("⚙️ Scoring Methodology & Advanced Weight Controls", expanded=False):
    st.markdown(f"**Active Preset**: `{DEFAULT_PRESET_NAME}` &nbsp;|&nbsp; **Engine Version**: `{METHODOLOGY_VERSION}`")
    st.caption("Adjust weight parameters transparently. Click 'Reset to Default' to restore the audited baseline.")

    w_cols = st.columns(3)
    with w_cols[0]:
        st.markdown("##### Account Fit Dimensions (Max: 100)")
        w_fit_emp = st.slider("Headcount Scale Max", 10.0, 60.0, float(st.session_state["scoring_weights"]["fit_headcount_max"]), 5.0)
        w_fit_foot = st.slider("Operating Footprint Max", 5.0, 30.0, float(st.session_state["scoring_weights"]["fit_footprint_max"]), 5.0)
        w_fit_sec = st.slider("Sector Criticality Max", 10.0, 40.0, float(st.session_state["scoring_weights"]["fit_sector_max"]), 5.0)
        w_fit_use = st.slider("EON Use-Case Fit Max", 10.0, 30.0, float(st.session_state["scoring_weights"]["fit_use_case_max"]), 5.0)
    with w_cols[1]:
        st.markdown("##### Trigger Relevance Dimensions (Max: 100)")
        w_trg_ast = st.slider("Asset Specificity Max", 10.0, 40.0, float(st.session_state["scoring_weights"]["trigger_asset_max"]), 5.0)
        w_trg_stg = st.slider("Project Stage Max", 10.0, 40.0, float(st.session_state["scoring_weights"]["trigger_stage_max"]), 5.0)
        w_trg_wrk = st.slider("Workforce Connection Max", 10.0, 40.0, float(st.session_state["scoring_weights"]["trigger_workforce_max"]), 5.0)
        w_trg_src = st.slider("Source Credibility Max", 5.0, 40.0, float(st.session_state["scoring_weights"]["trigger_source_max"]), 5.0)
    with w_cols[2]:
        st.markdown("##### Composite Blend (When CRM Known)")
        w_cmp_fit = st.slider("Fit %", 0.10, 0.70, float(st.session_state["scoring_weights"]["composite_weight_fit"]), 0.05)
        w_cmp_trg = st.slider("Trigger %", 0.10, 0.70, float(st.session_state["scoring_weights"]["composite_weight_trigger"]), 0.05)
        w_cmp_cnt = st.slider("Contact %", 0.05, 0.50, float(st.session_state["scoring_weights"]["composite_weight_contact"]), 0.05)

    if st.button("🔄 Reset to Default Weights"):
        st.session_state["scoring_weights"] = DEFAULT_WEIGHTS.copy()
        st.rerun()

    # Update active weights in session state with all 4 dimensions
    st.session_state["scoring_weights"].update({
        "fit_headcount_max": w_fit_emp,
        "fit_footprint_max": w_fit_foot,
        "fit_sector_max": w_fit_sec,
        "fit_use_case_max": w_fit_use,
        "trigger_asset_max": w_trg_ast,
        "trigger_stage_max": w_trg_stg,
        "trigger_workforce_max": w_trg_wrk,
        "trigger_source_max": w_trg_src,
        "composite_weight_fit": w_cmp_fit,
        "composite_weight_trigger": w_cmp_trg,
        "composite_weight_contact": w_cmp_cnt,
    })

# Ingestion Center: Optional Commercial Data & Wingman Trigger Upload (Collapsed by default)
with st.expander("📥 Optional Commercial & Trigger CSV Ingestion (Crosswalk, Wingman, CRM, Contacts)", expanded=False):
    st.caption("Upload an approved identity crosswalk to authorize alias/domain/ticker matching, Wingman dated triggers to enhance Trigger Relevance, and optional CRM/Contact files to enrich Contactability.")
    up_c0, up_c1, up_c2, up_c3 = st.columns(4)

    with up_c0:
        st.markdown("##### 1. Identity Crosswalk")
        cw_file = st.file_uploader("Account Identity Crosswalk (CSV):", type=["csv"], key="crosswalk_uploader")
        if cw_file:
            try:
                cw_res = parse_identity_crosswalk(cw_file)
                if cw_res["file_is_valid"]:
                    if cw_res["registry_applied"] and cw_res["registry"]:
                        st.session_state["uploaded_identity_registry"] = cw_res["registry"]
                        st.session_state["registry_input_state"] = "UPLOADED_VALID"
                        st.session_state["registry_applied"] = True
                        st.session_state["registry_review_required"] = False
                        reg = cw_res["registry"]
                        st.success(
                            f"Valid Registry: Ingested {len(cw_res['approved_rows'])} approved identities across "
                            f"{reg.approved_account_count} accounts. ({len(cw_res['quarantined_rows'])} quarantined)"
                        )
                    else:
                        st.session_state["uploaded_identity_registry"] = None
                        st.session_state["registry_input_state"] = "UPLOADED_INVALID"
                        st.session_state["registry_applied"] = False
                        st.session_state["registry_review_required"] = True
                        st.warning("Crosswalk parsed but 0 approved rows. Falling back to exact canonical names.")
                else:
                    st.session_state["uploaded_identity_registry"] = None
                    st.session_state["registry_input_state"] = "UPLOADED_INVALID"
                    st.session_state["registry_applied"] = False
                    st.session_state["registry_review_required"] = True
                    st.error(f"Validation failed: {len(cw_res['fatal_errors'])} complete-file errors. Registry rejected.")
                    for err in cw_res["fatal_errors"][:2]:
                        st.caption(f"❌ {err}")
                    if cw_res["normalized_collisions"]:
                        st.caption(f"⚠️ Collision: {cw_res['normalized_collisions'][0]}")
            except Exception as e:
                st.session_state["uploaded_identity_registry"] = None
                st.session_state["registry_input_state"] = "UPLOADED_INVALID"
                st.session_state["registry_applied"] = False
                st.session_state["registry_review_required"] = True
                st.error(f"Failed to read CSV: {e}")
        else:
            st.session_state["uploaded_identity_registry"] = None
            st.session_state["registry_input_state"] = "NOT_UPLOADED"
            st.session_state["registry_applied"] = False
            st.session_state["registry_review_required"] = False
        st.caption("Upload reviewed identity crosswalk to authorize entity matching routes.")

    with up_c1:
        st.markdown("##### 2. Wingman Triggers")
        w_file = st.file_uploader("Upload Wingman Triggers (CSV):", type=["csv"], key="wingman_uploader")
        if w_file:
            try:
                w_res = parse_wingman_trigger_export(w_file)
                if w_res["valid"]:
                    st.session_state["uploaded_wingman_records"] = w_res["records"]
                    st.session_state["uploaded_wingman_metadata"] = w_res["metadata"]
                    st.session_state["uploaded_wingman_multi_domains"] = w_res["multi_entity_domains"]
                    m = w_res["metadata"]
                    st.success(f"Ingested {m['valid_records_count']} rows ({m['active_trigger_records_count']} active, {m['zero_trigger_records_count']} zero-trigger scans across {m['unique_companies_count']} companies).")
                else:
                    st.error(f"Schema Error: {w_res.get('error')}")
            except Exception as e:
                st.error(f"Failed to read CSV: {e}")
        st.caption("Upload dated operational trigger intelligence to enrich Trigger Relevance & Temporal Urgency.")

    with up_c2:
        st.markdown("##### 3. CRM Accounts CSV")
        crm_file = st.file_uploader("Upload CRM Accounts (CSV):", type=["csv"], key="crm_uploader")
        if crm_file:
            try:
                crm_df = pd.read_csv(crm_file)
                valid, msg = validate_crm_schema(crm_df)
                if valid:
                    st.session_state["uploaded_crm_df"] = crm_df
                    st.success(f"Ingested {len(crm_df)} CRM accounts successfully.")
                else:
                    st.error(f"Schema Error: {msg}")
            except Exception as e:
                st.error(f"Failed to read CSV: {e}")

        sample_crm = pd.DataFrame([
            {"company_name": "ExxonMobil", "account_owner": "Sarah J.", "crm_stage": "Qualified Lead", "arr_potential": "$150,000", "notes": "Evaluating simulation training"},
            {"company_name": "Kinder Morgan", "account_owner": "David M.", "crm_stage": "Active Discovery", "arr_potential": "$200,000", "notes": "Pipeline expansion readiness"},
        ])
        st.download_button("📄 Download CRM CSV Template", sample_crm.to_csv(index=False), "crm_accounts_template.csv", "text/csv")

    with up_c3:
        st.markdown("##### 4. Target Contacts CSV")
        cnt_file = st.file_uploader("Upload Target Contacts (CSV):", type=["csv"], key="cnt_uploader")
        if cnt_file:
            try:
                cnt_df = pd.read_csv(cnt_file)
                valid, msg = validate_contact_schema(cnt_df)
                if valid:
                    st.session_state["uploaded_contacts_df"] = cnt_df
                    st.success(f"Ingested {len(cnt_df)} contacts successfully.")
                else:
                    st.error(f"Schema Error: {msg}")
            except Exception as e:
                st.error(f"Failed to read CSV: {e}")

        sample_cnt = pd.DataFrame([
            {"company_name": "ExxonMobil", "contact_name": "Marcus Vance", "title": "Director of Operations Training", "department": "Operational Capability", "email": "m.vance@exxonmobil.com"},
            {"company_name": "Kinder Morgan", "contact_name": "Elena Rostova", "title": "VP Capital Projects", "department": "Engineering & Construction", "email": "elena.rostova@kindermorgan.com"},
            {"company_name": "Sherwin-Williams", "contact_name": "Robert Chen", "title": "Head of Technical Competence", "department": "Manufacturing Excellence", "email": "rchen@sherwin.com"},
        ])
        st.download_button("📄 Download Contacts CSV Template", sample_cnt.to_csv(index=False), "target_contacts_template.csv", "text/csv")

    has_any_upload = (
        st.session_state.get("uploaded_identity_registry") is not None
        or st.session_state["uploaded_crm_df"] is not None
        or st.session_state["uploaded_contacts_df"] is not None
        or st.session_state["uploaded_wingman_records"] is not None
    )
    if has_any_upload:
        if st.button("🧹 Clear All Uploaded Data"):
            st.session_state["uploaded_identity_registry"] = None
            st.session_state["uploaded_crm_df"] = None
            st.session_state["uploaded_contacts_df"] = None
            st.session_state["uploaded_wingman_records"] = None
            st.session_state["uploaded_wingman_metadata"] = None
            st.session_state["uploaded_wingman_multi_domains"] = {}
            st.rerun()

st.markdown("---")

# Informational Notice when Baseline Reports is Selected
if scope == "Baseline Reports":
    st.info("💡 **Holdout Data Available**: Kinder Morgan was evaluated as an audited holdout and is available when switching scope to **Combined View** or **Audited Holdout Report** via the Data Scope selector in the sidebar.")

# Analysis Controls: Sector Scope Filter & User-Adjustable As-Of Date
sec_f1, sec_f2, sec_f3 = st.columns([2, 1, 1])
with sec_f1:
    sectors_present = sorted(list(set([classify_sector_from_line_of_work(r.get("line_of_work")) for _, r in companies_df.iterrows()])))
    sector_filter_options = [DEFAULT_EON_SCOPE, "All Industrial Sectors"] + sectors_present
    selected_sector = st.selectbox(
        "Portfolio Industry Scope:",
        options=sector_filter_options,
        index=0,
        help="Default scope filters to Oil, Gas, Energy Infrastructure, Refining and Petrochemicals. Out-of-scope entities (e.g. Sherwin-Williams) are accessible under 'All Industrial Sectors'.",
    )

with sec_f2:
    cur_as_of = st.session_state.get("analysis_as_of_date", date.today())
    sel_as_of = st.date_input(
        "📅 Analysis As-Of Date",
        value=cur_as_of,
        key="as_of_date_input",
        help="Reference date for calculating temporal urgency and milestone distance (defaults to runtime date).",
    )
    st.session_state["analysis_as_of_date"] = sel_as_of

with sec_f3:
    if selected_sector == DEFAULT_EON_SCOPE:
        st.caption("🔒 **Default EON Target Scope Active**: Non-core accounts excluded from default ranking.")
    else:
        st.caption("🌐 **Broader Scope Active**: Displays all evaluated industrial organizations.")
    st.caption(f"As-Of Reference: **{sel_as_of.isoformat()}**")

# Evaluate All Companies in Scope
wingman_records = st.session_state.get("uploaded_wingman_records")
wingman_multi_domains = st.session_state.get("uploaded_wingman_multi_domains", {})
active_as_of_date = st.session_state.get("analysis_as_of_date", date.today())

eval_records = []
for _, comp in companies_df.iterrows():
    c_name = comp["company_name"]
    comp_id = comp.get("company_id", "COMP-UNKNOWN")
    c_signals = signals_df[signals_df["company_name"] == c_name]

    c_domain = str(comp.get("domain", "") or "").strip()
    identity_reg = st.session_state.get("uploaded_identity_registry")

    fit = calculate_account_fit(comp, st.session_state["scoring_weights"])
    contact = calculate_contactability(
        company_name=c_name,
        contacts_df=st.session_state["uploaded_contacts_df"],
        crm_df=st.session_state["uploaded_crm_df"],
        weights=st.session_state["scoring_weights"],
        canonical_account_id=comp_id,
        identity_registry=identity_reg,
    )

    # Wingman trigger matching & source precedence
    wingman_match = None
    if wingman_records:
        wingman_match = match_company_to_wingman_records(
            company_id=comp_id,
            company_name=c_name,
            company_domain=c_domain,
            all_wingman_records=wingman_records,
            multi_entity_domains=wingman_multi_domains,
            identity_registry=identity_reg,
            report_sector=fit["sector"],
            report_wingman_tier=comp.get("wingman_tier"),
            registry_input_state=st.session_state.get("registry_input_state", "NOT_UPLOADED"),
            registry_applied=st.session_state.get("registry_applied", False),
            registry_review_required=st.session_state.get("registry_review_required", False),
        )

    if wingman_match and wingman_match["match_status"] == "MATCHED":
        if wingman_match["trigger_state"] == "ACTIVE_TRIGGERS":
            clusters = cluster_wingman_events(wingman_match["matched_records"], comp_id)
            wingman_trig = calculate_wingman_trigger_relevance(
                clusters, as_of_date=active_as_of_date, weights=st.session_state["scoring_weights"]
            )
            trigger_score = wingman_trig["score"]
            trigger_raw = wingman_trig["raw_points"]
            trigger_max_raw = wingman_trig["max_raw_points"]
            temporal_status = wingman_trig["temporal_status_as_of"]
            lead_trigger = wingman_trig["lead_cluster"]["lead_summary"] if wingman_trig.get("lead_cluster") else "Operational trigger"
            trigger_intel_source = "WINGMAN_ACTIVE"
            trigger_dict = wingman_trig
            next_action = derive_recommended_action_wingman(
                temporal_status_as_of=temporal_status,
                trigger_score=trigger_score,
                contact_status=contact["status"],
                evidence_coverage_pct=fit["evidence_coverage_pct"],
                trigger_state="ACTIVE_TRIGGERS",
            )
        else:  # SCANNED_ZERO_TRIGGERS
            trigger_score = 0.0
            trigger_raw = 0.0
            trigger_max_raw = 100.0
            temporal_status = "NONE_DETECTED"
            lead_trigger = "Scanned with 0 qualifying triggers"
            trigger_intel_source = "WINGMAN_ZERO_TRIGGERS"
            trigger_dict = {
                "score": 0.0,
                "raw_points": 0.0,
                "max_raw_points": 100.0,
                "temporal_status_as_of": "NONE_DETECTED",
                "trigger_evidence_confidence": "NOT_APPLICABLE",
                "clusters": [],
                "distinct_projects_count": 0,
                "lead_cluster": None,
                "notes": "Systematically researched in Wingman with 0 qualifying operational triggers.",
            }
            next_action = "Monitor"
    else:
        # Fallback to Pattern Report forward signals
        report_trig = calculate_trigger_relevance(c_signals, st.session_state["scoring_weights"])
        trigger_score = report_trig["score"]
        trigger_raw = report_trig["raw_points"]
        trigger_max_raw = report_trig["max_raw_points"]
        temporal_status = report_trig["temporal_urgency"]
        lead_trigger = report_trig["clusters"][0]["headline"] if report_trig["clusters"] else "General operational expansion"
        trigger_intel_source = "REPORT_FALLBACK" if wingman_records else "REPORT_ONLY"
        trigger_dict = report_trig
        priority_rep = derive_priority_and_readiness(fit, report_trig, contact, st.session_state["scoring_weights"])
        next_action = priority_rep["recommended_next_action"]

    # Calculate composite score
    is_contact_known = contact["status"] == "KNOWN"
    if is_contact_known:
        w_fit = float(st.session_state["scoring_weights"]["composite_weight_fit"])
        w_trg = float(st.session_state["scoring_weights"]["composite_weight_trigger"])
        w_cnt = float(st.session_state["scoring_weights"]["composite_weight_contact"])
        s_w = w_fit + w_trg + w_cnt
        eff_fit = w_fit / s_w if s_w > 0 else 0.333
        eff_trg = w_trg / s_w if s_w > 0 else 0.333
        eff_cnt = w_cnt / s_w if s_w > 0 else 0.333
        composite = round(eff_fit * fit["score"] + eff_trg * trigger_score + eff_cnt * contact["score"], 1)
        eff_weights_str = f"fit={eff_fit:.2f};trigger={eff_trg:.2f};contact={eff_cnt:.2f}"
        derivation_mode = "3-Component Blended"
    else:
        eff_fit = 0.50
        eff_trg = 0.50
        eff_cnt = 0.00
        composite = round(eff_fit * fit["score"] + eff_trg * trigger_score, 1)
        eff_weights_str = "fit=0.50;trigger=0.50;contact=0.00"
        derivation_mode = "Reweighted (Fit 50% / Trigger 50% - No CRM Data)"

    # Account opportunity tier
    if composite >= 75.0 and trigger_score >= 60.0:
        opportunity = "High-fit opportunity"
    elif composite >= 60.0:
        opportunity = "Moderate-fit opportunity"
    elif composite >= 40.0:
        opportunity = "Low-fit opportunity"
    else:
        opportunity = "Insufficient evidence"

    # Outreach readiness
    if contact["status"] == "UNKNOWN":
        readiness = "Buyer Needed"
    elif contact["status"] == "PARTIAL":
        readiness = "CRM Context Needed" if contact.get("role_coverage") == "PRIMARY_BUYER_IDENTIFIED" else "Buyer Needed"
    else:
        readiness = "Ready"

    scope_lbl = get_scope_label(fit["sector"])

    priority_dict = {
        "composite_score": composite,
        "effective_weights_str": eff_weights_str,
        "account_opportunity": opportunity,
        "outreach_readiness": readiness,
        "recommended_next_action": next_action,
        "temporal_urgency": temporal_status,
        "derivation_mode": derivation_mode,
        "overall_confidence": "HIGH" if (fit["confidence_level"] == "HIGH" and is_contact_known) else ("MEDIUM" if fit["confidence_level"] != "LOW" else "LOW"),
    }

    eval_records.append({
        "company_name": c_name,
        "company_id": comp_id,
        "source_row": comp,
        "sector": fit["sector"],
        "sector_scope_status": scope_lbl,
        "is_in_core_eon_scope": fit["is_in_core_eon_scope"],
        "wingman_tier": comp.get("wingman_tier", "UNASSIGNED"),
        "account_opportunity": opportunity,
        "outreach_readiness": readiness,
        "recommended_next_action": next_action,
        "temporal_urgency": temporal_status,
        "composite_score": composite,
        "fit_score": fit["score"],
        "fit_raw_points": fit["raw_points"],
        "fit_max_raw_points": fit["max_raw_points"],
        "trigger_score": trigger_score,
        "trigger_raw_points": trigger_raw,
        "trigger_max_raw_points": trigger_max_raw,
        "contact_score": contact["score"],
        "contact_raw_points": contact["raw_points"],
        "contact_max_raw_points": contact["max_raw_points"],
        "contactability": contact["status"],
        "evidence_coverage_pct": fit["evidence_coverage_pct"],
        "confidence_level": fit["confidence_level"],
        "fit_dict": fit,
        "trigger_dict": trigger_dict,
        "contact_dict": contact,
        "priority_dict": priority_dict,
        "lead_project_trigger": lead_trigger,
        "target_buyer_department": "Operational Training & Workforce Competence",
        "wingman_match": wingman_match,
        "trigger_intel_source": trigger_intel_source,
        "wingman_export_ingested": bool(wingman_match and wingman_match["match_status"] == "MATCHED"),
        "wingman_match_method": wingman_match["match_method"] if wingman_match else "NONE",
        "wingman_match_confidence": wingman_match["match_confidence"] if wingman_match else "NONE",
        "trigger_state": wingman_match["trigger_state"] if wingman_match else ("ABSENT_FROM_EXPORT" if wingman_records else "REPORT_ONLY"),
        "scan_confidence": wingman_match["scan_confidence"] if wingman_match else "NOT_APPLICABLE",
        "trigger_evidence_confidence": trigger_dict.get("trigger_evidence_confidence", "NOT_APPLICABLE"),
        "wingman_trigger_count": wingman_match["matched_records_count"] if wingman_match else 0,
        "wingman_cluster_count": len(trigger_dict.get("clusters", [])) if wingman_match else 0,
        "sector_conflict_flag": wingman_match.get("sector_conflict_flag", False) if wingman_match else False,
        "tier_conflict_flag": wingman_match.get("tier_conflict_flag", False) if wingman_match else False,
        "analysis_as_of_date": active_as_of_date.isoformat(),
    })

eval_df = pd.DataFrame(eval_records)

# Apply Default Scope or Sector Filter
if selected_sector == DEFAULT_EON_SCOPE:
    eval_df = eval_df[eval_df["is_in_core_eon_scope"] == True]
elif selected_sector != "All Industrial Sectors":
    eval_df = eval_df[eval_df["sector"] == selected_sector]

st.subheader("📋 Portfolio Recommendation & Account Prioritization Matrix")
st.caption(f"Displaying **{len(eval_df)}** organization(s). Source `wingman_tier` remains separate from dynamic `account_opportunity`.")

# Display Formatted Matrix with Fit, Trigger, Composite, and Coverage columns
matrix_cols = [
    "company_name",
    "sector",
    "sector_scope_status",
    "account_opportunity",
    "outreach_readiness",
    "recommended_next_action",
    "fit_score",
    "trigger_score",
    "composite_score",
    "contactability",
    "evidence_coverage_pct",
    "confidence_level",
    "temporal_urgency",
    "wingman_tier",
]
disp_matrix = eval_df[matrix_cols].copy()
disp_matrix.columns = [
    "Company",
    "Sector",
    "Scope Status",
    "Account Opportunity",
    "Outreach Readiness",
    "Recommended Next Action",
    "Fit Score",
    "Trigger Score",
    "Composite Score",
    "Contactability",
    "Coverage %",
    "Confidence",
    "Temporal Urgency",
    "Wingman Tier (Report)",
]

st.dataframe(disp_matrix, use_container_width=True, hide_index=True)

if wingman_records:
    with st.expander("🛡️ Wingman Account Match Audit Table (Entity Resolution Provenance)", expanded=False):
        audit_rows = []
        for e in eval_records:
            wm = e.get("wingman_match")
            if wm:
                audit_rows.append({
                    "canonical_account": wm.get("canonical_account", e["company_name"]),
                    "match_status": wm.get("match_status", "UNMATCHED"),
                    "detailed_match_status": wm.get("detailed_match_status", "UNMATCHED"),
                    "match_confidence": wm.get("match_confidence", "NONE"),
                    "raw_matched_record_count": wm.get("raw_matched_record_count", 0),
                    "distinct_source_company_names": ", ".join(wm.get("distinct_source_company_names", [])),
                    "distinct_source_domains": ", ".join(wm.get("distinct_source_domains", [])),
                    "match_methods": ", ".join(wm.get("match_methods", [])),
                    "match_review_required": wm.get("match_review_required", False),
                    "sector_conflict_review_required": wm.get("sector_conflict_review_required", False),
                    "tier_conflict_review_required": wm.get("tier_conflict_review_required", False),
                    "tier_assignment_review_required": wm.get("tier_assignment_review_required", False),
                    "multiple_export_tiers_review_required": wm.get("multiple_export_tiers_review_required", False),
                    "registry_review_required": wm.get("registry_review_required", False),
                    "any_review_required": wm.get("any_review_required", False),
                    "trigger_state": wm.get("trigger_state", e.get("trigger_state", "ABSENT_FROM_EXPORT")),
                    "trigger_score": f"{e.get('trigger_score', 0.0):.1f}",
                    "temporal_urgency": e.get("temporal_urgency", "UNKNOWN"),
                    "recommended_next_action": e.get("recommended_next_action", "Monitor"),
                })
        if audit_rows:
            audit_df = pd.DataFrame(audit_rows)
            st.dataframe(audit_df, use_container_width=True, hide_index=True)
            st.download_button(
                "📥 Download Account Match Audit Table (CSV)",
                audit_df.to_csv(index=False),
                "wingman_account_match_audit.csv",
                "text/csv",
            )

st.markdown("---")

# Account Deep Dive & Outreach Studio
st.subheader("🔍 Account Deep Dive & Consultative Outreach Studio")

company_list = eval_df["company_name"].tolist()
if not company_list:
    st.info("No companies match the selected sector scope.")
    st.stop()

selected_company = st.selectbox("Select Organization for Deep-Dive Outreach Analysis:", options=company_list, index=0)
active_eval = [e for e in eval_records if e["company_name"] == selected_company][0]

# Metrics Row for Active Account
m1, m2, m3, m4 = st.columns(4)
with m1:
    opp_val = active_eval["account_opportunity"]
    badge_c = "green" if "High-fit" in opp_val else "blue" if "Moderate-fit" in opp_val else "gray"
    st.markdown(f"**Account Opportunity:**<br>{render_badge(opp_val, badge_c)}", unsafe_allow_html=True)
    st.caption(f"Composite Score: **{active_eval['composite_score']} / 100**")

with m2:
    read_val = active_eval["outreach_readiness"]
    badge_r = "green" if read_val == "Ready" else "amber"
    st.markdown(f"**Outreach Readiness:**<br>{render_badge(read_val, badge_r)}", unsafe_allow_html=True)
    st.caption(f"Contactability: **{active_eval['contactability']}**")

with m3:
    act_val = active_eval["recommended_next_action"]
    badge_a = "green" if "Contact now" in act_val else "blue" if "Identify buyer" in act_val else "amber" if "Validate trigger" in act_val else "gray"
    st.markdown(f"**Recommended Action:**<br>{render_badge(act_val, badge_a)}", unsafe_allow_html=True)
    st.caption(f"Temporal Urgency: **{active_eval['temporal_urgency']}**")

with m4:
    cov_val = active_eval["evidence_coverage_pct"]
    conf_val = active_eval["confidence_level"]
    badge_cf = "green" if conf_val == "HIGH" else "amber" if conf_val == "MEDIUM" else "red"
    st.markdown(f"**Evidence Coverage:**<br>{render_badge(f'{cov_val}% ({conf_val})', badge_cf)}", unsafe_allow_html=True)
    st.caption("Based on non-missing report fields")

st.markdown("<br>", unsafe_allow_html=True)

# Shortened Tab Labels: Scorecard, Triggers, Discovery, Outreach Brief
t_breakdown, t_triggers, t_discovery, t_brief = st.tabs([
    "Scorecard",
    "Triggers",
    "Discovery",
    "Outreach Brief",
])

with t_breakdown:
    st.markdown("#### 1. Decoupled Component Scorecard")

    # Conflict and Provenance Alerts
    if active_eval.get("sector_conflict_flag"):
        st.warning(f"⚠️ **Sector Classification Discrepancy**: Report classifies as **{active_eval['sector']}**, but Wingman export classifies as **{active_eval['wingman_match']['trigger_export_segment']}**. Report-derived sector is preserved.")
    if active_eval.get("tier_conflict_flag"):
        wm_match_info = active_eval.get("wingman_match", {})
        if wm_match_info.get("multiple_export_tiers_flag"):
            st.warning(f"⚠️ **Multiple Export Tiers Review Required**: Conflicting tiers observed across legitimately matched export records: **{wm_match_info.get('observed_export_tiers')}**. Report tier is preserved for scoring.")
        else:
            st.warning(f"⚠️ **Wingman Tier Discrepancy**: Report records **{active_eval['wingman_tier']}**, while Wingman export assigns **Tier {wm_match_info.get('trigger_export_tier')}**. Report tier is preserved for scoring.")

    sc1, sc2, sc3 = st.columns(3)

    fit_d = active_eval["fit_dict"]
    with sc1:
        st.markdown(f"##### Account Fit: **{fit_d['score']}/100**")
        st.caption(f"Raw Points: **{fit_d['raw_points']} / {fit_d['max_raw_points']} pts** (Normalized to 0–100)")
        st.progress(fit_d["score"] / 100.0)
        b = fit_d["breakdown"]
        st.markdown(f"• **Operational Scale:** `{b['headcount_pts']} / {b['headcount_max']} pts` ({b['headcount_status']})")
        st.markdown(f"• **Operating Footprint:** `{b['footprint_pts']} / {b['footprint_max']} pts` ({b['footprint_status']})")
        st.markdown(f"• **Sector Criticality:** `{b['sector_pts']} / {b['sector_max']} pts` ({b['sector']})")
        st.markdown(f"• **EON Use-Case Fit:** `{b['use_case_pts']} / {b['use_case_max']} pts` ({b['use_case_status']})")
        if b["use_case_status"] == "SUPPORTED":
            st.caption(f"Evidence: \"{b['use_case_evidence'][:90]}...\"")
        else:
            st.caption("Use-case alignment not assessed from public text.")

    trg_d = active_eval["trigger_dict"]
    with sc2:
        st.markdown(f"##### Trigger Relevance: **{trg_d['score']}/100**")
        st.caption(f"Raw Points: **{trg_d['raw_points']} / {trg_d['max_raw_points']} pts** (Normalized to 0–100)")
        st.progress(trg_d["score"] / 100.0)
        st.markdown(f"• **Trigger Intel Source:** `{active_eval['trigger_intel_source']}`")
        st.markdown(f"• **Temporal Status (As-Of):** `{active_eval['temporal_urgency']}`")
        st.markdown(f"• **Distinct Project Clusters:** `{trg_d.get('distinct_projects_count', len(trg_d.get('clusters', [])))}`")
        if active_eval.get("wingman_match"):
            wm = active_eval["wingman_match"]
            st.markdown(f"• **Scan Confidence:** `{wm.get('scan_confidence', 'N/A')}`")
            st.markdown(f"• **Trigger Evidence Conf.:** `{active_eval.get('trigger_evidence_confidence', 'N/A')}`")
        else:
            st.caption("Derived from Pattern Report forward signals.")

    cnt_d = active_eval["contact_dict"]
    with sc3:
        cnt_score_disp = f"{cnt_d['score']}/100" if cnt_d['status'] != "UNKNOWN" else "UNKNOWN (0 pts)"
        st.markdown(f"##### Contactability: **{cnt_score_disp}**")
        st.caption(f"Raw Points: **{cnt_d['raw_points']} / {cnt_d['max_raw_points']} pts**")
        st.markdown(f"• **Status:** `{active_eval['contactability']}`")
        if cnt_d["status"] != "UNKNOWN":
            st.progress(cnt_d["score"] / 100.0)
            st.markdown(f"• **Role Coverage:** `{cnt_d['role_coverage']}`")
            st.markdown(f"• **CRM Stage:** `{cnt_d['stage']}`")
            st.markdown(f"• **Contacts Matched:** `{len(cnt_d['matched_contacts'])}`")
        else:
            st.info("⚪ [DATA AVAILABILITY] No CRM or contact data uploaded. Priority re-weighted 50% Fit / 50% Trigger.")

with t_triggers:
    st.markdown("#### 2. Clustered Operational Trigger Intelligence")

    is_wingman = active_eval.get("trigger_intel_source") == "WINGMAN_ACTIVE"
    is_zero_trig = active_eval.get("trigger_intel_source") == "WINGMAN_ZERO_TRIGGERS"

    if is_zero_trig:
        st.success("✅ **[SCANNED ZERO TRIGGERS]** This organization was systematically evaluated against all eight operational trigger categories; 0 qualifying events were identified. Recommended Action: **Monitor**.")
        if active_eval.get("wingman_match") and active_eval["wingman_match"].get("matched_records"):
            st.caption(f"Audit Note: *{active_eval['wingman_match']['matched_records'][0].get('notes')}*")

    elif is_wingman:
        st.caption("Exclusively driven by dated Wingman operational triggers. Evaluated relative to selected Analysis As-Of Date.")
        w_clusters = active_eval["trigger_dict"].get("clusters", [])
        for c in w_clusters:
            prec_str = c.get("date_precision", "DAY")
            dt_raw = c.get("lead_date_raw") or "Undated"
            temp_status = c.get("temporal_status_as_of", "UNKNOWN")
            badge_t = "green" if temp_status in ("CURRENT_ACTIVE", "UPCOMING_0_180_DAYS") else "blue" if temp_status == "PLANNED_181_365_DAYS" else "amber"
            abbr_summary = abbreviate_monetary_values(c.get("lead_summary", ""))

            st.markdown(
                f"""
                <div style="background-color: #ffffff; border: 1px solid #e2e8f0; border-radius: 8px; padding: 14px 18px; margin-bottom: 12px;">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
                        <div>
                            <span style="font-size: 0.74rem; font-weight: 700; color: #166534; background-color: #f0fdf4; padding: 2px 6px; border-radius: 4px; border: 1px solid #bbf7d0; margin-right: 6px;">[WINGMAN TRIGGER: {c['trigger_type'].upper()}]</span>
                            <span style="font-weight: 700; color: #1e293b; font-size: 0.95rem;">{abbr_summary}</span>
                        </div>
                        <div>{render_badge(f"SCORE: {c['cluster_score']}/100", badge_t)}</div>
                    </div>
                    <div style="font-size: 0.84rem; color: #64748b; margin-bottom: 6px;">
                        Trigger Date: <strong>{dt_raw}</strong> (<code>Precision: {prec_str}</code>) &nbsp;|&nbsp;
                        At Scan: <code>{c.get('date_relation_at_scan')}</code> &nbsp;|&nbsp;
                        As-Of Status: <span style="font-weight: 600; color: #0284c7;">{temp_status}</span> &nbsp;|&nbsp;
                        Clustered Records: <strong>{c.get('child_records_count', 1)}</strong>
                    </div>
                    <div style="font-size: 0.80rem; color: #475569; margin-bottom: 8px;">
                        • <strong>Asset:</strong> {c.get('asset_detail', '')} ({c.get('asset_pts', 0)} / 25 pts) &nbsp;|&nbsp;
                        • <strong>Stage:</strong> {c.get('stage_heuristic', '')} ({c.get('stage_pts', 0)} / 25 pts) &nbsp;|&nbsp;
                        • <strong>Workforce:</strong> {c.get('workforce_detail', '')} ({c.get('workforce_pts', 0)} / 25 pts) &nbsp;|&nbsp;
                        • <strong>Source:</strong> {c.get('source_tier', '')} ({c.get('source_pts', 0)} / 25 pts)
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            if c.get("all_source_urls"):
                url_links = " &nbsp;|&nbsp; ".join([f"[Source Link {idx+1}]({u})" for idx, u in enumerate(c["all_source_urls"])])
                st.markdown(f"🔗 **Source Verification:** {url_links}")

    # Display Pattern Report Forward Signals (Contextual / Fallback)
    rep_signals = signals_df[signals_df["company_name"] == active_eval["company_name"]]
    with st.expander("📄 Pattern Report Forward Signals (Contextual Background Evidence)", expanded=(not is_wingman and not is_zero_trig)):
        if rep_signals.empty:
            st.caption("No forward signals extracted in Pattern Report.")
        else:
            rep_clusters = cluster_forward_signals(rep_signals, st.session_state["scoring_weights"])
            for c in rep_clusters:
                dup_b = render_badge("DUPLICATE (DEDUPLICATED)", "gray") if c["is_duplicate_cluster"] else render_badge(f"SCORE: {c['cluster_score']}/100", "blue")
                hl_abbr = abbreviate_monetary_values(c['headline'])
                tag_label = "[REPORT FALLBACK SIGNAL]" if not is_wingman else "[REPORT CONTEXT SIGNAL]"
                st.markdown(
                    f"""
                    <div style="background-color: #ffffff; border: 1px solid #e2e8f0; border-radius: 8px; padding: 12px 16px; margin-bottom: 10px;">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
                            <div>
                                <span style="font-size: 0.72rem; font-weight: 700; color: #4338ca; background-color: #eef2ff; padding: 2px 6px; border-radius: 4px; border: 1px solid #c7d2fe; margin-right: 6px;">{tag_label}</span>
                                <span style="font-weight: 600; color: #1e293b; font-size: 0.90rem;">{hl_abbr}</span>
                            </div>
                            <div>{dup_b}</div>
                        </div>
                        <div style="font-size: 0.82rem; color: #64748b; margin-bottom: 4px;">
                            Reported by <strong>{c['outlet']}</strong> &nbsp;|&nbsp; Page {c['page_number']} &nbsp;|&nbsp; Stage: {c['stage_heuristic']}
                        </div>
                        <div style="background-color: #f8fafc; border-left: 2px solid #cbd5e1; padding: 6px 10px; font-size: 0.82rem; color: #334155; font-style: italic;">
                            "{c['implication']}"
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

with t_discovery:
    st.markdown("#### 3. The Seven Patterns as Consultative Discovery Topics")
    st.markdown(
        """
        <div style="background-color: #fffbeb; border: 1px dashed #f59e0b; padding: 10px 14px; border-radius: 6px; margin-bottom: 16px; font-size: 0.86rem; color: #92400e;">
            <strong>Consultative Sales Principle:</strong> Public silence across The Seven is not an operational weakness. Frame conversations as exploratory questions anchored in EON's canonical software solutions.
        </div>
        """,
        unsafe_allow_html=True,
    )

    for pat in canonical_patterns:
        st.markdown(
            f"""
            <div style="background-color: #ffffff; border: 1px solid #e2e8f0; border-radius: 8px; padding: 14px 18px; margin-bottom: 12px;">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
                    <div>
                        <span style="background-color: #3b82f6; color: white; padding: 2px 8px; border-radius: 10px; font-weight: 700; font-size: 0.78rem;">PATTERN {pat['pattern_number']:02d}</span>
                        <span style="font-weight: 700; color: #0f172a; margin-left: 8px; font-size: 0.95rem;">{pat['pattern_name']}</span>
                    </div>
                    <div>
                        <span style="color: #2563eb; font-weight: 600; font-size: 0.84rem;">Closed By: {pat['solution_closed_by']}</span>
                    </div>
                </div>
                <div style="font-size: 0.85rem; color: #64748b; font-style: italic; margin-bottom: 8px;">
                    "{pat['quote']}"
                </div>
                <div style="background-color: #f5f3ff; border-left: 3px solid #8b5cf6; padding: 8px 12px; border-radius: 4px;">
                    <div style="font-weight: 700; color: #6d28d9; font-size: 0.78rem; text-transform: uppercase;">🟣 [SUGGESTED DISCOVERY QUESTION]</div>
                    <div style="font-size: 0.86rem; color: #4c1d95; margin-top: 2px;">{pat['discovery_question']}</div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

with t_brief:
    st.markdown("#### 4. Tailored Outreach Brief & Executive Copy")
    st.caption("Sales reps can review or copy this brief. All data points carry strict provenance tags.")

    brief = generate_tailored_outreach_brief(
        company_row=active_eval["source_row"],
        fit_result=active_eval["fit_dict"],
        trigger_result=active_eval["trigger_dict"],
        contact_result=active_eval["contact_dict"],
        priority_result=active_eval["priority_dict"],
        canonical_patterns=canonical_patterns,
        product_copy_dict=APPROVED_PRODUCT_POSITIONING,
    )

    b_col1, b_col2 = st.columns([3, 2])
    with b_col1:
        st.markdown(f"**Suggested Email Subject:** `{brief['subject_line']}`")
        brief_text = f"Subject: {brief['subject_line']}\n\n"
        for p in brief["body_paragraphs"]:
            st.markdown(p)
            brief_text += p + "\n\n"
        st.markdown(f"*{brief['crm_context']}*")
        brief_text += brief['crm_context']

    with b_col2:
        st.markdown("##### 👥 Target Stakeholder Hierarchy")
        st.markdown("**Primary Buyer Families (Target for Initial Conversations):**")
        for r in brief["recommended_primary_buyers"]:
            st.markdown(f"• <span style='color: #166534; font-weight: 600;'>{r}</span>", unsafe_allow_html=True)

        st.markdown("**Co-Sponsors & Influencers (Project-Specific):**")
        for r in brief["recommended_influencers"]:
            st.markdown(f"• <span style='color: #1e40af;'>{r}</span>", unsafe_allow_html=True)

        st.markdown("**Explicit Exclusions:**")
        for r in brief["excluded_roles"]:
            st.markdown(f"• <span style='color: #991b1b; font-style: italic;'>{r}</span>", unsafe_allow_html=True)

    st.text_area("📋 Copyable Outreach Brief Text (with provenance tags):", brief_text, height=220)

st.markdown("---")

# Export Center with Privacy-Safe Masking and Calculation Lineage
st.subheader("📤 Export Recommendations & Commercial Datasets")
exp_c1, exp_c2 = st.columns([2, 2])

with exp_c1:
    mask_toggle = st.checkbox("🛡️ Privacy-Safe Export (Mask Contact Names & Emails)", value=True, help="Masks individual personal contact info (e.g. J. D***, ***@company.com) to comply with data privacy policies.")

with exp_c2:
    # Prepare export rows with full calculation lineage
    export_data = []
    for e in eval_records:
        matched_c = e["contact_dict"].get("matched_contacts", [])
        c_name = matched_c[0].get("contact_name") if matched_c else ""
        c_email = matched_c[0].get("email") if matched_c else ""
        export_data.append({
            "company_name": e["company_name"],
            "sector": e["sector"],
            "sector_scope_status": e["sector_scope_status"],
            "wingman_tier": e["wingman_tier"],
            "account_opportunity": e["account_opportunity"],
            "outreach_readiness": e["outreach_readiness"],
            "recommended_next_action": e["recommended_next_action"],
            "temporal_urgency": e["temporal_urgency"],
            "composite_score": e["composite_score"],
            "fit_score": e["fit_score"],
            "fit_raw_points": e["fit_dict"].get("raw_points", e["fit_score"]),
            "fit_max_raw_points": e["fit_dict"].get("max_raw_points", 100.0),
            "trigger_score": e["trigger_score"],
            "trigger_raw_points": e["trigger_dict"].get("raw_points", e["trigger_score"]),
            "trigger_max_raw_points": e["trigger_dict"].get("max_raw_points", 100.0),
            "contactability": e["contactability"],
            "contact_score": e["contact_score"],
            "contact_raw_points": e["contact_dict"].get("raw_points", 0.0),
            "contact_max_raw_points": e["contact_dict"].get("max_raw_points", 100.0),
            "effective_composite_weights": e["priority_dict"].get("effective_weights_str", "fit=0.50;trigger=0.50;contact=0.00"),
            "derivation_mode": e["priority_dict"].get("derivation_mode", "Reweighted"),
            "evidence_coverage_pct": e["evidence_coverage_pct"],
            "confidence_level": e["confidence_level"],
            "target_buyer_department": e["target_buyer_department"],
            "lead_project_trigger": e["lead_project_trigger"],
            "contact_name": c_name,
            "contact_email": c_email,
        })

    export_df = generate_privacy_safe_export(
        export_data,
        mask_pii=mask_toggle,
        active_weights=st.session_state["scoring_weights"],
    )
    render_download_button(
        export_df,
        f"buyer_outreach_recommendations_{scope.split()[0].lower()}.csv",
        "Download Recommendations Matrix (CSV)",
    )
