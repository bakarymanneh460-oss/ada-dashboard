# =========================================
# REDI AUTOMATED DATA QUALITY MONITORING SYSTEM
# FINAL PRODUCTION (HARDENED + MULTI-UID + FAILSAFE)
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

from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet

import plotly.express as px

# Optional AI dependency safety
try:
    from sklearn.ensemble import IsolationForest
    AI_AVAILABLE = True
except:
    AI_AVAILABLE = False

# =========================================
# PAGE CONFIG
# =========================================
st.set_page_config(
    page_title="REDI Data Quality System",
    layout="wide",
    page_icon="📊"
)

# =========================================
# SAFE CONFIG LOADER
# =========================================
def safe_load_config():
    try:
        with open("config.yaml") as file:
            return yaml.load(file, Loader=SafeLoader)
    except:
        return None

config = safe_load_config()

# =========================================
# STYLING
# =========================================
st.markdown("""
<style>
.stApp { background: linear-gradient(135deg,#f3f7ff,#dbeafe); }
.kpi-card { padding:20px;border-radius:14px;color:white;text-align:center; }
</style>
""", unsafe_allow_html=True)

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
# AUTH SAFE MODE
# =========================================
if not config:
    st.error("Missing config.yaml")
    st.stop()

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
    st.error("Wrong credentials")
    st.stop()

if auth_status is None:
    st.warning("Login required")
    st.stop()

authenticator.logout("Logout", "sidebar")

# safe role fetch
role = config["credentials"]["usernames"].get(username, {}).get("role", "user")

# =========================================
# AUDIT
# =========================================
os.makedirs("audit", exist_ok=True)

def log_action(user, action):
    try:
        file = "audit/audit_log.csv"
        df = pd.DataFrame([{
            "user": user,
            "action": action,
            "time": datetime.now()
        }])

        if os.path.exists(file):
            df = pd.concat([pd.read_csv(file), df])

        df.to_csv(file, index=False)
    except Exception as e:
        logging.error(str(e))

log_action(username, "login")

# =========================================
# SIDEBAR
# =========================================
st.sidebar.title("📊 REDI System")

# MULTI UID SUPPORT (ENTERPRISE FIX)
uid_input = st.sidebar.text_area(
    "Kobo UID(s) (comma or new line separated)"
)

uids = [
    u.strip()
    for u in uid_input.replace("\n", ",").split(",")
    if u.strip()
]

KOBO_TOKEN = st.secrets.get("KOBO_TOKEN", None)

page_options = ["Dashboard", "Explorer", "Quality Analytics", "Downloads"]

if role == "enumerator":
    page_options = ["Dashboard", "Explorer"]
elif role == "supervisor":
    page_options = ["Dashboard", "Explorer", "Quality Analytics"]

page = st.sidebar.radio("Navigation", page_options)

# =========================================
# DATA FETCH (ROBUST + MULTI UID MERGE)
# =========================================
@st.cache_data(ttl=120)
def fetch_kobo(uid, token):

    if not uid:
        return pd.DataFrame()

    headers = {"Authorization": f"Token {token}"} if token else {}

    url = f"https://kf.kobotoolbox.org/api/v2/assets/{uid}/data/?format=json&page_size=1000"

    out = []

    while url:
        try:
            r = requests.get(url, headers=headers, timeout=30)
            if r.status_code != 200:
                logging.error(f"Kobo error {r.status_code}")
                break

            js = r.json()
            out.extend(js.get("results", []))
            url = js.get("next")

        except Exception as e:
            logging.error(str(e))
            break

    return pd.json_normalize(out)

# merge multiple UIDs
df_list = [fetch_kobo(u, KOBO_TOKEN) for u in uids if u]
df = pd.concat(df_list, ignore_index=True) if df_list else pd.DataFrame()

if df.empty:
    st.warning("No data found for UID(s)")
    st.stop()

# =========================================
# COLUMN DETECTION
# =========================================
def detect(cols):
    for c in df.columns:
        for k in cols:
            if k in c.lower():
                return c
    return None

DATE_COL = detect(["submission", "date", "time"])
ENUM_COL = detect(["enum", "user", "name"])
AGE_COL = detect(["age"])
GENDER_COL = detect(["gender", "sex"])

if DATE_COL:
    df[DATE_COL] = pd.to_datetime(df[DATE_COL], errors="coerce")

# =========================================
# FILTERS
# =========================================
st.sidebar.subheader("Filters")

if DATE_COL:
    min_d = df[DATE_COL].min()
    max_d = df[DATE_COL].max()

    c1, c2 = st.sidebar.columns(2)
    start = c1.date_input("Start", min_d)
    end = c2.date_input("End", max_d)

    df = df[(df[DATE_COL] >= pd.to_datetime(start)) &
            (df[DATE_COL] <= pd.to_datetime(end))]

# =========================================
# ANOMALY DETECTION
# =========================================
num = df.select_dtypes(include=np.number).columns

df["anomaly_flag"] = False
df["ai_flag"] = False

if len(num) > 0:
    z = np.abs((df[num] - df[num].mean()) / df[num].std().replace(0, 1))
    df["anomaly_flag"] = z.max(axis=1) > 4.5

    if AI_AVAILABLE and len(num) > 2:
        try:
            model = IsolationForest(contamination=0.005, random_state=42)
            df["ai_flag"] = model.fit_predict(df[num].fillna(0)) == -1
        except Exception as e:
            logging.error(str(e))

# =========================================
# QUALITATIVE FLAGS
# =========================================
df["qualitative_flag"] = False
df["qualitative_issue"] = ""

required = ["name", "gender", "age", "region"]

req_cols = [c for c in df.columns for r in required if r in c.lower()]

for c in req_cols:
    miss = df[c].isna() | (df[c].astype(str).str.strip() == "")
    df.loc[miss, "qualitative_flag"] = True
    df.loc[miss, "qualitative_issue"] += f"Missing {c}; "

# age rule
if AGE_COL:
    a = pd.to_numeric(df[AGE_COL], errors="coerce")
    bad = (a < 0) | (a > 120)
    df.loc[bad, "qualitative_flag"] = True
    df.loc[bad, "qualitative_issue"] += "Invalid age; "

# gender logic
if GENDER_COL:
    if "preg" in " ".join(df.columns).lower():
        preg_col = [c for c in df.columns if "preg" in c.lower()][0]

        mask = (
            df[GENDER_COL].astype(str).str.lower().str.contains("male", na=False)
            & df[preg_col].astype(str).str.lower().str.contains("yes", na=False)
        )

        df.loc[mask, "qualitative_flag"] = True
        df.loc[mask, "qualitative_issue"] += "Male pregnant; "

# =========================================
# FINAL FLAGS
# =========================================
df["flag_score"] = df[["anomaly_flag", "ai_flag", "qualitative_flag"]].sum(axis=1)
df["final_flag"] = df["flag_score"] > 0

clean_df = df[~df["final_flag"]]
flag_df = df[df["final_flag"]]

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

    st.title("REDI Data Quality Dashboard")

    c1, c2, c3, c4 = st.columns(4)

    c1.metric("Total", total)
    c2.metric("Valid", valid)
    c3.metric("Flagged", bad)
    c4.metric("Quality %", f"{score:.1f}")

    fig = px.bar(
        pd.DataFrame({"Type": ["Valid", "Flagged"], "Count": [valid, bad]}),
        x="Type", y="Count"
    )

    st.plotly_chart(fig, use_container_width=True)

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
elif page == "Quality Analytics":
    st.subheader("Issue Summary")

    summary = pd.DataFrame({
        "Issue": ["Anomaly", "AI", "Qualitative"],
        "Count": [
            df["anomaly_flag"].sum(),
            df["ai_flag"].sum(),
            df["qualitative_flag"].sum()
        ]
    })

    st.dataframe(summary)
    st.plotly_chart(px.pie(summary, names="Issue", values="Count"))

# =========================================
# DOWNLOADS
# =========================================
elif page == "Downloads":

    def excel(df_):
        out = io.BytesIO()
        with pd.ExcelWriter(out, engine="openpyxl") as w:
            df_.to_excel(w, index=False)
        out.seek(0)
        return out

    def pdf():
        buf = io.BytesIO()
        doc = SimpleDocTemplate(buf)
        styles = getSampleStyleSheet()

        elements = [
            Paragraph("REDI Report", styles["Title"]),
            Spacer(1, 12),
            Table([
                ["Metric", "Value"],
                ["Total", total],
                ["Valid", valid],
                ["Flagged", bad],
                ["Score", f"{score:.2f}%"]
            ])
        ]

        doc.build(elements)
        buf.seek(0)
        return buf

    st.download_button("Full Excel", excel(df), "full.xlsx")
    st.download_button("Clean Excel", excel(clean_df), "clean.xlsx")
    st.download_button("Flagged Excel", excel(flag_df), "flagged.xlsx")
    st.download_button("PDF Report", pdf(), "report.pdf")

# =========================================
# FOOTER
# =========================================
st.caption(f"REDI System | Updated {datetime.now()}")
