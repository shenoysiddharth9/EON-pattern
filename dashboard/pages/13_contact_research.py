"""
Page 13: Contact Research (Colleague Tool Integration)
EON Commercial Intelligence | External Review Build — Proposed Phase 1

Integrates access to the colleague-shared Contact Research tool and local backend:
- Direct interactive lookup for portfolio companies wired to http://localhost:8787/api/contact-research
- Embedded access to the colleague's standalone HTML tool (EON_Prospect_Ranker_DEMO_FAST_CACHED.html)
"""

import os
from pathlib import Path
import streamlit as st
import streamlit.components.v1 as components
import pandas as pd

from dashboard.data_source import get_active_dataset, render_source_banner
from dashboard.contact_research import (
    CONTACT_API_URL,
    is_contact_server_online,
    get_contact_research_secrets,
    render_contact_research_ui,
    render_secrets_diagnostics,
)

# Page header
st.title("👥 Contact Research (Colleague Tool)")
render_source_banner()

st.caption(
    "EON Commercial Intelligence | External Review Build — Proposed Phase 1 | "
    "Access the colleague-shared Contact Research tool and local Agentic V1 backend."
)

# Backend status check
secrets = get_contact_research_secrets()
has_in_process_keys = bool(secrets.get("brave_key") and (secrets.get("openai_key") or secrets.get("genai_key")))
server_active = is_contact_server_online()
if server_active:
    st.success(f"🟢 **Local Backend Active**: Connected to Contact Research API at `{CONTACT_API_URL}`")
elif has_in_process_keys:
    st.success("🟢 **In-Process Engine Active**: Live research configured via Streamlit secrets.")
else:
    st.info(
        "💡 **Contact Intelligence Engine**: Benchmark accounts (e.g. Baker Hughes) are available immediately. "
        "For full live research across all accounts, configure `OPENAI_API_KEY` and `BRAVE_SEARCH_API_KEY` in Streamlit App Settings → Secrets, "
        "or run the local server on port 8787."
    )

# Non-sensitive diagnostics (safe boolean check, candidate SHA-256 fingerprints, and server-side health probe)
render_secrets_diagnostics(show_admin_debug_default=True)


# Load Active Portfolio for company selection
with st.spinner("Loading portfolio accounts..."):
    active_ds = get_active_dataset()
    companies_df = active_ds["portfolio"]["companies_df"]

tab_lookup, tab_colleague_tool = st.tabs([
    "🔍 Portfolio Account Research",
    "🌐 Colleague Prospect Ranker (Embedded)",
])

with tab_lookup:
    st.markdown("### 🏢 Interactive Company Contact Research")
    st.caption("Select an account from the portfolio or type a custom company name to run contact research against the local endpoint.")

    comp_options = ["— Select an account from the portfolio —"] + sorted(companies_df["company_name"].unique())
    selected_comp = st.selectbox(
        "Choose Portfolio Company:",
        options=comp_options,
        index=0,
        help="Select any company in the active portfolio to auto-fill research metadata.",
    )

    custom_name = ""
    target_comp = ""
    target_domain = ""
    target_segment = ""

    if selected_comp and selected_comp != "— Select an account from the portfolio —":
        crow = companies_df[companies_df["company_name"] == selected_comp].iloc[0]
        target_comp = selected_comp
        target_domain = crow.get("domain", "") or ""
        target_segment = crow.get("segment", "") or ""
    else:
        st.markdown("##### Or Enter Custom Account Details:")
        c1, c2, c3 = st.columns(3)
        with c1:
            target_comp = st.text_input("Company Name:", placeholder="e.g. Baker Hughes")
        with c2:
            target_domain = st.text_input("Website / Domain:", placeholder="e.g. bakerhughes.com")
        with c3:
            target_segment = st.text_input("Segment / Industry:", placeholder="e.g. Oilfield Services")

    if target_comp.strip():
        render_contact_research_ui(
            company_name=target_comp.strip(),
            website=target_domain.strip(),
            segment=target_segment.strip(),
            key_prefix="page13_interactive",
        )
    else:
        st.info("👆 Select a company above or enter a company name to trigger contact research.")

with tab_colleague_tool:
    st.markdown("### 🌐 Colleague Standalone Tool (DEMO FAST + CACHED)")
    st.caption("Embedded view of `EON_Prospect_Ranker_DEMO_FAST_CACHED.html`. Connects to `http://localhost:8787/api/contact-research`.")

    # Locate colleague HTML file
    candidates = [
        Path(__file__).resolve().parent.parent.parent / "contact_intelligence" / "EON_Prospect_Ranker_DEMO_FAST_CACHED.html",
        Path.home() / "Downloads" / "EON_Contact_Intelligence_Shared_Package" / "EON_Prospect_Ranker_DEMO_FAST_CACHED.html",
    ]
    html_path = None
    for p in candidates:
        if p.exists():
            html_path = p
            break

    if html_path and html_path.exists():
        with open(html_path, "r", encoding="utf-8") as f:
            html_content = f.read()
        components.html(html_content, height=950, scrolling=True)
    else:
        st.error("Could not locate `EON_Prospect_Ranker_DEMO_FAST_CACHED.html`.")
