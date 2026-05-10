# =========================================
# REDI MULTI-FORM DATA QUALITY SYSTEM
# FINAL ENTERPRISE-READY STREAMLIT APP
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
# PAGE CONFIG
# =========================================
st.set_page_config(
    page_title="REDI Multi-Form System",
    layout="wide",
    page_icon="📊"
)

APP_NAME = "REDI Multi-Form Data Quality System"

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
# AUTH
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
    st.error("Invalid login")
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
# MULTI-FORM INPUT
# =========================================
st.sidebar.title("REDI System")

uid_input = st.sidebar.text_area("Enter Kobo UIDs (one per line)")

load_btn = st.sidebar.button("Load Forms")

KOBO_TOKEN = st.secrets.get("KOBO_TOKEN", None)

headers = {
    "Authorization": f"Token {KOBO_TOKEN}"
} if KOBO_TOKEN else {}

page = st.sidebar.radio(
    "Navigation",
    ["Dashboard", "Explorer", "Analytics", "Downloads"]
)

# =========================================
# SESSION STORAGE
# =========================================
if "datasets" not in st.session_state:
    st.session_state.datasets = {}

# =========================================
# UNIVERSAL KOBO FETCH
# =========================================
def fetch_form(uid):

    base_urls = [
        "https://kf.kobotoolbox.org",
        "https://eu.kobotoolbox.org"
    ]

    for base in base_urls:

        url = f"{base}/api/v2/assets/{uid}/data/?format=json&page_size=1000"

        rows = []

        try:
            while url:

                r = requests.get(url, headers=headers, timeout=30)

                if r.status_code != 200:
                    break

                data = r.json()

                if "results" in data:
                    rows.extend(data["results"])

                url = data.get("next")

            if rows:
                df = pd.json_normalize(rows)
                df["__form_id"] = uid
                df["__loaded_at"] = datetime.now()
                return df

        except Exception as e:
            log_error(e)
            continue

    return pd.DataFrame()

# =========================================
# LOAD FORMS
# =========================================
if load_btn and uid_input:

    uids = [u.strip() for u in uid_input.splitlines() if u.strip()]

    for uid in uids:

        with st.spinner(f"Loading {uid}"):

            df = fetch_form(uid)

            if not df.empty:
                st.session_state.datasets[uid] = df

    st.success(f"Loaded {len(st.session_state.datasets)} forms")

# =========================================
# COMBINE DATASETS
# =========================================
if st.session_state.datasets:
    df = pd.concat(st.session_state.datasets.values(), ignore_index=True)
else:
    df = pd.DataFrame()

if df.empty:
    st.warning("No data loaded")
    st.stop()

# =========================================
# QUALITY ENGINE
# =========================================
num_cols = df.select_dtypes(include=["number"]).columns

df["anomaly_flag"] = False
df["ai_flag"] = False
df["missing_flag"] = False

# Z-score anomaly
if len(num_cols) > 0:
    z = np.abs(
        (df[num_cols] - df[num_cols].mean()) /
        df[num_cols].std().replace(0, 1)
    )
    df["anomaly_flag"] = z.max(axis=1) > 4.5

# AI anomaly
if ENABLE_AI and len(num_cols) > 2:
    try:
        model = IsolationForest(contamination=AI_CONTAMINATION)
        df["ai_flag"] = model.fit_predict(df[num_cols].fillna(0)) == -1
    except Exception as e:
        log_error(e)

# Missing values
df["missing_flag"] = df.isna().any(axis=1)

# =========================================
# FINAL SCORING
# =========================================
df["flag_score"] = (
    df["anomaly_flag"].astype(int) +
    df["ai_flag"].astype(int) +
    df["missing_flag"].astype(int)
)

df["final_flag"] = df["flag_score"] >= 1

clean_df = df[~df["final_flag"]]
flag_df = df[df["final_flag"]]

# =========================================
# KPI
# =========================================
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

    c1.metric("Total Records", total)
    c2.metric("Valid Records", valid)
    c3.metric("Flagged Records", bad)
    c4.metric("Quality Score", f"{score:.2f}%")

    st.plotly_chart(px.bar(x=["Valid", "Flagged"], y=[valid, bad]))


    st.subheader("Form Breakdown")

    breakdown = pd.DataFrame([
        {
            "Form": uid,
            "Records": len(data)
        }
        for uid, data in st.session_state.datasets.items()
    ])

    st.dataframe(breakdown)


# =========================================
# EXPLORER
# =========================================
elif page == "Explorer":

    st.subheader("Clean Data")
    st.dataframe(clean_df, use_container_width=True)

    st.subheader("Flagged Data")
    st.dataframe(flag_df, use_container_width=True)


# =========================================
# ANALYTICS
# =========================================
elif page == "Analytics":

    st.subheader("Quality Breakdown")

    summary = pd.DataFrame({
        "Issue": ["Anomaly", "AI", "Missing"],
        "Count": [
            df["anomaly_flag"].sum(),
            df["ai_flag"].sum(),
            df["missing_flag"].sum()
        ]
    })

    st.dataframe(summary)
    st.plotly_chart(px.pie(summary, names="Issue", values="Count"))


# =========================================
# DOWNLOADS
# =========================================
elif page == "Downloads":

    def to_excel(data):
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            data.to_excel(writer, index=False)
        buffer.seek(0)
        return buffer

    st.download_button("Download Clean", to_excel(clean_df))
    st.download_button("Download Flagged", to_excel(flag_df))


# =========================================
# FOOTER
# =========================================
st.caption(f"{APP_NAME} | {datetime.now()}")
