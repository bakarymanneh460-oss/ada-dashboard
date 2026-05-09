```python
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
st.set_page_config(page_title="REDI Automated Data Quality Monitoring System", layout="wide")

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

FAST_THRESHOLD = st.sidebar.slider("Fast Submission Threshold (seconds)", 10, 300, 60)

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
                st.error(f"API Error: {r.status_code}")
                break
            data = r.json()
            all_data.extend(data.get("results", []))
            url = data.get("next")
        except Exception as e:
            st.error(f"Data fetch failed: {e}")
            break

    return pd.json_normalize(all_data)

with st.spinner("Fetching data..."):
    df = fetch_data(FORM_UID, KOBO_TOKEN)

if df.empty:
    st.error("No data found or invalid Form UID")
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

DATE_COL = detect(["submission_time", "date", "time"])
HH_COL = detect(["hh", "household", "id"])
ENUM_COL = detect(["enum", "enumerator", "name", "user"])
REGION_COL = detect(["region", "district", "area"])

if "_submission_time" in df.columns:
    DATE_COL = "_submission_time"

if DATE_COL:
    df[DATE_COL] = pd.to_datetime(df[DATE_COL], errors="coerce")
else:
    st.warning("No date column detected — time-based features limited.")

# ==============================
# FILTERS
# ==============================
if DATE_COL:
    c1, c2 = st.sidebar.columns(2)
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
# ANOMALY DETECTION (IMPROVED)
# ==============================
num_cols = df.select_dtypes(include=["number"]).columns

if len(num_cols) > 0:
    std = df[num_cols].std().replace(0,1)
    z = np.abs((df[num_cols] - df[num_cols].mean()) / std)

    df["anomaly_flag"] = (
        (z.max(axis=1) > 3) |
        (df[num_cols].isna().sum(axis=1) > 0)
    )
else:
    df["anomaly_flag"] = False

# ==============================
# ENUMERATOR PERFORMANCE (IMPROVED)
# ==============================
if ENUM_COL and DATE_COL:
    df = df.sort_values(DATE_COL)

    df["time_diff"] = df.groupby(ENUM_COL)[DATE_COL].diff().dt.total_seconds()

    f = df.groupby(ENUM_COL).agg(
        total=("time_diff","count"),
        fast=("time_diff", lambda x: (x < FAST_THRESHOLD).sum())
    ).reset_index()

    f["fraud_score"] = ((f["fast"]/f["total"]).fillna(0)*100).clip(upper=100)

    df = df.merge(f[[ENUM_COL,"fraud_score"]], on=ENUM_COL, how="left")
    df["fraud_flag"] = df["fraud_score"] > 50
else:
    df["fraud_flag"] = False

# ==============================
# HOUSEHOLD TRACKING
# ==============================
if HH_COL and "Month" in df.columns:

    hh_tracking = df.groupby(HH_COL)["Month"].nunique().reset_index(name="months_recorded")
    hh_tracking["completeness_%"] = ((hh_tracking["months_recorded"]/12)*100).clip(upper=100)

    trend_flags = []

    for hh, g in df.groupby(HH_COL):
        g = g.sort_values("Month")

        for col in num_cols:
            vals = g[col].dropna()
            if len(vals) >= 2 and (vals.pct_change().abs() > 2).any():
                trend_flags.append(hh)
                break

    df["household_trend_flag"] = df[HH_COL].isin(trend_flags)

else:
    hh_tracking = pd.DataFrame()
    df["household_trend_flag"] = False

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

    st.title("📊 REDI Automated Data Quality Monitoring System")

    c1,c2,c3,c4 = st.columns(4)
    c1.markdown(f'<div class="kpi-card" style="background:#2563eb"><h3>Total</h3><h1>{total}</h1></div>', unsafe_allow_html=True)
    c2.markdown(f'<div class="kpi-card" style="background:#16a34a"><h3>Valid</h3><h1>{valid}</h1></div>', unsafe_allow_html=True)
    c3.markdown(f'<div class="kpi-card" style="background:#dc2626"><h3>Flagged</h3><h1>{bad}</h1></div>', unsafe_allow_html=True)
    c4.markdown(f'<div class="kpi-card" style="background:#7c3aed"><h3>Score</h3><h1>{score:.1f}%</h1></div>', unsafe_allow_html=True)

    st.subheader("Data Quality Distribution")
    st.bar_chart(pd.DataFrame({
        "Status": ["Valid", "Flagged"],
        "Count": [valid, bad]
    }).set_index("Status"))

    # Insights
    st.subheader("🔍 Key Insights")
    if bad > 0:
        st.warning(f"{bad} records flagged ({(bad/total*100):.1f}%)")
    else:
        st.success("High data quality — no major issues detected")

    if df["fraud_flag"].sum() > 0:
        st.error("Potential enumerator fraud detected")

    if ENUM_COL:
        st.subheader("Enumerator Performance")
        e = df.groupby(ENUM_COL)["anomaly_flag"].agg(["count","sum"]).reset_index()
        e["score"] = (1 - e["sum"]/e["count"])*100
        st.dataframe(e.sort_values("score",ascending=False))

        st.subheader("⚠️ High-Risk Enumerators")
        risky = df.groupby(ENUM_COL)["fraud_flag"].mean().sort_values(ascending=False).head(5)
        st.dataframe(risky)

    if HH_COL and not hh_tracking.empty:
        st.subheader("Household Tracking")
        st.dataframe(hh_tracking.sort_values("completeness_%", ascending=False))

    if REGION_COL:
        st.subheader("Regional Performance")
        r = df.groupby(REGION_COL)["anomaly_flag"].agg(["count","sum"]).reset_index()
        r["score"] = (1 - r["sum"]/r["count"])*100
        st.dataframe(r)

    if "Month" in df.columns:
        st.subheader("Monthly Trend")
        st.line_chart(df.groupby("Month").size())

# ==============================
# EXPLORER
# ==============================
elif page=="Explorer":
    st.title("Explorer")

    tab1,tab2=st.tabs(["Clean","Flagged"])
    tab1.dataframe(clean_df)
    tab2.dataframe(flag_df)

# ==============================
# DOWNLOADS (UPGRADED)
# ==============================
elif page=="Downloads":

    def to_excel(data):
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            data.to_excel(writer, index=False)
        output.seek(0)
        return output

    def full_excel():
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            clean_df.to_excel(writer, index=False, sheet_name="Clean")
            flag_df.to_excel(writer, index=False, sheet_name="Flagged")

            meta = pd.DataFrame({
                "Metric": ["Total", "Valid", "Flagged", "Score"],
                "Value": [total, valid, bad, score]
            })
            meta.to_excel(writer, sheet_name="Summary", index=False)

        output.seek(0)
        return output

    def generate_pdf():
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer)
        styles = getSampleStyleSheet()

        content = [
            Paragraph("REDI Data Quality Report", styles['Title']),
            Spacer(1, 12),
            Paragraph(f"Total Records: {total}", styles['Normal']),
            Paragraph(f"Valid Records: {valid}", styles['Normal']),
            Paragraph(f"Flagged Records: {bad}", styles['Normal']),
            Paragraph(f"Quality Score: {score:.2f}%", styles['Normal']),
            Spacer(1, 12),
            Paragraph("Key Insights:", styles['Heading2']),
            Paragraph(f"{bad} records flagged due to anomalies.", styles['Normal']),
            Paragraph("Fraud detection based on rapid submissions.", styles['Normal']),
        ]

        doc.build(content)
        buffer.seek(0)
        return buffer

    col1,col2,col3,col4 = st.columns(4)

    with col1:
        st.markdown('<div class="btn-green">📊 Full Excel</div>', unsafe_allow_html=True)
        st.download_button("", full_excel(), "redi_full.xlsx")

    with col2:
        st.markdown('<div class="btn-green">✅ Clean Excel</div>', unsafe_allow_html=True)
        st.download_button("", to_excel(clean_df), "clean.xlsx")

    with col3:
        st.markdown('<div class="btn-red">⚠️ Flagged Excel</div>', unsafe_allow_html=True)
        st.download_button("", to_excel(flag_df), "flagged.xlsx")

    with col4:
        st.markdown('<div class="btn-green">📄 PDF Report</div>', unsafe_allow_html=True)
        st.download_button("", generate_pdf(), "report.pdf")

# ==============================
# FOOTER
# ==============================
st.markdown("---")
st.caption(f"REDI System • Automated Data Quality Monitoring • Version 1.0 | Updated {datetime.now()}")
```
