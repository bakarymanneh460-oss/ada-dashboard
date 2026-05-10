# =========================================
# REDI AUTOMATED DATA QUALITY MONITORING SYSTEM
# TRUE FINAL VERSION (STABLE)
# =========================================

import streamlit as st
import pandas as pd
import io
import requests
import numpy as np
import os
import logging
import yaml
import streamlit_authenticator as stauth

from yaml.loader import SafeLoader
from datetime import datetime
from sklearn.ensemble import IsolationForest

from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet

import plotly.express as px

# =========================================
# CONFIG
# =========================================
st.set_page_config(
    page_title="REDI Automated Data Quality Monitoring System",
    layout="wide",
    page_icon="📊"
)

# ✅ FIXED (this was missing before)
APP_NAME = "REDI Automated Data Quality Monitoring System"

# =========================================
# STYLING
# =========================================
st.markdown("""
<style>
.stApp {background: linear-gradient(135deg,#f3f7ff,#dbeafe);}
section[data-testid="stSidebar"] {background:#1e3a8a !important;}
section[data-testid="stSidebar"] * {color:white !important;}
section[data-testid="stSidebar"] input {
    background:white !important; color:black !important; font-weight:700 !important;
}
section[data-testid="stSidebar"] .stDateInput input {color:black !important;}

.kpi-card {padding:20px;border-radius:14px;color:white;text-align:center;}

.btn-blue {background:#2563eb;color:white;padding:12px;border-radius:10px;}
.btn-green {background:#16a34a;color:white;padding:12px;border-radius:10px;}
.btn-red {background:#dc2626;color:white;padding:12px;border-radius:10px;}
.btn-purple {background:#7c3aed;color:white;padding:12px;border-radius:10px;}
</style>
""", unsafe_allow_html=True)

# =========================================
# AUTH
# =========================================
with open("config.yaml") as file:
    config = yaml.load(file, Loader=SafeLoader)

authenticator = stauth.Authenticate(
    config["credentials"],
    config["cookie"]["name"],
    config["cookie"]["key"],
    config["cookie"]["expiry_days"]
)

authenticator.login()

auth = st.session_state.get("authentication_status")
username = st.session_state.get("username")
name = st.session_state.get("name")

if auth is False:
    st.error("Incorrect username or password")
    st.stop()

if auth is None:
    st.warning("Please login")
    st.stop()

authenticator.logout("Logout", "sidebar")

st.sidebar.success(f"Welcome {name}")
role = config["credentials"]["usernames"][username]["role"]
st.sidebar.info(f"Role: {role}")

# =========================================
# KOBO TOKEN
# =========================================
KOBO_TOKEN = st.secrets.get("KOBO_TOKEN")
if not KOBO_TOKEN:
    st.error("Missing KoBo token")
    st.stop()

# =========================================
# SIDEBAR
# =========================================
st.sidebar.title("📊 REDI ADA System")
FORM_UID = st.sidebar.text_input("KoBo Form UID")

pages = ["Dashboard","Explorer","Quality Analytics","Downloads"]
if role == "enumerator":
    pages = ["Dashboard","Explorer"]
elif role == "supervisor":
    pages = ["Dashboard","Explorer","Quality Analytics"]

page = st.sidebar.radio("Navigation", pages)

# =========================================
# FETCH (FULL PAGINATION)
# =========================================
@st.cache_data(ttl=60)
def fetch(uid, token):
    if not uid:
        return pd.DataFrame()

    headers = {"Authorization": f"Token {token}"}
    url = f"https://kf.kobotoolbox.org/api/v2/assets/{uid}/data/"
    params = {"format":"json","page_size":1000}

    all_data = []
    while url:
        r = requests.get(url, headers=headers, params=params)
        data = r.json()
        all_data.extend(data.get("results", []))
        url = data.get("next")
        params = None

    return pd.json_normalize(all_data)

df = fetch(FORM_UID, KOBO_TOKEN)

if df.empty:
    st.warning("No data found")
    st.stop()

# =========================================
# DATE FILTER (FIXED — NO DATA LOSS)
# =========================================
def detect(names):
    for c in df.columns:
        for n in names:
            if n in c.lower():
                return c
    return None

DATE_COL = detect(["submission_time","date","time"])
if "_submission_time" in df.columns:
    DATE_COL = "_submission_time"

if DATE_COL:
    df[DATE_COL] = pd.to_datetime(df[DATE_COL], errors="coerce")

    st.sidebar.subheader("Filters")
    c1, c2 = st.sidebar.columns(2)

    start = c1.date_input("Start", df[DATE_COL].min())
    end = c2.date_input("End", df[DATE_COL].max())

    mask = (
        (df[DATE_COL] >= pd.to_datetime(start)) &
        (df[DATE_COL] <= pd.to_datetime(end))
    )

    # ✅ KEY FIX: keep missing dates
    df = df[mask | df[DATE_COL].isna()]

# =========================================
# ANOMALY
# =========================================
num_cols = df.select_dtypes(include="number").columns

if len(num_cols)>0:
    z = np.abs((df[num_cols]-df[num_cols].mean())/df[num_cols].std().replace(0,1))
    df["anomaly_flag"] = (z > 2.5).any(axis=1)
else:
    df["anomaly_flag"] = False

# =========================================
# AI
# =========================================
if len(num_cols)>2:
    model = IsolationForest(contamination=0.02)
    df["ai_flag"] = model.fit_predict(df[num_cols].fillna(0))==-1
else:
    df["ai_flag"] = False

# =========================================
# QUALITATIVE
# =========================================
df["qualitative_flag"] = False
df["qualitative_issue"] = ""

for col in df.columns:
    if any(k in col.lower() for k in ["name","age","gender"]):
        mask = df[col].isna() | (df[col].astype(str).str.strip()=="")
        df.loc[mask,"qualitative_flag"]=True
        df.loc[mask,"qualitative_issue"]+=f"Missing {col}; "

# =========================================
# FINAL FLAG
# =========================================
df["final_flag"] = df["qualitative_flag"] | df["anomaly_flag"] | df["ai_flag"]

# WHY FLAGGED
df["why_flagged"] = df.apply(
    lambda r: " | ".join(filter(None,[
        r["qualitative_issue"] if r["qualitative_flag"] else "",
        "Stat anomaly" if r["anomaly_flag"] else "",
        "AI anomaly" if r["ai_flag"] else ""
    ])) or "No issues", axis=1
)

# =========================================
# SPLIT
# =========================================
clean = df[~df["final_flag"]]
flag = df[df["final_flag"]]

total=len(df)
valid=len(clean)
bad=len(flag)
score=(valid/total)*100 if total else 0

# =========================================
# DASHBOARD
# =========================================
if page=="Dashboard":
    st.title(APP_NAME)

    c1,c2,c3,c4=st.columns(4)

    c1.markdown(f"<div class='kpi-card' style='background:#2563eb'><h3>Total</h3><h1>{total}</h1></div>",unsafe_allow_html=True)
    c2.markdown(f"<div class='kpi-card' style='background:#16a34a'><h3>Valid</h3><h1>{valid}</h1></div>",unsafe_allow_html=True)
    c3.markdown(f"<div class='kpi-card' style='background:#dc2626'><h3>Flagged</h3><h1>{bad}</h1></div>",unsafe_allow_html=True)
    c4.markdown(f"<div class='kpi-card' style='background:#7c3aed'><h3>Score</h3><h1>{score:.1f}%</h1></div>",unsafe_allow_html=True)

# =========================================
# EXPLORER
# =========================================
elif page=="Explorer":
    t1,t2=st.tabs(["Clean","Flagged"])
    with t1: st.dataframe(clean)
    with t2: st.dataframe(flag)

# =========================================
# QUALITY ANALYTICS
# =========================================
elif page=="Quality Analytics":
    summary=pd.DataFrame({
        "Category":["Quantitative","Qualitative"],
        "Count":[int(df["anomaly_flag"].sum()+df["ai_flag"].sum()),
                 int(df["qualitative_flag"].sum())]
    })
    st.dataframe(summary)
    st.plotly_chart(px.pie(summary,names="Category",values="Count"))

# =========================================
# DOWNLOADS
# =========================================
elif page=="Downloads":

    def to_excel(d):
        o=io.BytesIO()
        with pd.ExcelWriter(o,engine="openpyxl") as w:
            d.to_excel(w,index=False)
        o.seek(0)
        return o

    def full_excel():
        o=io.BytesIO()
        with pd.ExcelWriter(o,engine="openpyxl") as w:
            clean.to_excel(w,index=False,sheet_name="Clean")
            flag.to_excel(w,index=False,sheet_name="Flagged")
        o.seek(0)
        return o

    def pdf():
        b=io.BytesIO()
        doc=SimpleDocTemplate(b)
        styles=getSampleStyleSheet()
        elems=[Paragraph("REDI Report",styles["Title"]),Spacer(1,12)]

        data=[["Metric","Value"],["Total",total],["Valid",valid],["Flagged",bad]]
        t=Table(data)
        t.setStyle(TableStyle([("GRID",(0,0),(-1,-1),1,colors.black)]))
        elems.append(t)

        doc.build(elems)
        b.seek(0)
        return b

    c1,c2,c3,c4=st.columns(4)

    with c1:
        st.markdown('<div class="btn-blue">📊 Full Dataset</div>',True)
        st.download_button("Download",full_excel(),"full.xlsx")

    with c2:
        st.markdown('<div class="btn-green">✅ Clean Data</div>',True)
        st.download_button("Download",to_excel(clean),"clean.xlsx")

    with c3:
        st.markdown('<div class="btn-red">⚠️ Flagged Data</div>',True)
        st.download_button("Download",to_excel(flag),"flagged.xlsx")

    with c4:
        st.markdown('<div class="btn-purple">📄 PDF Report</div>',True)
        st.download_button("Download",pdf(),"report.pdf")

# =========================================
# FOOTER
# =========================================
st.caption(f"{APP_NAME} | {datetime.now()}")
