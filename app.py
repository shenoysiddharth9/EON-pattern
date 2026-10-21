"""
EON Commercial Intelligence & Action Platform
External Review Build — Proposed Phase 1

Multi-page Streamlit application powered exclusively by the Wingman Trigger Export CSV.
Provides enterprise portfolio intelligence, market signal synthesis, and suggested sales actions.
"""

import streamlit as st
from dashboard.components import render_disclaimer
from dashboard.theme import apply_theme
from dashboard.data_source import render_data_source_sidebar

st.set_page_config(
    page_title="EON Commercial Intelligence | External Review Build",
    page_icon="📡",
    layout="wide",
    initial_sidebar_state="auto",
)

apply_theme()

# Define Navigation: 4 Core Top-Level Enterprise Workflow Surfaces
pages = [
    st.Page("dashboard/pages/10_portfolio_insights.py", title="Portfolio Insights", icon="💡", default=True),
    st.Page("dashboard/pages/11_company_browser.py", title="Company Browser (Original)", icon="🔍"),
    st.Page("dashboard/pages/15_enriched_portfolio.py", title="Portfolio & Dossiers (788)", icon="🗂️"),
    st.Page("dashboard/pages/12_company_ranker.py", title="Company Ranker", icon="📊"),
    st.Page("dashboard/pages/14_ask_eon.py", title="Ask EON", icon="💬"),
]

pg = st.navigation(pages)

if pg.title in ["Ask EON", "Company Browser (Original)", "Portfolio & Dossiers (788)"]:
    # On Ask EON and Company Browser: minimal context control (popover modal) so chrome does not compete with workspace
    with st.sidebar.popover("📁 Dataset details", help="Data sources differ by page"):
        st.caption("Original Browser / Ask EON: Wingman source. Enriched Portfolio: 788-record overlay.")
        st.markdown(
            """
            <div style="font-size: 0.78rem; color: #64748b; line-height: 1.45;">
                Dataset: <code>wingman-trigger-export-2026-09-17-sanitized.csv</code><br>
                For custom CSV uploads or data parameter tuning, switch to <strong>Portfolio Insights</strong> or <strong>Company Browser</strong>.
            </div>
            """,
            unsafe_allow_html=True,
        )
else:
    # Full persistent sidebar on analytical pages
    st.sidebar.markdown(
        """
        <div style="padding: 6px 0 14px 0;">
            <h2 style="margin: 0; font-size: 1.25rem; font-weight: 700; color: #1e3a8a;">🛡️ EON Commercial Intelligence</h2>
            <div style="margin-top: 4px; display: inline-block; background-color: #dbeafe; color: #1e40af; padding: 2px 8px; border-radius: 4px; font-size: 0.75rem; font-weight: 600;">
                External Review Build — Proposed Phase 1
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    render_data_source_sidebar()

pg.run()
