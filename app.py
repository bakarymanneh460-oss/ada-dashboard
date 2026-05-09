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
st.set_page_config(page_title="REDI Automated Data Quality Monitoring System", layout="wide")

# ==============================
# AUTH SYSTEM
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
# STYLE
# ==============================
st.markdown("""
<style>
section[data-testid="stSidebar"] {background-color:#1e3a8a !important;}
section[data-testid="stSidebar"] * {color:white !important;}
.kpi-card {padding:20px;border-radius:12px;color:white;text-align:center;font-weight:bold;}
.btn-green {background-color:#16a34a;color:white;padding:12px;border-radius:10px;text-align:center;font-weight:bold;}
.btn-red {background-color:#dc2626;color:white;padding:12px;border-radius:10px;text-align:center;font-weight:bold;}
</style>
""", unsafe_allow_html=True)

# ==============================
# LOGIN UI
# ==============================
if not st.session_state.logged_in:
    st.sidebar.subheader("🔐 Login")
    username = st.sidebar.text_input("Username")
    password = st.sidebar.text_input("Password", type="password")

    if st.sidebar.button("Login"):
        if login(username, password):
            st.sidebar.success("Login successful")
            st.rerun()
        else:
            st.sidebar.error("Invalid credentials")

    st.stop()

# ==============================
# SIDEBAR AFTER LOGIN
# ==============================
st.sidebar.success(f"Logged in as {st.session_state.username}")

if st.sidebar.button("Logout"):
    logout()
    st.rerun()

FORM_UID = st.sidebar.text_input("Form UID")
KOBO_TOKEN = st.secrets.get("KOBO_TOKEN", None)

# ROLE-BASED NAVIGATION
pages = ["Dashboard", "Explorer", "Downloads"]
if st.session_state.role == "admin":
    pages.append("Admin")

page = st.sidebar.radio("Navigation", pages)

if st.sidebar.button("🔄 Refresh"):
    st.cache_data.clear()
    st.rerun()

# ==============================
# FETCH
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
# DETECT
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
# NUMERIC
# ==============================
num_cols = df.select_dtypes(include=["number"]).columns

# ==============================
# ADAPTIVE THRESHOLDS
# ==============================
def compute_adaptive(df):
    thresholds = {}

    if len(num_cols) > 0:
        std = df[num_cols].std().replace(0, 1)
        z = np.abs((df[num_cols] - df[num_cols].mean()) / std)
        thresholds["z"] = max(2.5, min(z.stack().quantile(0.95), 4))

        Q1 = df[num_cols].quantile(0.25)
        Q3 = df[num_cols].quantile(0.75)
        IQR = Q3 - Q1
        thresholds["iqr"] = max(1.5, min(1.5 + IQR.mean(), 3))
    else:
        thresholds["z"] = 3
        thresholds["iqr"] = 1.5

    if DATE_COL and ENUM_COL:
        df["time_diff"] = df.groupby(ENUM_COL)[DATE_COL].diff().dt.total_seconds()
        fast = df["time_diff"].dropna().quantile(0.10)
        thresholds["fast"] = max(20, min(fast, 120))
    else:
        thresholds["fast"] = 60

    return thresholds

adaptive = compute_adaptive(df)

# ==============================
# FLAGS
# ==============================
df["anomaly_flag"] = False
df["text_flag"] = False
df["fraud_flag"] = False

if len(num_cols) > 0:
    std = df[num_cols].std().replace(0,1)
    z = np.abs((df[num_cols] - df[num_cols].mean()) / std)
    df["anomaly_flag"] = z.max(axis=1) > adaptive["z"]

for col in df.select_dtypes(include=["object"]).columns:
    s = df[col].astype(str).str.lower()
    df["text_flag"] |= s.isin(["", "na", "test"])

if ENUM_COL and DATE_COL:
    fast = adaptive["fast"]
    ratio = df.groupby(ENUM_COL)["time_diff"].apply(lambda x: (x < fast).mean())
    bad_enum = ratio[ratio > 0.7].index
    df["fraud_flag"] = df[ENUM_COL].isin(bad_enum)

# ==============================
# QUALITY SCORE
# ==============================
df["quality_score"] = 100
df.loc[df["anomaly_flag"], "quality_score"] -= 40
df.loc[df["text_flag"], "quality_score"] -= 20
df.loc[df["fraud_flag"], "quality_score"] -= 20
df["quality_score"] = df["quality_score"].clip(0,100)

flag_df = df[df["quality_score"] < 50]
clean_df = df[df["quality_score"] >= 50]

# ==============================
# DASHBOARD
# ==============================
if page == "Dashboard":
    st.title("📊 REDI Dashboard")

    c1,c2,c3,c4 = st.columns(4)
    c1.markdown(f'<div class="kpi-card" style="background:#2563eb">Total<br><h1>{len(df)}</h1></div>', unsafe_allow_html=True)
    c2.markdown(f'<div class="kpi-card" style="background:#16a34a">Valid<br><h1>{len(clean_df)}</h1></div>', unsafe_allow_html=True)
    c3.markdown(f'<div class="kpi-card" style="background:#dc2626">Flagged<br><h1>{len(flag_df)}</h1></div>', unsafe_allow_html=True)
    c4.markdown(f'<div class="kpi-card" style="background:#7c3aed">Avg Score<br><h1>{df["quality_score"].mean():.1f}</h1></div>', unsafe_allow_html=True)

# ==============================
# EXPLORER
# ==============================
elif page == "Explorer":
    tab1,tab2 = st.tabs(["Clean","Flagged"])
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

    st.download_button("Download Clean", to_excel(clean_df))
    st.download_button("Download Flagged", to_excel(flag_df))
    st.download_button("Download PDF", pdf())

# ==============================
# ADMIN PANEL
# ==============================
elif page == "Admin":

    st.title("🔐 Admin Panel")

    st.subheader("Adaptive Thresholds")
    st.write(adaptive)

    st.subheader("Flag Summary")
    st.write(df[["anomaly_flag","text_flag","fraud_flag"]].sum())

    st.dataframe(df)

# ==============================
# FOOTER
# ==============================
st.caption(f"Updated {datetime.now()}")
