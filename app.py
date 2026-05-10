# =========================================
# REDI AUTOMATED DATA QUALITY MONITORING SYSTEM
# FINAL RESTORED PRODUCTION VERSION
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
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
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
# STYLE (CLEAN BLUE)
# =========================================
st.markdown("""
<style>

.stApp {
    background: linear-gradient(135deg, #f3f7ff, #dbeafe);
}

[data-testid="stForm"] {
    background:white;
    padding:40px;
    border-radius:18px;
    box-shadow:0 6px 18px rgba(0,0,0,0.15);
}

section[data-testid="stSidebar"] {
    background:#1e3a8a !important;
    color:white !important;
}

.kpi-card {
    padding:20px;
    border-radius:14px;
    color:white;
    text-align:center;
}

.btn-green{background:#16a34a;padding:10px;color:white;border-radius:8px;}
.btn-red{background:#dc2626;padding:10px;color:white;border-radius:8px;}
.btn-blue{background:#2563eb;padding:10px;color:white;border-radius:8px;}
.btn-purple{background:#7c3aed;padding:10px;color:white;border-radius:8px;}

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
logging.basicConfig(filename="logs/app.log", level=logging.ERROR)

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
auth_status = st.session_state.get("authentication_status")
username = st.session_state.get("username")

if auth_status is False:
    st.error("Wrong login")
    st.stop()

if auth_status is None:
    st.warning("Login required")
    st.stop()

authenticator.logout("Logout", "sidebar")

role = config["credentials"]["usernames"][username]["role"]

st.sidebar.success(f"Welcome {name}")
st.sidebar.info(f"Role: {role}")

# =========================================
# SIDEBAR
# =========================================
st.sidebar.title("📊 REDI System")

FORM_UID = st.sidebar.text_input("Kobo Form UID")

page = st.sidebar.radio(
    "Navigation",
    ["Dashboard", "Explorer", "Quality Analytics", "Downloads"]
)

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
        r = requests.get(url, headers=headers)
        if r.status_code != 200:
            break

        data = r.json()
        all_data.extend(data.get("results", []))
        url = data.get("next")

    return pd.json_normalize(all_data)

df = fetch_data(FORM_UID, st.secrets.get("KOBO_TOKEN", None))

if df.empty:
    st.warning("No data found")
    st.stop()

# =========================================
# COLUMN DETECTION
# =========================================
def detect(keys):
    for col in df.columns:
        for k in keys:
            if k in col.lower():
                return col
    return None

DATE_COL = detect(["submission_time","date","time"])
ENUM_COL = detect(["enum","enumerator","name"])

if DATE_COL:
    df[DATE_COL] = pd.to_datetime(df[DATE_COL], errors="coerce")

# =========================================
# FILTERS + MONTH
# =========================================
if DATE_COL:
    df["Month"] = df[DATE_COL].dt.to_period("M").astype(str)

# =========================================
# NUMERIC + QUANTITATIVE
# =========================================
num_cols = df.select_dtypes(include=["number"]).columns

if len(num_cols) > 0:
    z = np.abs((df[num_cols] - df[num_cols].mean()) /
               df[num_cols].std().replace(0,1))
    df["anomaly_flag"] = z.max(axis=1) > 4.5
else:
    df["anomaly_flag"] = False

if ENABLE_AI and len(num_cols) > 2:
    model = IsolationForest(contamination=AI_CONTAMINATION, random_state=42)
    df["ai_flag"] = model.fit_predict(df[num_cols].fillna(0)) == -1
else:
    df["ai_flag"] = False

# =========================================
# QUALITATIVE ENGINE (FULL RESTORED)
# =========================================
df["qualitative_flag"] = False

required = ["name","gender","age","region"]

for col in df.columns:
    if any(r in col.lower() for r in required):
        miss = df[col].isna() | (df[col].astype(str).str.strip()=="")
        df.loc[miss,"qualitative_flag"] = True

age_col = detect(["age"])

if age_col:
    bad = (pd.to_numeric(df[age_col], errors="coerce") < 0) | \
          (pd.to_numeric(df[age_col], errors="coerce") > 120)
    df.loc[bad,"qualitative_flag"] = True

# =========================================
# FINAL FLAGS
# =========================================
df["final_flag"] = (
    df["anomaly_flag"] |
    df["ai_flag"] |
    df["qualitative_flag"]
)

clean_df = df[~df["final_flag"]]
flag_df = df[df["final_flag"]]

total = len(df)
valid = len(clean_df)
bad = len(flag_df)
score = (valid/total*100) if total else 0

# =========================================
# DASHBOARD
# =========================================
if page == "Dashboard":

    st.title(APP_NAME)

    c1,c2,c3,c4 = st.columns(4)

    c1.metric("Total", total)
    c2.metric("Valid", valid)
    c3.metric("Flagged", bad)
    c4.metric("Quality Score", f"{score:.1f}%")

    st.bar_chart(pd.DataFrame({"Valid":[valid],"Flagged":[bad]}))

    if ENUM_COL:
        st.subheader("Enumerator Performance")
        st.dataframe(df.groupby(ENUM_COL).size().reset_index(name="submissions"))

# =========================================
# EXPLORER
# =========================================
elif page == "Explorer":
    st.dataframe(clean_df)
    st.dataframe(flag_df)

# =========================================
# ANALYTICS
# =========================================
elif page == "Quality Analytics":

    st.dataframe(pd.DataFrame({
        "Type":["Anomaly","AI","Qualitative"],
        "Count":[df["anomaly_flag"].sum(),
                 df["ai_flag"].sum(),
                 df["qualitative_flag"].sum()]
    }))

# =========================================
# DOWNLOADS
# =========================================
elif page == "Downloads":

    st.download_button("Clean CSV",
        clean_df.to_csv(index=False),"clean.csv")

    st.download_button("Flagged CSV",
        flag_df.to_csv(index=False),"flagged.csv")

# =========================================
# FOOTER
# =========================================
st.caption(f"{APP_NAME} | {datetime.now()}")
