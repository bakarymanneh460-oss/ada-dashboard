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
# AUTO REFRESH (REAL-TIME)
# ==============================
try:
    from streamlit_autorefresh import st_autorefresh
    st_autorefresh(interval=30000, key="data_refresh")  # 30 sec refresh
except:
    pass

# ==============================
# CONFIG
# ==============================
st.set_page_config(page_title="REDI Data Quality System", layout="wide")

ANOMALY_CONTAMINATION = 0.05
FAST_THRESHOLD = 60

# ==============================
# STYLE
# ==============================
st.markdown("""
<style>
section[data-testid="stSidebar"] {background-color:#1e3a8a !important;}
section[data-testid="stSidebar"] * {color:white !important;}
section[data-testid="stSidebar"] input {background:white !important; color:black !important;}

.kpi-card {
    padding:20px;
    border-radius:14px;
    color:white;
    text-align:center;
    font-weight:bold;
    box-shadow:0px 4px 12px rgba(0,0,0,0.2);
}
</style>
""", unsafe_allow_html=True)

# ==============================
# SIDEBAR
# ==============================
st.sidebar.title("📊 REDI System")
st.sidebar.caption("Live Data Quality Monitoring")

FORM_UID = st.sidebar.text_input("Form UID")
KOBO_TOKEN = st.secrets.get("KOBO_TOKEN", None)

pages = ["Dashboard", "Explorer", "Downloads", "AI Explain"]
page = st.sidebar.radio("Navigation", pages)

if st.sidebar.button("🔄 Refresh Now"):
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

DATE_COL = detect(["submission_time", "date"]) or "_submission_time"
ENUM_COL = detect(["enum", "name", "user"])
HH_COL = detect(["hh", "household", "id"])

# ==============================
# DATE FILTER
# ==============================
df[DATE_COL] = pd.to_datetime(df[DATE_COL], errors="coerce")

start_default = df[DATE_COL].min().date()
end_default = df[DATE_COL].max().date()

c1, c2 = st.sidebar.columns(2)
start_date = c1.date_input("Start Date", start_default)
end_date = c2.date_input("End Date", end_default)

df = df[
    (df[DATE_COL] >= pd.to_datetime(start_date)) &
    (df[DATE_COL] <= pd.to_datetime(end_date))
]

# ==============================
# FEATURES
# ==============================
num_cols = df.select_dtypes(include=["number"]).columns

if ENUM_COL:
    df["time_diff"] = df.groupby(ENUM_COL)[DATE_COL].diff().dt.total_seconds()
else:
    df["time_diff"] = np.nan

# ==============================
# ADAPTIVE THRESHOLDS
# ==============================
def compute_adaptive(df):
    thresholds = {}

    if len(num_cols) > 0:
        std = df[num_cols].std().replace(0, 1)
        z = np.abs((df[num_cols] - df[num_cols].mean()) / std)
        thresholds["z"] = max(2.5, min(z.stack().quantile(0.95), 4))
    else:
        thresholds["z"] = 3

    if ENUM_COL:
        t = df["time_diff"].dropna()
        thresholds["fast"] = max(20, min(t.quantile(0.10), 120)) if len(t) else FAST_THRESHOLD
    else:
        thresholds["fast"] = FAST_THRESHOLD

    return thresholds

adaptive = compute_adaptive(df)

# ==============================
# FRAUD
# ==============================
if ENUM_COL:
    fraud_ratio = df.groupby(ENUM_COL)["time_diff"].apply(
        lambda x: (x.fillna(9999) < adaptive["fast"]).mean()
    )
    bad_enum = fraud_ratio[fraud_ratio > 0.7].index
    df["fraud_flag"] = df[ENUM_COL].isin(bad_enum)
else:
    df["fraud_flag"] = False

# ==============================
# NUMERIC ANOMALY
# ==============================
if len(num_cols) > 0:

    std = df[num_cols].std().replace(0, 1)
    z = np.abs((df[num_cols] - df[num_cols].mean()) / std)
    z_flag = z.max(axis=1) > adaptive["z"]

    Q1 = df[num_cols].quantile(0.25)
    Q3 = df[num_cols].quantile(0.75)
    IQR = Q3 - Q1

    iqr_flag = ((df[num_cols] < (Q1 - 1.5 * IQR)) |
                (df[num_cols] > (Q3 + 1.5 * IQR))).any(axis=1)

    iso_flag = IsolationForest(
        contamination=ANOMALY_CONTAMINATION,
        random_state=42
    ).fit_predict(df[num_cols].fillna(0)) == -1

    df["anomaly_flag"] = z_flag | iqr_flag | iso_flag
else:
    df["anomaly_flag"] = False

# ==============================
# TEXT ISSUES
# ==============================
df["text_flag"] = False
for col in df.select_dtypes(include=["object"]).columns:
    s = df[col].astype(str).str.lower()
    df["text_flag"] |= s.isin(["", "na", "n/a", "none", "null", "test"])

# ==============================
# HOUSEHOLD
# ==============================
df["household_trend_flag"] = False
if HH_COL and len(num_cols) > 0:
    for hh, g in df.groupby(HH_COL):
        for col in num_cols:
            if (g[col].pct_change().abs() > 3).any():
                df.loc[df[HH_COL] == hh, "household_trend_flag"] = True

# ==============================
# FLAG REASONS
# ==============================
df["flag_reason"] = df.apply(
    lambda x: ", ".join(filter(None, [
        "Numeric anomaly" if x["anomaly_flag"] else None,
        "Text issue" if x["text_flag"] else None,
        "Speed anomaly" if x["fraud_flag"] else None,
        "Household inconsistency" if x["household_trend_flag"] else None
    ])) or "Clean",
    axis=1
)

# ==============================
# SCORE
# ==============================
df["quality_score"] = 100
df.loc[df["anomaly_flag"], "quality_score"] -= 40
df.loc[df["text_flag"], "quality_score"] -= 15
df.loc[df["fraud_flag"], "quality_score"] -= 15
df.loc[df["household_trend_flag"], "quality_score"] -= 15
df["quality_score"] = df["quality_score"].clip(0, 100)

df["quality_category"] = pd.cut(
    df["quality_score"],
    bins=[0,50,75,90,100],
    labels=["Poor","Fair","Good","Excellent"]
)

flag_df = df[df["quality_score"] < 50]
clean_df = df[df["quality_score"] >= 50]

# ==============================
# AI EXPLANATION
# ==============================
def explain_row(row):
    r = []
    if row["anomaly_flag"]:
        r.append("⚠ Numeric anomaly detected")
    if row["text_flag"]:
        r.append("✍ Invalid or empty text detected")
    if row["fraud_flag"]:
        r.append("⏱ Suspicious fast submission pattern")
    if row["household_trend_flag"]:
        r.append("🏠 Household inconsistency detected")
    return "\n".join(r) if r else "✅ Clean record"

# ==============================
# DASHBOARD
# ==============================
if page == "Dashboard":
    st.title("📊 REDI Live Dashboard")

    c1,c2,c3,c4 = st.columns(4)

    c1.markdown(f'<div class="kpi-card" style="background:linear-gradient(135deg,#2563eb,#1e40af)">📦 Total<br><h1>{len(df)}</h1></div>', unsafe_allow_html=True)
    c2.markdown(f'<div class="kpi-card" style="background:linear-gradient(135deg,#16a34a,#15803d)">✅ Valid<br><h1>{len(clean_df)}</h1></div>', unsafe_allow_html=True)
    c3.markdown(f'<div class="kpi-card" style="background:linear-gradient(135deg,#dc2626,#991b1b)">⚠ Flagged<br><h1>{len(flag_df)}</h1></div>', unsafe_allow_html=True)
    c4.markdown(f'<div class="kpi-card" style="background:linear-gradient(135deg,#7c3aed,#5b21b6)">📊 Avg Score<br><h1>{df["quality_score"].mean():.1f}</h1></div>', unsafe_allow_html=True)

    st.bar_chart(df["quality_category"].value_counts())

# ==============================
# EXPLORER
# ==============================
elif page == "Explorer":
    tab1, tab2 = st.tabs(["Clean", "Flagged"])
    tab1.dataframe(clean_df)
    tab2.dataframe(flag_df)

# ==============================
# AI EXPLAIN
# ==============================
elif page == "AI Explain":
    st.title("🧠 AI Explanation Panel")

    idx = st.selectbox("Select Record", df.index)

    st.dataframe(df.loc[idx].to_frame())
    st.info(explain_row(df.loc[idx]))

# ==============================
# FOOTER
# ==============================
st.caption(f"Live System • Updated {datetime.now()}")
