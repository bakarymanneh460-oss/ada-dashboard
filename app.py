import streamlit as st
import pandas as pd
import io
import requests
from datetime import datetime
import numpy as np
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from sklearn.ensemble import IsolationForest

# ==============================
# CONFIG
# ==============================
st.set_page_config(page_title="REDI System", layout="wide")

# ==============================
# SIDEBAR (ALWAYS FIRST)
# ==============================
st.sidebar.title("📊 REDI System")

FORM_UID = st.sidebar.text_input("Form UID")
KOBO_TOKEN = st.secrets.get("KOBO_TOKEN", None)

# ==============================
# SESSION STATE
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

# ==============================
# LOGIN UI (BLOCK ACCESS IF NOT LOGGED IN)
# ==============================
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

# ==============================
# AFTER LOGIN SIDEBAR
# ==============================
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

    all_data = []
    while url:
        try:
            r = requests.get(url, headers=headers)
            if r.status_code != 200:
                break
            data = r.json()
            all_data.extend(data.get("results", []))
            url = data.get("next")
        except:
            break

    return pd.json_normalize(all_data)

df = fetch_data(FORM_UID, KOBO_TOKEN)

if df.empty:
    st.warning("No data found")
    st.stop()

# ==============================
# COLUMN DETECTION
# ==============================
def detect(names):
    for col in df.columns:
        for n in names:
            if n in col.lower():
                return col
    return None

DATE_COL = detect(["submission_time", "date"])
ENUM_COL = detect(["enum", "user"])
HH_COL = detect(["hh", "household"])

if "_submission_time" in df.columns:
    DATE_COL = "_submission_time"

if DATE_COL:
    df[DATE_COL] = pd.to_datetime(df[DATE_COL], errors="coerce")

# ==============================
# NUMERIC COLUMNS
# ==============================
num_cols = df.select_dtypes(include=["number"]).columns

# ==============================
# ANOMALY DETECTION
# ==============================
df["anomaly_flag"] = False

if len(num_cols) > 0:
    std = df[num_cols].std().replace(0, 1)
    z = np.abs((df[num_cols] - df[num_cols].mean()) / std)
    df["anomaly_flag"] = z.max(axis=1) > 3

# ==============================
# TEXT CHECK
# ==============================
df["text_flag"] = False
for col in df.select_dtypes(include=["object"]).columns:
    s = df[col].astype(str).str.lower()
    df["text_flag"] |= s.isin(["", "na", "n/a", "test", "none"])

# ==============================
# FRAUD CHECK (FAST SUBMISSIONS)
# ==============================
df["fraud_flag"] = False

if ENUM_COL and DATE_COL:
    df["time_diff"] = df.groupby(ENUM_COL)[DATE_COL].diff().dt.total_seconds()
    fast_users = df.groupby(ENUM_COL)["time_diff"].apply(lambda x: (x < 30).mean() > 0.7)
    df["fraud_flag"] = df[ENUM_COL].isin(fast_users[fast_users].index)

# ==============================
# QUALITY SCORE
# ==============================
df["quality_score"] = 100
df.loc[df["anomaly_flag"], "quality_score"] -= 40
df.loc[df["text_flag"], "quality_score"] -= 20
df.loc[df["fraud_flag"], "quality_score"] -= 20
df["quality_score"] = df["quality_score"].clip(0, 100)

flag_df = df[df["quality_score"] < 50]
clean_df = df[df["quality_score"] >= 50]

# ==============================
# DASHBOARD
# ==============================
if page == "Dashboard":

    st.title("📊 REDI Dashboard")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total", len(df))
    c2.metric("Valid", len(clean_df))
    c3.metric("Flagged", len(flag_df))
    c4.metric("Avg Score", f"{df['quality_score'].mean():.1f}")

# ==============================
# EXPLORER
# ==============================
elif page == "Explorer":
    tab1, tab2 = st.tabs(["Clean", "Flagged"])
    tab1.dataframe(clean_df)
    tab2.dataframe(flag_df)

# ==============================
# DOWNLOADS
# ==============================
elif page == "Downloads":

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

        content = [
            Paragraph("REDI Report", styles['Title']),
            Paragraph(f"Total: {len(df)}", styles['Normal']),
            Paragraph(f"Valid: {len(clean_df)}", styles['Normal']),
            Paragraph(f"Flagged: {len(flag_df)}", styles['Normal']),
        ]

        doc.build(content)
        buffer.seek(0)
        return buffer

    st.download_button("Full Excel", to_excel(df))
    st.download_button("Clean Excel", to_excel(clean_df))
    st.download_button("Flagged Excel", to_excel(flag_df))
    st.download_button("PDF Report", pdf())

# ==============================
# ADMIN PANEL (ONLY ADMIN)
# ==============================
elif page == "Admin":

    st.title("🔐 Admin Panel")

    st.subheader("Raw Data")
    st.dataframe(df)

    st.subheader("Flag Summary")
    st.write({
        "Anomalies": int(df["anomaly_flag"].sum()),
        "Text Issues": int(df["text_flag"].sum()),
        "Fraud Flags": int(df["fraud_flag"].sum())
    })

# ==============================
# FOOTER
# ==============================
st.caption(f"Updated {datetime.now()}")
