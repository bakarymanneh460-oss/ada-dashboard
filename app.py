# =========================================
# REDI AUTOMATED DATA QUALITY MONITORING SYSTEM
# FINAL UPGRADED PRODUCTION VERSION
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

# =========================================
# BASIC STYLE
# =========================================
st.markdown("""
<style>
.stApp {
    background: linear-gradient(135deg,#f3f7ff,#dbeafe);
}
</style>
""", unsafe_allow_html=True)

# =========================================
# CONFIG
# =========================================
APP_NAME = "REDI Data Quality Monitoring System"
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
# AUTH (SAFE LOAD)
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
# SIDEBAR
# =========================================
st.sidebar.title("REDI System")

FORM_UID = st.sidebar.text_input("Kobo Form UID")

page = st.sidebar.radio("Navigation", [
    "Dashboard",
    "Explorer",
    "Quality Analytics",
    "Downloads"
])

CALIBRATION = st.sidebar.checkbox("🧪 Calibration Mode")

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
        r = requests.get(url, headers=headers, timeout=30)

        if r.status_code != 200:
            break

        data = r.json()
        all_data.extend(data.get("results", []))
        url = data.get("next")

    return pd.json_normalize(all_data)


KOBO_TOKEN = st.secrets.get("KOBO_TOKEN", None)
df = fetch_data(FORM_UID, KOBO_TOKEN)

if df.empty:
    st.warning("No data found")
    st.stop()

# =========================================
# COLUMN DETECTION
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
# NUMERIC + AI ANOMALY
# =========================================
num_cols = df.select_dtypes(include=["number"]).columns

if len(num_cols) > 0:
    std = df[num_cols].std().replace(0, 1)
    z = np.abs((df[num_cols] - df[num_cols].mean()) / std)
    df["anomaly_flag"] = z.max(axis=1) > 4.5
else:
    df["anomaly_flag"] = False

if ENABLE_AI and len(num_cols) > 2:
    model = IsolationForest(contamination=AI_CONTAMINATION, random_state=42)
    df["ai_flag"] = model.fit_predict(df[num_cols].fillna(0)) == -1
else:
    df["ai_flag"] = False

# =========================================
# QUALITATIVE ENGINE (FIXED)
# =========================================
df["qualitative_score"] = 0.0
df["qualitative_warning"] = ""

required_keywords = ["name", "gender", "age", "region", "district"]
required_cols = [c for c in df.columns if any(k in c.lower() for k in required_keywords)]

for col in required_cols:
    missing = df[col].isna() | (df[col].astype(str).str.strip() == "")
    df.loc[missing, "qualitative_score"] = df.loc[missing, "qualitative_score"] + 2
    df.loc[missing, "qualitative_warning"] += f"Missing {col}; "

text_cols = df.select_dtypes(include=["object"]).columns

invalid_patterns = ["asdf", "test", "xxx", "na", "n/a", "unknown"]

for col in text_cols:
    mask = df[col].astype(str).str.lower().isin(invalid_patterns)
    df.loc[mask, "qualitative_score"] = df.loc[mask, "qualitative_score"] + 1
    df.loc[mask, "qualitative_warning"] += f"Invalid text {col}; "

common_errors = {
    "teh":"the","recieve":"receive","adress":"address",
    "tdak":"tidak","sya":"saya","rumh":"rumah"
}

for col in text_cols:
    lower = df[col].astype(str).str.lower()
    for w, c in common_errors.items():
        mask = lower.str.contains(w, na=False)
        df.loc[mask, "qualitative_score"] = df.loc[mask, "qualitative_score"] + 0.5
        df.loc[mask, "qualitative_warning"] += f"{w}->{c}; "

df["qualitative_flag"] = df["qualitative_score"] >= 3

# =========================================
# RISK ENGINE
# =========================================
df["risk_score"] = (
    df["anomaly_flag"].astype(int) * 3 +
    df["ai_flag"].astype(int) * 4 +
    df["qualitative_score"]
)

def risk(x):
    if x >= 6:
        return "High Risk"
    elif x >= 3:
        return "Medium Risk"
    elif x > 0:
        return "Low Risk"
    return "Clean"

df["risk_level"] = df["risk_score"].apply(risk)

clean_df = df[df["risk_level"] == "Clean"]
flag_df = df[df["risk_level"] != "Clean"]

# =========================================
# KPI
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

    st.plotly_chart(
        px.histogram(df, x="risk_level", color="risk_level"),
        use_container_width=True
    )

# =========================================
# EXPLORER
# =========================================
elif page == "Explorer":

    st.title("Data Explorer")

    tab1, tab2 = st.tabs(["Clean", "Flagged"])

    with tab1:
        st.dataframe(clean_df)

    with tab2:
        st.dataframe(flag_df)

# =========================================
# ANALYTICS
# =========================================
elif page == "Quality Analytics":

    st.title("Quality Analytics")

    st.metric("AI Outliers", df["ai_flag"].sum())
    st.metric("Rule Anomalies", df["anomaly_flag"].sum())
    st.metric("Qualitative Score", df["qualitative_score"].sum())

    st.plotly_chart(
        px.pie(
            names=df["risk_level"].value_counts().index,
            values=df["risk_level"].value_counts().values
        ),
        use_container_width=True
    )

# =========================================
# DOWNLOADS
# =========================================
elif page == "Downloads":

    st.title("Downloads")

    def to_excel(data):
        out = io.BytesIO()
        with pd.ExcelWriter(out, engine="openpyxl") as w:
            data.to_excel(w, index=False)
        return out.getvalue()

    st.download_button("Full Data", to_excel(df), "full.xlsx")
    st.download_button("Clean Data", to_excel(clean_df), "clean.xlsx")
    st.download_button("Flagged Data", to_excel(flag_df), "flagged.xlsx")

# =========================================
# CALIBRATION MODE
# =========================================
if CALIBRATION:

    st.subheader("Calibration Sample (50 rows)")

    sample = df.sample(min(50, len(df)))

    st.dataframe(sample[[
        "risk_score",
        "risk_level",
        "qualitative_warning"
    ]])

# =========================================
# FOOTER
# =========================================
st.caption(f"{APP_NAME} | {datetime.now()}")
