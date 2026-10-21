"""Enriched portfolio explorer based on the supplied 788-record Focus Finder overlay.
This is separate from the original Wingman 785-account transactional workspace.
"""
import json
from pathlib import Path
import pandas as pd
import streamlit as st
from dashboard.theme import hero

DATA_FILE = Path(__file__).resolve().parents[2] / "data" / "focus-dataset.json"

@st.cache_data(show_spinner=False)
def load_portfolio():
    data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    records = data.get("records", [])
    if len(records) != 788:
        st.warning(f"Dataset has {len(records)} records; expected 788. Verify data/focus-dataset.json.")
    return data, records

def val(x):
    return "Not available from verified source" if x is None or x == "" else str(x)

def show_dossier(r):
    st.markdown('<div class="eon-section">Company dossier</div>',unsafe_allow_html=True)
    st.subheader(r.get("company", "Company dossier"))
    st.caption(f"Portfolio snapshot: 2026-09-17 · research overlay may have newer dates · Source: focus-dataset.json")
    a,b,c,d = st.columns(4)
    a.metric("Focus score", val(r.get("score")))
    b.metric("Portfolio tier", val(r.get("tier")))
    c.metric("Trigger types", r.get("n_types", 0))
    d.metric("Signal events", r.get("n_events", 0))
    if r.get("domain"):
        st.link_button("Visit company website ↗", "https://"+r["domain"].replace("https://", "").replace("http://", ""))
    t1,t2,t3,t4=st.tabs(["Commercial signals & takeaway", "Decision-maker contacts", "Company profile", "Score & evidence"])
    with t1:
        st.markdown("**Signals**")
        types=r.get("types") or []
        st.write(", ".join(types) if types else "No current verified signal types in supplied record")
        st.markdown("**Evidence excerpts from dataset**")
        for item in r.get("signals_sample") or []: st.info(item)
        st.markdown("**Recent researched updates**")
        updates=r.get("recent_updates") or []
        if not updates: st.caption("No recent researched updates recorded.")
        for u in updates:
            st.markdown(f"**{u.get('headline','Update')}** — {u.get('date','Date unavailable')}")
            st.write(u.get("summary", ""))
            if u.get("source_url"): st.link_button("Evidence source ↗",u["source_url"])
        st.markdown("**Suggested next actions**")
        for action in r.get("actions") or []: st.write("• "+action)
    with t2:
        st.caption("Suggested contacts are not necessarily verified training buyers. Confirm role and current employment before outreach.")
        st.write("Contact research status:", val(r.get("contacts_status")))
        contacts=r.get("suggested_contacts") or []
        if not contacts: st.warning("No named suggested contacts found in this record.")
        for c in contacts:
            st.markdown(f"**{val(c.get('name'))}** — {val(c.get('title'))}")
            st.caption(f"Evidence: {val(c.get('evidence'))} · {val(c.get('evidence_note'))}")
            if c.get("source_url"): st.link_button("Open contact evidence ↗", c["source_url"])
        st.write("Buyer persona:",val(r.get("persona")))
    with t3:
        left,right=st.columns(2)
        for lbl,key in [("Segment","segment"),("Subvertical","subvertical"),("Headquarters","hq"),("Revenue","revenue"),("Fiscal year","revenue_fy")]: left.write(f"**{lbl}:** {val(r.get(key))}")
        for lbl,key in [("Employees","employees"),("Training evidence","training"),("Safety evidence","safety"),("Expansion evidence","expansion"),("Business model review flag","profile_review")]: right.write(f"**{lbl}:** {val(r.get(key))}")
        st.caption("SEC statutory verification remains in the original Company Browser. This overlay does not invent filing values.")
    with t4:
        st.write("**Original Focus Score breakdown (not independently recalculated)**")
        parts=r.get("parts") or {}
        if parts: st.dataframe(pd.DataFrame([{"Component":k,"Points":v} for k,v in parts.items()]),hide_index=True,use_container_width=True)
        st.caption("Focus Score is the supplied portfolio metric. Fit and Readiness below are provisional analytical lenses, not trained purchase probabilities.")
        st.write("**Source events / score explanation**")
        st.write(f"Latest baseline trigger: {val(r.get('latest'))}")

def fit_score(r):
    return max(0,min(100,25*str(r.get('training','')).lower().startswith('yes')+25*str(r.get('safety','')).lower().startswith('yes')+20*str(r.get('expansion','')).lower().startswith('yes')+15*bool(r.get('subvertical'))+15*bool(r.get('enriched'))-30*bool(r.get('profile_review'))))

def readiness_score(r):
    p=r.get('parts') or {}
    return round(max(0,min(100,(float(p.get('tier') or 0)+float(p.get('signals') or 0))/59*100)))

hero("EON / Commercial intelligence", "Portfolio & Company Dossiers", "Explore 788 enriched accounts, compare buying signals, and open evidence-backed company dossiers. The research overlay is separate from the original Wingman workspace.")
data,records=load_portfolio()
rows=[]
for r in records:
    rows.append({"Company":r.get("company",""),"Tier":r.get("tier"),"Focus Score":r.get("score"),"Fit (provisional)":fit_score(r),"Readiness (provisional)":readiness_score(r),"Subvertical":r.get("subvertical") or "Unclassified","Trigger types":r.get("n_types",0),"Buyer status":r.get("contacts_status") or "Unknown"})
df=pd.DataFrame(rows)
co1,co2,co3,co4=st.columns(4)
co1.metric("Accounts",len(df))
co2.metric("With Focus Score",int(df["Focus Score"].notna().sum()))
co3.metric("Tier 1",int((df["Tier"]==1).sum()))
co4.metric("Named buyer candidates",sum(bool(r.get("suggested_contacts")) for r in records))
st.markdown('<div class="eon-section">Explore accounts</div>',unsafe_allow_html=True)
query=st.text_input("Search accounts",placeholder="Search company, subvertical, or buyer research status…")
c1,c2=st.columns(2)
with c1: tiers=st.multiselect("Tier",sorted(df["Tier"].dropna().unique().tolist()),default=[])
with c2: status=st.selectbox("Buyer status",["All"]+sorted(df["Buyer status"].dropna().unique().tolist()))
filtered=df.copy()
if query:
    filtered=filtered[filtered[["Company","Subvertical","Buyer status"]].astype(str).apply(lambda x:x.str.contains(query,case=False,regex=False)).any(axis=1)]
if tiers: filtered=filtered[filtered["Tier"].isin(tiers)]
if status!="All": filtered=filtered[filtered["Buyer status"]==status]
filtered=filtered.sort_values("Focus Score",ascending=False,na_position="last")
st.caption(f"Showing {len(filtered)} of {len(df)} records. Click a company using the selector below to open its dossier.")
st.caption("Select a row to open its dossier, or use the company picker beneath the table.")
selection=st.dataframe(filtered,use_container_width=True,hide_index=True,height=380,
    on_select="rerun",selection_mode="single-row",key="eon_portfolio_grid",
    column_config={"Focus Score":st.column_config.ProgressColumn("Focus Score",min_value=0,max_value=100,format="%d"),
                   "Fit (provisional)":st.column_config.ProgressColumn("Fit · provisional",min_value=0,max_value=100,format="%d"),
                   "Readiness (provisional)":st.column_config.ProgressColumn("Readiness · provisional",min_value=0,max_value=100,format="%d")})
options=filtered["Company"].tolist()
selected_rows=selection.selection.rows if selection is not None else []
selected_from_grid=options[selected_rows[0]] if selected_rows and selected_rows[0]<len(options) else None
left,right=st.columns([3,1])
with left:
    selected=st.selectbox("Company dossier",options,index=(options.index(selected_from_grid) if selected_from_grid in options else 0) if options else None,placeholder="Choose a company") if options else None
with right:
    st.write("")
    st.write("")
    st.download_button("↓ Export filtered CSV",filtered.to_csv(index=False).encode("utf-8"),"eon_portfolio_filtered.csv","text/csv",use_container_width=True)
st.divider()
if selected:
    rec=next((r for r in records if r.get("company")==selected),None)
    if rec: show_dossier(rec)
st.divider()
st.info("For original detailed SEC intelligence, live governance and original Ask EON conversation, use the **Company Browser (Original)** and **Ask EON** pages from the navigation. Their data source remains the original Wingman export; this 788-company overlay is separate.")
