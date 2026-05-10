# =========================================
# REDI FULL SYSTEM (RESTORED + STABLE)
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
    page_title="REDI Automated Data Quality Monitoring System",
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
except:
    st.error("❌ config.yaml missing")
    st.stop()

if "cookie" not in config:
    st.error("❌ cookie config missing")
    st.stop()

# =========================================
# AUTH (FIXED)
# =========================================
try:
    authenticator = stauth.Authenticate(
        config["credentials"],
        config["cookie"].get("name", "redi_cookie"),
        config["cookie"].get("key", "redi_secure_key"),
        config["cookie"].get("expiry_days", 1),
        auto_hash=True   # 🔥 KEY FIX
    )
    authenticator.login()
except:
    st.error("❌ Authentication error")
    st.stop()

auth_status = st.session_state.get("authentication_status")

if auth_status is False:
    st.error("Incorrect username or password")
    st.stop()

if auth_status is None:
    st.warning("Please login")
    st.stop()

name = st.session_state.get("name")
username = st.session_state.get("username")

try:
    role = config["credentials"]["usernames"][username]["role"]
except:
    role = "user"

authenticator.logout("Logout", "sidebar")

# =========================================
# LOGGING
# =========================================
os.makedirs("logs", exist_ok=True)
logging.basicConfig(filename="logs/redi.log", level=logging.ERROR)

# =========================================
# SIDEBAR
# =========================================
st.sidebar.title("📊 REDI Universal Data System")
st.sidebar.success(f"Welcome {name}")
st.sidebar.info(f"Role: {role}")

FORM_UID = st.sidebar.text_input("KoBo Form UID")

if not FORM_UID:
    st.warning("Enter KoBo UID")
    st.stop()

KOBO_TOKEN = st.secrets.get("KOBO_TOKEN")

if not KOBO_TOKEN:
    st.error("Missing KOBO_TOKEN")
    st.stop()

# =========================================
# NAVIGATION
# =========================================
pages = ["Dashboard", "Explorer", "Quality Analytics", "Downloads"]

if role == "enumerator":
    pages = ["Dashboard", "Explorer"]
elif role == "supervisor":
    pages = ["Dashboard", "Explorer", "Quality Analytics"]

page = st.sidebar.radio("Navigation", pages)

# =========================================
# FETCH DATA
# =========================================
@st.cache_data(ttl=120)
def fetch_data(uid, token):
    url = f"https://kf.kobotoolbox.org/api/v2/assets/{uid}/data/?format=json&page_size=1000"
    headers = {"Authorization": f"Token {token}"}
    data_all = []

    while url:
        try:
            r = requests.get(url, headers=headers, timeout=30)
            if r.status_code != 200:
                return None
            data = r.json()
            data_all.extend(data.get("results", []))
            url = data.get("next")
        except Exception as e:
            logging.error(str(e))
            return None

    return pd.json_normalize(data_all)

# =========================================
# LOAD DATA
# =========================================
with st.spinner("Loading Kobo data..."):
    df = fetch_data(FORM_UID, KOBO_TOKEN)

if df is None:
    st.error("Failed to fetch data")
    st.stop()

if df.empty:
    st.warning("No data found")
    st.stop()

# =========================================
# NUMERIC + FLAGS
# =========================================
num_cols = df.select_dtypes(include=["number"]).columns

if len(num_cols) > 0:
    z = np.abs((df[num_cols] - df[num_cols].mean()) / df[num_cols].std().replace(0,1))
    df["anomaly_flag"] = z.max(axis=1) > 4
else:
    df["anomaly_flag"] = False

if len(num_cols) > 2:
    try:
        model = IsolationForest(contamination=0.01)
        df["ai_flag"] = model.fit_predict(df[num_cols].fillna(0)) == -1
    except:
        df["ai_flag"] = False
else:
    df["ai_flag"] = False

# =========================================
# QUALITATIVE CHECKS (RESTORED)
# =========================================
df["qualitative_flag"] = False
df["qualitative_issue"] = ""

for col in df.columns:
    if df[col].isna().any():
        df.loc[df[col].isna(), "qualitative_flag"] = True
        df.loc[df[col].isna(), "qualitative_issue"] += f"Missing {col}; "

# =========================================
# FINAL FLAGS
# =========================================
df["final_flag"] = df["anomaly_flag"] | df["ai_flag"] | df["qualitative_flag"]

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
if page == "Dashboard":

    st.title(APP_NAME)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total", total)
    c2.metric("Valid", valid)
    c3.metric("Flagged", bad)
    c4.metric("Quality %", f"{score:.1f}")

    fig = px.bar(
        pd.DataFrame({"Type": ["Valid","Flagged"], "Count":[valid,bad]}),
        x="Type",
        y="Count"
    )
    st.plotly_chart(fig, use_container_width=True)

# =========================================
# EXPLORER
# =========================================
elif page == "Explorer":
    st.title("Explorer")

    tab1, tab2 = st.tabs(["Clean", "Flagged"])
    tab1.dataframe(clean_df, use_container_width=True)
    tab2.dataframe(flag_df, use_container_width=True)

# =========================================
# ANALYTICS
# =========================================
elif page == "Quality Analytics":

    st.title("Quality Analytics")

    summary = pd.DataFrame({
        "Issue": ["Anomaly", "AI", "Qualitative"],
        "Count": [
            df["anomaly_flag"].sum(),
            df["ai_flag"].sum(),
            df["qualitative_flag"].sum()
        ]
    })

    st.dataframe(summary, use_container_width=True)

    st.plotly_chart(
        px.pie(summary, names="Issue", values="Count"),
        use_container_width=True
    )

# =========================================
# DOWNLOADS
# =========================================
elif page == "Downloads":

    st.title("Downloads")

    def to_excel(data):
        buffer = io.BytesIO()
        data.to_excel(buffer, index=False)
        return buffer.getvalue()

    st.download_button("Download Clean", to_excel(clean_df), "clean.xlsx")
    st.download_button("Download Flagged", to_excel(flag_df), "flagged.xlsx")

# =========================================
# FOOTER
# =========================================
st.caption(f"{APP_NAME} | {datetime.now()}")
