# =========================================
# REDI ADA LOGIN SYSTEM - DEPLOYMENT SAFE
# =========================================

import streamlit as st
import pandas as pd
import requests
import numpy as np
import yaml
import io
import os
import logging

from yaml.loader import SafeLoader
from datetime import datetime
from sklearn.ensemble import IsolationForest
import streamlit_authenticator as stauth
import plotly.express as px

# =========================================
# PAGE CONFIG
# =========================================
st.set_page_config(
    page_title="REDI ADA Login System",
    layout="wide",
    page_icon="📊"
)

APP_NAME = "REDI Automated Data Quality Monitoring System"

# =========================================
# SAFE CONFIG LOAD
# =========================================
try:
    with open("config.yaml") as file:
        config = yaml.load(file, Loader=SafeLoader)
except Exception:
    st.error("❌ config.yaml missing or broken")
    st.stop()

# =========================================
# SAFE COOKIE CHECK
# =========================================
if "cookie" not in config:
    st.error("❌ Missing 'cookie' section in config.yaml")
    st.stop()

# =========================================
# AUTHENTICATION (AUTO HASH ENABLED)
# =========================================
try:
    authenticator = stauth.Authenticate(
        config["credentials"],
        config["cookie"].get("name", "redi_cookie"),
        config["cookie"].get("key", "redi_secure_key"),
        config["cookie"].get("expiry_days", 1),
        auto_hash=True   # ✅ CRITICAL FIX
    )

    authenticator.login()

except Exception as e:
    st.error("❌ Authentication system error. Check config.yaml")
    st.stop()

# =========================================
# LOGIN STATE
# =========================================
auth_status = st.session_state.get("authentication_status")

if auth_status is False:
    st.error("❌ Incorrect username or password")
    st.stop()

if auth_status is None:
    st.warning("Please login to continue")
    st.stop()

name = st.session_state.get("name")
username = st.session_state.get("username")

# =========================================
# ROLE SAFE ACCESS
# =========================================
try:
    role = config["credentials"]["usernames"][username].get("role", "user")
except:
    role = "user"

authenticator.logout("Logout", "sidebar")

# =========================================
# LOGGING
# =========================================
os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    filename="logs/redi.log",
    level=logging.ERROR
)

# =========================================
# SIDEBAR
# =========================================
st.sidebar.title("📊 REDI ADA System")
st.sidebar.success(f"Welcome {name}")
st.sidebar.info(f"Role: {role}")

FORM_UID = st.sidebar.text_input("KoBo Form UID")

if not FORM_UID:
    st.warning("⚠️ Please enter KoBo Form UID")
    st.stop()

# =========================================
# KOBO TOKEN
# =========================================
KOBO_TOKEN = st.secrets.get("KOBO_TOKEN")

if not KOBO_TOKEN:
    st.error("❌ KOBO_TOKEN missing in secrets")
    st.stop()

# =========================================
# FETCH DATA
# =========================================
@st.cache_data(ttl=120)
def fetch_data(uid, token):
    url = f"https://kf.kobotoolbox.org/api/v2/assets/{uid}/data/?format=json&page_size=1000"

    headers = {
        "Authorization": f"Token {token}"
    }

    all_data = []

    while url:
        try:
            r = requests.get(url, headers=headers, timeout=30)

            if r.status_code != 200:
                return None

            data = r.json()
            all_data.extend(data.get("results", []))
            url = data.get("next")

        except Exception as e:
            logging.error(str(e))
            return None

    return pd.json_normalize(all_data)

# =========================================
# LOAD DATA
# =========================================
with st.spinner("Fetching data from Kobo..."):
    df = fetch_data(FORM_UID, KOBO_TOKEN)

if df is None:
    st.error("❌ Failed to fetch data. Check UID or token.")
    st.stop()

if df.empty:
    st.warning("No data found for this form.")
    st.stop()

# =========================================
# NUMERIC COLUMNS
# =========================================
num_cols = df.select_dtypes(include=["number"]).columns

# =========================================
# BASIC ANOMALY
# =========================================
if len(num_cols) > 0:
    std = df[num_cols].std().replace(0, 1)
    z = np.abs((df[num_cols] - df[num_cols].mean()) / std)
    df["anomaly_flag"] = z.max(axis=1) > 4
else:
    df["anomaly_flag"] = False

# =========================================
# AI ANOMALY
# =========================================
if len(num_cols) > 2:
    try:
        model = IsolationForest(contamination=0.01, random_state=42)
        df["ai_flag"] = model.fit_predict(df[num_cols].fillna(0)) == -1
    except Exception as e:
        logging.error(str(e))
        df["ai_flag"] = False
else:
    df["ai_flag"] = False

# =========================================
# FINAL FLAG
# =========================================
df["final_flag"] = df["anomaly_flag"] | df["ai_flag"]

clean_df = df[~df["final_flag"]]
flag_df = df[df["final_flag"]]

# =========================================
# KPIs
# =========================================
total = len(df)
valid = len(clean_df)
bad = len(flag_df)
score = (valid / total * 100) if total else 0

# =========================================
# DASHBOARD
# =========================================
st.title(APP_NAME)

c1, c2, c3, c4 = st.columns(4)

c1.metric("Total Records", total)
c2.metric("Valid Records", valid)
c3.metric("Flagged Records", bad)
c4.metric("Quality Score", f"{score:.1f}%")

# =========================================
# CHART
# =========================================
fig = px.bar(
    pd.DataFrame({
        "Category": ["Valid", "Flagged"],
        "Count": [valid, bad]
    }),
    x="Category",
    y="Count",
    text="Count"
)

st.plotly_chart(fig, use_container_width=True)

# =========================================
# TABLE VIEW
# =========================================
tab1, tab2 = st.tabs(["Clean Data", "Flagged Data"])

with tab1:
    st.dataframe(clean_df, use_container_width=True)

with tab2:
    st.dataframe(flag_df, use_container_width=True)

# =========================================
# DOWNLOADS
# =========================================
def to_excel(data):
    buffer = io.BytesIO()
    data.to_excel(buffer, index=False)
    return buffer.getvalue()

st.subheader("Download Data")

col1, col2 = st.columns(2)

with col1:
    st.download_button(
        "Download Clean Data",
        to_excel(clean_df),
        "clean_data.xlsx"
    )

with col2:
    st.download_button(
        "Download Flagged Data",
        to_excel(flag_df),
        "flagged_data.xlsx"
    )

# =========================================
# FOOTER
# =========================================
st.caption(f"{APP_NAME} | Last Updated: {datetime.now()}")
