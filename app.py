import streamlit as st
import pandas as pd
import io
import requests
from datetime import datetime
import numpy as np

import plotly.express as px

from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import colors

from sklearn.ensemble import IsolationForest

# ==============================
# CONFIG
# ==============================
st.set_page_config(page_title="REDI Data Quality System", layout="wide")

# ==============================
# STYLE (RESTORED UI)
# ==============================
st.markdown("""
<style>

section[data-testid="stSidebar"] {
    background-color:#1e3a8a !important;
}
section[data-testid="stSidebar"] * {
    color:white !important;
}
section[data-testid="stSidebar"] input {
    background:white !important;
    color:black !important;
}

.kpi-card {
    padding:20px;
    border-radius:12px;
    color:white;
    text-align:center;
    font-weight:bold;
}

.btn-green {
    background-color:#16a34a;
    color:white;
    padding:10px;
    border-radius:8px;
    font-weight:bold;
}

.btn-red {
    background-color:#dc2626;
    color:white;
    padding:10px;
    border-radius:8px;
    font-weight:bold;
}

</style>
""", unsafe_allow_html=True)

# ==============================
# SIDEBAR (ALWAYS VISIBLE)
# ==============================
st.sidebar.title("📊 REDI System")

FORM_UID = st.sidebar.text_input("Form UID")
KOBO_TOKEN = st.secrets.get("KOBO_TOKEN", None)

# ==============================
# LOGIN SYSTEM
# ==============================
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
    st.session_state.role = None
    st.session_state.username = None

def login(username, password):
    users = st.secrets["auth"]["users"]
    for u in users:
        if u["username"] == username and u["password"] == password:
            st.session_state.logged_in = True
            st.session_state.role = u["role"]
            st.session_state.username = username
            return True
    return False

def logout():
    st.session_state.logged_in = False
    st.session_state.role = None
    st.session_state.username = None

if not st.session_state.logged_in:

    st.sidebar.subheader("🔐 Login")

    username = st.sidebar.text_input("Username")
    password = st.sidebar.text_input("Password", type="password")

    if st.sidebar.button("Login"):
        if login(username, password):
            st.rerun()
        else:
            st.sidebar.error("Invalid credentials")

    st.warning("Please login to continue")
    st.stop()

st.sidebar.success(f"Logged in as {st.session_state.username}")

if st.sidebar.button("Logout"):
    logout()
    st.rerun()

# ==============================
# NAVIGATION
# ==============================
pages = ["Dashboard", "Explorer", "Downloads"]

if st.session_state.role == "admin":
    pages.append("Admin")

page = st.sidebar.radio("Navigation", pages)

# ==============================
# FETCH DATA
# ==============================
@st.cache_data(ttl=120)
def fetch_data(uid, token):
    if not uid:
        return pd.DataFrame()

    headers = {"Authorization": f"Token {token}"} if token else {}
    url = f"https://kf.kobotoolbox.org/api/v2/assets/{uid}/data/?format=json&page_size=1000"

    data_all = []
    while url:
        try:
            r = requests.get(url, headers=headers)
            if r.status_code != 200:
                break
            data = r.json()
            data_all.extend(data.get("results", []))
            url = data.get("next")
        except:
            break

    return pd.json_normalize(data_all)

df = fetch_data(FORM_UID, KOBO_TOKEN)

if df.empty:
    st.warning("No data found")
    st.stop()

# ==============================
# COLUMN DETECTION (FIXED)
# ==============================
def detect(keys):
    for col in df.columns:
        for k in keys:
            if k in col.lower():
                return col
    return None

DATE_COL = detect(["submission", "date", "time"]) or "_submission_time"
ENUM_COL = detect(["enum", "interviewer", "user"])
HH_COL = detect(["household", "hh", "id"])

if DATE_COL in df.columns:
    df[DATE_COL] = pd.to_datetime(df[DATE_COL], errors="coerce")

# ==============================
# NUMERIC COLUMNS
# ==============================
num_cols = df.select_dtypes(include=["number"]).columns

# ==============================
# ANOMALY DETECTION
# ==============================
df["anomaly_flag"] = False
df["fraud_flag"] = False
df["text_flag"] = False

# ---- Numeric anomaly
if len(num_cols) > 0:
    z = np.abs((df[num_cols] - df[num_cols].mean()) / df[num_cols].std().replace(0,1))
    df["anomaly_flag"] = z.max(axis=1) > 2.5

# ---- Text anomaly
for col in df.select_dtypes(include=["object"]).columns:
    s = df[col].astype(str).str.lower()
    df["text_flag"] |= s.str.len() < 2

# ---- Fraud detection
if ENUM_COL and DATE_COL in df.columns:
    df["time_diff"] = df.groupby(ENUM_COL)[DATE_COL].diff().dt.total_seconds()

    fast_users = df.groupby(ENUM_COL)["time_diff"].apply(
        lambda x: (x < 60).mean() > 0.6
    )

    df["fraud_flag"] = df[ENUM_COL].isin(fast_users[fast_users].index)

# ==============================
# AI EXPLANATION (PLAIN ENGLISH)
# ==============================
def explain(row):
    reasons = []

    if row["anomaly_flag"]:
        reasons.append("Unusual numeric values compared to dataset patterns")

    if row["text_flag"]:
        reasons.append("Missing or invalid text responses")

    if row["fraud_flag"]:
        reasons.append("Suspicious rapid submission pattern detected")

    if not reasons:
        return "No issues detected — data is consistent"

    return " | ".join(reasons)

df["ai_explanation"] = df.apply(explain, axis=1)

# ==============================
# QUALITY SCORE
# ==============================
df["quality_score"] = 100
df.loc[df["anomaly_flag"], "quality_score"] -= 40
df.loc[df["text_flag"], "quality_score"] -= 20
df.loc[df["fraud_flag"], "quality_score"] -= 20
df["quality_score"] = df["quality_score"].clip(0,100)

clean_df = df[df["quality_score"] >= 60]
flag_df = df[df["quality_score"] < 60]

# ==============================
# DASHBOARD (PLOTLY)
# ==============================
if page == "Dashboard":

    st.title("📊 REDI Data Quality Dashboard")

    c1, c2, c3, c4 = st.columns(4)

    c1.markdown(f'<div class="kpi-card" style="background:#2563eb">Total<br>{len(df)}</div>', unsafe_allow_html=True)
    c2.markdown(f'<div class="kpi-card" style="background:#16a34a">Clean<br>{len(clean_df)}</div>', unsafe_allow_html=True)
    c3.markdown(f'<div class="kpi-card" style="background:#dc2626">Flagged<br>{len(flag_df)}</div>', unsafe_allow_html=True)
    c4.markdown(f'<div class="kpi-card" style="background:#7c3aed">Score<br>{df["quality_score"].mean():.1f}</div>', unsafe_allow_html=True)

    fig1 = px.bar(
        x=["Clean", "Flagged"],
        y=[len(clean_df), len(flag_df)],
        color=["Clean", "Flagged"],
        color_discrete_map={"Clean":"#16a34a","Flagged":"#dc2626"}
    )
    st.plotly_chart(fig1, use_container_width=True)

    fig2 = px.histogram(df, x="quality_score", nbins=10)
    st.plotly_chart(fig2, use_container_width=True)

# ==============================
# EXPLORER
# ==============================
elif page == "Explorer":
    tab1, tab2 = st.tabs(["Clean", "Flagged"])

    tab1.dataframe(clean_df)
    tab2.dataframe(flag_df[["quality_score","ai_explanation"]])

# ==============================
# DOWNLOADS (FULL SYSTEM)
# ==============================
elif page == "Downloads":

    st.title("📥 Export Center")

    def to_excel(data):
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            data.to_excel(writer, index=False)
        output.seek(0)
        return output

    def pdf():

        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer)
        styles = getSampleStyleSheet()

        elements = []

        try:
            elements.append(Image("assets/logo.png", width=80, height=80))
        except:
            pass

        elements.append(Paragraph("REDI DATA QUALITY REPORT", styles["Title"]))
        elements.append(Spacer(1, 10))

        table = Table([
            ["Metric","Value"],
            ["Total",len(df)],
            ["Clean",len(clean_df)],
            ["Flagged",len(flag_df)],
            ["Avg Score",f"{df['quality_score'].mean():.2f}"]
        ])

        table.setStyle(TableStyle([
            ("BACKGROUND",(0,0),(-1,0),colors.grey),
            ("TEXTCOLOR",(0,0),(-1,0),colors.white),
            ("GRID",(0,0),(-1,-1),0.5,colors.black)
        ]))

        elements.append(table)
        elements.append(Spacer(1,20))
        elements.append(Paragraph(f"Generated: {datetime.now()}", styles["Normal"]))

        doc.build(elements)
        buffer.seek(0)
        return buffer

    st.download_button("Full Excel", to_excel(df), "full.xlsx")
    st.download_button("Clean Excel", to_excel(clean_df), "clean.xlsx")
    st.download_button("Flagged Excel", to_excel(flag_df), "flagged.xlsx")
    st.download_button("PDF Report", pdf(), "report.pdf")

# ==============================
# ADMIN PANEL
# ==============================
elif page == "Admin":

    st.title("🔐 Admin Panel")

    st.subheader("System Overview")
    st.write(df.describe(include="all"))

    st.subheader("AI Explanations")
    st.dataframe(df[df["quality_score"] < 60][["quality_score","ai_explanation"]])

# ==============================
# FOOTER
# ==============================
st.caption(f"Updated {datetime.now()}")
