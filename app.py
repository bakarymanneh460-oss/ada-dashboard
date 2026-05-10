# =========================================
# REDI DATA QUALITY MONITORING SYSTEM
# ENTERPRISE FINAL STREAMLIT VERSION
# DEPLOYMENT-STABLE SINGLE ENTRY POINT
# =========================================

import streamlit as st
import pandas as pd
import numpy as np
import os
import logging
import requests
import yaml
import io

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


APP_NAME = "REDI Automated Data Quality Monitoring System"


# =========================================
# LOGGING (SAFE FOR PRODUCTION)
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
# AUTHENTICATION (STABLE)
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

auth_status = st.session_state.get("authentication_status")

if auth_status is False:
    st.error("Incorrect username or password")
    st.stop()

if auth_status is None:
    st.warning("Please login")
    st.stop()

username = st.session_state.get("username")
name = st.session_state.get("name")

authenticator.logout("Logout", "sidebar")


# =========================================
# ROLE SYSTEM
# =========================================
role = config["credentials"]["usernames"][username]["role"]

st.sidebar.success(f"Welcome {name}")
st.sidebar.info(f"Role: {role}")


# =========================================
# AUDIT LOGGING
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


log_action(username, "login")


# =========================================
# SIDEBAR INPUTS
# =========================================
st.sidebar.title("📊 REDI System")

FORM_UID = st.sidebar.text_input("Kobo Form UID")

KOBO_TOKEN = st.secrets.get("KOBO_TOKEN", None)


# =========================================
# SAFE DATA FETCHER
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
                log_error(f"Kobo API error: {r.status_code}")
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
    st.warning("No data found for this Form ID")
    st.stop()


# =========================================
# COLUMN DETECTION
# =========================================
def detect(cols):

    for col in df.columns:
        for c in cols:
            if c in col.lower():
                return col
    return None


DATE_COL = detect(["submission", "date", "time"])
ENUM_COL = detect(["enum", "enumerator", "user"])


if DATE_COL:
    df[DATE_COL] = pd.to_datetime(df[DATE_COL], errors="coerce")


# =========================================
# FILTERS
# =========================================
st.sidebar.subheader("Filters")

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
# NUMERIC FEATURES
# =========================================
num_cols = df.select_dtypes(include=["number"]).columns


# =========================================
# STATISTICAL ANOMALY DETECTION
# =========================================
df["anomaly_flag"] = False

try:
    if len(num_cols) > 0:

        z = np.abs(
            (df[num_cols] - df[num_cols].mean()) /
            df[num_cols].std().replace(0, 1)
        )

        df["anomaly_flag"] = z.max(axis=1) > 4.5

except Exception as e:
    log_error(e)


# =========================================
# AI ANOMALY DETECTION
# =========================================
df["ai_flag"] = False

try:
    if len(num_cols) > 2:

        model = IsolationForest(contamination=0.005, random_state=42)

        df["ai_flag"] = model.fit_predict(
            df[num_cols].fillna(0)
        ) == -1

except Exception as e:
    log_error(e)


# =========================================
# DATA QUALITY CHECKS
# =========================================
df["quality_flag"] = False

for col in df.columns:

    missing = (
        df[col].isna() |
        (df[col].astype(str).str.strip() == "")
    )

    df.loc[missing, "quality_flag"] = True


# =========================================
# FINAL SCORING ENGINE
# =========================================
df["flag_score"] = (
    df["anomaly_flag"].astype(int) +
    df["ai_flag"].astype(int) +
    df["quality_flag"].astype(int)
)

df["final_flag"] = df["flag_score"] >= 1


# =========================================
# SPLIT DATASETS
# =========================================
clean_df = df[~df["final_flag"]]
flag_df = df[df["final_flag"]]


# =========================================
# KPI METRICS
# =========================================
total = len(df)
valid = len(clean_df)
flagged = len(flag_df)

score = (valid / total) * 100 if total else 0


# =========================================
# NAVIGATION
# =========================================
page = st.sidebar.radio(
    "Navigation",
    ["Dashboard", "Explorer", "Analytics", "Downloads"]
)


# =========================================
# DASHBOARD
# =========================================
if page == "Dashboard":

    st.title(APP_NAME)

    c1, c2, c3, c4 = st.columns(4)

    c1.metric("Total Records", total)
    c2.metric("Valid Records", valid)
    c3.metric("Flagged Records", flagged)
    c4.metric("Quality Score", f"{score:.2f}%")

    fig = px.bar(
        x=["Valid", "Flagged"],
        y=[valid, flagged],
        title="Data Quality Overview"
    )

    st.plotly_chart(fig, use_container_width=True)


# =========================================
# EXPLORER
# =========================================
elif page == "Explorer":

    st.title("Data Explorer")

    tab1, tab2 = st.tabs(["Clean Data", "Flagged Data"])

    with tab1:
        st.dataframe(clean_df, use_container_width=True)

    with tab2:
        st.dataframe(flag_df, use_container_width=True)


# =========================================
# ANALYTICS
# =========================================
elif page == "Analytics":

    st.title("Quality Analytics")

    summary = pd.DataFrame({
        "Issue": ["Anomaly", "AI", "Missing"],
        "Count": [
            df["anomaly_flag"].sum(),
            df["ai_flag"].sum(),
            df["quality_flag"].sum()
        ]
    })

    st.dataframe(summary)

    fig = px.pie(summary, names="Issue", values="Count")
    st.plotly_chart(fig)


# =========================================
# DOWNLOADS
# =========================================
elif page == "Downloads":

    st.title("Export Data")

    def to_excel(data):
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            data.to_excel(writer, index=False)
        output.seek(0)
        return output

    st.download_button(
        "Download Clean Data",
        to_excel(clean_df),
        file_name="clean_data.xlsx"
    )

    st.download_button(
        "Download Flagged Data",
        to_excel(flag_df),
        file_name="flagged_data.xlsx"
    )


# =========================================
# FOOTER
# =========================================
st.caption(
    f"{APP_NAME} | Last Updated: {datetime.now()}"
)
