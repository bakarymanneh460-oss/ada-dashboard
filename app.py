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
# UI STYLE
# ==============================
st.markdown("""
<style>
section[data-testid="stSidebar"] {
    background-color: #1e3a8a !important;
}
section[data-testid="stSidebar"] * {
    color: white !important;
}
section[data-testid="stSidebar"] input {
    background-color: white !important;
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
st.sidebar.caption("Field Data Quality Monitoring Tool")

FORM_UID = st.sidebar.text_input("Form UID", "")
page = st.sidebar.radio("Navigation", ["Dashboard", "Explorer", "Downloads"])

KOBO_TOKEN = st.secrets.get("KOBO_TOKEN", None)

if engine:
    st.sidebar.success("🟢 Database connected")
else:
    st.sidebar.info("🟡 Using Kobo API")

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
# FILTERS
# ==============================
if "_submission_time" in df.columns:
    df["_submission_time"] = pd.to_datetime(df["_submission_time"], errors="coerce")

    min_date = df["_submission_time"].min()
    max_date = df["_submission_time"].max()

    c1, c2 = st.sidebar.columns(2)
    start_date = c1.date_input("Start Date", min_date)
    end_date = c2.date_input("End Date", max_date)

    df = df[
        (df["_submission_time"] >= pd.to_datetime(start_date)) &
        (df["_submission_time"] <= pd.to_datetime(end_date))
    ]

search = st.sidebar.text_input("🔍 Search data")
if search:
    df = df[df.astype(str).apply(lambda x: x.str.contains(search, case=False, na=False).any(), axis=1)]

# ==============================
# PREP
# ==============================
if "_submission_time" in df.columns:
    df["Month"] = df["_submission_time"].dt.to_period("M").astype(str)

# ==============================
# PANEL CONSISTENCY
# ==============================
if "HH_ID" in df.columns and "Month" in df.columns:

    panel_flags = []
    numeric_cols_panel = df.select_dtypes(include=["number"]).columns.tolist()

    for hh, group in df.groupby("HH_ID"):
        group = group.sort_values("Month")

        for col in numeric_cols_panel:
            vals = group[col].dropna()
            if len(vals) >= 2:
                change = vals.pct_change().abs()
                if (change > 2).any():
                    panel_flags.append(hh)
                    break

    df["panel_inconsistency"] = df["HH_ID"].isin(panel_flags)
else:
    df["panel_inconsistency"] = False

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

# ==============================
# ENUMERATOR FRAUD
# ==============================
enum_col = next((c for c in df.columns if "enumerator" in c.lower() or "name" in c.lower()), None)

if enum_col and "_submission_time" in df.columns:
    df = df.sort_values("_submission_time")
    df["time_diff"] = df.groupby(enum_col)["_submission_time"].diff().dt.total_seconds()

    fraud_stats = df.groupby(enum_col).agg(
        submissions=("time_diff", "count"),
        fast=("time_diff", lambda x: (x < 60).sum())
    ).reset_index()

    fraud_stats["fraud_score"] = (fraud_stats["fast"] / fraud_stats["submissions"]) * 100

    df = df.merge(fraud_stats[[enum_col, "fraud_score"]], on=enum_col, how="left")
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

    # Alerts
    st.subheader("🚨 Alerts")
    if df["anomaly_flag"].sum() > 0:
        st.error(f"⚠️ {df['anomaly_flag'].sum()} anomalies detected")
    if df["panel_inconsistency"].sum() > 0:
        st.error(f"🔁 {df['panel_inconsistency'].sum()} panel inconsistencies")
    if df["fraud_flag"].sum() > 0:
        st.error("🚨 Enumerator fraud risk detected")

    # Enumerator
    if enum_col:
        st.subheader("🚶 Enumerator Performance")
        enum_df = df.groupby(enum_col)["anomaly_flag"].agg(["count","sum"]).reset_index()
        enum_df["score"] = (1 - enum_df["sum"] / enum_df["count"]) * 100
        st.dataframe(enum_df.sort_values("score", ascending=False))
        st.bar_chart(enum_df.set_index(enum_col)["score"])

    # Regional
    region_col = next((c for c in df.columns if "region" in c.lower() or "district" in c.lower()), None)
    if region_col:
        st.subheader("🗺️ Regional Performance")
        region_df = df.groupby(region_col).agg(total=("anomaly_flag","count"), flagged=("anomaly_flag","sum")).reset_index()
        region_df["quality_score"] = (1 - region_df["flagged"]/region_df["total"]) * 100
        st.dataframe(region_df.sort_values("quality_score", ascending=False))
        st.bar_chart(region_df.set_index(region_col)["quality_score"])

    # Household
    if "HH_ID" in df.columns and "Month" in df.columns:
        st.subheader("🏠 Household Tracking (12-Month Index)")
        hh = df.groupby("HH_ID")["Month"].nunique().reset_index(name="months")
        hh["completeness_%"] = (hh["months"] / 12) * 100
        st.dataframe(hh.sort_values("completeness_%", ascending=False))
        st.bar_chart(hh["months"])

    if "Month" in df.columns:
        st.subheader("📅 Monthly Trend")
        st.line_chart(df.groupby("Month").size())

    st.subheader("⚠️ Flagged Data")
    st.dataframe(flag_df.head(50))

# ==============================
# EXPLORER
# ==============================
elif page == "Explorer":
    st.title("🔍 Data Explorer")
    tab1, tab2 = st.tabs(["✅ Clean Data", "⚠️ Flagged Data"])
    with tab1:
        st.dataframe(clean_df)
    with tab2:
        st.dataframe(flag_df)

# ==============================
# DOWNLOADS
# ==============================
elif page == "Downloads":

    st.subheader("📥 Download Center")

    def to_excel():
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            clean_df.to_excel(writer, index=False, sheet_name="Clean")
            flag_df.to_excel(writer, index=False, sheet_name="Flagged")
        return output.getvalue()

    def to_pdf():
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer)
        styles = getSampleStyleSheet()
        content = []
        content.append(Paragraph("REDI DATA QUALITY REPORT", styles["Title"]))
        content.append(Spacer(1, 10))
        content.append(Paragraph(f"Generated: {datetime.now()}", styles["Normal"]))
        content.append(Paragraph(f"Total: {total}", styles["Normal"]))
        content.append(Paragraph(f"Valid: {valid}", styles["Normal"]))
        content.append(Paragraph(f"Flagged: {bad}", styles["Normal"]))
        content.append(Paragraph(f"Score: {score:.2f}%", styles["Normal"]))

        fig = plt.figure()
        plt.bar(["Valid","Flagged"], [valid,bad])
        img = io.BytesIO()
        plt.savefig(img, format="png")
        plt.close(fig)
        img.seek(0)

        content.append(Image(img, width=400, height=250))
        doc.build(content)
        buffer.seek(0)
        return buffer.getvalue()

    excel_b64 = base64.b64encode(to_excel()).decode()
    pdf_b64 = base64.b64encode(to_pdf()).decode()
    clean_b64 = base64.b64encode(clean_df.to_csv(index=False).encode()).decode()
    flagged_b64 = base64.b64encode(flag_df.to_csv(index=False).encode()).decode()

    c1, c2, c3, c4 = st.columns(4)

    c1.markdown(f'<a href="data:application/octet-stream;base64,{excel_b64}" download="redi_full.xlsx"><button style="width:100%;background:#16a34a;color:white;padding:12px;border-radius:10px;">📊 Full Excel</button></a>', unsafe_allow_html=True)
    c2.markdown(f'<a href="data:text/csv;base64,{clean_b64}" download="clean.csv"><button style="width:100%;background:#22c55e;color:white;padding:12px;border-radius:10px;">✅ Clean</button></a>', unsafe_allow_html=True)
    c3.markdown(f'<a href="data:text/csv;base64,{flagged_b64}" download="flagged.csv"><button style="width:100%;background:#dc2626;color:white;padding:12px;border-radius:10px;">⚠️ Flagged</button></a>', unsafe_allow_html=True)
    c4.markdown(f'<a href="data:application/pdf;base64,{pdf_b64}" download="report.pdf"><button style="width:100%;background:#1d4ed8;color:white;padding:12px;border-radius:10px;">📄 PDF</button></a>', unsafe_allow_html=True)

st.caption(f"Updated: {datetime.now()}")
