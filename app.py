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
# STYLE
# ==============================
st.markdown("""
<style>
section[data-testid="stSidebar"] {background-color:#1e3a8a !important;}
section[data-testid="stSidebar"] * {color:white !important;}
section[data-testid="stSidebar"] input {background:white !important; color:black !important;}

.kpi-card {padding:20px;border-radius:12px;color:white;text-align:center;font-weight:bold;}
.btn-green {background-color:#16a34a;color:white;padding:12px;border-radius:10px;text-align:center;font-weight:bold;}
.btn-red {background-color:#dc2626;color:white;padding:12px;border-radius:10px;text-align:center;font-weight:bold;}
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
ENUM_COL = detect(["enum", "name", "user"])
HH_COL = detect(["hh", "household", "id"])

if "_submission_time" in df.columns:
    DATE_COL = "_submission_time"

if DATE_COL:
    df[DATE_COL] = pd.to_datetime(df[DATE_COL], errors="coerce")

# ==============================
# FRAUD DETECTION (SPEED)
# ==============================
if ENUM_COL and DATE_COL:
    df = df.sort_values(DATE_COL)
    df["time_diff"] = df.groupby(ENUM_COL)[DATE_COL].diff().dt.total_seconds()
    df["fraud_flag"] = df["time_diff"] < FAST_THRESHOLD
else:
    df["fraud_flag"] = False

# ==============================
# NUMERIC ANOMALY DETECTION
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

    df["anomaly_flag"] = z_flag | iqr_flag | iso_flag | missing_flag
else:
    df["anomaly_flag"] = False

# ==============================
# QUALITATIVE CHECKS
# ==============================
text_cols = df.select_dtypes(include=["object"]).columns
df["text_flag"] = False

for col in text_cols:
    col_series = df[col].astype(str).str.lower()
    empty_flag = col_series.isin(["", "na", "n/a", "none", "null", "ok", "test"])
    short_flag = col_series.str.len() < 3
    repetition_flag = col_series.map(col_series.value_counts(normalize=True)) > 0.5

    combined = empty_flag | short_flag | repetition_flag
    df.loc[combined, "text_flag"] = True

# ==============================
# HOUSEHOLD TREND (simple)
# ==============================
if HH_COL and len(num_cols) > 0:
    df["household_trend_flag"] = False
    for hh, g in df.groupby(HH_COL):
        for col in num_cols:
            if len(g[col].dropna()) > 1 and (g[col].pct_change().abs() > 2).any():
                df.loc[df[HH_COL] == hh, "household_trend_flag"] = True
else:
    df["household_trend_flag"] = False

# ==============================
# FLAG REASONS
# ==============================
reasons = []
for i in range(len(df)):
    r = []
    if df["anomaly_flag"].iloc[i]: r.append("Numeric anomaly")
    if df["text_flag"].iloc[i]: r.append("Text issue")
    if df["fraud_flag"].iloc[i]: r.append("Fast submission")
    if df["household_trend_flag"].iloc[i]: r.append("Household inconsistency")
    reasons.append(", ".join(r) if r else "Clean")

df["flag_reason"] = reasons

# ==============================
# UNIFIED QUALITY SCORE
# ==============================
df["quality_score"] = 100
df.loc[df["anomaly_flag"], "quality_score"] -= 40
df.loc[df["text_flag"], "quality_score"] -= 20
df.loc[df["fraud_flag"], "quality_score"] -= 20
df.loc[df["household_trend_flag"], "quality_score"] -= 20
df["quality_score"] = df["quality_score"].clip(0, 100)

def categorize(x):
    if x >= 90: return "Excellent"
    elif x >= 75: return "Good"
    elif x >= 50: return "Fair"
    else: return "Poor"

df["quality_category"] = df["quality_score"].apply(categorize)

# ==============================
# SPLIT
# ==============================
clean_df = df[df["quality_score"] >= 75]
flag_df = df[df["quality_score"] < 75]

total, valid, bad = len(df), len(clean_df), len(flag_df)
score = (valid/total*100) if total else 0

# ==============================
# DASHBOARD
# ==============================
if page == "Dashboard":
    st.title("📊 REDI Data Quality Dashboard")

    c1,c2,c3,c4 = st.columns(4)
    c1.markdown(f'<div class="kpi-card" style="background:#2563eb">Total<br><h1>{total}</h1></div>', unsafe_allow_html=True)
    c2.markdown(f'<div class="kpi-card" style="background:#16a34a">Valid<br><h1>{valid}</h1></div>', unsafe_allow_html=True)
    c3.markdown(f'<div class="kpi-card" style="background:#dc2626">Flagged<br><h1>{bad}</h1></div>', unsafe_allow_html=True)
    c4.markdown(f'<div class="kpi-card" style="background:#7c3aed">Score<br><h1>{score:.1f}%</h1></div>', unsafe_allow_html=True)

    st.bar_chart(df["quality_category"].value_counts())

# ==============================
# EXPLORER
# ==============================
elif page == "Explorer":

    tab1, tab2 = st.tabs(["Clean", "Flagged"])
    tab1.dataframe(clean_df)
    tab2.dataframe(flag_df)

    st.subheader("🔍 Detailed Flag Analysis")
    st.dataframe(flag_df[["quality_score","quality_category","flag_reason"]])

    st.subheader("🔎 Rows containing '383'")
    st.write(flag_df[flag_df.astype(str).apply(lambda x: x.str.contains("383")).any(axis=1)])

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
            Spacer(1, 12),
            Paragraph(f"Total: {total}", styles['Normal']),
            Paragraph(f"Valid: {valid}", styles['Normal']),
            Paragraph(f"Flagged: {bad}", styles['Normal']),
            Paragraph(f"Score: {score:.2f}%", styles['Normal']),
        ]

        doc.build(content)
        buffer.seek(0)
        return buffer

    col1,col2,col3,col4 = st.columns(4)

    with col1:
        st.markdown('<div class="btn-green">📊 Full Excel</div>', unsafe_allow_html=True)
        st.download_button("", full_excel(), "full.xlsx")

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
st.caption(f"Updated {datetime.now()}")
