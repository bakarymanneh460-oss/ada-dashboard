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

from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle
)

from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet

import plotly.express as px

# =========================================
# PAGE CONFIG
# =========================================
st.set_page_config(
    page_title="REDI Automated Data Quality Monitoring System",
    layout="wide",
    page_icon="📊"
)

# =========================================
# FULL STYLING (LIGHT BLUE THEME)
# =========================================
st.markdown("""
<style>

.stApp {
    background: linear-gradient(135deg, #f3f7ff, #dbeafe);
}

[data-testid="stForm"] {
    background-color: white;
    padding: 40px;
    border-radius: 18px;
    box-shadow: 0 6px 18px rgba(0,0,0,0.15);
}

input {
    border-radius: 8px !important;
}

button[kind="primary"] {
    background-color: #1e3a8a !important;
    color: white !important;
    border-radius: 10px !important;
    font-weight: bold !important;
}

section[data-testid="stSidebar"] {
    background-color:#1e3a8a !important;
}

section[data-testid="stSidebar"] * {
    color:white !important;
}

.kpi-card {
    padding:20px;
    border-radius:14px;
    color:white;
    text-align:center;
    box-shadow:0 4px 10px rgba(0,0,0,0.2);
}

.btn-green {background:#16a34a;color:white;padding:12px;border-radius:10px;}
.btn-red {background:#dc2626;color:white;padding:12px;border-radius:10px;}
.btn-blue {background:#2563eb;color:white;padding:12px;border-radius:10px;}
.btn-purple {background:#7c3aed;color:white;padding:12px;border-radius:10px;}

</style>
""", unsafe_allow_html=True)

# =========================================
# CONFIG
# =========================================
APP_NAME = "REDI Automated Data Quality Monitoring System"
ENABLE_AI = True
AI_CONTAMINATION = 0.005

# =========================================
# LOGGING
# =========================================
os.makedirs("logs", exist_ok=True)

logging.basicConfig(
    filename="logs/redi.log",
    level=logging.ERROR,
    format="%(asctime)s %(levelname)s %(message)s"
)

# =========================================
# AUTHENTICATION
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
authentication_status = st.session_state.get("authentication_status")
username = st.session_state.get("username")

if authentication_status is False:
    st.error("Incorrect username or password")
    st.stop()

if authentication_status is None:
    st.warning("Please login")
    st.stop()

authenticator.logout("Logout", "sidebar")

role = config["credentials"]["usernames"][username]["role"]

st.sidebar.success(f"Welcome {name}")
st.sidebar.info(f"Role: {role}")

# =========================================
# SIDEBAR
# =========================================
st.sidebar.title("📊 REDI Data System")
FORM_UID = st.sidebar.text_input("Kobo Form UID")

page = st.sidebar.radio(
    "Navigation",
    ["Dashboard", "Explorer", "Quality Analytics", "Downloads"]
)

# =========================================
# FETCH DATA
# =========================================
@st.cache_data(ttl=120)
def fetch_data(uid, token):

    if not uid:
        return pd.DataFrame()

    headers = {"Authorization": f"Token {token}"} if token else {}

    url = f"https://kf.kobotoolbox.org/api/v2/assets/{uid}/data/?format=json&page_size=1000"

    data_all = []

    while url:
        r = requests.get(url, headers=headers, timeout=30)
        if r.status_code != 200:
            break

        data = r.json()
        data_all.extend(data.get("results", []))
        url = data.get("next")

    return pd.json_normalize(data_all)

df = fetch_data(FORM_UID, st.secrets.get("KOBO_TOKEN", None))

if df.empty:
    st.warning("No data found")
    st.stop()

# =========================================
# COLUMN DETECTION
# =========================================
def detect(keys):
    for col in df.columns:
        for k in keys:
            if k in col.lower():
                return col
    return None

DATE_COL = detect(["submission_time", "date", "time"])
ENUM_COL = detect(["enum", "enumerator", "name"])

if DATE_COL:
    df[DATE_COL] = pd.to_datetime(df[DATE_COL], errors="coerce")

# =========================================
# QUANTITATIVE (ANOMALY + AI ONLY)
# =========================================
num_cols = df.select_dtypes(include=["number"]).columns

if len(num_cols) > 0:
    z = np.abs((df[num_cols] - df[num_cols].mean()) / df[num_cols].std().replace(0, 1))
    df["anomaly_flag"] = z.max(axis=1) > 4.5
else:
    df["anomaly_flag"] = False

if ENABLE_AI and len(num_cols) > 2:
    model = IsolationForest(contamination=AI_CONTAMINATION, random_state=42)
    df["ai_flag"] = model.fit_predict(df[num_cols].fillna(0)) == -1
else:
    df["ai_flag"] = False

# =========================================
# QUALITATIVE ENGINE (FULL)
# =========================================
df["qualitative_flag"] = False
df["qualitative_issue"] = ""

# Required fields
required_keywords = ["name", "gender", "age", "region"]
for col in df.columns:
    if any(k in col.lower() for k in required_keywords):
        miss = df[col].isna() | (df[col].astype(str).str.strip() == "")
        df.loc[miss, "qualitative_flag"] = True
        df.loc[miss, "qualitative_issue"] += f"Missing {col}; "

# Age rule
age_col = detect(["age"])
if age_col:
    bad_age = (pd.to_numeric(df[age_col], errors="coerce") < 0) | \
              (pd.to_numeric(df[age_col], errors="coerce") > 120)
    df.loc[bad_age, "qualitative_flag"] = True
    df.loc[bad_age, "qualitative_issue"] += "Invalid age; "

# Skip logic
marital = detect(["marital"])
children = detect(["child"])
if marital and children:
    mask = df[marital].astype(str).str.lower().str.contains("single", na=False) & \
           (pd.to_numeric(df[children], errors="coerce") > 5)
    df.loc[mask, "qualitative_flag"] = True
    df.loc[mask, "qualitative_issue"] += "Skip logic error; "

# Text inconsistency
bad_words = ["test", "asdf", "xxx", "unknown"]
for col in df.select_dtypes(include=["object"]).columns:
    mask = df[col].astype(str).str.lower().isin(bad_words)
    df.loc[mask, "qualitative_flag"] = True

# Spelling issues (EN + ID)
spell = {
    "teh":"the","recieve":"receive",
    "tdak":"tidak","sya":"saya"
}

for col in df.select_dtypes(include=["object"]).columns:
    text = df[col].astype(str).str.lower()
    for w in spell:
        mask = text.str.contains(w, na=False)
        df.loc[mask, "qualitative_flag"] = True

# Advanced rule
edu = detect(["education"])
if edu and age_col:
    mask = df[edu].astype(str).str.lower().str.contains("phd|doctorate") & \
           (pd.to_numeric(df[age_col], errors="coerce") < 15)
    df.loc[mask, "qualitative_flag"] = True

# =========================================
# FINAL FLAGS (ONLY REAL ERRORS)
# =========================================
df["final_flag"] = (
    df["anomaly_flag"] |
    df["ai_flag"] |
    df["qualitative_flag"]
)

clean_df = df[~df["final_flag"]]
flag_df = df[df["final_flag"]]

total = len(df)
valid = len(clean_df)
bad = len(flag_df)

score = (valid / total * 100) if total else 0

# =========================================
# DASHBOARD
# =========================================
if page == "Dashboard":

    st.title(APP_NAME)

    c1, c2, c3, c4 = st.columns(4)

    c1.markdown(f"""<div class="kpi-card" style="background:#2563eb"><h3>Total</h3><h1>{total}</h1></div>""", unsafe_allow_html=True)
    c2.markdown(f"""<div class="kpi-card" style="background:#16a34a"><h3>Valid</h3><h1>{valid}</h1></div>""", unsafe_allow_html=True)
    c3.markdown(f"""<div class="kpi-card" style="background:#dc2626"><h3>Flagged</h3><h1>{bad}</h1></div>""", unsafe_allow_html=True)
    c4.markdown(f"""<div class="kpi-card" style="background:#7c3aed"><h3>Score</h3><h1>{score:.1f}%</h1></div>""", unsafe_allow_html=True)

    st.bar_chart(pd.DataFrame({"Valid":[valid],"Flagged":[bad]}))

# =========================================
# EXPLORER
# =========================================
elif page == "Explorer":
    st.title("Explorer")
    st.dataframe(clean_df)
    st.dataframe(flag_df)

# =========================================
# ANALYTICS
# =========================================
elif page == "Quality Analytics":

    st.title("Analytics")

    st.dataframe(pd.DataFrame({
        "Type":["Anomaly","AI","Qualitative"],
        "Count":[df["anomaly_flag"].sum(), df["ai_flag"].sum(), df["qualitative_flag"].sum()]
    }))

# =========================================
# DOWNLOADS
# =========================================
elif page == "Downloads":

    st.title("Downloads")

    st.download_button("Clean Data", clean_df.to_csv(index=False), "clean.csv")
    st.download_button("Flagged Data", flag_df.to_csv(index=False), "flagged.csv")

# =========================================
# FOOTER
# =========================================
st.caption(f"{APP_NAME} | {datetime.now()}")
