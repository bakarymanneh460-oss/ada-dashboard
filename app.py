import streamlit as st
import pandas as pd
import numpy as np
import requests
import io
import hashlib
import sqlite3
from datetime import datetime

import plotly.express as px

from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet

# ==============================
# CONFIG
# ==============================
st.set_page_config(page_title="REDI ADA System", layout="wide")

# ==============================
# BLUE UI THEME
# ==============================
st.markdown("""
<style>
[data-testid="stAppViewContainer"] {
    background-color: #0b3d91;
}
h1,h2,h3,h4,h5,p,div {
    color:white !important;
}
section[data-testid="stSidebar"] {
    background-color:#062a63 !important;
}
section[data-testid="stSidebar"] * {
    color:white !important;
}
.kpi-card {
    padding:18px;
    border-radius:12px;
    color:white;
    text-align:center;
    font-weight:bold;
}
input, textarea {
    color:black !important;
}
</style>
""", unsafe_allow_html=True)

# ==============================
# DATABASE (USERS)
# ==============================
conn = sqlite3.connect("redi_users.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    username TEXT PRIMARY KEY,
    password TEXT,
    role TEXT,
    form_uid TEXT
)
""")
conn.commit()

# ==============================
# SESSION STATE
# ==============================
if "auth" not in st.session_state:
    st.session_state.auth = False
    st.session_state.user = None
    st.session_state.role = None
    st.session_state.form_uid = None

# ==============================
# SECURITY
# ==============================
def hash_pw(p):
    return hashlib.sha256(p.encode()).hexdigest()

def create_user(u,p,role,uid):
    try:
        cursor.execute(
            "INSERT INTO users VALUES (?,?,?,?)",
            (u, hash_pw(p), role, uid)
        )
        conn.commit()
        return True
    except:
        return False

def auth(u,p):
    cursor.execute("SELECT password, role, form_uid FROM users WHERE username=?", (u,))
    r = cursor.fetchone()
    if r and r[0] == hash_pw(p):
        return r[1], r[2]
    return None, None

def login(u,p):
    role, uid = auth(u,p)
    if role:
        st.session_state.auth = True
        st.session_state.user = u
        st.session_state.role = role
        st.session_state.form_uid = uid
        return True
    return False

def logout():
    st.session_state.auth = False

# ==============================
# LOGIN PAGE
# ==============================
if not st.session_state.auth:
    st.title("📊 REDI ADA System")

    with st.form("login"):
        u = st.text_input("Username")
        p = st.text_input("Password", type="password")
        if st.form_submit_button("Login"):
            if login(u,p):
                st.success("Login successful")
                st.rerun()
            else:
                st.error("Invalid credentials")

    st.stop()

# ==============================
# SIDEBAR
# ==============================
st.sidebar.title("REDI ADA System")
st.sidebar.success(st.session_state.user)

if st.sidebar.button("Logout"):
    logout()
    st.rerun()

# ==============================
# ADMIN PANEL
# ==============================
if st.session_state.role == "admin":
    st.sidebar.subheader("🔐 Admin Panel")

    nu = st.sidebar.text_input("New User")
    npw = st.sidebar.text_input("New Password", type="password")
    role = st.sidebar.selectbox("Role", ["admin","enumerator","viewer"])
    uid = st.sidebar.text_input("Form UID")

    if st.sidebar.button("Create User"):
        if create_user(nu,npw,role,uid):
            st.sidebar.success("User created")
        else:
            st.sidebar.error("User exists")

    st.sidebar.write(pd.read_sql("SELECT username,role FROM users", conn))

# ==============================
# DATA FETCH
# ==============================
@st.cache_data(ttl=120)
def fetch(uid):
    url = f"https://kf.kobotoolbox.org/api/v2/assets/{uid}/data/?format=json&page_size=1000"
    data = []

    while url:
        try:
            r = requests.get(url)
            j = r.json()
            data.extend(j.get("results", []))
            url = j.get("next")
        except:
            break

    return pd.json_normalize(data)

df = fetch(st.session_state.form_uid)

if df.empty:
    st.stop()

# ==============================
# ANALYTICS ENGINE
# ==============================
num_cols = df.select_dtypes(include=["number"]).columns

df["quant_anomaly"] = False
if len(num_cols):
    z = np.abs((df[num_cols] - df[num_cols].mean()) /
               df[num_cols].std().replace(0,1))
    df["quant_anomaly"] = z.max(axis=1) > 2.5

# ==============================
# QUALITATIVE ANALYSIS
# ==============================
text_cols = df.select_dtypes(include=["object"]).columns

def sentiment(t):
    t = str(t).lower()
    if any(x in t for x in ["bad","poor","no","hate"]):
        return "negative"
    if any(x in t for x in ["good","yes","better","improve"]):
        return "positive"
    return "neutral"

def theme(t):
    t = str(t).lower()
    if "school" in t: return "Education"
    if "health" in t: return "Health"
    if "money" in t: return "Finance"
    return "Other"

col = text_cols[0] if len(text_cols) else None

if col:
    df["sentiment"] = df[col].apply(sentiment)
    df["theme"] = df[col].apply(theme)
else:
    df["sentiment"] = "neutral"
    df["theme"] = "unknown"

# ==============================
# FRAUD CHECK
# ==============================
df["fraud"] = False
if "_submission_time" in df.columns:
    df["_submission_time"] = pd.to_datetime(df["_submission_time"], errors="coerce")
    df["speed"] = df["_submission_time"].diff().dt.total_seconds()
    df["fraud"] = df["speed"] < 60

# ==============================
# FINAL SCORE
# ==============================
df["score"] = 100
df.loc[df["quant_anomaly"], "score"] -= 40
df.loc[df["fraud"], "score"] -= 20
df.loc[df["sentiment"] == "negative", "score"] -= 10
df["score"] = df["score"].clip(0,100)

clean = df[df["score"] >= 60]
flagged = df[df["score"] < 60]

# ==============================
# DASHBOARD
# ==============================
st.title("📊 REDI ADA System")

c1,c2,c3,c4 = st.columns(4)

c1.markdown(f"### Total\n{len(df)}")
c2.markdown(f"### Clean\n{len(clean)}")
c3.markdown(f"### Flagged\n{len(flagged)}")
c4.markdown(f"### Score\n{df['score'].mean():.1f}")

fig = px.bar(
    x=["Clean","Flagged"],
    y=[len(clean),len(flagged)],
    color=["Clean","Flagged"],
    color_discrete_map={"Clean":"green","Flagged":"red"}
)

st.plotly_chart(fig)

# ==============================
# TABLE
# ==============================
st.subheader("Dataset")
st.dataframe(df)

# ==============================
# EXPORTS
# ==============================
st.subheader("Outputs")

def to_excel(d):
    out = io.BytesIO()
    with pd.ExcelWriter(out, engine="openpyxl") as w:
        d.to_excel(w,index=False)
    out.seek(0)
    return out

def pdf():
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf)
    s = getSampleStyleSheet()

    e = [
        Paragraph("REDI ADA MIXED-METHODS REPORT", s["Title"]),
        Spacer(1,10),
        Paragraph(f"Total: {len(df)}", s["Normal"]),
        Paragraph(f"Clean: {len(clean)}", s["Normal"]),
        Paragraph(f"Flagged: {len(flagged)}", s["Normal"]),
        Paragraph(f"Avg Score: {df['score'].mean():.2f}", s["Normal"]),
        Spacer(1,10),
        Paragraph("Sentiment & Theme analysis included", s["Normal"])
    ]

    doc.build(e)
    buf.seek(0)
    return buf

st.download_button("Full Excel", to_excel(df), "full.xlsx")
st.download_button("Clean Excel", to_excel(clean), "clean.xlsx")
st.download_button("Flagged Excel", to_excel(flagged), "flagged.xlsx")
st.download_button("PDF Report", pdf(), "report.pdf")
