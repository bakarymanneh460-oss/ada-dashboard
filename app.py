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
# STYLE (RESTORED)
# ==============================
st.markdown("""
<style>
section[data-testid="stSidebar"] {background-color:#1e3a8a !important;}
section[data-testid="stSidebar"] * {color:white !important;}
section[data-testid="stSidebar"] input {background:white !important; color:black !important;}

.kpi-card {
    padding:20px;
    border-radius:12px;
    color:white;
    text-align:center;
    font-weight:bold;
}

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

FAST_THRESHOLD = st.sidebar.slider("Fast Submission Threshold (sec)", 10, 300, 60)
ANOMALY_CONTAMINATION = st.sidebar.slider("Anomaly Sensitivity", 0.01, 0.20, 0.05)

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
            st.error(f"Fetch failed: {e}")
            break

    return pd.json_normalize(all_data)

df = fetch_data(FORM_UID, KOBO_TOKEN)

if df.empty:
    st.warning("No data found")
    st.stop()

# ==============================
# DETECT COLUMNS
# ==============================
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

# ==============================
# ANOMALY DETECTION + EXPLANATION
# ==============================
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
        if z_flag.iloc[i]: r.append("Extreme value (Z-score)")
        if iqr_flag.iloc[i]: r.append("Outlier (IQR)")
        if iso_flag[i]: r.append("Pattern anomaly (ML)")
        if missing_flag.iloc[i]: r.append("Missing data")
        explanations.append(", ".join(r) if r else "Clean")

    df["flag_reason"] = explanations
    df["anomaly_flag"] = z_flag | iqr_flag | iso_flag | missing_flag
else:
    df["anomaly_flag"] = False
    df["flag_reason"] = "No numeric data"

# ==============================
# SPLIT
# ==============================
clean_df = df[~df["anomaly_flag"]]
flag_df = df[df["anomaly_flag"]]

total, valid, bad = len(df), len(clean_df), len(flag_df)
score = (valid/total*100) if total else 0

# ==============================
# DASHBOARD (COLORED KPIs RESTORED)
# ==============================
if page == "Dashboard":

    st.title("📊 REDI Data Quality Dashboard")

    c1,c2,c3,c4 = st.columns(4)

    c1.markdown(f'<div class="kpi-card" style="background:#2563eb"><h3>Total</h3><h1>{total}</h1></div>', unsafe_allow_html=True)
    c2.markdown(f'<div class="kpi-card" style="background:#16a34a"><h3>Valid</h3><h1>{valid}</h1></div>', unsafe_allow_html=True)
    c3.markdown(f'<div class="kpi-card" style="background:#dc2626"><h3>Flagged</h3><h1>{bad}</h1></div>', unsafe_allow_html=True)
    c4.markdown(f'<div class="kpi-card" style="background:#7c3aed"><h3>Score</h3><h1>{score:.1f}%</h1></div>', unsafe_allow_html=True)

    st.bar_chart(pd.DataFrame({"Valid":[valid],"Flagged":[bad]}))

# ==============================
# EXPLORER
# ==============================
elif page == "Explorer":
    tab1, tab2 = st.tabs(["Clean", "Flagged"])
    tab1.dataframe(clean_df)
    tab2.dataframe(flag_df)

# ==============================
# DOWNLOADS (COLORED BUTTONS RESTORED)
# ==============================
elif page == "Downloads":

    def to_excel(data):
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            data.to_excel(writer, index=False)
        output.seek(0)
        return output

    col1,col2,col3 = st.columns(3)

    with col1:
        st.markdown('<div class="btn-green">✅ Clean Excel</div>', unsafe_allow_html=True)
        st.download_button("", to_excel(clean_df), "clean.xlsx")

    with col2:
        st.markdown('<div class="btn-red">⚠️ Flagged Excel</div>', unsafe_allow_html=True)
        st.download_button("", to_excel(flag_df), "flagged.xlsx")

# FOOTER
st.caption(f"Updated {datetime.now()}")
