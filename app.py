# =========================================
# REDI AUTOMATED DATA QUALITY MONITORING SYSTEM
# FINAL PRODUCTION VERSION (CLEAN + FIXED)
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
# PAGE CONFIG
# =========================================
st.set_page_config(
    page_title="REDI Data Quality System",
    layout="wide",
    page_icon="📊"
)

# =========================================
# STYLE (SIMPLIFIED BLUE UI)
# =========================================
st.markdown("""
<style>
.stApp {
    background: linear-gradient(135deg,#1e3a8a,#2563eb);
}

section[data-testid="stSidebar"] {
    background-color:#1e3a8a !important;
}

section[data-testid="stSidebar"] * {
    color:white !important;
}

section[data-testid="stSidebar"] input {
    background:white !important;
    color:black !important;
    font-weight:700 !important;
    border-radius:8px !important;
}

.kpi-card {
    padding:20px;
    border-radius:14px;
    color:white;
    text-align:center;
    box-shadow:0 4px 10px rgba(0,0,0,0.2);
}

.btn-green {background:#16a34a;color:white;padding:10px;border-radius:8px;font-weight:bold;}
.btn-red {background:#dc2626;color:white;padding:10px;border-radius:8px;font-weight:bold;}
.btn-blue {background:#2563eb;color:white;padding:10px;border-radius:8px;font-weight:bold;}
</style>
""", unsafe_allow_html=True)

# =========================================
# CONFIG
# =========================================
APP_NAME = "REDI Data Quality Monitoring System"

ENABLE_AI = True
AI_CONTAMINATION = 0.01

# =========================================
# LOGGING
# =========================================
os.makedirs("logs", exist_ok=True)
logging.basicConfig(filename="logs/app.log", level=logging.ERROR)

# =========================================
# AUTH (SAFE)
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

name = st.session_state.get("name")
status = st.session_state.get("authentication_status")
username = st.session_state.get("username")

if status is False:
    st.error("Wrong login")
    st.stop()
if status is None:
    st.warning("Login required")
    st.stop()

authenticator.logout("Logout","sidebar")

role = config["credentials"]["usernames"][username]["role"]

st.sidebar.success(f"Welcome {name}")
st.sidebar.info(f"Role: {role}")

# =========================================
# DATA INPUT
# =========================================
FORM_UID = st.sidebar.text_input("Kobo Form UID")

KOBO_TOKEN = st.secrets.get("KOBO_TOKEN", None)

# =========================================
# FETCH DATA
# =========================================
@st.cache_data(ttl=120)
def fetch_data(uid, token):

    if not uid:
        return pd.DataFrame()

    headers = {"Authorization": f"Token {token}"} if token else {}
    url = f"https://kf.kobotoolbox.org/api/v2/assets/{uid}/data/?format=json&page_size=1000"

    out = []

    while url:
        r = requests.get(url, headers=headers)
        if r.status_code != 200:
            break
        js = r.json()
        out.extend(js.get("results", []))
        url = js.get("next")

    return pd.json_normalize(out)

df = fetch_data(FORM_UID, KOBO_TOKEN)

if df.empty:
    st.warning("No data found")
    st.stop()

# =========================================
# COLUMN DETECTION
# =========================================
def detect(keys):
    for c in df.columns:
        for k in keys:
            if k in c.lower():
                return c
    return None

DATE_COL = detect(["submission","date","time"])
ENUM_COL = detect(["enum","interviewer","user"])
REGION_COL = detect(["region","district"])
HH_COL = detect(["hh","household"])

if "_submission_time" in df.columns:
    DATE_COL = "_submission_time"

if DATE_COL:
    df[DATE_COL] = pd.to_datetime(df[DATE_COL], errors="coerce")

# =========================================
# FILTERS
# =========================================
if DATE_COL:
    c1,c2 = st.sidebar.columns(2)
    start = c1.date_input("Start", df[DATE_COL].min())
    end = c2.date_input("End", df[DATE_COL].max())

    df = df[(df[DATE_COL]>=pd.to_datetime(start)) &
            (df[DATE_COL]<=pd.to_datetime(end))]

# =========================================
# MONTH
# =========================================
if DATE_COL:
    df["Month"] = df[DATE_COL].dt.to_period("M").astype(str)

# =========================================
# NUMERIC COLUMNS
# =========================================
num_cols = df.select_dtypes(include=["number"]).columns

# =========================================
# QUANTITATIVE ANOMALY ONLY (FIXED)
# =========================================
if len(num_cols) > 0:
    std = df[num_cols].std().replace(0,1)
    z = np.abs((df[num_cols] - df[num_cols].mean())/std)

    df["quant_anomaly"] = z.max(axis=1) > 4.5
else:
    df["quant_anomaly"] = False

# =========================================
# AI ANOMALY
# =========================================
if ENABLE_AI and len(num_cols) > 2:
    try:
        model = IsolationForest(contamination=AI_CONTAMINATION, random_state=42)
        df["ai_flag"] = model.fit_predict(df[num_cols].fillna(0)) == -1
    except:
        df["ai_flag"] = False
else:
    df["ai_flag"] = False

# =========================================
# QUALITATIVE RULE ENGINE (NEW)
# =========================================
text_cols = df.select_dtypes(include=["object"]).columns

def text_quality_checks(row):
    issues = 0

    # required field check
    for c in text_cols:
        if pd.isna(row[c]) or str(row[c]).strip() == "":
            issues += 1

    # spelling / inconsistency heuristic (simple version)
    for c in text_cols:
        val = str(row[c]).lower()
        if len(val) > 0 and ("???", "asdf", "1234") in val:
            issues += 1

    return issues

if len(text_cols) > 0:
    df["qual_issue_count"] = df.apply(text_quality_checks, axis=1)
    df["qual_flag"] = df["qual_issue_count"] > 0
else:
    df["qual_flag"] = False

# =========================================
# FINAL FLAG LOGIC (ONLY QUAL + QUANT)
# =========================================
df["flag_score"] = (
    df["quant_anomaly"].astype(int) +
    df["ai_flag"].astype(int) +
    df["qual_flag"].astype(int)
)

df["final_flag"] = df["flag_score"] >= 2

# =========================================
# CLEAN / FLAGGED
# =========================================
clean_df = df[~df["final_flag"]]
flag_df = df[df["final_flag"]]

total = len(df)
valid = len(clean_df)
bad = len(flag_df)

score = (valid/total*100) if total else 0

# =========================================
# DASHBOARD
# =========================================
if role != "enumerator":

    st.title(APP_NAME)

    c1,c2,c3,c4 = st.columns(4)

    c1.markdown(f'<div class="kpi-card" style="background:#2563eb"><h3>Total</h3><h1>{total}</h1></div>', unsafe_allow_html=True)
    c2.markdown(f'<div class="kpi-card" style="background:#16a34a"><h3>Valid</h3><h1>{valid}</h1></div>', unsafe_allow_html=True)
    c3.markdown(f'<div class="kpi-card" style="background:#dc2626"><h3>Flagged</h3><h1>{bad}</h1></div>', unsafe_allow_html=True)
    c4.markdown(f'<div class="kpi-card" style="background:#7c3aed"><h3>Score</h3><h1>{score:.1f}%</h1></div>', unsafe_allow_html=True)

    st.subheader("Quality Overview")

    st.bar_chart(pd.DataFrame({"Valid":[valid],"Flagged":[bad]}))

# =========================================
# EXPLORER
# =========================================
if role != "enumerator" and st.sidebar.radio("Nav",["Dashboard","Explorer"])=="Explorer":

    st.title("Explorer")

    tab1,tab2 = st.tabs(["Clean","Flagged"])

    with tab1:
        st.dataframe(clean_df)

    with tab2:
        st.dataframe(flag_df)

# =========================================
# DOWNLOADS
# =========================================
if role == "supervisor":

    st.title("Downloads")

    def to_excel(d):
        b = io.BytesIO()
        with pd.ExcelWriter(b, engine="openpyxl") as w:
            d.to_excel(w,index=False)
        return b

    st.download_button("Clean", to_excel(clean_df), "clean.xlsx")
    st.download_button("Flagged", to_excel(flag_df), "flagged.xlsx")

# =========================================
# FOOTER
# =========================================
st.caption(f"{APP_NAME} | Updated {datetime.now()}")
