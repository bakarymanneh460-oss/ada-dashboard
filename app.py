# =========================================
# REDI DATA QUALITY SYSTEM (FINAL SAFE PROD)
# STREAMLIT CLOUD COMPATIBLE VERSION
# =========================================

import streamlit as st
import pandas as pd
import numpy as np
import requests
import os
import logging
import yaml
import io

from datetime import datetime
from sklearn.ensemble import IsolationForest
from yaml.loader import SafeLoader

import plotly.express as px

# =========================================
# OPTIONAL DATABASE LAYER (SAFE IMPORT)
# =========================================
DB_ENABLED = True

try:
    from sqlalchemy import create_engine, text
except Exception:
    DB_ENABLED = False
    create_engine = None
    text = None

engine = None

if DB_ENABLED:
    try:
        DB_URL = st.secrets.get("DB_URL", None)
        if DB_URL:
            engine = create_engine(DB_URL, pool_pre_ping=True)
    except Exception:
        engine = None
        DB_ENABLED = False


# =========================================
# PAGE CONFIG
# =========================================
st.set_page_config(
    page_title="REDI Data Quality System",
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

def log_error(e):
    logging.error(str(e))


# =========================================
# AUTHENTICATION
# =========================================
with open("config.yaml") as file:
    config = yaml.load(file, Loader=SafeLoader)

import streamlit_authenticator as stauth

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

username = st.session_state["username"]
name = st.session_state["name"]

authenticator.logout("Logout", "sidebar")

role = config["credentials"]["usernames"][username]["role"]

st.sidebar.success(f"Welcome {name}")
st.sidebar.info(f"Role: {role}")


# =========================================
# SIDEBAR INPUT
# =========================================
st.sidebar.title("REDI System")

FORM_UID = st.sidebar.text_input("Kobo Form UID")
KOBO_TOKEN = st.secrets.get("KOBO_TOKEN", None)

page = st.sidebar.radio(
    "Navigation",
    ["Dashboard", "Explorer", "Analytics", "Downloads"]
)


# =========================================
# DATA FETCH (SAFE)
# =========================================
@st.cache_data(ttl=120)
def fetch_data(uid, token):

    if not uid:
        return pd.DataFrame()

    headers = {"Authorization": f"Token {token}"} if token else {}

    url = f"https://kf.kobotoolbox.org/api/v2/assets/{uid}/data/?format=json&page_size=1000"

    results = []

    while url:
        try:
            r = requests.get(url, headers=headers, timeout=30)

            if r.status_code != 200:
                log_error(f"API error {r.status_code}")
                break

            data = r.json()
            results.extend(data.get("results", []))
            url = data.get("next")

        except Exception as e:
            log_error(e)
            break

    return pd.json_normalize(results)


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


DATE_COL = detect(["date", "time", "submission"])

if DATE_COL:
    df[DATE_COL] = pd.to_datetime(df[DATE_COL], errors="coerce")


# =========================================
# FILTERS
# =========================================
st.sidebar.subheader("Filters")

if DATE_COL:
    start = st.sidebar.date_input("Start", df[DATE_COL].min())
    end = st.sidebar.date_input("End", df[DATE_COL].max())

    df = df[(df[DATE_COL] >= pd.to_datetime(start)) &
            (df[DATE_COL] <= pd.to_datetime(end))]

search = st.sidebar.text_input("Search")

if search:
    df = df[df.astype(str).apply(
        lambda x: x.str.contains(search, case=False, na=False).any(),
        axis=1
    )]


# =========================================
# QUALITY ENGINE
# =========================================
num_cols = df.select_dtypes(include=["number"]).columns

df["anomaly_flag"] = False
df["ai_flag"] = False
df["quality_flag"] = False


# Z-score anomaly
if len(num_cols) > 0:
    try:
        z = np.abs(
            (df[num_cols] - df[num_cols].mean()) /
            df[num_cols].std().replace(0, 1)
        )
        df["anomaly_flag"] = z.max(axis=1) > 4.5
    except:
        pass


# AI anomaly
if ENABLE_AI and len(num_cols) > 2:
    try:
        model = IsolationForest(contamination=AI_CONTAMINATION)
        df["ai_flag"] = model.fit_predict(df[num_cols].fillna(0)) == -1
    except:
        pass


# Missing values
for col in df.columns:
    miss = df[col].isna() | (df[col].astype(str).str.strip() == "")
    df.loc[miss, "quality_flag"] = True


# =========================================
# FINAL SCORING
# =========================================
df["flag_score"] = (
    df["anomaly_flag"].astype(int) +
    df["ai_flag"].astype(int) +
    df["quality_flag"].astype(int)
)

df["final_flag"] = df["flag_score"] >= 1

clean_df = df[~df["final_flag"]]
flag_df = df[df["final_flag"]]


# =========================================
# OPTIONAL PERSISTENCE (SAFE)
# =========================================
def save_data():

    if engine is None:
        return

    try:
        df.to_sql("processed_data", engine, if_exists="append", index=False)
        flag_df.to_sql("flagged_data", engine, if_exists="append", index=False)
    except Exception as e:
        log_error(e)


save_data()


# =========================================
# KPI
# =========================================
total = len(df)
valid = len(clean_df)
bad = len(flag_df)

score = (valid / total) * 100 if total else 0


# =========================================
# UI
# =========================================
if page == "Dashboard":

    st.title(APP_NAME)

    c1, c2, c3, c4 = st.columns(4)

    c1.metric("Total", total)
    c2.metric("Valid", valid)
    c3.metric("Flagged", bad)
    c4.metric("Score", f"{score:.2f}%")

    st.plotly_chart(px.bar(x=["Valid", "Flagged"], y=[valid, bad]))


elif page == "Explorer":

    st.subheader("Clean Data")
    st.dataframe(clean_df, use_container_width=True)

    st.subheader("Flagged Data")
    st.dataframe(flag_df, use_container_width=True)


elif page == "Analytics":

    st.subheader("Quality Breakdown")

    summary = pd.DataFrame({
        "Issue": ["Anomaly", "AI", "Missing"],
        "Count": [
            df["anomaly_flag"].sum(),
            df["ai_flag"].sum(),
            df["quality_flag"].sum()
        ]
    })

    st.dataframe(summary)
    st.plotly_chart(px.pie(summary, names="Issue", values="Count"))


elif page == "Downloads":

    def to_excel(data):
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            data.to_excel(writer, index=False)
        buffer.seek(0)
        return buffer

    st.download_button("Clean Data", to_excel(clean_df))
    st.download_button("Flagged Data", to_excel(flag_df))


# =========================================
# FOOTER
# =========================================
st.caption(f"{APP_NAME} | {datetime.now()}")
