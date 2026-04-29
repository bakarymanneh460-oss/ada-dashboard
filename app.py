import streamlit as st
import pandas as pd
import io
import requests
from datetime import datetime
import matplotlib.pyplot as plt
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image
from reportlab.lib.styles import getSampleStyleSheet
import base64
import numpy as np

# ==============================
# SAFE DB IMPORT
# ==============================
try:
    from sqlalchemy import create_engine
    DB_URL = st.secrets.get("DATABASE_URL", None)
    engine = create_engine(DB_URL) if DB_URL else None
except:
    engine = None

st.set_page_config(page_title="REDI Data Quality System", layout="wide")

# ==============================
# 🎨 UI STYLE (RESTORED)
# ==============================
st.markdown("""
<style>
section[data-testid="stSidebar"] {
    background-color: #1e3a8a !important;
}
section[data-testid="stSidebar"] * {
    color: white !important;
}
section[data-testid="stSidebar"] input,
section[data-testid="stSidebar"] textarea {
    background-color: white !important;
    color: black !important;
}
section[data-testid="stSidebar"] div[data-baseweb="input"] input {
    color: black !important;
}
.kpi-card {
    padding: 20px;
    border-radius: 12px;
    color: white;
    text-align: center;
}
</style>
""", unsafe_allow_html=True)

# ==============================
# SIDEBAR
# ==============================
st.sidebar.markdown("## 📊 REDI Data Quality System")
st.sidebar.caption("Field Data Quality & Monitoring Tool")

FORM_UID = st.sidebar.text_input("Form UID", "")
page = st.sidebar.radio("Navigation", ["Dashboard", "Explorer", "Downloads"])

KOBO_TOKEN = st.secrets.get("KOBO_TOKEN", None)

if engine:
    st.sidebar.success("🟢 Database connected")
else:
    st.sidebar.info("🟡 Using Kobo API")

# ==============================
# 🔄 MANUAL REFRESH
# ==============================
if st.sidebar.button("🔄 Refresh Data"):
    st.cache_data.clear()
    st.rerun()

# ==============================
# FETCH DATA
# ==============================
@st.cache_data(ttl=120)
def fetch_data(uid, token):

    if engine:
        try:
            df = pd.read_sql("SELECT * FROM clean_data", engine)
            if not df.empty:
                return df
        except:
            pass

    if not uid:
        return pd.DataFrame()

    url = f"https://kf.kobotoolbox.org/api/v2/assets/{uid}/data/"
    headers = {"Authorization": f"Token {token}"} if token else {}

    try:
        r = requests.get(url, headers=headers)
        if r.status_code != 200:
            return pd.DataFrame()
        return pd.json_normalize(r.json().get("results", []))
    except:
        return pd.DataFrame()

df = fetch_data(FORM_UID, KOBO_TOKEN)

if df.empty:
    st.warning("No data available")
    st.stop()

# ==============================
# PREP
# ==============================
if "_submission_time" in df.columns:
    df["_submission_time"] = pd.to_datetime(df["_submission_time"], errors="coerce")
    df["Month"] = df["_submission_time"].dt.to_period("M").astype(str)

# ==============================
# ANOMALY DETECTION
# ==============================
numeric_cols = df.select_dtypes(include=["number"]).columns

if len(numeric_cols) > 0:
    std = df[numeric_cols].std().replace(0, 1)
    z = np.abs((df[numeric_cols] - df[numeric_cols].mean()) / std)
    df["anomaly_flag"] = z.max(axis=1) > 3
else:
    df["anomaly_flag"] = False

clean_df = df[~df["anomaly_flag"]]
flag_df = df[df["anomaly_flag"]]

total = len(df)
valid = len(clean_df)
bad = len(flag_df)
score = (valid / total * 100) if total else 0

# ==============================
# DASHBOARD
# ==============================
if page == "Dashboard":

    st.title("📊 REDI Data Quality Dashboard")

    c1, c2, c3, c4 = st.columns(4)
    c1.markdown(f'<div class="kpi-card" style="background:#2563eb"><h3>Total</h3><h1>{total}</h1></div>', unsafe_allow_html=True)
    c2.markdown(f'<div class="kpi-card" style="background:#16a34a"><h3>Valid</h3><h1>{valid}</h1></div>', unsafe_allow_html=True)
    c3.markdown(f'<div class="kpi-card" style="background:#dc2626"><h3>Flagged</h3><h1>{bad}</h1></div>', unsafe_allow_html=True)
    c4.markdown(f'<div class="kpi-card" style="background:#7c3aed"><h3>Score</h3><h1>{score:.1f}%</h1></div>', unsafe_allow_html=True)

    st.bar_chart(pd.DataFrame({"Valid":[valid], "Flagged":[bad]}))

    # Enumerator
    enum_col = next((c for c in df.columns if "enumerator" in c.lower() or "name" in c.lower()), None)
    if enum_col:
        st.subheader("🚶 Enumerator Performance")

        enum_df = df.groupby(enum_col)["anomaly_flag"].agg(["count","sum"]).reset_index()
        enum_df["score"] = (1 - enum_df["sum"] / enum_df["count"]) * 100

        st.dataframe(enum_df.sort_values("score", ascending=False))
        st.bar_chart(enum_df.set_index(enum_col)["score"])

    # Household tracking
    if "HH_ID" in df.columns and "Month" in df.columns:
        st.subheader("🏠 Household Tracking")

        hh = df.groupby("HH_ID")["Month"].nunique().reset_index(name="months")
        hh["completeness_%"] = (hh["months"] / 12) * 100

        st.dataframe(hh.sort_values("completeness_%", ascending=False))
        st.bar_chart(hh["months"])

    # Monthly
    if "Month" in df.columns:
        st.subheader("📅 Monthly Trend")
        st.line_chart(df.groupby("Month").size())

    # Flagged
    st.subheader("⚠️ Flagged Data")
    st.dataframe(flag_df.head(50))

# ==============================
# EXPLORER
# ==============================
elif page == "Explorer":
    st.dataframe(df)

# ==============================
# DOWNLOADS
# ==============================
elif page == "Downloads":

    st.subheader("Download Center")

    st.download_button("📁 Clean CSV", clean_df.to_csv(index=False), "clean.csv")
    st.download_button("⚠️ Flagged CSV", flag_df.to_csv(index=False), "flagged.csv")

st.caption(f"Updated: {datetime.now()}")
