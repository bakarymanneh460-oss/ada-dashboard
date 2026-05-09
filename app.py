import streamlit as st
import pandas as pd
import io
import requests
from datetime import datetime
import numpy as np
import matplotlib.pyplot as plt

from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image
from reportlab.lib.styles import getSampleStyleSheet

from sklearn.ensemble import IsolationForest

# ==============================
# AUTO REFRESH (60s)
# ==============================
try:
    from streamlit_autorefresh import st_autorefresh
    st_autorefresh(interval=60000, key="refresh_60s")
except:
    pass

# ==============================
# CONFIG
# ==============================
st.set_page_config(page_title="REDI ADA System", layout="wide")

ANOMALY_CONTAMINATION = 0.05
FAST_THRESHOLD = 60

# ==============================
# STYLE
# ==============================
st.markdown("""
<style>
section[data-testid="stSidebar"] {background-color:#1e3a8a !important;}
section[data-testid="stSidebar"] * {color:white !important;}

.kpi-card {
    padding:18px;
    border-radius:14px;
    color:white;
    text-align:center;
    font-weight:bold;
    box-shadow:0 4px 12px rgba(0,0,0,0.2);
}
</style>
""", unsafe_allow_html=True)

# ==============================
# SIDEBAR (FINAL - UID FIX)
# ==============================
st.sidebar.title("📂 REDI ADA System")

st.sidebar.markdown(
    """
    <div style="
        font-size:16px;
        font-weight:700;
        color:#ffffff;
        margin-bottom:6px;
    ">
    🔗 KoBo Form UID
    </div>
    """,
    unsafe_allow_html=True
)

FORM_UID = st.sidebar.text_input(
    label="",
    value="aSkM3DhA9dZDRR3pDgpHwj",
    placeholder="Enter KoBo Form UID..."
)

st.sidebar.caption("Example: aSkM3DhA9dZDRR3pDgpHwj")

KOBO_TOKEN = st.secrets.get("KOBO_TOKEN", None)

pages = ["Dashboard", "Explorer", "Downloads", "AI Explain"]
page = st.sidebar.radio("Navigation", pages)

if st.sidebar.button("🔄 Refresh Data"):
    st.cache_data.clear()
    st.rerun()

# ==============================
# FETCH DATA
# ==============================
@st.cache_data(ttl=120)
def fetch_data(uid, token):
    if not uid:
        return pd.DataFrame()

    headers = {"Authorization": f"Token {token}"} if token else {}
    url = f"https://kf.kobotoolbox.org/api/v2/assets/{uid}/data/?format=json&page_size=1000"

    all_data = []
    while url:
        r = requests.get(url, headers=headers)
        if r.status_code != 200:
            break
        data = r.json()
        all_data.extend(data.get("results", []))
        url = data.get("next")

    return pd.json_normalize(all_data)

df = fetch_data(FORM_UID, KOBO_TOKEN)

if df.empty:
    st.warning("No data found for this KoBo Form UID")
    st.stop()

# ==============================
# COLUMN DETECTION
# ==============================
def detect(keys):
    for c in df.columns:
        for k in keys:
            if k in c.lower():
                return c
    return None

DATE_COL = detect(["submission_time", "date"]) or "_submission_time"
ENUM_COL = detect(["enum", "name", "user"])
HH_COL = detect(["hh", "household", "id"])

df[DATE_COL] = pd.to_datetime(df[DATE_COL], errors="coerce")

# ==============================
# DATE FILTER
# ==============================
start = df[DATE_COL].min().date()
end = df[DATE_COL].max().date()

c1, c2 = st.sidebar.columns(2)
start_date = c1.date_input("Start", start)
end_date = c2.date_input("End", end)

df = df[(df[DATE_COL] >= pd.to_datetime(start_date)) &
        (df[DATE_COL] <= pd.to_datetime(end_date))]

# ==============================
# FEATURES
# ==============================
num_cols = df.select_dtypes(include=["number"]).columns

if ENUM_COL:
    df["time_diff"] = df.groupby(ENUM_COL)[DATE_COL].diff().dt.total_seconds()
else:
    df["time_diff"] = np.nan

# ==============================
# THRESHOLDS
# ==============================
def thresholds(df):
    t = {}

    if len(num_cols) > 0:
        z = np.abs((df[num_cols] - df[num_cols].mean()) /
                   df[num_cols].std().replace(0, 1))
        t["z"] = max(2.5, min(z.stack().quantile(0.95), 4))
    else:
        t["z"] = 3

    if ENUM_COL:
        tt = df["time_diff"].dropna()
        t["fast"] = max(20, min(tt.quantile(0.10), 120)) if len(tt) else FAST_THRESHOLD
    else:
        t["fast"] = FAST_THRESHOLD

    return t

thr = thresholds(df)

# ==============================
# FRAUD DETECTION
# ==============================
if ENUM_COL:
    fr = df.groupby(ENUM_COL)["time_diff"].apply(
        lambda x: (x.fillna(9999) < thr["fast"]).mean()
    )
    bad = fr[fr > 0.7].index
    df["fraud_flag"] = df[ENUM_COL].isin(bad)
else:
    df["fraud_flag"] = False

# ==============================
# NUMERIC ANOMALY
# ==============================
if len(num_cols) > 0 and len(df) > 10:

    z = np.abs((df[num_cols] - df[num_cols].mean()) /
               df[num_cols].std().replace(0, 1))
    z_flag = z.max(axis=1) > thr["z"]

    Q1 = df[num_cols].quantile(0.25)
    Q3 = df[num_cols].quantile(0.75)
    IQR = Q3 - Q1

    iqr_flag = ((df[num_cols] < (Q1 - 1.5 * IQR)) |
                (df[num_cols] > (Q3 + 1.5 * IQR))).any(axis=1)

    iso = IsolationForest(contamination=ANOMALY_CONTAMINATION, random_state=42)
    iso_flag = iso.fit_predict(df[num_cols].fillna(0)) == -1

    df["anomaly_flag"] = z_flag | iqr_flag | iso_flag
else:
    df["anomaly_flag"] = False

# ==============================
# QUALITATIVE CHECK
# ==============================
df["text_flag"] = False

text_cols = df.select_dtypes(include=["object"]).columns

for col in text_cols:
    s = df[col].astype(str).fillna("").str.lower()

    df["text_flag"] |= (
        s.isin(["", "na", "n/a", "none", "null", "test", "xxx"]) |
        (s.str.len() < 2) |
        (s.str.count(r"[a-zA-Z]") < 1)
    )

# ==============================
# CATEGORICAL BIAS
# ==============================
df["cat_flag"] = False

for col in text_cols:
    if df[col].nunique() > 1:
        top_ratio = df[col].value_counts(normalize=True).iloc[0]
        if top_ratio > 0.95:
            df["cat_flag"] = True

# ==============================
# HOUSEHOLD TREND
# ==============================
df["household_trend_flag"] = False

if HH_COL and len(num_cols) > 0:
    for h, g in df.groupby(HH_COL):
        for c in num_cols:
            if (g[c].pct_change().abs() > 3).any():
                df.loc[df[HH_COL] == h, "household_trend_flag"] = True

# ==============================
# FINAL FLAGS
# ==============================
df["quality_issue_flag"] = (
    df["anomaly_flag"] |
    df["text_flag"] |
    df["fraud_flag"] |
    df["household_trend_flag"] |
    df["cat_flag"]
)

# ==============================
# SCORE
# ==============================
df["quality_score"] = 100
df.loc[df["anomaly_flag"], "quality_score"] -= 35
df.loc[df["text_flag"], "quality_score"] -= 10
df.loc[df["fraud_flag"], "quality_score"] -= 15
df.loc[df["household_trend_flag"], "quality_score"] -= 15
df.loc[df["cat_flag"], "quality_score"] -= 10

df["quality_score"] = df["quality_score"].clip(0, 100)

df["quality_category"] = pd.cut(
    df["quality_score"],
    [0, 50, 75, 90, 100],
    labels=["Poor", "Fair", "Good", "Excellent"]
)

clean_df = df[df["quality_score"] >= 50]
flag_df = df[df["quality_score"] < 50]

# ==============================
# AI EXPLAIN
# ==============================
def explain(row):
    r = []
    if row["anomaly_flag"]: r.append("Numeric anomaly")
    if row["text_flag"]: r.append("Text issue")
    if row["fraud_flag"]: r.append("Speed anomaly")
    if row["household_trend_flag"]: r.append("Household inconsistency")
    if row["cat_flag"]: r.append("Categorical imbalance")
    return "\n".join(r) if r else "Clean record"

# ==============================
# DASHBOARD
# ==============================
if page == "Dashboard":
    st.title("📊 REDI ADA Dashboard")

    st.markdown(f"""
    <div style="background:#0f172a;padding:10px;border-radius:10px;color:white;">
    🔗 Active KoBo UID: {FORM_UID}
    </div>
    """, unsafe_allow_html=True)

    c1,c2,c3,c4 = st.columns(4)

    c1.markdown(f'<div class="kpi-card" style="background:#2563eb">Total<br><h1>{len(df)}</h1></div>', unsafe_allow_html=True)
    c2.markdown(f'<div class="kpi-card" style="background:#16a34a">Clean<br><h1>{len(clean_df)}</h1></div>', unsafe_allow_html=True)
    c3.markdown(f'<div class="kpi-card" style="background:#dc2626">Flagged<br><h1>{len(flag_df)}</h1></div>', unsafe_allow_html=True)
    c4.markdown(f'<div class="kpi-card" style="background:#7c3aed">Avg Score<br><h1>{df["quality_score"].mean():.1f}</h1></div>', unsafe_allow_html=True)

    st.bar_chart(df["quality_category"].value_counts())

# ==============================
# EXPLORER
# ==============================
elif page == "Explorer":
    t1,t2 = st.tabs(["Clean", "Flagged"])
    t1.dataframe(clean_df)
    t2.dataframe(flag_df)

# ==============================
# AI EXPLAIN
# ==============================
elif page == "AI Explain":
    i = st.selectbox("Select record", df.index)
    st.dataframe(df.loc[i].to_frame())
    st.info(explain(df.loc[i]))

# ==============================
# DOWNLOADS
# ==============================
elif page == "Downloads":

    def excel(data):
        out = io.BytesIO()
        with pd.ExcelWriter(out, engine="openpyxl") as w:
            data.to_excel(w, index=False)
        return out

    def full_excel():
        out = io.BytesIO()
        with pd.ExcelWriter(out, engine="openpyxl") as w:
            df.to_excel(w, sheet_name="All")
            clean_df.to_excel(w, sheet_name="Clean")
            flag_df.to_excel(w, sheet_name="Flagged")
        return out

    def pdf_report():
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer)
        styles = getSampleStyleSheet()

        fig = plt.figure()
        df["quality_category"].value_counts().plot(kind="bar")
        plt.title("Quality Distribution")
        c1 = "/tmp/c1.png"
        plt.savefig(c1); plt.close(fig)

        fig = plt.figure()
        pd.Series({
            "Numeric": df["anomaly_flag"].sum(),
            "Text": df["text_flag"].sum(),
            "Fraud": df["fraud_flag"].sum(),
            "Cat": df["cat_flag"].sum()
        }).plot(kind="bar")
        plt.title("Issues Breakdown")
        c2 = "/tmp/c2.png"
        plt.savefig(c2); plt.close(fig)

        narrative = f"""
        Dataset UID: {FORM_UID}
        Total records: {len(df)}
        Clean: {len(clean_df)} | Flagged: {len(flag_df)}
        Average score: {df['quality_score'].mean():.2f}
        """

        content = [
            Paragraph("REDI ADA Data Quality Report", styles["Title"]),
            Spacer(1, 12),
            Paragraph(narrative, styles["Normal"]),
            Spacer(1, 12),
            Image(c1, width=400, height=250),
            Spacer(1, 12),
            Image(c2, width=400, height=250)
        ]

        doc.build(content)
        buffer.seek(0)
        return buffer

    st.title("📥 Downloads")

    c1,c2,c3,c4 = st.columns(4)

    with c1:
        st.download_button("📊 Full Excel", full_excel(), "full.xlsx")

    with c2:
        st.download_button("✅ Clean Excel", excel(clean_df), "clean.xlsx")

    with c3:
        st.download_button("⚠ Flagged Excel", excel(flag_df), "flagged.xlsx")

    with c4:
        st.download_button("📄 PDF Report", pdf_report(), "report.pdf")

# ==============================
# FOOTER
# ==============================
st.caption(f"REDI ADA System • Updated {datetime.now()}")
