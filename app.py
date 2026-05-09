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
# COLUMN DETECTION
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
# FRAUD DETECTION
# ==============================
if ENUM_COL and DATE_COL:
    df = df.sort_values(DATE_COL)
    df["time_diff"] = df.groupby(ENUM_COL)[DATE_COL].diff().dt.total_seconds()
    df["fraud_flag"] = df["time_diff"] < FAST_THRESHOLD
else:
    df["fraud_flag"] = False

# ==============================
# NUMERIC ANOMALY
# ==============================
num_cols = df.select_dtypes(include=["number"]).columns

if len(num_cols) > 0:
    std = df[num_cols].std().replace(0, 1)
    z_flag = (np.abs((df[num_cols] - df[num_cols].mean()) / std).max(axis=1) > 3)

    Q1 = df[num_cols].quantile(0.25)
    Q3 = df[num_cols].quantile(0.75)
    IQR = Q3 - Q1
    iqr_flag = ((df[num_cols] < (Q1 - 1.5 * IQR)) | (df[num_cols] > (Q3 + 1.5 * IQR))).any(axis=1)

    iso_flag = IsolationForest(contamination=ANOMALY_CONTAMINATION, random_state=42)\
        .fit_predict(df[num_cols].fillna(0)) == -1

    missing_flag = df[num_cols].isna().sum(axis=1) > 0

    df["anomaly_flag"] = z_flag | iqr_flag | iso_flag | missing_flag
else:
    df["anomaly_flag"] = False

# ==============================
# TEXT CHECK
# ==============================
df["text_flag"] = False
for col in df.select_dtypes(include=["object"]).columns:
    s = df[col].astype(str).str.lower()
    df["text_flag"] |= s.isin(["", "na", "n/a", "none", "ok", "test"]) | (s.str.len() < 3)

# ==============================
# HOUSEHOLD TREND
# ==============================
df["household_trend_flag"] = False
if HH_COL and len(num_cols) > 0:
    for hh, g in df.groupby(HH_COL):
        for col in num_cols:
            if len(g[col].dropna()) > 1 and (g[col].pct_change().abs() > 2).any():
                df.loc[df[HH_COL] == hh, "household_trend_flag"] = True

# ==============================
# FLAG REASONS
# ==============================
df["flag_reason"] = (
    df["anomaly_flag"].map({True:"Numeric anomaly",False:""}) + 
    df["text_flag"].map({True:", Text issue",False:""}) +
    df["fraud_flag"].map({True:", Fast submission",False:""}) +
    df["household_trend_flag"].map({True:", Household inconsistency",False:""})
).str.strip(", ")

df["flag_reason"] = df["flag_reason"].replace("", "Clean")

# ==============================
# QUALITY SCORE
# ==============================
df["quality_score"] = 100
df.loc[df["anomaly_flag"], "quality_score"] -= 40
df.loc[df["text_flag"], "quality_score"] -= 20
df.loc[df["fraud_flag"], "quality_score"] -= 20
df.loc[df["household_trend_flag"], "quality_score"] -= 20
df["quality_score"] = df["quality_score"].clip(0,100)

df["quality_category"] = pd.cut(
    df["quality_score"],
    bins=[0,50,75,90,100],
    labels=["Poor","Fair","Good","Excellent"]
)

clean_df = df[df["quality_score"] >= 75]
flag_df = df[df["quality_score"] < 75]

# ==============================
# DASHBOARD
# ==============================
if page=="Dashboard":
    st.title("📊 REDI Dashboard")

    c1,c2,c3,c4 = st.columns(4)
    c1.markdown(f'<div class="kpi-card" style="background:#2563eb">Total<br><h1>{len(df)}</h1></div>', unsafe_allow_html=True)
    c2.markdown(f'<div class="kpi-card" style="background:#16a34a">Valid<br><h1>{len(clean_df)}</h1></div>', unsafe_allow_html=True)
    c3.markdown(f'<div class="kpi-card" style="background:#dc2626">Flagged<br><h1>{len(flag_df)}</h1></div>', unsafe_allow_html=True)
    c4.markdown(f'<div class="kpi-card" style="background:#7c3aed">Avg Score<br><h1>{df["quality_score"].mean():.1f}</h1></div>', unsafe_allow_html=True)

    st.bar_chart(df["quality_category"].value_counts())

# ==============================
# EXPLORER (WITH INVESTIGATION PANEL)
# ==============================
elif page=="Explorer":

    st.title("🔍 Data Explorer & Investigation")

    tab1, tab2 = st.tabs(["Clean Data","Flagged Data"])
    tab1.dataframe(clean_df)
    tab2.dataframe(flag_df)

    st.subheader("📊 Flag Summary")
    st.dataframe(flag_df["flag_reason"].value_counts())

    # 🔍 SEARCH TOOL
    st.subheader("🔎 Investigation Tool")
    search = st.text_input("Search any value")

    if search:
        results = df[df.astype(str).apply(lambda x: x.str.contains(search, case=False, na=False)).any(axis=1)]
        st.success(f"{len(results)} results found")
        st.dataframe(results)

        # ROW INSPECTION
        st.subheader("🧠 Row Inspection")
        if not results.empty:
            idx = st.selectbox("Select row index", results.index)
            row = df.loc[idx]

            st.write(row)

            st.info(f"""
            Quality Score: {row['quality_score']}
            Category: {row['quality_category']}
            Reason: {row['flag_reason']}
            """)

# ==============================
# DOWNLOADS
# ==============================
elif page=="Downloads":

    def to_excel(data):
        output=io.BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            data.to_excel(writer,index=False)
        output.seek(0)
        return output

    def full_excel():
        output=io.BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            clean_df.to_excel(writer,"Clean",index=False)
            flag_df.to_excel(writer,"Flagged",index=False)
        output.seek(0)
        return output

    def pdf():
        buffer=io.BytesIO()
        doc=SimpleDocTemplate(buffer)
        styles=getSampleStyleSheet()
        content=[
            Paragraph("REDI Report",styles['Title']),
            Spacer(1,12),
            Paragraph(f"Total: {len(df)}",styles['Normal']),
            Paragraph(f"Valid: {len(clean_df)}",styles['Normal']),
            Paragraph(f"Flagged: {len(flag_df)}",styles['Normal']),
        ]
        doc.build(content)
        buffer.seek(0)
        return buffer

    c1,c2,c3,c4=st.columns(4)

    with c1:
        st.markdown('<div class="btn-green">📊 Full Excel</div>',unsafe_allow_html=True)
        st.download_button("",full_excel(),"full.xlsx")

    with c2:
        st.markdown('<div class="btn-green">✅ Clean</div>',unsafe_allow_html=True)
        st.download_button("",to_excel(clean_df),"clean.xlsx")

    with c3:
        st.markdown('<div class="btn-red">⚠️ Flagged</div>',unsafe_allow_html=True)
        st.download_button("",to_excel(flag_df),"flagged.xlsx")

    with c4:
        st.markdown('<div class="btn-green">📄 PDF</div>',unsafe_allow_html=True)
        st.download_button("",pdf(),"report.pdf")

# ==============================
# FOOTER
# ==============================
st.caption(f"Updated {datetime.now()}")
