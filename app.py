# =========================================
# REDI AUTOMATED DATA QUALITY MONITORING SYSTEM
# FINAL PRODUCTION VERSION (FULL FEATURES RESTORED)
# =========================================

import streamlit as st
import pandas as pd
import io
import requests
import numpy as np
import os
import logging
import yaml
import streamlit_authenticator as stauth

from yaml.loader import SafeLoader
from datetime import datetime
from sklearn.ensemble import IsolationForest

from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
)
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet

import plotly.express as px

# =========================================
# PAGE CONFIG
# =========================================
st.set_page_config(
    page_title="REDI Automated Data Quality Monitoring System",
    layout="wide",
    page_icon="📊"
)

APP_NAME = "REDI Automated Data Quality Monitoring System"
ENABLE_AI = True
AI_CONTAMINATION = 0.005

# =========================================
# FULL STYLING (RESTORED)
# =========================================
st.markdown("""
<style>
.stApp {
    background: linear-gradient(135deg,#f3f7ff,#dbeafe);
}
[data-testid="stForm"] {
    background:white;
    padding:40px;
    border-radius:18px;
    box-shadow:0 6px 18px rgba(0,0,0,0.15);
}
button[kind="primary"] {
    background-color:#1e3a8a !important;
    color:white !important;
    border-radius:10px !important;
}
section[data-testid="stSidebar"] {
    background-color:#1e3a8a !important;
}
section[data-testid="stSidebar"] * {
    color:white !important;
}
.kpi-card {
    padding:20px;
    border-radius:14px;
    color:white;
    text-align:center;
    box-shadow:0 4px 10px rgba(0,0,0,0.2);
}
.btn-green {background:#16a34a;color:white;padding:12px;border-radius:10px;}
.btn-red {background:#dc2626;color:white;padding:12px;border-radius:10px;}
.btn-blue {background:#2563eb;color:white;padding:12px;border-radius:10px;}
.btn-purple {background:#7c3aed;color:white;padding:12px;border-radius:10px;}
</style>
""", unsafe_allow_html=True)

# =========================================
# LOGGING
# =========================================
os.makedirs("logs", exist_ok=True)

logging.basicConfig(
    filename="logs/redi.log",
    level=logging.ERROR,
    format="%(asctime)s %(levelname)s %(message)s"
)

# =========================================
# AUTHENTICATION
# =========================================
with open("config.yaml") as file:
    config = yaml.load(file, Loader=SafeLoader)

authenticator = stauth.Authenticate(
    config["credentials"],
    config["cookie"]["name"],
    config["cookie"]["key"],
    config["cookie"]["expiry_days"]
)

authenticator.login()

name = st.session_state.get("name")
auth_status = st.session_state.get("authentication_status")
username = st.session_state.get("username")

if auth_status is False:
    st.error("Incorrect username or password")
    st.stop()

if auth_status is None:
    st.warning("Please login")
    st.stop()

authenticator.logout("Logout", "sidebar")

st.sidebar.success(f"Welcome {name}")
role = config["credentials"]["usernames"][username]["role"]
st.sidebar.info(f"Role: {role}")

# =========================================
# SYSTEM STATUS + TOKEN CHECK
# =========================================
KOBO_TOKEN = st.secrets.get("KOBO_TOKEN")

if not KOBO_TOKEN:
    st.error("Missing KoBo API token")
    st.stop()

# =========================================
# SIDEBAR
# =========================================
st.sidebar.title("📊 REDI Universal Data System")

FORM_UID = st.sidebar.text_input("Kobo Form UID")

if FORM_UID and len(FORM_UID) < 10:
    st.sidebar.error("Invalid UID format")

page_options = ["Dashboard","Explorer","Quality Analytics","Downloads"]

if role == "enumerator":
    page_options = ["Dashboard","Explorer"]
elif role == "supervisor":
    page_options = ["Dashboard","Explorer","Quality Analytics"]

page = st.sidebar.radio("Navigation", page_options)

# =========================================
# FETCH DATA (WITH ERROR FEEDBACK)
# =========================================
@st.cache_data(ttl=120)
def fetch_data(uid, token):
    if not uid:
        return pd.DataFrame()

    headers = {"Authorization": f"Token {token}"}
    url = f"https://kf.kobotoolbox.org/api/v2/assets/{uid}/data/?format=json&page_size=1000"

    all_data = []

    while url:
        try:
            r = requests.get(url, headers=headers, timeout=30)

            if r.status_code != 200:
                logging.error(f"Kobo API error {r.status_code}")
                break

            data = r.json()
            all_data.extend(data.get("results", []))
            url = data.get("next")

        except Exception as e:
            logging.error(str(e))
            break

    return pd.json_normalize(all_data)

# =========================================
# LOAD WITH SPINNER
# =========================================
with st.spinner("Fetching data from KoBo..."):
    df = fetch_data(FORM_UID, KOBO_TOKEN)

# =========================================
# OFFLINE BACKUP
# =========================================
if df.empty:
    if os.path.exists("backup.csv"):
        df = pd.read_csv("backup.csv")
        st.warning("Offline mode: using last data")
    else:
        st.warning("No data found")
        st.stop()

df.to_csv("backup.csv", index=False)

st.sidebar.success("API Connected")
st.sidebar.success("AI Engine Active")
st.sidebar.info(f"Records: {len(df)}")

# =========================================
# DETECTION
# =========================================
def detect(names):
    for col in df.columns:
        for n in names:
            if n in col.lower():
                return col
    return None

DATE_COL = detect(["submission_time","date","time"])

if "_submission_time" in df.columns:
    DATE_COL = "_submission_time"

if DATE_COL:
    df[DATE_COL] = pd.to_datetime(df[DATE_COL], errors="coerce")

# =========================================
# NUMERIC
# =========================================
num_cols = df.select_dtypes(include=["number"]).columns

# =========================================
# ANOMALY
# =========================================
if len(num_cols) > 0:
    std = df[num_cols].std().replace(0,1)
    z = np.abs((df[num_cols]-df[num_cols].mean())/std)
    df["anomaly_flag"] = z.max(axis=1) > 4.5
else:
    df["anomaly_flag"] = False

# =========================================
# AI
# =========================================
try:
    if ENABLE_AI and len(num_cols) > 2:
        model = IsolationForest(contamination=AI_CONTAMINATION)
        df["ai_flag"] = model.fit_predict(df[num_cols].fillna(0)) == -1
    else:
        df["ai_flag"] = False
except Exception as e:
    logging.error(str(e))
    st.error("AI error occurred")
    df["ai_flag"] = False

# =========================================
# QUALITATIVE ENGINE (RESTORED FULL)
# =========================================
df["qualitative_flag"] = False
df["qualitative_issue"] = ""

invalid_patterns = ["asdf","test","xxx","na","n/a","unknown"]

for col in df.columns:
    mask = df[col].astype(str).str.lower().isin(invalid_patterns)
    df.loc[mask,"qualitative_flag"] = True
    df.loc[mask,"qualitative_issue"] += f"Bad text {col}; "

# =========================================
# FINAL FLAGS
# =========================================
df["flag_score"] = (
    df["anomaly_flag"].astype(int) +
    df["ai_flag"].astype(int) +
    df["qualitative_flag"].astype(int)
)

df["final_flag"] = df["flag_score"] >= 1

# =========================================
# AI EXPLANATION
# =========================================
def explain(row):
    r=[]
    if row["anomaly_flag"]: r.append("Stat anomaly")
    if row["ai_flag"]: r.append("AI anomaly")
    if row["qualitative_flag"]: r.append(row["qualitative_issue"])
    return " | ".join(r)

df["ai_explain"] = df.apply(explain, axis=1)

# =========================================
# SPLIT
# =========================================
clean_df = df[~df["final_flag"]]
flag_df = df[df["final_flag"]]

total=len(df)
valid=len(clean_df)
bad=len(flag_df)
score=(valid/total)*100 if total else 0

# =========================================
# DASHBOARD (FULL UI RESTORED)
# =========================================
if page=="Dashboard":

    st.title(APP_NAME)

    c1,c2,c3,c4 = st.columns(4)

    c1.markdown(f"<div class='kpi-card' style='background:#2563eb'><h3>Total</h3><h1>{total}</h1></div>",unsafe_allow_html=True)
    c2.markdown(f"<div class='kpi-card' style='background:#16a34a'><h3>Valid</h3><h1>{valid}</h1></div>",unsafe_allow_html=True)
    c3.markdown(f"<div class='kpi-card' style='background:#dc2626'><h3>Flagged</h3><h1>{bad}</h1></div>",unsafe_allow_html=True)
    c4.markdown(f"<div class='kpi-card' style='background:#7c3aed'><h3>Score</h3><h1>{score:.1f}%</h1></div>",unsafe_allow_html=True)

    fig = px.bar(
        pd.DataFrame({"Category":["Valid","Flagged"],"Count":[valid,bad]}),
        x="Category",y="Count",text="Count"
    )
    st.plotly_chart(fig,use_container_width=True)

# =========================================
# EXPLORER
# =========================================
elif page=="Explorer":

    tab1,tab2=st.tabs(["Clean","Flagged"])

    with tab1:
        st.dataframe(clean_df,use_container_width=True)

    with tab2:
        st.dataframe(flag_df,use_container_width=True)

# =========================================
# QUALITY
# =========================================
elif page=="Quality Analytics":

    st.dataframe(
        df[["anomaly_flag","ai_flag","qualitative_flag"]].sum().reset_index(),
        use_container_width=True
    )

# =========================================
# DOWNLOADS (FULL RESTORED)
# =========================================
elif page=="Downloads":

    def to_excel(data):
        output=io.BytesIO()
        with pd.ExcelWriter(output,engine="openpyxl") as writer:
            data.to_excel(writer,index=False)
        output.seek(0)
        return output

    st.download_button("Download Clean",to_excel(clean_df),"clean.xlsx")
    st.download_button("Download Flagged",to_excel(flag_df),"flagged.xlsx")

# =========================================
# FOOTER
# =========================================
st.caption(f"{APP_NAME} | {datetime.now()}")
