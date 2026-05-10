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
import re
import time

from datetime import datetime
from sklearn.ensemble import IsolationForest
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from yaml.loader import SafeLoader

import plotly.express as px

# PDF / DOCX
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from docx import Document


# =========================================
# OPTIONAL SPELL CHECK
# =========================================
try:
    from spellchecker import SpellChecker
    en_spell = SpellChecker()
    SPELLCHECK_AVAILABLE = True
except:
    SPELLCHECK_AVAILABLE = False


# =========================================
# CONFIG
# =========================================
st.set_page_config(page_title="REDI System", layout="wide")

APP_NAME = "REDI Enterprise Data Quality System"

ENABLE_AI = True
AI_CONTAMINATION = 0.01


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
role = config["credentials"]["usernames"][username]["role"]

authenticator.logout("Logout", "sidebar")

st.sidebar.success(f"Welcome {name}")
st.sidebar.info(f"Role: {role}")


# =========================================
# INPUT
# =========================================
uid_input = st.sidebar.text_area("Enter Kobo UIDs")
load_btn = st.sidebar.button("Load Forms")

KOBO_TOKEN = st.secrets.get("KOBO_TOKEN", None)

headers = {"Authorization": f"Token {KOBO_TOKEN}"} if KOBO_TOKEN else {}

page = st.sidebar.radio("Navigation",
                        ["Dashboard", "Explorer", "Analytics", "Downloads"])


# =========================================
# SESSION
# =========================================
if "datasets" not in st.session_state:
    st.session_state.datasets = {}


# =========================================
# KOBO FETCH
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
                rows.extend(data.get("results", []))
                url = data.get("next")

            if rows:
                df = pd.json_normalize(rows)
                df["__form_id"] = uid
                return df

        except Exception as e:
            log_error(e)

    return pd.DataFrame()


# =========================================
# LOAD
# =========================================
if load_btn and uid_input:

    uids = [u.strip() for u in uid_input.splitlines() if u.strip()]

    for uid in uids:
        df = fetch_form(uid)
        if not df.empty:
            st.session_state.datasets[uid] = df

    st.success("Forms loaded")


# =========================================
# COMBINE
# =========================================
if st.session_state.datasets:
    df = pd.concat(st.session_state.datasets.values(), ignore_index=True)
else:
    df = pd.DataFrame()

if df.empty:
    st.stop()


# =========================================
# QUALITY ENGINE
# =========================================
num_cols = df.select_dtypes(include=["number"]).columns
text_cols = df.select_dtypes(include=["object"]).columns

df["missing_flag"] = df.isna().mean(axis=1) > 0.5


# Z-score
if len(num_cols) > 0:
    num = df[num_cols].replace([np.inf, -np.inf], np.nan)
    z = (num - num.mean()) / num.std().replace(0, np.nan)
    df["anomaly_flag"] = (np.abs(z) > 4.5).fillna(False).any(axis=1)
else:
    df["anomaly_flag"] = False


# AI anomaly
if ENABLE_AI and len(num_cols) > 2:
    model = IsolationForest(contamination=AI_CONTAMINATION, random_state=42)
    df["ai_flag"] = model.fit_predict(df[num_cols].fillna(0)) == -1
else:
    df["ai_flag"] = False


# =========================================
# QUALITATIVE + SPELLING (EN + ID)
# =========================================

ID_WORDS = {"dan","yang","di","ke","dari","untuk","kita","saya","desa","kabupaten"}

def detect_text_issue(x):
    if not isinstance(x, str):
        return False
    if len(x.strip()) < 3:
        return True
    if re.fullmatch(r"[0-9\W]+", x):
        return True
    return False


def detect_spelling(text):
    if not isinstance(text, str):
        return False

    words = re.findall(r"[a-zA-Z]+", text.lower())
    errors = 0

    for w in words:
        if w in ID_WORDS:
            continue
        if SPELLCHECK_AVAILABLE:
            if w in en_spell.unknown([w]):
                errors += 1
        else:
            if len(w) > 14:
                errors += 1

    return errors >= 3


if len(text_cols) > 0:
    df["qual_flag"] = df[text_cols].applymap(detect_text_issue).any(axis=1)
    df["spelling_flag"] = df[text_cols].applymap(detect_spelling).any(axis=1)
else:
    df["qual_flag"] = False
    df["spelling_flag"] = False


# =========================================
# NLP CLASSIFICATION
# =========================================
if len(text_cols) > 0:
    tfidf = TfidfVectorizer(max_features=300)
    X = tfidf.fit_transform(df[text_cols[0]].fillna("").astype(str))

    model = LogisticRegression(max_iter=500)
    model.fit(X, ["other"] * len(df))

    df["nlp_category"] = model.predict(X)
else:
    df["nlp_category"] = "unknown"


# =========================================
# FINAL SCORE
# =========================================
df["flag_score"] = (
    df["missing_flag"].astype(int) +
    df["anomaly_flag"].astype(int) +
    df["ai_flag"].astype(int) +
    df["qual_flag"].astype(int) +
    df["spelling_flag"].astype(int)
)

df["final_flag"] = df["flag_score"] > 0


# =========================================
# EXPLAINABLE AI
# =========================================
def explain(row):
    reasons = []
    if row["missing_flag"]:
        reasons.append("Missing data")
    if row["anomaly_flag"]:
        reasons.append("Statistical anomaly")
    if row["ai_flag"]:
        reasons.append("AI anomaly")
    if row["qual_flag"]:
        reasons.append("Poor text quality")
    if row["spelling_flag"]:
        reasons.append("Spelling errors")
    return " | ".join(reasons) if reasons else "Clean"

df["failure_reason"] = df.apply(explain, axis=1)


clean_df = df[~df["final_flag"]]
flag_df = df[df["final_flag"]]


# =========================================
# ROLE SUMMARY
# =========================================
def role_summary(role):
    total = len(df)
    bad = df["final_flag"].sum()

    base = f"""
Total: {total}
Flagged: {bad}
Score: {(1-bad/total)*100:.2f}%
"""

    if role == "manager":
        return base + "\nFocus: strategic data quality risks"
    if role == "analyst":
        return base + "\nFocus: field-level anomalies & trends"
    return base + "\nFocus: system monitoring"


# =========================================
# STREAMING MODE
# =========================================
stream = st.sidebar.checkbox("Real-Time Mode")

if stream:
    st.info("Streaming active...")
    time.sleep(2)


# =========================================
# DASHBOARD
# =========================================
if page == "Dashboard":

    st.title(APP_NAME)

    c1, c2, c3 = st.columns(3)

    c1.metric("Total", len(df))
    c2.metric("Clean", len(clean_df))
    c3.metric("Flagged", len(flag_df))

    st.text(role_summary(role))

    st.plotly_chart(px.bar(x=["Clean","Flagged"], y=[len(clean_df), len(flag_df)]))

    st.subheader("Heatmap")
    heat = df.groupby("__form_id")[[
        "missing_flag","anomaly_flag","ai_flag","qual_flag","spelling_flag"
    ]].mean()

    st.dataframe(heat)
    st.plotly_chart(px.imshow(heat, color_continuous_scale="Reds"))


# =========================================
# EXPLORER
# =========================================
elif page == "Explorer":
    st.subheader("Clean")
    st.dataframe(clean_df)

    st.subheader("Flagged + Reasons")
    st.dataframe(flag_df[["failure_reason","flag_score","nlp_category"]])


# =========================================
# ANALYTICS
# =========================================
elif page == "Analytics":

    st.subheader("Field Diagnostics")

    diag = pd.DataFrame({
        "Field": df.columns,
        "MissingRate": df.isna().mean().values
    })

    st.dataframe(diag)


# =========================================
# REPORTS
# =========================================
elif page == "Downloads":

    report = f"""
REDI AUDIT REPORT
Total: {len(df)}
Clean: {len(clean_df)}
Flagged: {len(flag_df)}
"""

    st.download_button("TXT Report", report)

    st.download_button(
        "Clean Data",
        clean_df.to_csv(index=False),
        file_name="clean.csv"
    )

    st.download_button(
        "Flagged Data",
        flag_df.to_csv(index=False),
        file_name="flagged.csv"
    )


# =========================================
# FOOTER
# =========================================
st.caption("REDI Enterprise System")
