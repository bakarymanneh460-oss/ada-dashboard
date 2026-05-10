# =========================================
# REDI DATA QUALITY MONITORING SYSTEM
# FINAL PRODUCTION VERSION (ENHANCED)
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
import smtplib

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

from email.mime.text import MIMEText
from twilio.rest import Client

# =========================================
# CONFIG
# =========================================
st.set_page_config(
    page_title="REDI Data Quality System",
    layout="wide",
    page_icon="📊"
)

APP_NAME = "REDI Data Quality Monitoring System"

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
    st.error("Incorrect login")
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
# ALERT RATE LIMIT
# =========================================
if "last_alert_time" not in st.session_state:
    st.session_state.last_alert_time = 0

# =========================================
# ALERT FUNCTIONS
# =========================================
def send_whatsapp(message):

    try:
        client = Client(
            st.secrets["TWILIO_SID"],
            st.secrets["TWILIO_AUTH"]
        )

        client.messages.create(
            body=message,
            from_=st.secrets["TWILIO_WHATSAPP_FROM"],
            to=st.secrets["TWILIO_WHATSAPP_TO"]
        )

    except Exception as e:
        logging.error(str(e))


def send_email(subject, body):

    try:
        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"] = st.secrets["EMAIL_USER"]
        msg["To"] = st.secrets["EMAIL_TO"]

        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(
            st.secrets["EMAIL_USER"],
            st.secrets["EMAIL_PASS"]
        )
        server.send_message(msg)
        server.quit()

    except Exception as e:
        logging.error(str(e))

# =========================================
# DATA FETCH
# =========================================
@st.cache_data(ttl=120)
def fetch_data(uid, token):

    if not uid:
        return pd.DataFrame()

    url = f"https://kf.kobotoolbox.org/api/v2/assets/{uid}/data/?format=json&page_size=1000"
    headers = {"Authorization": f"Token {token}"} if token else {}

    all_data = []

    try:
        while url:
            r = requests.get(url, headers=headers, timeout=30)

            if r.status_code != 200:
                logging.error(f"API error {r.status_code}")
                break

            js = r.json()
            all_data.extend(js.get("results", []))
            url = js.get("next")

    except Exception as e:
        logging.error(str(e))
        return pd.DataFrame()

    return pd.json_normalize(all_data)

# =========================================
# SIDEBAR
# =========================================
st.sidebar.title("📊 REDI System")

FORM_UID = st.sidebar.text_input("Kobo UID")

KOBO_TOKEN = st.secrets.get("KOBO_TOKEN", None)

# LIVE MODE
live = st.sidebar.toggle("🔴 Live Mode", value=False)

refresh_rate = st.sidebar.selectbox(
    "Refresh (sec)",
    [5, 10, 30],
    index=1
)

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
# FLAGS
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

# AI anomaly
num_cols = df.select_dtypes(include=["number"]).columns

df["ai_flag"] = False

if len(num_cols) > 2:
    model = IsolationForest(contamination=0.005, random_state=42)
    pred = model.fit_predict(df[num_cols].fillna(0))
    df["ai_flag"] = pred == -1

# Final flag
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
now = time.time()

if len(flag_df) > 0 and (now - st.session_state.last_alert_time > 300):

    msg = f"REDI ALERT 🚨 {len(flag_df)} anomalies detected"

    send_whatsapp(msg)
    send_email("REDI Alert", msg)

    st.session_state.last_alert_time = now

# =========================================
# LIVE MODE REFRESH
# =========================================
if live:
    time.sleep(refresh_rate)
    st.rerun()

# =========================================
# DASHBOARD
# =========================================
page = st.sidebar.radio("Navigation", [
    "Dashboard",
    "Explorer",
    "Insights"
])

if page == "Dashboard":

    st.title(APP_NAME)

    c1, c2, c3, c4 = st.columns(4)

    c1.metric("Total", total)
    c2.metric("Valid", valid)
    c3.metric("Flagged", bad)
    c4.metric("Quality Score", f"{score:.2f}%")

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
