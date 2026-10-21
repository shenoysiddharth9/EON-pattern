"""
Page 6: The Seven Failure Mode Patterns
All 7 operational safety failure modes per company with segregated benchmark qualifiers and macro status.
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
patterns_df = data.get("patterns", pd.DataFrame())
companies_df = data.get("companies", pd.DataFrame())

st.title("⚡ The Seven Failure Mode Patterns")
render_disclaimer()

# Macro Status Callout Banner
st.markdown(
    """
    <div style="background-color: #f8fafc; border-left: 5px solid #0284c7; padding: 14px 20px; border-radius: 6px; margin-bottom: 22px;">
        <div style="font-weight: 700; color: #0369a1; font-size: 0.95rem; margin-bottom: 4px;">
            🔍 MACRO FINDING: ALL PATTERNS SILENT ACROSS PORTFOLIO (0/7 ANSWERED)
        </div>
        <div style="font-size: 0.88rem; color: #334155; line-height: 1.45;">
            In every evaluated report, all 7 pattern statuses evaluate to <code>YOUR RECORD IS SILENT</code>.<br>
            Zero failure modes are addressed or closed by verifiable internal company safety records.
            Sector benchmarks cite international safety metrics (IOGP, Kimberlite, academic research) with segregated context qualifiers.
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

if patterns_df.empty:
    st.warning("No pattern records found in the selected scope.")
    st.stop()

# Company Selector
companies_available = sorted(patterns_df["company_name"].dropna().unique().tolist())
selected_comp = st.selectbox(
    "Select Organization to View Patterns:",
    options=companies_available,
    index=0,
)

comp_patterns = patterns_df[patterns_df["company_name"] == selected_comp].sort_values("pattern_number")

st.markdown(f"### 📋 Pattern Evaluation: **{selected_comp}** (7 of 7 Patterns Evaluated)")
st.caption(f"Showing all 7 standard operational failure modes extracted dynamically from the report.")

# Render 7 Pattern Cards
for _, pat in comp_patterns.iterrows():
    pat_num = pat.get("pattern_number")
    pat_name = pat.get("pattern_name")
    rec_status = pat.get("company_record_status")
    quote = pat.get("quote")
    solution = pat.get("solution_closed_by")
    bench_summary = pat.get("sector_benchmark_summary")
    bench_source = pat.get("sector_benchmark_source")
    bench_qualifier = pat.get("sector_benchmark_qualifier")
    page_num = pat.get("page_number")

    with st.container():
        st.markdown(
            f"""
            <div style="background-color: #ffffff; border: 1px solid #e2e8f0; border-radius: 8px; padding: 20px; margin-bottom: 18px; box-shadow: 0 1px 3px rgba(0,0,0,0.05);">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; flex-wrap: wrap; gap: 8px;">
                    <div>
                        <span style="background-color: #3b82f6; color: white; padding: 3px 10px; border-radius: 12px; font-weight: 700; font-size: 0.82rem;">PATTERN {pat_num:02d}</span>
                        <span style="font-size: 1.15rem; font-weight: 700; color: #0f172a; margin-left: 8px;">{pat_name}</span>
                    </div>
                    <div style="display: flex; gap: 8px; align-items: center;">
                        {render_badge(str(rec_status), 'amber')}
                        <span style="font-size: 0.78rem; color: #64748b;">Page {page_num}</span>
                    </div>
                </div>
                <div style="background-color: #f8fafc; border-left: 3px solid #94a3b8; padding: 10px 14px; margin-bottom: 14px; font-style: italic; color: #334155; font-size: 0.92rem;">
                    "{quote}"
                </div>
                <div style="margin-bottom: 12px; font-size: 0.88rem;">
                    <strong style="color: #1e293b;">EON Solution:</strong> <span style="color: #2563eb; font-weight: 600;">{solution}</span>
                </div>
                <div style="background-color: #f1f5f9; border-radius: 6px; padding: 12px 14px; font-size: 0.85rem; color: #1e293b; margin-bottom: 10px;">
                    <div style="font-weight: 600; color: #475569; margin-bottom: 4px;">Sector Benchmark:</div>
                    <div style="line-height: 1.4;">{bench_summary or 'No sector benchmark stated.'}</div>
                    <div style="font-size: 0.78rem; color: #64748b; margin-top: 4px;">Source: <em>{bench_source or 'Unspecified'}</em></div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        # Segregated Qualifier Callout if present
        if pd.notna(bench_qualifier) and str(bench_qualifier).strip():
            st.markdown(
                f"""
                <div style="margin-top: -10px; margin-bottom: 22px; margin-left: 20px; background-color: #fffbeb; border: 1px dashed #f59e0b; border-radius: 6px; padding: 8px 14px;">
                    <span style="font-weight: 700; color: #b45309; font-size: 0.8rem;">⚠️ SEGREGATED BENCHMARK QUALIFIER:</span>
                    <span style="font-size: 0.82rem; color: #92400e; margin-left: 6px;">"{bench_qualifier}"</span>
                </div>
                """,
                unsafe_allow_html=True,
            )

st.markdown("---")
render_download_button(patterns_df, f"seven_patterns_{scope.split()[0].lower()}.csv", "Download The Seven Patterns (CSV)")
