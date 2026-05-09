import streamlit as st
import pandas as pd
import io
import requests
from datetime import datetime
import numpy as np
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from sklearn.ensemble import IsolationForest

# CONFIG
st.set_page_config(page_title="REDI Automated Data Quality Monitoring System", layout="wide")

# SIDEBAR
st.sidebar.title("📊 REDI Universal Data System")

FORM_UID = st.sidebar.text_input("Form UID")
page = st.sidebar.radio("Navigation", ["Dashboard", "Explorer", "Downloads"])

KOBO_TOKEN = st.secrets.get("KOBO_TOKEN", None)

FAST_THRESHOLD = st.sidebar.slider("Fast Submission Threshold (sec)", 10, 300, 60)
ANOMALY_CONTAMINATION = st.sidebar.slider("Anomaly Sensitivity", 0.01, 0.20, 0.05)

if st.sidebar.button("🔄 Refresh"):
    st.cache_data.clear()
    st.rerun()

# FETCH
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
            st.error(f"Fetch failed: {e}")
            break

    return pd.json_normalize(all_data)

df = fetch_data(FORM_UID, KOBO_TOKEN)

if df.empty:
    st.warning("No data found")
    st.stop()

# DETECT COLUMNS
def detect(names):
    for col in df.columns:
        for n in names:
            if n in col.lower():
                return col
    return None

DATE_COL = detect(["submission_time", "date"])
ENUM_COL = detect(["enum", "name"])
HH_COL = detect(["hh", "household"])
REGION_COL = detect(["region", "district"])

if "_submission_time" in df.columns:
    DATE_COL = "_submission_time"

if DATE_COL:
    df[DATE_COL] = pd.to_datetime(df[DATE_COL], errors="coerce")
    df["Month"] = df[DATE_COL].dt.to_period("M").astype(str)

# ANOMALY DETECTION + EXPLANATION
num_cols = df.select_dtypes(include=["number"]).columns

if len(num_cols) > 0:
    std = df[num_cols].std().replace(0, 1)
    z = np.abs((df[num_cols] - df[num_cols].mean()) / std)
    z_flag = (z.max(axis=1) > 3)

    Q1 = df[num_cols].quantile(0.25)
    Q3 = df[num_cols].quantile(0.75)
    IQR = Q3 - Q1
    iqr_flag = ((df[num_cols] < (Q1 - 1.5 * IQR)) | (df[num_cols] > (Q3 + 1.5 * IQR))).any(axis=1)

    try:
        iso = IsolationForest(contamination=ANOMALY_CONTAMINATION, random_state=42)
        iso_flag = iso.fit_predict(df[num_cols].fillna(0)) == -1
    except:
        iso_flag = pd.Series([False]*len(df))

    missing_flag = df[num_cols].isna().sum(axis=1) > 0

    explanations = []
    for i in range(len(df)):
        r = []
        if z_flag.iloc[i]:
            r.append("Extreme value (Z-score)")
        if iqr_flag.iloc[i]:
            r.append("Outlier (IQR)")
        if iso_flag[i]:
            r.append("Pattern anomaly (ML)")
        if missing_flag.iloc[i]:
            r.append("Missing data")
        explanations.append(", ".join(r) if r else "Clean")

    df["flag_reason"] = explanations
    df["anomaly_flag"] = z_flag | iqr_flag | iso_flag | missing_flag
else:
    df["anomaly_flag"] = False
    df["flag_reason"] = "No numeric data"

# ENUMERATOR FRAUD
if ENUM_COL and DATE_COL:
    df = df.sort_values(DATE_COL)
    df["time_diff"] = df.groupby(ENUM_COL)[DATE_COL].diff().dt.total_seconds()

    fraud = df.groupby(ENUM_COL)["time_diff"].apply(lambda x: (x < FAST_THRESHOLD).mean()*100)
    df["fraud_score"] = df[ENUM_COL].map(fraud)
    df["fraud_flag"] = df["fraud_score"] > 50

    df["flag_reason"] = df.apply(
        lambda x: x["flag_reason"] + ", Fast submission (fraud)"
        if x["fraud_flag"] else x["flag_reason"],
        axis=1
    )
else:
    df["fraud_flag"] = False

# HOUSEHOLD TRACKING
if HH_COL and "Month" in df.columns:
    hh_tracking = df.groupby(HH_COL)["Month"].nunique().reset_index(name="months_recorded")
    hh_tracking["completeness_%"] = (hh_tracking["months_recorded"]/12*100).clip(upper=100)
else:
    hh_tracking = pd.DataFrame()

# SPLIT
clean_df = df[~df["anomaly_flag"]]
flag_df = df[df["anomaly_flag"]]

total, valid, bad = len(df), len(clean_df), len(flag_df)
score = (valid/total*100) if total else 0

# DASHBOARD
if page == "Dashboard":
    st.title("📊 REDI Data Quality Dashboard")

    c1,c2,c3,c4 = st.columns(4)
    c1.metric("Total", total)
    c2.metric("Valid", valid)
    c3.metric("Flagged", bad)
    c4.metric("Score", f"{score:.1f}%")

    st.bar_chart(pd.DataFrame({"Valid":[valid],"Flagged":[bad]}))

    if ENUM_COL:
        st.subheader("Enumerator Performance")
        e = df.groupby(ENUM_COL)["anomaly_flag"].agg(["count","sum"])
        e["score"] = (1 - e["sum"]/e["count"])*100
        st.dataframe(e)

    if not hh_tracking.empty:
        st.subheader("Household Tracking")
        st.dataframe(hh_tracking)

# EXPLORER
elif page == "Explorer":
    tab1, tab2 = st.tabs(["Clean", "Flagged"])
    tab1.dataframe(clean_df)
    tab2.dataframe(flag_df)

    st.subheader("Flag Explanation Summary")
    st.dataframe(flag_df["flag_reason"].value_counts())

# DOWNLOADS
elif page == "Downloads":

    def to_excel(data):
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            data.to_excel(writer, index=False)
        output.seek(0)
        return output

    def full_excel():
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            clean_df.to_excel(writer, sheet_name="Clean", index=False)
            flag_df.to_excel(writer, sheet_name="Flagged", index=False)
        output.seek(0)
        return output

    def generate_pdf():
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer)
        styles = getSampleStyleSheet()

        content = [
            Paragraph("REDI Data Quality Report", styles['Title']),
            Spacer(1,12),
            Paragraph(f"Total: {total}", styles['Normal']),
            Paragraph(f"Valid: {valid}", styles['Normal']),
            Paragraph(f"Flagged: {bad}", styles['Normal']),
            Paragraph(f"Score: {score:.2f}%", styles['Normal'])
        ]

        doc.build(content)
        buffer.seek(0)
        return buffer

    c1,c2,c3,c4 = st.columns(4)
    c1.download_button("Full Excel", full_excel(), "full.xlsx")
    c2.download_button("Clean Excel", to_excel(clean_df), "clean.xlsx")
    c3.download_button("Flagged Excel", to_excel(flag_df), "flagged.xlsx")
    c4.download_button("PDF Report", generate_pdf(), "report.pdf")

# FOOTER
st.caption(f"Updated {datetime.now()}")
