import streamlit as st
import pandas as pd
import numpy as np
import requests
import io
import hashlib
from datetime import datetime, timedelta

import plotly.express as px

from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import colors

# ==============================
# PAGE CONFIG
# ==============================
st.set_page_config(page_title="REDI SaaS Platform", layout="wide")

# ==============================
# STYLES (RESTORED ENTERPRISE UI)
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

/* KPI CARDS */
.kpi-card {
    padding:18px;
    border-radius:12px;
    color:white;
    text-align:center;
    font-weight:bold;
    box-shadow:0px 4px 10px rgba(0,0,0,0.15);
}

/* BUTTONS */
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
# SESSION INIT
# ==============================
if "auth" not in st.session_state:
    st.session_state.auth = False
    st.session_state.user = None
    st.session_state.role = None
    st.session_state.form_uid = None
    st.session_state.logs = []
    st.session_state.last_action = datetime.now()

# ==============================
# USERS (HASHED)
# ==============================
USERS = {
    "admin": {
        "password": hashlib.sha256("admin123".encode()).hexdigest(),
        "role": "admin",
        "form_uid": None
    },
    "enum1": {
        "password": hashlib.sha256("enum123".encode()).hexdigest(),
        "role": "enumerator",
        "form_uid": "LOCKED_FORM_UID_1"
    },
    "viewer1": {
        "password": hashlib.sha256("view123".encode()).hexdigest(),
        "role": "viewer",
        "form_uid": "LOCKED_FORM_UID_2"
    }
}

# ==============================
# LOGGING SYSTEM
# ==============================
def log(action):
    st.session_state.logs.append(
        f"{datetime.now()} | {st.session_state.user} | {action}"
    )

# ==============================
# SESSION TIMEOUT (15 MIN)
# ==============================
if st.session_state.auth:
    if datetime.now() - st.session_state.last_action > timedelta(minutes=15):
        st.warning("Session expired")
        st.session_state.auth = False
        st.rerun()

    st.session_state.last_action = datetime.now()

# ==============================
# LOGIN FUNCTION
# ==============================
def login(username, password):
    if username in USERS:
        hashed = hashlib.sha256(password.encode()).hexdigest()

        if USERS[username]["password"] == hashed:
            st.session_state.auth = True
            st.session_state.user = username
            st.session_state.role = USERS[username]["role"]
            st.session_state.form_uid = USERS[username]["form_uid"]

            log("LOGIN")
            return True
    return False

def logout():
    log("LOGOUT")
    st.session_state.auth = False
    st.session_state.user = None
    st.session_state.role = None
    st.session_state.form_uid = None

# ==============================
# LOGIN PAGE
# ==============================
if not st.session_state.auth:

    st.title("📊 REDI SaaS Platform")

    with st.form("login"):
        u = st.text_input("Username")
        p = st.text_input("Password", type="password")
        submit = st.form_submit_button("Login")

        if submit:
            if login(u, p):
                st.success("Login successful")
                st.rerun()
            else:
                st.error("Invalid credentials")

    st.stop()

# ==============================
# SIDEBAR (POST LOGIN)
# ==============================
st.sidebar.title("📊 REDI System")

st.sidebar.success(f"User: {st.session_state.user}")
st.sidebar.info(f"Role: {st.session_state.role}")

if st.sidebar.button("Logout"):
    logout()
    st.rerun()

# ==============================
# FORM UID (SAAS LOCKED)
# ==============================
FORM_UID = st.session_state.form_uid

if st.session_state.role == "admin":
    FORM_UID = st.sidebar.text_input("Form UID (Admin)")
else:
    st.sidebar.code(FORM_UID or "NO ACCESS")

if not FORM_UID:
    st.error("Form UID not assigned")
    st.stop()

# ==============================
# FETCH DATA
# ==============================
@st.cache_data(ttl=120)
def fetch_data(uid):
    url = f"https://kf.kobotoolbox.org/api/v2/assets/{uid}/data/?format=json&page_size=1000"

    all_data = []
    while url:
        try:
            r = requests.get(url)
            j = r.json()
            all_data.extend(j.get("results", []))
            url = j.get("next")
        except:
            break

    return pd.json_normalize(all_data)

df = fetch_data(FORM_UID)

if df.empty:
    st.warning("No data available")
    st.stop()

# ==============================
# COLUMN DETECTION
# ==============================
def detect(keys):
    for c in df.columns:
        for k in keys:
            if k in c.lower():
                return c
    return None

DATE_COL = detect(["submission", "time", "date"]) or "_submission_time"

if DATE_COL in df.columns:
    df[DATE_COL] = pd.to_datetime(df[DATE_COL], errors="coerce")

# ==============================
# ANOMALY ENGINE
# ==============================
num_cols = df.select_dtypes(include=["number"]).columns

df["anomaly_flag"] = False
df["text_flag"] = False
df["fraud_flag"] = False

if len(num_cols) > 0:
    z = np.abs((df[num_cols] - df[num_cols].mean()) /
               df[num_cols].std().replace(0, 1))
    df["anomaly_flag"] = z.max(axis=1) > 2.5

for c in df.select_dtypes(include=["object"]).columns:
    df["text_flag"] |= df[c].astype(str).str.len() < 2

if DATE_COL in df.columns:
    df["time_diff"] = df[DATE_COL].diff().dt.total_seconds()
    df["fraud_flag"] = df["time_diff"] < 60

# ==============================
# AI EXPLANATION
# ==============================
def explain(row):
    r = []
    if row["anomaly_flag"]:
        r.append("Unusual numeric pattern detected")
    if row["text_flag"]:
        r.append("Invalid text response")
    if row["fraud_flag"]:
        r.append("Rapid submission detected")
    return " | ".join(r) if r else "Clean record"

df["ai_explanation"] = df.apply(explain, axis=1)

# ==============================
# QUALITY SCORE
# ==============================
df["quality_score"] = 100
df.loc[df["anomaly_flag"], "quality_score"] -= 40
df.loc[df["text_flag"], "quality_score"] -= 20
df.loc[df["fraud_flag"], "quality_score"] -= 20
df["quality_score"] = df["quality_score"].clip(0, 100)

clean_df = df[df["quality_score"] >= 60]
flag_df = df[df["quality_score"] < 60]

# ==============================
# DASHBOARD
# ==============================
st.title("📊 REDI SaaS Dashboard")

c1, c2, c3, c4 = st.columns(4)

c1.markdown(f'<div class="kpi-card" style="background:#2563eb">Total<br>{len(df)}</div>', unsafe_allow_html=True)
c2.markdown(f'<div class="kpi-card" style="background:#16a34a">Clean<br>{len(clean_df)}</div>', unsafe_allow_html=True)
c3.markdown(f'<div class="kpi-card" style="background:#dc2626">Flagged<br>{len(flag_df)}</div>', unsafe_allow_html=True)
c4.markdown(f'<div class="kpi-card" style="background:#7c3aed">Score<br>{df["quality_score"].mean():.1f}</div>', unsafe_allow_html=True)

fig = px.bar(
    x=["Clean", "Flagged"],
    y=[len(clean_df), len(flag_df)],
    color=["Clean", "Flagged"],
    color_discrete_map={"Clean": "#16a34a", "Flagged": "#dc2626"}
)

st.plotly_chart(fig, use_container_width=True)

# ==============================
# EXPLORER
# ==============================
st.subheader("Data Explorer")

if st.session_state.role == "admin":
    st.dataframe(df)
elif st.session_state.role == "enumerator":
    st.dataframe(clean_df)
else:
    st.dataframe(clean_df[["quality_score"]])

# ==============================
# EXPORTS
# ==============================
st.subheader("Exports")

def to_excel(data):
    out = io.BytesIO()
    with pd.ExcelWriter(out, engine="openpyxl") as writer:
        data.to_excel(writer, index=False)
    out.seek(0)
    return out

def pdf():
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer)
    styles = getSampleStyleSheet()

    elements = [
        Paragraph("REDI SaaS REPORT", styles["Title"]),
        Spacer(1, 10),
        Paragraph(f"Total: {len(df)}", styles["Normal"]),
        Paragraph(f"Clean: {len(clean_df)}", styles["Normal"]),
        Paragraph(f"Flagged: {len(flag_df)}", styles["Normal"]),
        Paragraph(f"Score: {df['quality_score'].mean():.2f}", styles["Normal"]),
        Spacer(1, 10),
        Paragraph(f"Generated: {datetime.now()}", styles["Normal"]),
    ]

    doc.build(elements)
    buffer.seek(0)
    return buffer

st.download_button("Full Excel", to_excel(df), "full.xlsx")
st.download_button("Clean Excel", to_excel(clean_df), "clean.xlsx")
st.download_button("Flagged Excel", to_excel(flag_df), "flagged.xlsx")
st.download_button("PDF Report", pdf(), "report.pdf")

# ==============================
# AUDIT LOGS (ADMIN ONLY)
# ==============================
if st.session_state.role == "admin":
    st.subheader("🔐 Audit Logs")
    st.text("\n".join(st.session_state.logs))
