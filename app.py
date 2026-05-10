# =========================================
# REDI DATA QUALITY MONITORING SYSTEM
# FINAL MASTER VERSION (UN / WORLD BANK STYLE + MOBILE SAFE)
# =========================================

import streamlit as st
import pandas as pd
import numpy as np
import requests
import os
import logging
import yaml
import time

import streamlit_authenticator as stauth

from yaml.loader import SafeLoader
from datetime import datetime
from sklearn.ensemble import IsolationForest

import plotly.express as px

# =========================================
# PAGE CONFIG
# =========================================
st.set_page_config(
    page_title="REDI Data Quality System",
    layout="wide",
    page_icon="📊"
)

APP_NAME = "REDI Data Quality Monitoring System"

# =========================================
# 🎨 UN / WORLD BANK STYLE THEME
# =========================================
st.markdown("""
<style>

/* GLOBAL BACKGROUND */
.stApp {
    background: #f7fafc;
    font-family: "Segoe UI", Roboto, sans-serif;
}

/* SIDEBAR (UN STYLE) */
section[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #0b2e4a, #123a5a);
    color: white;
}

section[data-testid="stSidebar"] * {
    color: white !important;
}

/* SIDEBAR INPUTS */
section[data-testid="stSidebar"] input {
    background-color: #ffffff !important;
    color: #0b2e4a !important;
    border-radius: 6px !important;
    border: 1px solid #cbd5e1 !important;
}

/* KPI CARDS */
.kpi-card {
    background: white;
    border-left: 6px solid #1d4ed8;
    padding: 18px;
    border-radius: 10px;
    box-shadow: 0 2px 10px rgba(0,0,0,0.08);
    text-align: center;
}

/* BUTTONS */
.btn-blue {background:#1d4ed8;color:white;padding:10px;border-radius:6px;font-weight:600;}
.btn-green {background:#16a34a;color:white;padding:10px;border-radius:6px;font-weight:600;}
.btn-red {background:#dc2626;color:white;padding:10px;border-radius:6px;font-weight:600;}
.btn-purple {background:#6d28d9;color:white;padding:10px;border-radius:6px;font-weight:600;}

/* HEADINGS */
h1, h2, h3 {color:#0b2e4a;}

/* TABLE HEADER */
th {
    background-color: #0b2e4a !important;
    color: white !important;
}

/* MOBILE */
@media only screen and (max-width: 768px) {
    .kpi-card {margin-bottom:10px;}
    h1 {font-size:22px !important;}
}

</style>
""", unsafe_allow_html=True)

# =========================================
# SAFE LOGGING (NO FAIL SYSTEM)
# =========================================
os.makedirs("logs", exist_ok=True)

logging.basicConfig(
    filename="logs/redi.log",
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)

def alert_system(msg):
    logging.info(msg)
    st.warning(f"🚨 ALERT: {msg}")

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

if st.session_state.get("authentication_status") is False:
    st.error("Wrong login")
    st.stop()

if st.session_state.get("authentication_status") is None:
    st.warning("Login required")
    st.stop()

name = st.session_state.get("name")
username = st.session_state.get("username")

authenticator.logout("Logout", "sidebar")
st.sidebar.success(f"Welcome {name}")

role = config["credentials"]["usernames"][username]["role"]

# =========================================
# SIDEBAR
# =========================================
st.sidebar.title("📊 REDI System")

FORM_UID = st.sidebar.text_input("Kobo UID")
KOBO_TOKEN = st.secrets.get("KOBO_TOKEN", None)

live_mode = st.sidebar.toggle("🔴 Live Mode", value=False)
refresh_rate = st.sidebar.selectbox("Refresh (sec)", [5, 10, 30], index=1)

# =========================================
# DATA FETCH
# =========================================
@st.cache_data(ttl=120)
def fetch_data(uid, token):

    if not uid:
        return pd.DataFrame()

    url = f"https://kf.kobotoolbox.org/api/v2/assets/{uid}/data/?format=json&page_size=1000"
    headers = {"Authorization": f"Token {token}"} if token else {}

    data = []

    try:
        while url:
            r = requests.get(url, headers=headers, timeout=30)

            if r.status_code != 200:
                logging.error(f"API error {r.status_code}")
                break

            js = r.json()
            data.extend(js.get("results", []))
            url = js.get("next")

    except Exception as e:
        logging.error(str(e))
        return pd.DataFrame()

    return pd.json_normalize(data)

# =========================================
# LOAD DATA
# =========================================
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

AGE_COL = detect(["age"])
ENUM_COL = detect(["enum", "user"])

# =========================================
# QUALITY ENGINE
# =========================================
df["reason"] = ""
df["flag"] = False

# Missing values
for col in df.columns:
    if any(k in col.lower() for k in ["name", "age", "gender"]):

        mask = df[col].isna()

        df.loc[mask, "flag"] = True
        df.loc[mask, "reason"] += f"Missing {col}; "

# Age rule
if AGE_COL:
    age = pd.to_numeric(df[AGE_COL], errors="coerce")
    mask = (age < 0) | (age > 120)

    df.loc[mask, "flag"] = True
    df.loc[mask, "reason"] += "Invalid age; "

# =========================================
# AI ANOMALY DETECTION
# =========================================
num_cols = df.select_dtypes(include=["number"]).columns

df["ai_flag"] = False

if len(num_cols) > 2:
    model = IsolationForest(contamination=0.005, random_state=42)
    pred = model.fit_predict(df[num_cols].fillna(0))
    df["ai_flag"] = pred == -1

# =========================================
# FINAL FLAGS
# =========================================
df["final_flag"] = df["flag"] | df["ai_flag"]

clean_df = df[~df["final_flag"]]
flag_df = df[df["final_flag"]]

# =========================================
# AI EXPLANATION
# =========================================
def explain(row):

    r = []

    if row["flag"]:
        r.append(row["reason"])

    if row["ai_flag"]:
        r.append("AI anomaly detected")

    return " | ".join(r) if r else "Normal"

df["ai_explanation"] = df.apply(explain, axis=1)

# =========================================
# KPI
# =========================================
total = len(df)
valid = len(clean_df)
bad = len(flag_df)
score = (valid / total * 100) if total else 0

# =========================================
# ALERT SYSTEM (SAFE)
# =========================================
if len(flag_df) > 0:
    alert_system(f"{len(flag_df)} anomalies detected")

# =========================================
# LIVE MODE
# =========================================
if live_mode:
    time.sleep(refresh_rate)
    st.rerun()

# =========================================
# NAVIGATION
# =========================================
page = st.sidebar.radio("Navigation", [
    "Dashboard",
    "Explorer",
    "Insights"
])

# =========================================
# DASHBOARD
# =========================================
if page == "Dashboard":

    st.markdown(f"""
    # 🏛️ {APP_NAME}
    ### UN / World Bank Style Data Quality Dashboard
    """)

    c1, c2 = st.columns(2)
    c3, c4 = st.columns(2)

    c1.markdown(f'<div class="kpi-card"><h3>Total</h3><h1>{total}</h1></div>', unsafe_allow_html=True)
    c2.markdown(f'<div class="kpi-card"><h3>Valid</h3><h1>{valid}</h1></div>', unsafe_allow_html=True)
    c3.markdown(f'<div class="kpi-card"><h3>Flagged</h3><h1>{bad}</h1></div>', unsafe_allow_html=True)
    c4.markdown(f'<div class="kpi-card"><h3>Score</h3><h1>{score:.1f}%</h1></div>', unsafe_allow_html=True)

    st.subheader("Quality Overview")

    fig = px.bar(
        pd.DataFrame({"Type": ["Valid", "Flagged"], "Count": [valid, bad]}),
        x="Type",
        y="Count"
    )

    st.plotly_chart(fig, use_container_width=True)

    if ENUM_COL:

        leaderboard = df.groupby(ENUM_COL).agg(
            total=("final_flag", "count"),
            flagged=("final_flag", "sum")
        ).reset_index()

        leaderboard["score"] = (1 - leaderboard["flagged"]/leaderboard["total"]) * 100

        st.subheader("🏆 Enumerator Leaderboard")
        st.dataframe(leaderboard.sort_values("score", ascending=False))

# =========================================
# EXPLORER
# =========================================
elif page == "Explorer":

    st.title("Data Explorer")

    tab1, tab2 = st.tabs(["Clean", "Flagged"])

    with tab1:
        st.dataframe(clean_df, use_container_width=True)

    with tab2:
        st.dataframe(flag_df[["ai_explanation"] + list(flag_df.columns)])

# =========================================
# INSIGHTS
# =========================================
elif page == "Insights":

    st.title("Insights")

    st.bar_chart(flag_df["reason"].value_counts().head(10))

# =========================================
# FOOTER
# =========================================
st.caption(f"{APP_NAME} | Generated {datetime.now()}")
