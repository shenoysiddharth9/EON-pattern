"""Shared non-invasive Streamlit UI shell; never changes analysis or extraction logic."""
import streamlit as st

CSS = r"""
<style>
:root { --eon-accent:#47d7c5; --eon-blue:#64aaff; }
[data-testid="stAppViewContainer"] {background: radial-gradient(ellipse at 85% -15%, rgba(30,71,109,.25), transparent 42%), #0b1018;}
[data-testid="stHeader"] {background: rgba(11,16,24,.80);backdrop-filter:blur(12px);}
[data-testid="stSidebar"] {background: #101925;border-right:1px solid #243244;}
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p {color:#a9bacb;}
[data-testid="stSidebarNav"] a {border-radius:10px;margin:3px 5px;}
[data-testid="stSidebarNav"] a[aria-current="page"] {background:#17384a;color:#d9fff8;}
.block-container {padding-top:1.8rem;max-width:1520px;padding-bottom:5rem;}
h1,h2,h3 {letter-spacing:-.025em;}
h1 {font-size:clamp(1.85rem,3vw,2.7rem)!important;font-weight:760!important;}
h2 {font-size:1.45rem!important;}
[data-testid="stMetric"] {background:linear-gradient(145deg,#172335,#111c29);border:1px solid #2a3b4d;border-radius:16px;padding:18px 20px;min-height:116px;}
[data-testid="stMetricLabel"] {color:#b3c3d1;}
[data-testid="stMetricValue"] {color:#effffb;letter-spacing:-.03em;}
[data-testid="stDataFrame"], [data-testid="stTable"], [data-testid="stVerticalBlockBorderWrapper"] {border-radius:13px;}
[data-testid="stTabs"] [data-baseweb="tab-list"] {gap:8px;border-bottom:1px solid #2e4050;}
[data-testid="stTabs"] button {border-radius:9px 9px 0 0;padding:10px 15px;}
[data-testid="stTabs"] button[aria-selected="true"] {color:#71ead9;border-bottom:2px solid #47d7c5;}
.stButton button[kind="primary"], [data-testid="stDownloadButton"] button {border-radius:10px;font-weight:650;}
[data-testid="stTextInput"] input, [data-testid="stSelectbox"]>div, [data-testid="stMultiSelect"]>div {border-radius:10px;}
a {text-underline-offset:3px;}
.eon-hero {padding:24px 26px;border-radius:18px;background:linear-gradient(115deg,#15394b 0%,#14263c 60%,#152036 100%);border:1px solid #315769;margin-bottom:23px;}
.eon-eyebrow {font-size:.76rem;letter-spacing:.14em;text-transform:uppercase;color:#7ce6d6;font-weight:800;}
.eon-hero h1 {margin:7px 0 8px;color:#f0fffc;}
.eon-hero p {color:#bad0da;margin:0;max-width:920px;line-height:1.55;}
.eon-section {font-weight:730;font-size:1.14rem;letter-spacing:-.015em;margin:14px 0;}
.eon-note {border:1px solid #355064;background:#122435;border-radius:12px;padding:12px 16px;color:#c9dce6;font-size:.9rem;}
</style>
"""

def apply_theme():
    st.markdown(CSS,unsafe_allow_html=True)

def hero(eyebrow,title,description):
    import html
    st.markdown(f'<div class="eon-hero"><div class="eon-eyebrow">{html.escape(eyebrow)}</div><h1>{html.escape(title)}</h1><p>{html.escape(description)}</p></div>',unsafe_allow_html=True)
