import streamlit as st
import pandas as pd
import io
import requests
from datetime import datetime
import numpy as np
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet

# ==============================
# CONFIG
# ==============================
st.set_page_config(page_title="REDI Universal Data System", layout="wide")

# ==============================
# STYLE
# ==============================
st.markdown("""
<style>
section[data-testid="stSidebar"] {background-color:#1e3a8a !important;}
section[data-testid="stSidebar"] * {color:white !important;}
section[data-testid="stSidebar"] input {background:white !important; color:black !important;}

.kpi-card {padding:20px;border-radius:12px;color:white;text-align:center;}

.btn-green {
    background-color:#16a34a;
    color:white;
    padding:12px;
    border-radius:10px;
    text-align:center;
    font-weight:bold;
}
.btn-red {
    background-color:#dc2626;
    color:white;
    padding:12px;
    border-radius:10px;
    text-align:center;
    font-weight:bold;
}
</style>
""", unsafe_allow_html=True)

# ==============================
# SIDEBAR
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

DATE_PLACEHOLDER = st.sidebar.empty()

# ==============================
# FETCH (pagination safe)
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
# SMART DETECTION
# ==============================
def detect(names):
    for col in df.columns:
        for n in names:
            if n in col.lower():
                return col
    return None

DATE_COL = detect(["submission_time","date","time"])
if "_submission_time" in df.columns:
    DATE_COL = "_submission_time"

ENUM_COL = detect(["enum","enumerator","name","user"])

if DATE_COL:
    df[DATE_COL] = pd.to_datetime(df[DATE_COL], errors="coerce")

# ==============================
# FILTERS
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
    std = df[num_cols].std().replace(0,1)
    z = np.abs((df[num_cols] - df[num_cols].mean()) / std)
    df["anomaly_flag"] = z.max(axis=1) > 3
else:
    df["anomaly_flag"] = False

# ==============================
# ENUMERATOR PERFORMANCE
# ==============================
if ENUM_COL and DATE_COL:
    df = df.sort_values(DATE_COL)

    df["time_diff"] = df.groupby(ENUM_COL)[DATE_COL].diff().dt.total_seconds()

    enum_perf = df.groupby(ENUM_COL).agg(
        total=("time_diff","count"),
        fast=("time_diff", lambda x: (x < 60).sum())
    ).reset_index()

    enum_perf["fraud_score"] = ((enum_perf["fast"]/enum_perf["total"]).fillna(0)*100).clip(upper=100)

    df = df.merge(enum_perf[[ENUM_COL,"fraud_score"]], on=ENUM_COL, how="left")

    df["fraud_flag"] = df["fraud_score"] > 50
else:
    df["fraud_flag"] = False

# ==============================
# SPLIT
# ==============================
clean_df = df[~df["anomaly_flag"]]
flag_df = df[df["anomaly_flag"]]

total = len(df)
valid = len(clean_df)
bad = len(flag_df)
score = (valid/total*100) if total else 0

# ==============================
# DASHBOARD
# ==============================
if page == "Dashboard":

    st.title("📊 REDI Field Data Quality Monitoring System")

    c1,c2,c3,c4 = st.columns(4)
    c1.markdown(f'<div class="kpi-card" style="background:#2563eb"><h3>Total</h3><h1>{total}</h1></div>', unsafe_allow_html=True)
    c2.markdown(f'<div class="kpi-card" style="background:#16a34a"><h3>Valid</h3><h1>{valid}</h1></div>', unsafe_allow_html=True)
    c3.markdown(f'<div class="kpi-card" style="background:#dc2626"><h3>Flagged</h3><h1>{bad}</h1></div>', unsafe_allow_html=True)
    c4.markdown(f'<div class="kpi-card" style="background:#7c3aed"><h3>Score</h3><h1>{score:.1f}%</h1></div>', unsafe_allow_html=True)

    st.bar_chart(pd.DataFrame({"Valid":[valid],"Flagged":[bad]}))

    # Enumerator Dashboard
    if ENUM_COL:
        st.subheader("Enumerator Performance")

        e = df.groupby(ENUM_COL).agg(
            submissions=("anomaly_flag","count"),
            issues=("anomaly_flag","sum")
        ).reset_index()

        e["quality_score"] = (1 - e["issues"]/e["submissions"]) * 100

        if "fraud_score" in df.columns:
            fraud = df.groupby(ENUM_COL)["fraud_score"].mean().reset_index()
            e = e.merge(fraud, on=ENUM_COL, how="left")

        st.dataframe(e.sort_values("quality_score", ascending=False))

# ==============================
# EXPLORER
# ==============================
elif page=="Explorer":
    st.title("Explorer")
    tab1,tab2 = st.tabs(["Clean Data","Flagged Data"])
    tab1.dataframe(clean_df)
    tab2.dataframe(flag_df)

# ==============================
# DOWNLOADS
# ==============================
elif page=="Downloads":

    st.title("Downloads")

    def to_excel():
        o = io.BytesIO()
        with pd.ExcelWriter(o, engine="openpyxl") as w:
            clean_df.to_excel(w,index=False,sheet_name="Clean")
            flag_df.to_excel(w,index=False,sheet_name="Flagged")
        return o.getvalue()

    def generate_pdf():
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer)
        styles = getSampleStyleSheet()

        elements = []
        elements.append(Paragraph("REDI Field Data Quality Report", styles['Title']))
        elements.append(Spacer(1,12))
        elements.append(Paragraph(f"Total: {total}", styles['Normal']))
        elements.append(Paragraph(f"Valid: {valid}", styles['Normal']))
        elements.append(Paragraph(f"Flagged: {bad}", styles['Normal']))
        elements.append(Paragraph(f"Score: {score:.2f}%", styles['Normal']))

        doc.build(elements)
        buffer.seek(0)
        return buffer

    col1,col2,col3,col4 = st.columns(4)

    with col1:
        st.markdown('<div class="btn-green">📊 Full Excel</div>', unsafe_allow_html=True)
        st.download_button("", to_excel(), "redi_full.xlsx")

    with col2:
        st.markdown('<div class="btn-green">✅ Clean Data</div>', unsafe_allow_html=True)
        st.download_button("", clean_df.to_csv(index=False), "clean.csv")

    with col3:
        st.markdown('<div class="btn-red">⚠️ Flagged Data</div>', unsafe_allow_html=True)
        st.download_button("", flag_df.to_csv(index=False), "flagged.csv")

    with col4:
        st.markdown('<div class="btn-green">📄 PDF Report</div>', unsafe_allow_html=True)
        st.download_button("", generate_pdf(), "report.pdf")

# ==============================
# FOOTER
# ==============================
st.caption(f"Last updated: {datetime.now()}")
