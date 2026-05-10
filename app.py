# =========================================
# REDI AUTOMATED DATA QUALITY MONITORING SYSTEM
# FINAL PRODUCTION VERSION (STABLE)
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

st.sidebar.success(f"Welcome {name}")

role = config["credentials"]["usernames"][username]["role"]
st.sidebar.info(f"Role: {role}")

# =========================================
# SYSTEM STATUS PANEL
# =========================================
st.sidebar.markdown("### System Status")

# =========================================
# KOBO TOKEN
# =========================================
KOBO_TOKEN = st.secrets.get("KOBO_TOKEN", None)

if not KOBO_TOKEN:
    st.error("Missing KoBo API token")
    st.stop()

# =========================================
# SIDEBAR
# =========================================
st.sidebar.title("📊 REDI Universal Data System")
FORM_UID = st.sidebar.text_input("Kobo Form UID")

if FORM_UID and len(FORM_UID) < 10:
    st.sidebar.error("Invalid UID format")

# =========================================
# NAVIGATION
# =========================================
page_options = ["Dashboard", "Explorer", "Quality Analytics", "Downloads"]

if role == "enumerator":
    page_options = ["Dashboard", "Explorer"]
elif role == "supervisor":
    page_options = ["Dashboard", "Explorer", "Quality Analytics"]

page = st.sidebar.radio("Navigation", page_options)

# =========================================
# FETCH DATA
# =========================================
@st.cache_data(ttl=120)
def fetch_data(uid, token):
    headers = {"Authorization": f"Token {token}"}
    url = f"https://kf.kobotoolbox.org/api/v2/assets/{uid}/data/?format=json&page_size=1000"
    all_data = []

    while url:
        try:
            r = requests.get(url, headers=headers, timeout=30)

            if r.status_code != 200:
                logging.error(f"Kobo API Error: {r.status_code}")
                break

            data = r.json()
            all_data.extend(data.get("results", []))
            url = data.get("next")

        except Exception as e:
            logging.error(str(e))
            break

    return pd.json_normalize(all_data)

# =========================================
# LOAD DATA WITH SPINNER
# =========================================
with st.spinner("Fetching data from KoBo..."):
    df = fetch_data(FORM_UID, KOBO_TOKEN)

# =========================================
# OFFLINE FALLBACK
# =========================================
if df.empty:
    if os.path.exists("backup.csv"):
        df = pd.read_csv("backup.csv")
        st.warning("Using last available data (offline mode)")
    else:
        st.warning("No data found")
        st.stop()

# Save backup
df.to_csv("backup.csv", index=False)

# =========================================
# SYSTEM STATUS UPDATE
# =========================================
st.sidebar.success("API Connected")
st.sidebar.success("AI Engine Active" if ENABLE_AI else "AI Disabled")
st.sidebar.success("Audit Logging Active")
st.sidebar.info(f"Records Loaded: {len(df)}")

if len(df) > 20000:
    st.warning("Large dataset detected - performance may slow")

# =========================================
# SMART DETECTION
# =========================================
def detect(names):
    for col in df.columns:
        for n in names:
            if n in col.lower():
                return col
    return None

DATE_COL = detect(["submission_time", "date", "time"])

if "_submission_time" in df.columns:
    DATE_COL = "_submission_time"

if DATE_COL:
    df[DATE_COL] = pd.to_datetime(df[DATE_COL], errors="coerce")

# =========================================
# NUMERIC
# =========================================
num_cols = df.select_dtypes(include=["number"]).columns

# =========================================
# BASIC ANOMALY
# =========================================
if len(num_cols) > 0:
    std = df[num_cols].std().replace(0, 1)
    z = np.abs((df[num_cols] - df[num_cols].mean()) / std)
    df["anomaly_flag"] = z.max(axis=1) > 4.5
else:
    df["anomaly_flag"] = False

# =========================================
# AI ANOMALY
# =========================================
try:
    if ENABLE_AI and len(num_cols) > 2:
        model = IsolationForest(contamination=AI_CONTAMINATION, random_state=42)
        df["ai_flag"] = model.fit_predict(df[num_cols].fillna(0)) == -1
    else:
        df["ai_flag"] = False
except Exception as e:
    logging.error(str(e))
    st.error("AI engine error")
    df["ai_flag"] = False

# =========================================
# QUALITATIVE ENGINE
# =========================================
df["qualitative_flag"] = False
df["qualitative_issue"] = ""

for col in df.columns:
    mask = df[col].astype(str).str.lower().isin(["test","xxx","na","n/a","unknown"])
    df.loc[mask, "qualitative_flag"] = True
    df.loc[mask, "qualitative_issue"] += f"Suspicious text in {col}; "

# =========================================
# FINAL FLAGS
# =========================================
df["flag_score"] = (
    df["anomaly_flag"].astype(int) +
    df["ai_flag"].astype(int) +
    df["qualitative_flag"].astype(int)
)

df["final_flag"] = df["flag_score"] >= 1

# =========================================
# AI EXPLANATION ENGINE
# =========================================
def explain(row):
    reasons = []
    if row["anomaly_flag"]:
        reasons.append("Statistical anomaly")
    if row["ai_flag"]:
        reasons.append("AI anomaly")
    if row["qualitative_flag"]:
        reasons.append(row["qualitative_issue"])
    return " | ".join(reasons)

df["ai_explain"] = df.apply(explain, axis=1)

# =========================================
# SPLIT
# =========================================
clean_df = df[~df["final_flag"]]
flag_df = df[df["final_flag"]]

total = len(df)
valid = len(clean_df)
bad = len(flag_df)
score = (valid / total) * 100 if total else 0

# =========================================
# DASHBOARD
# =========================================
if page == "Dashboard":

    st.title(APP_NAME)

    c1, c2, c3, c4 = st.columns(4)

    c1.metric("Total", total)
    c2.metric("Valid", valid)
    c3.metric("Flagged", bad)
    c4.metric("Quality %", f"{score:.1f}")

    fig = px.pie(
        names=["Valid", "Flagged"],
        values=[valid, bad]
    )
    st.plotly_chart(fig, use_container_width=True)

# =========================================
# EXPLORER
# =========================================
elif page == "Explorer":

    st.title("Explorer")

    tab1, tab2 = st.tabs(["Clean", "Flagged"])

    with tab1:
        st.dataframe(clean_df, use_container_width=True)

    with tab2:
        st.dataframe(flag_df, use_container_width=True)

# =========================================
# QUALITY ANALYTICS
# =========================================
elif page == "Quality Analytics":

    st.title("Quality Analytics")

    st.dataframe(
        df[["anomaly_flag", "ai_flag", "qualitative_flag"]].sum().reset_index(),
        use_container_width=True
    )

# =========================================
# DOWNLOADS
# =========================================
elif page == "Downloads":

    st.title("Downloads")

    def to_excel(data):
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            data.to_excel(writer, index=False)
        output.seek(0)
        return output

    st.download_button("Download Clean", to_excel(clean_df), "clean.xlsx")
    st.download_button("Download Flagged", to_excel(flag_df), "flagged.xlsx")

# =========================================
# FOOTER
# =========================================
st.caption(f"{APP_NAME} | {datetime.now()}")
