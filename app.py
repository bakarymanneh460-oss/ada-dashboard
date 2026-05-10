# =========================================
# REDI ADA SYSTEM — TRUE FINAL STABLE VERSION
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
# CONFIG
# =========================================
st.set_page_config(page_title="REDI ADA System", layout="wide", page_icon="📊")

APP_NAME = "REDI ADA System"
ENABLE_AI = True
AI_CONTAMINATION = 0.015

# =========================================
# STYLING (FIXED VISIBILITY)
# =========================================
st.markdown("""
<style>
.stApp {background: linear-gradient(135deg,#f3f7ff,#dbeafe);}

section[data-testid="stSidebar"] {background-color:#1e3a8a !important;}
section[data-testid="stSidebar"] * {color:white !important;}

section[data-testid="stSidebar"] input {
    background:white !important;
    color:black !important;
    font-weight:700 !important;
    border-radius:8px !important;
}

section[data-testid="stSidebar"] .stDateInput input {
    color:black !important;
}

.kpi-card {
    padding:20px;border-radius:14px;color:white;text-align:center;
    box-shadow:0 4px 10px rgba(0,0,0,0.2);
}

.btn-green {background:#16a34a;color:white;padding:12px;border-radius:10px;}
.btn-red {background:#dc2626;color:white;padding:12px;border-radius:10px;}
.btn-blue {background:#2563eb;color:white;padding:12px;border-radius:10px;}
.btn-purple {background:#7c3aed;color:white;padding:12px;border-radius:10px;}
</style>
""", unsafe_allow_html=True)

# =========================================
# LOGGING
# =========================================
os.makedirs("logs", exist_ok=True)
logging.basicConfig(filename="logs/redi.log", level=logging.ERROR)

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
auth = st.session_state.get("authentication_status")
username = st.session_state.get("username")

if auth is False:
    st.error("Incorrect username or password")
    st.stop()

if auth is None:
    st.warning("Please login")
    st.stop()

authenticator.logout("Logout", "sidebar")

st.sidebar.success(f"Welcome {name}")
role = config["credentials"]["usernames"][username]["role"]
st.sidebar.info(f"Role: {role}")

# =========================================
# TOKEN
# =========================================
KOBO_TOKEN = st.secrets.get("KOBO_TOKEN")

if not KOBO_TOKEN:
    st.error("Missing KoBo API token")
    st.stop()

# =========================================
# SIDEBAR
# =========================================
st.sidebar.title("📊 REDI ADA System")

FORM_UID = st.sidebar.text_input("KoBo Form UID")

pages = ["Dashboard","Explorer","Quality Analytics","Downloads"]

if role == "enumerator":
    pages = ["Dashboard","Explorer"]
elif role == "supervisor":
    pages = ["Dashboard","Explorer","Quality Analytics"]

page = st.sidebar.radio("Navigation", pages)

# =========================================
# FETCH
# =========================================
@st.cache_data(ttl=120)
def fetch(uid, token):
    if not uid:
        return pd.DataFrame()

    headers = {"Authorization": f"Token {token}"}
    url = f"https://kf.kobotoolbox.org/api/v2/assets/{uid}/data/?format=json&page_size=1000"

    data = []
    while url:
        try:
            r = requests.get(url, headers=headers, timeout=30)
            if r.status_code != 200:
                break
            j = r.json()
            data.extend(j.get("results", []))
            url = j.get("next")
        except:
            break

    return pd.json_normalize(data)

# =========================================
# LOAD
# =========================================
with st.spinner("Fetching data..."):
    df = fetch(FORM_UID, KOBO_TOKEN)

if df.empty:
    st.warning("No data found")
    st.stop()

# =========================================
# DATE FILTER
# =========================================
def detect(names):
    for c in df.columns:
        for n in names:
            if n in c.lower():
                return c
    return None

DATE_COL = detect(["submission_time","date","time"])

if "_submission_time" in df.columns:
    DATE_COL = "_submission_time"

if DATE_COL:
    df[DATE_COL] = pd.to_datetime(df[DATE_COL], errors="coerce")

    st.sidebar.subheader("Filters")
    c1,c2 = st.sidebar.columns(2)

    start = c1.date_input("Start", df[DATE_COL].min())
    end = c2.date_input("End", df[DATE_COL].max())

    df = df[(df[DATE_COL]>=pd.to_datetime(start)) &
            (df[DATE_COL]<=pd.to_datetime(end))]

# =========================================
# NUMERIC
# =========================================
num_cols = df.select_dtypes(include=["number"]).columns

# =========================================
# STAT ANOMALY
# =========================================
if len(num_cols)>0:
    std = df[num_cols].std().replace(0,1)
    z = np.abs((df[num_cols]-df[num_cols].mean())/std)
    df["anomaly_flag"] = (z > 3).sum(axis=1) > 2
else:
    df["anomaly_flag"] = False

# =========================================
# AI
# =========================================
if ENABLE_AI and len(num_cols)>2:
    model = IsolationForest(contamination=AI_CONTAMINATION, random_state=42)
    df["ai_flag"] = model.fit_predict(df[num_cols].fillna(0)) == -1
else:
    df["ai_flag"] = False

# =========================================
# QUALITATIVE
# =========================================
df["qualitative_flag"] = False
df["qualitative_issue"] = ""

required_exact = ["name","age","gender","region"]

for col in df.columns:
    if col.lower() in required_exact:
        mask = df[col].isna() | (df[col].astype(str).str.strip()=="")
        df.loc[mask,"qualitative_flag"] = True
        df.loc[mask,"qualitative_issue"] += f"Missing {col}; "

bad = ["asdf","test","xxx","n/a","unknown"]

for col in df.select_dtypes(include="object"):
    mask = df[col].astype(str).str.lower().isin(bad)
    df.loc[mask,"qualitative_flag"] = True
    df.loc[mask,"qualitative_issue"] += f"Bad text {col}; "

# =========================================
# FINAL FLAG LOGIC (BALANCED)
# =========================================
df["final_flag"] = (
    df["qualitative_flag"] |
    df["anomaly_flag"] |
    df["ai_flag"]
)

# =========================================
# WHY FLAGGED
# =========================================
def explain_row(r):
    reasons = []

    if r["qualitative_flag"]:
        reasons.append(f"Data issue: {r['qualitative_issue']}")

    if r["anomaly_flag"]:
        reasons.append("Unusual numeric pattern detected")

    if r["ai_flag"]:
        reasons.append("AI anomaly detected")

    if not reasons:
        return "No issues"

    return " | ".join(reasons)

df["why_flagged"] = df.apply(explain_row, axis=1)

# =========================================
# SPLIT
# =========================================
clean = df[~df["final_flag"]]
flag = df[df["final_flag"]]

total=len(df)
valid=len(clean)
bad=len(flag)
score=(valid/total)*100 if total else 0

# =========================================
# DASHBOARD
# =========================================
if page=="Dashboard":
    st.title(APP_NAME)

    c1,c2,c3,c4 = st.columns(4)

    c1.markdown(f"<div class='kpi-card' style='background:#2563eb'><h3>Total</h3><h1>{total}</h1></div>",unsafe_allow_html=True)
    c2.markdown(f"<div class='kpi-card' style='background:#16a34a'><h3>Valid</h3><h1>{valid}</h1></div>",unsafe_allow_html=True)
    c3.markdown(f"<div class='kpi-card' style='background:#dc2626'><h3>Flagged</h3><h1>{bad}</h1></div>",unsafe_allow_html=True)
    c4.markdown(f"<div class='kpi-card' style='background:#7c3aed'><h3>Score</h3><h1>{score:.1f}%</h1></div>",unsafe_allow_html=True)

    st.plotly_chart(px.bar(
        pd.DataFrame({"Category":["Valid","Flagged"],"Count":[valid,bad]}),
        x="Category",y="Count",text="Count"
    ),use_container_width=True)

# =========================================
# EXPLORER
# =========================================
elif page=="Explorer":
    t1,t2 = st.tabs(["Clean","Flagged"])

    with t1:
        st.dataframe(clean, use_container_width=True)

    with t2:
        st.subheader("⚠️ Flagged Records (with Reasons)")
        cols = list(flag.columns)
        if "why_flagged" in cols:
            cols.insert(0, cols.pop(cols.index("why_flagged")))
        st.dataframe(flag[cols], use_container_width=True)

# =========================================
# QUALITY ANALYTICS
# =========================================
elif page=="Quality Analytics":
    summary = pd.DataFrame({
        "Category": ["Quantitative","Qualitative"],
        "Count": [
            int(df["anomaly_flag"].sum() + df["ai_flag"].sum()),
            int(df["qualitative_flag"].sum())
        ]
    })
    st.dataframe(summary)
    st.plotly_chart(px.pie(summary,names="Category",values="Count"))

# =========================================
# DOWNLOADS (FULL RESTORED)
# =========================================
elif page=="Downloads":

    st.title("Downloads & Reports")

    def to_excel(data):
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            data.to_excel(writer, index=False)
        output.seek(0)
        return output

    def full_excel():
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            clean.to_excel(writer, index=False, sheet_name="Clean")
            flag.to_excel(writer, index=False, sheet_name="Flagged")
        output.seek(0)
        return output

    def generate_pdf():
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer)
        styles = getSampleStyleSheet()

        elements = []
        elements.append(Paragraph("REDI Data Quality Report", styles["Title"]))
        elements.append(Spacer(1, 12))

        table_data = [
            ["Metric", "Value"],
            ["Total Records", str(total)],
            ["Valid Records", str(valid)],
            ["Flagged Records", str(bad)],
            ["Quality Score", f"{score:.2f}%"]
        ]

        table = Table(table_data)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,0), colors.grey),
            ("TEXTCOLOR", (0,0), (-1,0), colors.whitesmoke),
            ("GRID", (0,0), (-1,-1), 1, colors.black),
        ]))

        elements.append(table)
        doc.build(elements)
        buffer.seek(0)
        return buffer

    c1, c2, c3, c4 = st.columns(4)

    with c1:
        st.markdown('<div class="btn-blue">📊 Full Dataset Export</div>', unsafe_allow_html=True)
        st.download_button("Download Full Excel", full_excel(), "redi_full.xlsx")

    with c2:
        st.markdown('<div class="btn-green">✅ Clean Data Export</div>', unsafe_allow_html=True)
        st.download_button("Download Clean Excel", to_excel(clean), "clean.xlsx")

    with c3:
        st.markdown('<div class="btn-red">⚠️ Flagged Data Export</div>', unsafe_allow_html=True)
        st.download_button("Download Flagged Excel", to_excel(flag), "flagged.xlsx")

    with c4:
        st.markdown('<div class="btn-purple">📄 PDF Report</div>', unsafe_allow_html=True)
        st.download_button("Download PDF Report", generate_pdf(), "redi_report.pdf")

# =========================================
# FOOTER
# =========================================
st.caption(f"{APP_NAME} | {datetime.now()}")
