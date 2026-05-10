# =========================================
# REDI DATA QUALITY MONITORING SYSTEM
# NO-FAIL EXAM / DEMO VERSION (STREAMLIT SAFE)
# =========================================

import streamlit as st
import pandas as pd
import numpy as np
import requests
import os
import logging
import yaml
import io
import time

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

APP_NAME = "REDI Data Quality Monitoring System"

# =========================================
# SAFE LOGGING (FALLBACK ALERT SYSTEM)
# =========================================
os.makedirs("logs", exist_ok=True)

logging.basicConfig(
    filename="logs/redi.log",
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)

def alert_system(message):
    """
    SAFE ALERT SYSTEM (NO EXTERNAL DEPENDENCIES)
    Replaces WhatsApp/email to avoid failure in exams/demo
    """
    logging.info(f"ALERT: {message}")
    st.warning(f"🚨 SYSTEM ALERT: {message}")

# =========================================
# AUTHENTICATION SAFE LOAD
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
    st.error("Incorrect username or password")
    st.stop()

if st.session_state.get("authentication_status") is None:
    st.warning("Please login")
    st.stop()

name = st.session_state.get("name")
username = st.session_state.get("username")

authenticator.logout("Logout", "sidebar")
st.sidebar.success(f"Welcome {name}")

role = config["credentials"]["usernames"][username]["role"]

# =========================================
# DATA FETCH (SAFE)
# =========================================
@st.cache_data(ttl=120)
def fetch_data(uid, token):

    if not uid:
        return pd.DataFrame()

    url = f"https://kf.kobotoolbox.org/api/v2/assets/{uid}/data/?format=json&page_size=1000"
    headers = {"Authorization": f"Token {token}"} if token else {}

    data_all = []

    try:
        while url:
            r = requests.get(url, headers=headers, timeout=30)

            if r.status_code != 200:
                logging.error(f"API error {r.status_code}")
                break

            js = r.json()
            data_all.extend(js.get("results", []))
            url = js.get("next")

    except Exception as e:
        logging.error(str(e))
        return pd.DataFrame()

    return pd.json_normalize(data_all)

# =========================================
# SIDEBAR
# =========================================
st.sidebar.title("📊 REDI System")

FORM_UID = st.sidebar.text_input("Kobo UID")
KOBO_TOKEN = st.secrets.get("KOBO_TOKEN", None)

# LIVE MODE (SAFE SIMULATION)
live_mode = st.sidebar.toggle("🔴 Live Mode", value=False)
refresh_rate = st.sidebar.selectbox("Refresh (sec)", [5, 10, 30], index=1)

# =========================================
# LOAD DATA
# =========================================
with st.spinner("Loading data..."):
    df = fetch_data(FORM_UID, KOBO_TOKEN)

if df.empty:
    st.warning("No data available")
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
GENDER_COL = detect(["gender", "sex"])
ENUM_COL = detect(["enum", "user"])

# =========================================
# QUALITY ENGINE INIT
# =========================================
df["reason"] = ""
df["flag"] = False

# Missing values rule
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
# AI EXPLANATION (PER ROW)
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
# KPIs
# =========================================
total = len(df)
valid = len(clean_df)
bad = len(flag_df)
score = (valid / total * 100) if total else 0

# =========================================
# SAFE ALERT SYSTEM (NO FAIL MODE)
# =========================================
if len(flag_df) > 0:
    alert_system(f"{len(flag_df)} anomalies detected in dataset")

# =========================================
# LIVE MODE SIMULATION
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

    st.title(APP_NAME)

    c1, c2, c3, c4 = st.columns(4)

    c1.metric("Total", total)
    c2.metric("Valid", valid)
    c3.metric("Flagged", bad)
    c4.metric("Quality Score", f"{score:.2f}%")

    st.subheader("Data Quality Overview")

    fig = px.bar(
        pd.DataFrame({"Type": ["Valid", "Flagged"], "Count": [valid, bad]}),
        x="Type",
        y="Count"
    )

    st.plotly_chart(fig, use_container_width=True)

    # ENUMERATOR LEADERBOARD
    if ENUM_COL:

        leaderboard = df.groupby(ENUM_COL).agg(
            total=("final_flag", "count"),
            flagged=("final_flag", "sum")
        ).reset_index()

        leaderboard["score"] = (1 - leaderboard["flagged"] / leaderboard["total"]) * 100

        st.subheader("🏆 Enumerator Leaderboard")
        st.dataframe(leaderboard.sort_values("score", ascending=False))

# =========================================
# EXPLORER
# =========================================
elif page == "Explorer":

    st.title("Data Explorer")

    tab1, tab2 = st.tabs(["Clean Data", "Flagged Data"])

    with tab1:
        st.dataframe(clean_df, use_container_width=True)

    with tab2:
        st.dataframe(flag_df[["ai_explanation"] + list(flag_df.columns)])

# =========================================
# INSIGHTS
# =========================================
elif page == "Insights":

    st.title("Key Insights")

    st.bar_chart(flag_df["reason"].value_counts().head(10))

# =========================================
# FOOTER
# =========================================
st.caption(f"{APP_NAME} | Generated at {datetime.now()}")
