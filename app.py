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
# SAFE DB (OPTIONAL ENTERPRISE)
# ==============================
try:
    from sqlalchemy import create_engine
    DB_URL = st.secrets.get("DATABASE_URL", None)
    engine = create_engine(DB_URL) if DB_URL else None
except:
    engine = None

# ==============================
# CONFIG
# ==============================
st.set_page_config(page_title="REDI Enterprise System", layout="wide")

# ==============================
# AUTO REFRESH (ENTERPRISE FEEL)
# ==============================
st.markdown("""
<script>
setTimeout(function(){window.location.reload();}, 60000);
</script>
""", unsafe_allow_html=True)

# ==============================
# STYLE
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
# SIDEBAR
# ==============================
st.sidebar.title("📊 REDI Enterprise System")
FORM_UID = st.sidebar.text_input("Form UID")
page = st.sidebar.radio("Navigation", ["Dashboard", "Explorer", "Downloads"])

KOBO_TOKEN = st.secrets.get("KOBO_TOKEN", None)

if engine:
    st.sidebar.success("🟢 Database Mode")
else:
    st.sidebar.info("🟡 API Mode")

if st.sidebar.button("🔄 Refresh"):
    st.cache_data.clear()
    st.rerun()

# ==============================
# ENTERPRISE FETCH (DELTA + DB)
# ==============================
@st.cache_data(ttl=60)
def fetch_data(uid, token):
    if not uid:
        return pd.DataFrame()

    # 1. TRY DATABASE FIRST
    if engine:
        try:
            df = pd.read_sql(f"SELECT * FROM redi_data WHERE form_uid='{uid}'", engine)
            if not df.empty:
                return df
        except:
            pass

    # 2. DELTA SYNC FROM KOBO
    headers = {"Authorization": f"Token {token}"} if token else {}

    last_time = st.session_state.get("last_sync", None)

    if last_time:
        url = f"https://kf.kobotoolbox.org/api/v2/assets/{uid}/data/?query={{\"_submission_time\":{{\"$gt\":\"{last_time}\"}}}}"
    else:
        url = f"https://kf.kobotoolbox.org/api/v2/assets/{uid}/data/?page_size=1000"

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

    new_df = pd.json_normalize(all_data)

    if new_df.empty:
        return st.session_state.get("data_store", pd.DataFrame())

    # UPDATE LAST SYNC
    if "_submission_time" in new_df.columns:
        st.session_state["last_sync"] = new_df["_submission_time"].max()

    # MERGE MEMORY
    if "data_store" not in st.session_state:
        st.session_state["data_store"] = new_df
    else:
        st.session_state["data_store"] = pd.concat(
            [st.session_state["data_store"], new_df]
        ).drop_duplicates()

    final_df = st.session_state["data_store"]

    # 3. SAVE TO DATABASE (ENTERPRISE)
    if engine:
        try:
            final_df["form_uid"] = uid
            final_df.to_sql("redi_data", engine, if_exists="append", index=False)
        except:
            pass

    return final_df

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
HH_COL = detect(["hh","household","id"])
ENUM_COL = detect(["enum","enumerator","name","user"])
REGION_COL = detect(["region","district","area"])

if "_submission_time" in df.columns:
    DATE_COL = "_submission_time"

if DATE_COL:
    df[DATE_COL] = pd.to_datetime(df[DATE_COL], errors="coerce")

# ==============================
# FILTERS
# ==============================
if DATE_COL:
    c1,c2 = st.sidebar.columns(2)
    start = c1.date_input("Start", df[DATE_COL].min())
    end = c2.date_input("End", df[DATE_COL].max())
    df = df[(df[DATE_COL]>=pd.to_datetime(start)) & (df[DATE_COL]<=pd.to_datetime(end))]

search = st.sidebar.text_input("Search")
if search:
    df = df[df.astype(str).apply(lambda x: x.str.contains(search,case=False,na=False).any(),axis=1)]

# ==============================
# PREP
# ==============================
if DATE_COL:
    df["Month"] = df[DATE_COL].dt.to_period("M").astype(str)

# ==============================
# ANOMALY
# ==============================
num_cols = df.select_dtypes(include=["number"]).columns
if len(num_cols)>0:
    std = df[num_cols].std().replace(0,1)
    z = np.abs((df[num_cols]-df[num_cols].mean())/std)
    df["anomaly_flag"] = z.max(axis=1)>3
else:
    df["anomaly_flag"] = False

# ==============================
# PANEL
# ==============================
if HH_COL and "Month" in df.columns:
    flags=[]
    for hh,g in df.groupby(HH_COL):
        g=g.sort_values("Month")
        for col in num_cols:
            vals=g[col].dropna()
            if len(vals)>=2 and (vals.pct_change().abs()>2).any():
                flags.append(hh)
                break
    df["panel_inconsistency"]=df[HH_COL].isin(flags)
else:
    df["panel_inconsistency"]=False

# ==============================
# FRAUD
# ==============================
if ENUM_COL and DATE_COL:
    df=df.sort_values(DATE_COL)
    df["time_diff"]=df.groupby(ENUM_COL)[DATE_COL].diff().dt.total_seconds()

    f=df.groupby(ENUM_COL).agg(
        total=("time_diff","count"),
        fast=("time_diff",lambda x:(x<60).sum())
    ).reset_index()

    f["fraud_score"]=((f["fast"]/f["total"]).fillna(0)*100).clip(upper=100)
    df=df.merge(f[[ENUM_COL,"fraud_score"]],on=ENUM_COL,how="left")
    df["fraud_flag"]=df["fraud_score"]>50
else:
    df["fraud_flag"]=False

# ==============================
# SPLIT
# ==============================
clean_df=df[~df["anomaly_flag"]]
flag_df=df[df["anomaly_flag"]]

total=len(df)
valid=len(clean_df)
bad=len(flag_df)
score=(valid/total*100) if total else 0

# ==============================
# DASHBOARD
# ==============================
if page=="Dashboard":

    st.title("📊 REDI Enterprise Dashboard")

    c1,c2,c3,c4=st.columns(4)
    c1.markdown(f'<div class="kpi-card" style="background:#2563eb"><h3>Total</h3><h1>{total}</h1></div>',unsafe_allow_html=True)
    c2.markdown(f'<div class="kpi-card" style="background:#16a34a"><h3>Valid</h3><h1>{valid}</h1></div>',unsafe_allow_html=True)
    c3.markdown(f'<div class="kpi-card" style="background:#dc2626"><h3>Flagged</h3><h1>{bad}</h1></div>',unsafe_allow_html=True)
    c4.markdown(f'<div class="kpi-card" style="background:#7c3aed"><h3>Score</h3><h1>{score:.1f}%</h1></div>',unsafe_allow_html=True)

    st.bar_chart(pd.DataFrame({"Valid":[valid],"Flagged":[bad]}))

    st.subheader("🚨 Alerts")
    if df["anomaly_flag"].sum()>0: st.error(f"{df['anomaly_flag'].sum()} anomalies")
    if df["panel_inconsistency"].sum()>0: st.error("Panel issues detected")
    if df["fraud_flag"].sum()>0: st.error("Fraud risk detected")

# ==============================
# EXPLORER
# ==============================
elif page=="Explorer":
    st.title("Explorer")
    tab1,tab2=st.tabs(["Clean","Flagged"])
    tab1.dataframe(clean_df)
    tab2.dataframe(flag_df)

# ==============================
# DOWNLOADS
# ==============================
elif page=="Downloads":

    def to_excel():
        o=io.BytesIO()
        with pd.ExcelWriter(o,engine="openpyxl") as w:
            clean_df.to_excel(w,index=False)
            flag_df.to_excel(w,index=False)
        return o.getvalue()

    st.download_button("📊 Full Excel",to_excel(),"redi.xlsx")
    st.download_button("✅ Clean CSV",clean_df.to_csv(index=False),"clean.csv")
    st.download_button("⚠️ Flagged CSV",flag_df.to_csv(index=False),"flagged.csv")

st.caption(f"Updated {datetime.now()}")
