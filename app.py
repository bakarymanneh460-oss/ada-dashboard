import streamlit as st
import pandas as pd
import io
import requests
from datetime import datetime
import matplotlib.pyplot as plt
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
import numpy as np

# ==============================
# CONFIG
# ==============================
st.set_page_config(page_title="REDI Universal Data System", layout="wide")

# ==============================
# STYLE (ORIGINAL)
# ==============================
st.markdown("""
<style>
section[data-testid="stSidebar"] {background-color:#1e3a8a !important;}
section[data-testid="stSidebar"] * {color:white !important;}
section[data-testid="stSidebar"] input {background:white !important; color:black !important;}
.kpi-card {padding:20px;border-radius:12px;color:white;text-align:center;}
</style>
""", unsafe_allow_html=True)

# ==============================
# SIDEBAR (RESTORED + FINAL NAME)
# ==============================
st.sidebar.title("📊 REDI Universal Data System")
st.sidebar.caption("Field Data Quality Monitoring System")

FORM_UID = st.sidebar.text_input("Form UID")

page = st.sidebar.radio("Navigation", ["Dashboard", "Explorer", "Downloads"])

KOBO_TOKEN = st.secrets.get("KOBO_TOKEN", None)

st.sidebar.markdown("🟡 API Mode")

if st.sidebar.button("🔄 Refresh"):
    st.cache_data.clear()
    st.rerun()

# Placeholder for date filter positioning
DATE_PLACEHOLDER = st.sidebar.empty()

# ==============================
# FETCH (PAGINATION SAFE)
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
# SMART COLUMN DETECTION
# ==============================
def detect(names):
    for col in df.columns:
        for n in names:
            if n in col.lower():
                return col
    return None

DATE_COL = detect(["submission_time", "date", "time"])
HH_COL = detect(["hh", "household", "id"])
ENUM_COL = detect(["enum", "enumerator", "name", "user"])
REGION_COL = detect(["region", "district", "area"])

if "_submission_time" in df.columns:
    DATE_COL = "_submission_time"

if DATE_COL:
    df[DATE_COL] = pd.to_datetime(df[DATE_COL], errors="coerce")

# ==============================
# FILTERS (RESTORED)
# ==============================
if DATE_COL:
    c1, c2 = DATE_PLACEHOLDER.columns(2)
    start = c1.date_input("Start", df[DATE_COL].min())
    end = c2.date_input("End", df[DATE_COL].max())

    df = df[(df[DATE_COL] >= pd.to_datetime(start)) & (df[DATE_COL] <= pd.to_datetime(end))]

search = st.sidebar.text_input("Search")
if search:
    df = df[df.astype(str).apply(lambda x: x.str.contains(search, case=False, na=False).any(), axis=1)]

# ==============================
# PREP
# ==============================
if DATE_COL:
    df["Month"] = df[DATE_COL].dt.to_period("M").astype(str)

# ==============================
# ANOMALY DETECTION
# ==============================
num_cols = df.select_dtypes(include=["number"]).columns
if len(num_cols) > 0:
    std = df[num_cols].std().replace(0, 1)
    z = np.abs((df[num_cols] - df[num_cols].mean()) / std)
    df["anomaly_flag"] = z.max(axis=1) > 3
else:
    df["anomaly_flag"] = False

# ==============================
# SPLIT DATA
# ==============================
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

    st.title("📊 REDI Field Data Quality Monitoring System")

    c1, c2, c3, c4 = st.columns(4)
    c1.markdown(f'<div class="kpi-card" style="background:#2563eb"><h3>Total</h3><h1>{total}</h1></div>', unsafe_allow_html=True)
    c2.markdown(f'<div class="kpi-card" style="background:#16a34a"><h3>Valid</h3><h1>{valid}</h1></div>', unsafe_allow_html=True)
    c3.markdown(f'<div class="kpi-card" style="background:#dc2626"><h3>Flagged</h3><h1>{bad}</h1></div>', unsafe_allow_html=True)
    c4.markdown(f'<div class="kpi-card" style="background:#7c3aed"><h3>Score</h3><h1>{score:.1f}%</h1></div>', unsafe_allow_html=True)

    st.bar_chart(pd.DataFrame({"Valid": [valid], "Flagged": [bad]}))

    # Alerts
    st.subheader("🚨 Alerts")
    if df["anomaly_flag"].sum() > 0:
        st.error(f"{df['anomaly_flag'].sum()} anomalies detected")

    if "Month" in df.columns:
        st.subheader("Monthly Trend")
        st.line_chart(df.groupby("Month").size())

# ==============================
# EXPLORER
# ==============================
elif page == "Explorer":
    st.title("Explorer")

    tab1, tab2 = st.tabs(["Clean Data", "Flagged Data"])
    tab1.dataframe(clean_df)
    tab2.dataframe(flag_df)

# ==============================
# DOWNLOADS
# ==============================
elif page == "Downloads":

    st.title("Downloads")

    def to_excel():
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            clean_df.to_excel(writer, index=False, sheet_name="Clean")
            flag_df.to_excel(writer, index=False, sheet_name="Flagged")
        return output.getvalue()

    col1, col2, col3 = st.columns(3)

    col1.download_button("📊 Full Excel", to_excel(), "redi_data.xlsx")
    col2.download_button("✅ Clean CSV", clean_df.to_csv(index=False), "clean_data.csv")
    col3.download_button("⚠️ Flagged CSV", flag_df.to_csv(index=False), "flagged_data.csv")

# ==============================
# FOOTER
# ==============================
st.caption(f"Last updated: {datetime.now()}")
