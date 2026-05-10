# =========================================
# REDI AUTOMATED DATA QUALITY MONITORING SYSTEM
# FINAL PRODUCTION VERSION (FIXED KOBO TOTAL)
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
# FULL STYLING
# =========================================
st.markdown("""<style>
.stApp {
    background: linear-gradient(135deg,#f3f7ff,#dbeafe);
}
</style>""", unsafe_allow_html=True)

# =========================================
# CONFIG
# =========================================
APP_NAME = os.getenv(
    "APP_NAME",
    "REDI Automated Data Quality Monitoring System"
)

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

# =========================================
# AUDIT
# =========================================
os.makedirs("audit", exist_ok=True)

def log_action(user, action):
    log = pd.DataFrame([{
        "user": user,
        "action": action,
        "time": datetime.now()
    }])

    file = "audit/audit_log.csv"

    if os.path.exists(file):
        old = pd.read_csv(file)
        log = pd.concat([old, log])

    log.to_csv(file, index=False)

log_action(username, "logged_in")

# =========================================
# SIDEBAR
# =========================================
st.sidebar.title("📊 REDI System")

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
# LOAD DATA (FIXED)
# =========================================
raw_df = fetch_data(FORM_UID, KOBO_TOKEN)

if raw_df.empty:
    st.warning("No data found")
    st.stop()

df = raw_df.copy()

# =========================================
# DETECT COLUMNS
# =========================================
def detect(names):
    for col in df.columns:
        for n in names:
            if n in col.lower():
                return col
    return None

DATE_COL = detect(["submission_time", "date", "time"])

if DATE_COL:
    df[DATE_COL] = pd.to_datetime(df[DATE_COL], errors="coerce")

# =========================================
# FILTERS (APPLY ONLY TO df)
# =========================================
if DATE_COL:

    start = st.sidebar.date_input("Start", df[DATE_COL].min())
    end = st.sidebar.date_input("End", df[DATE_COL].max())

    df = df[
        (df[DATE_COL] >= pd.to_datetime(start)) &
        (df[DATE_COL] <= pd.to_datetime(end))
    ]

search = st.sidebar.text_input("Search")

if search:
    df = df[df.astype(str).apply(
        lambda x: x.str.contains(search, case=False, na=False).any(),
        axis=1
    )]

# =========================================
# ANOMALY DETECTION
# =========================================
num_cols = df.select_dtypes(include=["number"]).columns

if len(num_cols) > 0:

    std = df[num_cols].std().replace(0, 1)

    z = np.abs((df[num_cols] - df[num_cols].mean()) / std)

    df["anomaly_flag"] = z.max(axis=1) > 4.5

else:
    df["anomaly_flag"] = False

# AI
if ENABLE_AI and len(num_cols) > 2:
    model = IsolationForest(contamination=AI_CONTAMINATION, random_state=42)
    df["ai_flag"] = model.fit_predict(df[num_cols].fillna(0)) == -1
else:
    df["ai_flag"] = False

# =========================================
# QUALITY FLAGS
# =========================================
df["qualitative_flag"] = False

df["flag_score"] = (
    df["anomaly_flag"].astype(int) +
    df["ai_flag"].astype(int)
)

df["final_flag"] = df["flag_score"] >= 1

clean_df = df[~df["final_flag"]]
flag_df = df[df["final_flag"]]

# =========================================
# KPI (FIXED HERE)
# =========================================
total = len(raw_df)   # ✅ KOBO TRUE TOTAL
valid = len(clean_df)
bad = len(flag_df)

score = (valid / total) * 100 if total else 0

# =========================================
# DASHBOARD
# =========================================
st.title(APP_NAME)

c1, c2, c3, c4 = st.columns(4)

c1.metric("Total Kobo Records", total)
c2.metric("Valid Records", valid)
c3.metric("Flagged Records", bad)
c4.metric("Quality Score", f"{score:.1f}%")

# =========================================
# EXPLORER
# =========================================
st.subheader("Clean Data")
st.dataframe(clean_df, use_container_width=True)

st.subheader("Flagged Data")
st.dataframe(flag_df, use_container_width=True)

# =========================================
# FOOTER
# =========================================
st.caption(f"{APP_NAME} | Updated {datetime.now()}")
