# =========================================
# REDI ADA SYSTEM — TRUE FINAL (FIXED)
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
st.set_page_config(page_title="REDI ADA System", layout="wide", page_icon="📊")

APP_NAME = "REDI ADA System"
ENABLE_AI = True
AI_CONTAMINATION = 0.02

# =========================================
# STYLING (FIXED VISIBILITY)
# =========================================
st.markdown("""
<style>
.stApp {background: linear-gradient(135deg,#f3f7ff,#dbeafe);}
section[data-testid="stSidebar"] {background:#1e3a8a !important;}
section[data-testid="stSidebar"] * {color:white !important;}

section[data-testid="stSidebar"] input {
    background:white !important;
    color:black !important;
    font-weight:700 !important;
    border-radius:8px !important;
}

section[data-testid="stSidebar"] .stDateInput input {
    color:black !important;
}

.kpi-card {
    padding:20px;border-radius:14px;color:white;text-align:center;
}

.btn-green {background:#16a34a;color:white;padding:12px;border-radius:10px;}
.btn-red {background:#dc2626;color:white;padding:12px;border-radius:10px;}
.btn-blue {background:#2563eb;color:white;padding:12px;border-radius:10px;}
.btn-purple {background:#7c3aed;color:white;padding:12px;border-radius:10px;}
</style>
""", unsafe_allow_html=True)

# =========================================
# LOGGING
# =========================================
os.makedirs("logs", exist_ok=True)
logging.basicConfig(filename="logs/redi.log", level=logging.ERROR)

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
# TOKEN
# =========================================
KOBO_TOKEN = st.secrets.get("KOBO_TOKEN")

if not KOBO_TOKEN:
    st.error("Missing KoBo API token")
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
# FETCH (FIXED PAGINATION)
# =========================================
@st.cache_data(ttl=60)
def fetch(uid, token):

    if not uid:
        return pd.DataFrame()

    headers = {"Authorization": f"Token {token}"}
    base_url = f"https://kf.kobotoolbox.org/api/v2/assets/{uid}/data/"
    params = {"format": "json", "page_size": 1000}

    all_data = []
    next_url = base_url

    while next_url:
        try:
            r = requests.get(next_url, headers=headers, params=params, timeout=60)

            if r.status_code != 200:
                break

            data = r.json()
            all_data.extend(data.get("results", []))

            next_url = data.get("next")
            params = None

        except:
            break

    return pd.json_normalize(all_data)

# =========================================
# LOAD
# =========================================
df = fetch(FORM_UID, KOBO_TOKEN)

if df.empty:
    st.warning("No data found")
    st.stop()

# =========================================
# DATE FILTER
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
    c1,c2 = st.sidebar.columns(2)

    start = c1.date_input("Start", df[DATE_COL].min())
    end = c2.date_input("End", df[DATE_COL].max())

    df = df[(df[DATE_COL]>=pd.to_datetime(start)) &
            (df[DATE_COL]<=pd.to_datetime(end))]

# =========================================
# NUMERIC
# =========================================
num_cols = df.select_dtypes(include=["number"]).columns

# =========================================
# STAT ANOMALY (FIXED)
# =========================================
if len(num_cols)>0:
    std = df[num_cols].std().replace(0,1)
    z = np.abs((df[num_cols]-df[num_cols].mean())/std)
    df["anomaly_flag"] = (z > 2.5).any(axis=1)
else:
    df["anomaly_flag"] = False

# =========================================
# AI
# =========================================
if ENABLE_AI and len(num_cols)>2:
    model = IsolationForest(contamination=AI_CONTAMINATION, random_state=42)
    df["ai_flag"] = model.fit_predict(df[num_cols].fillna(0)) == -1
else:
    df["ai_flag"] = False

# =========================================
# QUALITATIVE (FIXED MATCHING)
# =========================================
df["qualitative_flag"] = False
df["qualitative_issue"] = ""

required = ["name","age","gender","region"]

for col in df.columns:
    if any(r in col.lower() for r in required):
        mask = df[col].isna() | (df[col].astype(str).str.strip()=="")
        df.loc[mask,"qualitative_flag"] = True
        df.loc[mask,"qualitative_issue"] += f"Missing {col}; "

bad = ["asdf","test","xxx","n/a","unknown"]

for col in df.select_dtypes(include="object"):
    mask = df[col].astype(str).str.lower().isin(bad)
    df.loc[mask,"qualitative_flag"] = True
    df.loc[mask,"qualitative_issue"] += f"Bad text {col}; "

# =========================================
# FINAL FLAG LOGIC (FIXED)
# =========================================
df["final_flag"] = (
    df["qualitative_flag"] |
    df["anomaly_flag"] |
    df["ai_flag"]
)

# =========================================
# WHY FLAGGED
# =========================================
def explain(r):
    reasons=[]
    if r["qualitative_flag"]:
        reasons.append(r["qualitative_issue"])
    if r["anomaly_flag"]:
        reasons.append("Stat anomaly")
    if r["ai_flag"]:
        reasons.append("AI anomaly")
    return " | ".join(reasons) if reasons else "No issues"

df["why_flagged"] = df.apply(explain, axis=1)

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

    c1,c2,c3,c4 = st.columns(4)

    c1.markdown(f"<div class='kpi-card' style='background:#2563eb'><h3>Total</h3><h1>{total}</h1></div>",unsafe_allow_html=True)
    c2.markdown(f"<div class='kpi-card' style='background:#16a34a'><h3>Valid</h3><h1>{valid}</h1></div>",unsafe_allow_html=True)
    c3.markdown(f"<div class='kpi-card' style='background:#dc2626'><h3>Flagged</h3><h1>{bad}</h1></div>",unsafe_allow_html=True)
    c4.markdown(f"<div class='kpi-card' style='background:#7c3aed'><h3>Score</h3><h1>{score:.1f}%</h1></div>",unsafe_allow_html=True)

# =========================================
# EXPLORER
# =========================================
elif page=="Explorer":
    t1,t2 = st.tabs(["Clean","Flagged"])

    with t1:
        st.dataframe(clean, use_container_width=True)

    with t2:
        st.dataframe(flag, use_container_width=True)

# =========================================
# QUALITY ANALYTICS
# =========================================
elif page=="Quality Analytics":
    summary = pd.DataFrame({
        "Category":["Quantitative","Qualitative"],
        "Count":[
            int(df["anomaly_flag"].sum()+df["ai_flag"].sum()),
            int(df["qualitative_flag"].sum())
        ]
    })
    st.dataframe(summary)
    st.plotly_chart(px.pie(summary,names="Category",values="Count"))

# =========================================
# DOWNLOADS (FULL)
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

    c1,c2,c3 = st.columns(3)

    c1.download_button("Clean",to_excel(clean),"clean.xlsx")
    c2.download_button("Flagged",to_excel(flag),"flagged.xlsx")
    c3.download_button("Full",full_excel(),"full.xlsx")

# =========================================
# FOOTER
# =========================================
st.caption(f"{APP_NAME} | {datetime.now()}")
