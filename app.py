# =========================================
# REDI AUTOMATED DATA QUALITY MONITORING SYSTEM
# ENTERPRISE FINAL PRODUCTION app.py
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
    page_title="REDI Data Quality System",
    layout="wide",
    page_icon="📊"
)

APP_NAME = "REDI Automated Data Quality Monitoring System"

ENABLE_AI = True
AI_CONTAMINATION = 0.005


# =========================================
# LOGGING (ENTERPRISE SAFE)
# =========================================
os.makedirs("logs", exist_ok=True)

logging.basicConfig(
    filename="logs/redi.log",
    level=logging.ERROR,
    format="%(asctime)s %(levelname)s %(message)s"
)

def log_error(e):
    logging.error(str(e))


def log_event(user, action, status="success"):
    os.makedirs("audit", exist_ok=True)

    df = pd.DataFrame([{
        "user": user,
        "action": action,
        "status": status,
        "time": datetime.utcnow()
    }])

    file = "audit/events.csv"

    if os.path.exists(file):
        old = pd.read_csv(file)
        df = pd.concat([old, df])

    df.to_csv(file, index=False)


# =========================================
# SAFE SECRETS
# =========================================
def safe_secret(key, default=None):
    try:
        return st.secrets.get(key, default)
    except Exception:
        return default


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

log_event(username, "login")


# =========================================
# ROLE SYSTEM
# =========================================
role = config["credentials"]["usernames"][username]["role"]

st.sidebar.success(f"Welcome {name}")
st.sidebar.info(f"Role: {role}")


# =========================================
# ROLE ENFORCEMENT (ENTERPRISE FIX)
# =========================================
def enforce_role(role, page):

    rules = {
        "enumerator": ["Dashboard", "Explorer"],
        "supervisor": ["Dashboard", "Explorer", "Quality Analytics"],
        "admin": ["Dashboard", "Explorer", "Quality Analytics", "Downloads"]
    }

    if page not in rules.get(role, []):
        st.error("Access Denied")
        st.stop()


# =========================================
# SIDEBAR
# =========================================
st.sidebar.title("📊 REDI System")

FORM_UID = st.sidebar.text_input("Kobo Form UID")

KOBO_TOKEN = safe_secret("KOBO_TOKEN", None)


# =========================================
# SAFE DATA FETCH (RETRY LOGIC)
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
    st.warning("No data found")
    st.stop()


# =========================================
# SYSTEM HEALTH
# =========================================
def system_health(df):

    return {
        "rows": len(df),
        "columns": len(df.columns),
        "missing_rate": float(df.isna().mean().mean()),
        "status": "GREEN" if len(df) > 0 else "RED"
    }


st.sidebar.success(f"System: {system_health(df)['status']}")


# =========================================
# COLUMN DETECTION
# =========================================
def detect(names):

    for col in df.columns:
        for n in names:
            if n in col.lower():
                return col
    return None


DATE_COL = detect(["submission", "date", "time"])

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
# NUMERIC COLUMNS
# =========================================
num_cols = df.select_dtypes(include=["number"]).columns


# =========================================
# ANOMALY DETECTION
# =========================================
df["anomaly_flag"] = False

if len(num_cols) > 0:
    try:
        z = np.abs(
            (df[num_cols] - df[num_cols].mean()) /
            df[num_cols].std().replace(0, 1)
        )
        df["anomaly_flag"] = z.max(axis=1) > 4.5
    except Exception as e:
        log_error(e)


# =========================================
# AI DETECTION
# =========================================
df["ai_flag"] = False

if ENABLE_AI and len(num_cols) > 2:
    try:
        model = IsolationForest(contamination=AI_CONTAMINATION, random_state=42)
        df["ai_flag"] = model.fit_predict(df[num_cols].fillna(0)) == -1
    except Exception as e:
        log_error(e)


# =========================================
# QUALITY CHECKS
# =========================================
df["quality_flag"] = False

for col in df.columns:
    missing = df[col].isna() | (df[col].astype(str).str.strip() == "")
    df.loc[missing, "quality_flag"] = True


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
# KPI
# =========================================
total = len(df)
valid = len(clean_df)
bad = len(flag_df)

score = (valid / total) * 100 if total else 0


# =========================================
# NAVIGATION
# =========================================
page = st.sidebar.radio(
    "Navigation",
    ["Dashboard", "Explorer", "Quality Analytics", "Downloads"]
)

enforce_role(role, page)


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

    fig = px.bar(x=["Valid", "Flagged"], y=[valid, bad])
    st.plotly_chart(fig, use_container_width=True)


# =========================================
# EXPLORER
# =========================================
elif page == "Explorer":

    st.title("Data Explorer")

    st.dataframe(clean_df, use_container_width=True)
    st.dataframe(flag_df, use_container_width=True)


# =========================================
# ANALYTICS
# =========================================
elif page == "Quality Analytics":

    st.title("Analytics")

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


# =========================================
# DOWNLOADS
# =========================================
elif page == "Downloads":

    st.title("Exports")

    def to_excel(data):
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            data.to_excel(writer, index=False)
        output.seek(0)
        return output

    st.download_button("Clean Data", to_excel(clean_df), file_name="clean.xlsx")
    st.download_button("Flagged Data", to_excel(flag_df), file_name="flagged.xlsx")


# =========================================
# FOOTER
# =========================================
st.caption(f"{APP_NAME} | {datetime.now()}")
