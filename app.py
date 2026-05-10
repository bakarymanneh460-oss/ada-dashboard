# =========================================
# REDI AUTOMATED DATA QUALITY MONITORING SYSTEM
# FINAL PRODUCTION STABLE VERSION
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
# CONFIG
# =========================================
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
# FETCH DATA
# =========================================
@st.cache_data(ttl=120)
def fetch_data(uid):
    if not uid:
        return pd.DataFrame()

    url = f"https://kf.kobotoolbox.org/api/v2/assets/{uid}/data/?format=json&page_size=1000"

    try:
        r = requests.get(url, timeout=30)

        if r.status_code != 200:
            return pd.DataFrame()

        data = r.json().get("results", [])
        return pd.json_normalize(data)

    except Exception as e:
        logging.error(str(e))
        return pd.DataFrame()

# =========================================
# SIDEBAR
# =========================================
st.sidebar.title("REDI System")

FORM_UID = st.sidebar.text_input("Kobo UID")

# =========================================
# LOAD DATA
# =========================================
df = fetch_data(FORM_UID)

if df.empty:
    st.warning("No data found")
    st.stop()

# =========================================
# SAFE INITIALIZATION (CRITICAL FIX)
# =========================================
df["qualitative_flag"] = False
df["qualitative_issue"] = ""
df["qualitative_score"] = 0.0   # FIX: prevents TypeError crash

# =========================================
# NUMERIC HANDLING
# =========================================
num_cols = df.select_dtypes(include=["number"]).columns

df["anomaly_flag"] = False
df["ai_flag"] = False

if len(num_cols) > 0:

    std = df[num_cols].std().replace(0, 1)
    z = np.abs((df[num_cols] - df[num_cols].mean()) / std)

    df["anomaly_flag"] = (z.max(axis=1) > 4.5)

# =========================================
# AI ANOMALY DETECTION
# =========================================
if ENABLE_AI and len(num_cols) > 2:

    try:
        model = IsolationForest(
            contamination=AI_CONTAMINATION,
            random_state=42
        )

        ai_df = df[num_cols].apply(pd.to_numeric, errors="coerce").fillna(0)

        pred = model.fit_predict(ai_df)
        df["ai_flag"] = (pred == -1)

    except Exception as e:
        logging.error(str(e))
        df["ai_flag"] = False

# =========================================
# QUALITATIVE ENGINE (STABLE)
# =========================================

text_cols = df.select_dtypes(include=["object"]).columns

# -----------------------------------------
# Soft noise handling (NOT hard flags)
# -----------------------------------------
soft_noise = ["test", "unknown", "n/a", "na", "xxx"]

for col in text_cols:

    lower = df[col].astype(str).str.lower()

    for val in soft_noise:

        mask = lower.str.contains(val, na=False)

        df.loc[mask, "qualitative_score"] = (
            df.loc[mask, "qualitative_score"].fillna(0) + 0.3
        )

        df.loc[mask, "qualitative_issue"] = (
            df.loc[mask, "qualitative_issue"].fillna("") +
            f"Soft noise ({val}) in {col}; "
        )

# -----------------------------------------
# REQUIRED FIELDS
# -----------------------------------------
required_keywords = ["name", "gender", "age", "region", "district"]

for col in df.columns:

    for key in required_keywords:

        if key in col.lower():

            mask = df[col].isna() | (df[col].astype(str).str.strip() == "")

            df.loc[mask, "qualitative_flag"] = True

            df.loc[mask, "qualitative_score"] += 1.0

            df.loc[mask, "qualitative_issue"] = (
                df.loc[mask, "qualitative_issue"].fillna("") +
                f"Missing {col}; "
            )

# -----------------------------------------
# SPELLING CHECK (LOW WEIGHT)
# -----------------------------------------
common_errors = {
    "teh": "the",
    "recieve": "receive",
    "adress": "address",
    "tdak": "tidak",
    "sya": "saya"
}

for col in text_cols:

    lower = df[col].astype(str).str.lower()

    for wrong, correct in common_errors.items():

        mask = lower.str.contains(wrong, na=False)

        df.loc[mask, "qualitative_score"] += 0.2

        df.loc[mask, "qualitative_issue"] = (
            df.loc[mask, "qualitative_issue"].fillna("") +
            f"Spelling {wrong}->{correct}; "
        )

# =========================================
# FINAL FLAGS (STABLE)
# =========================================
df["flag_score"] = (
    df["anomaly_flag"].fillna(False).astype(int) +
    df["ai_flag"].fillna(False).astype(int) +
    (df["qualitative_score"] > 1).astype(int)
)

df["final_flag"] = df["flag_score"] >= 1

# =========================================
# SPLIT DATA
# =========================================
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

c1, c2, c3 = st.columns(3)

c1.metric("Total Records", total)
c2.metric("Valid Records", valid)
c3.metric("Flagged Records", bad)

st.metric("Quality Score", f"{score:.2f}%")

# =========================================
# BREAKDOWN
# =========================================
st.subheader("Quality Breakdown")

breakdown = pd.DataFrame({
    "Type": ["Rule Issues", "AI Issues", "Data Noise"],
    "Count": [
        df["anomaly_flag"].sum(),
        df["ai_flag"].sum(),
        (df["qualitative_score"] > 1).sum()
    ]
})

st.dataframe(breakdown)

fig = px.bar(breakdown, x="Type", y="Count")
st.plotly_chart(fig, use_container_width=True)

# =========================================
# EXPLORER
# =========================================
st.subheader("Explorer")

tab1, tab2 = st.tabs(["Clean", "Flagged"])

with tab1:
    st.dataframe(clean_df, use_container_width=True)

with tab2:
    st.dataframe(flag_df, use_container_width=True)

# =========================================
# FOOTER
# =========================================
st.caption(f"{APP_NAME} | {datetime.now()}")
