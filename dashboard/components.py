"""
Reusable UI components, badges, and visual styling for EON Pattern Extractor Dashboard.
Enforces the strict color-coding contract:
  - Green: Valid / Explicit Zero / Reconciled / High Confidence
  - Amber: Missing / Derived Reconciliation / Analyst Assigned / Medium Confidence
  - Red: Discrepancy / Parsing Failed / Ambiguous / Low Confidence / Extraction Review Required
"""

import html
import streamlit as st
import pandas as pd


def render_disclaimer():
    """
    Renders the regulatory evidence-use & non-inference policy notice:
    a clean one-line notice with full policy details in a collapsed expander.
    """
    st.markdown(
        """
        <div style="background-color: rgba(234, 179, 8, 0.08); border-left: 4px solid #eab308; padding: 8px 14px; border-radius: 4px; margin-bottom: 10px;">
            <span style="font-size: 0.83rem; color: #78350f; font-weight: 500;">
                ⚠️ <strong>Evidence-Use Policy</strong>: Absence of regulatory enforcement records does not establish safe operations. Independent verification required.
            </span>
        </div>
        """,
        unsafe_allow_html=True,
    )
    with st.expander("📋 View Full Regulatory Evidence-Use & Non-Inference Policy", expanded=False):
        st.markdown(
            "The absence of regulatory enforcement records (OSHA, CSB, or global equivalents) does **not** establish safe operations. "
            "Publicly written accounts and press signals are unverified third-party disclosures and must be independently confirmed before commercial engagement (**independent verification required**)."
        )


def render_badge(text: str, badge_type: str = "secondary") -> str:
    """
    Generate an HTML badge string with consistent theme styling.
    badge_type: 'green' | 'amber' | 'red' | 'blue' | 'gray'
    """
    styles = {
        "green": "background-color: #dcfce7; color: #166534; border: 1px solid #86efac;",
        "amber": "background-color: #fef3c7; color: #92400e; border: 1px solid #fcd34d;",
        "red": "background-color: #fee2e2; color: #991b1b; border: 1px solid #fca5a5;",
        "blue": "background-color: #e0f2fe; color: #075985; border: 1px solid #7dd3fc;",
        "gray": "background-color: #f3f4f6; color: #374151; border: 1px solid #d1d5db;",
    }
    style = styles.get(badge_type, styles["gray"])
    clean_text = html.escape(str(text))
    return (
        f'<span style="{style} padding: 2px 8px; border-radius: 12px; font-weight: 600; '
        f'font-size: 0.78rem; display: inline-block; white-space: nowrap;">{clean_text}</span>'
    )


def get_status_badge(status: str) -> str:
    """Map validation_status or review flag to styled badge."""
    if not status or pd.isna(status):
        return render_badge("NOT SET", "gray")

    status_str = str(status).strip()
    if status_str in ("VALID", "EXPLICIT_ZERO", "TRUE", "True", "HIGH", "RECONCILED", "PASSED"):
        return render_badge(status_str, "green")
    elif status_str in ("MISSING_NOT_REPORTED", "DERIVED_RECONCILIATION", "MEDIUM", "ANALYST_NORMALIZED"):
        return render_badge(status_str, "amber")
    elif status_str in ("PARSING_FAILED", "AMBIGUOUS", "FALSE", "False", "LOW", "DISCREPANCY", "FAILED"):
        return render_badge(status_str, "red")
    else:
        return render_badge(status_str, "blue")


def render_kpi_card(title: str, value: str, subtitle: str = "", badge_text: str = "", badge_type: str = "gray"):
    """Render a card container for high-level metrics."""
    clean_title = html.escape(str(title))
    clean_value = html.escape(str(value))
    clean_subtitle = html.escape(str(subtitle))
    badge_html = f"<div>{render_badge(badge_text, badge_type)}</div>" if badge_text else ""
    st.markdown(
        f"""
        <div style="background-color: #ffffff; border: 1px solid #e5e7eb; border-radius: 8px; padding: 16px; box-shadow: 0 1px 3px rgba(0,0,0,0.05); margin-bottom: 12px;">
            <div style="font-size: 0.8rem; font-weight: 600; text-transform: uppercase; color: #6b7280; letter-spacing: 0.5px;">{clean_title}</div>
            <div style="display: flex; align-items: baseline; justify-content: space-between; margin-top: 6px;">
                <div style="font-size: 1.75rem; font-weight: 700; color: #111827;">{clean_value}</div>
                {badge_html}
            </div>
            <div style="font-size: 0.78rem; color: #6b7280; margin-top: 4px;">{clean_subtitle}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_download_button(df: pd.DataFrame, filename: str, label: str = "Download Data (CSV)", key: str = None):
    """Render a standardized CSV download button for filtered data."""
    csv_data = df.to_csv(index=False).encode("utf-8")
    st.download_button(
        label=label,
        data=csv_data,
        file_name=filename,
        mime="text/csv",
        key=key,
        help=f"Download {len(df)} filtered row(s) as CSV",
    )


def style_validation_status(val):
    """Pandas styler function for validation status column."""
    if not isinstance(val, str):
        return ""
    v = val.strip().upper()
    if v in ("VALID", "EXPLICIT_ZERO"):
        return "background-color: #dcfce7; color: #166534; font-weight: 600;"
    elif v in ("MISSING_NOT_REPORTED", "DERIVED_RECONCILIATION"):
        return "background-color: #fef3c7; color: #92400e; font-weight: 600;"
    elif v in ("PARSING_FAILED", "AMBIGUOUS", "DISCREPANCY"):
        return "background-color: #fee2e2; color: #991b1b; font-weight: 600;"
    return ""


def style_confidence(val):
    """Pandas styler function for confidence column."""
    if not isinstance(val, str):
        return ""
    v = val.strip().upper()
    if v == "HIGH":
        return "background-color: #dcfce7; color: #166534;"
    elif v == "MEDIUM":
        return "background-color: #fef3c7; color: #92400e;"
    elif v == "LOW":
        return "background-color: #fee2e2; color: #991b1b;"
    return ""
