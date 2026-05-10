# ==============================
# REDI FINAL PRODUCTION APP
# ==============================

import streamlit as st
import pandas as pd
import requests
import numpy as np
import os
import logging
import yaml
import io

from yaml.loader import SafeLoader
from datetime import datetime
from sklearn.ensemble import IsolationForest
import streamlit_authenticator as stauth
import plotly.express as px

# ==============================
# CONFIG
# ==============================
st.set_page_config(
    page_title="REDI ADA Login System",
    layout="wide"
)

APP_NAME = "REDI Automated Data Quality Monitoring System"

# ==============================
# SAFE CONFIG LOAD
# ==============================
try:
    with open("config.yaml") as file:
        config = yaml.load(file, Loader=SafeLoader)
except Exception:
    st.error("❌ Missing config.yaml")
    st.stop()

# ==============================
# AUTH
# ==============================
authenticator = stauth.Authenticate(
    config["credentials"],
    config["cookie"]["name"],
    config["cookie"]["key"],
    config["cookie"]["expiry_days"]
)

authenticator.login()

if st.session_state.get("authentication_status") is False:
    st.error("Invalid login")
    st.stop()

if st.session_state.get("authentication_status") is None:
    st.warning("Enter login credentials")
    st.stop()

name = st.session_state["name"]
username = st.session_state["username"]
role = config["credentials"]["usernames"][username]["role"]

authenticator.logout("Logout", "sidebar")

# ==============================
# LOGGING
# ==============================
os.makedirs("logs", exist_ok=True)
logging.basicConfig(filename="logs/app.log", level=logging.ERROR)

# ==============================
# SIDEBAR
# ==============================
st.sidebar.title("REDI ADA System")
st.sidebar.success(f"Welcome {name}")
st.sidebar.info(f"Role: {role}")

FORM_UID = st.sidebar.text_input("KoBo Form UID")

if not FORM_UID:
    st.warning("⚠️ Enter KoBo Form UID")
    st.stop()

# ==============================
# KOBO TOKEN
# ==============================
KOBO_TOKEN = st.secrets.get("KOBO_TOKEN")

# ==============================
# FETCH DATA
# ==============================
@st.cache_data(ttl=120)
def fetch_data(uid, token):
    url = f"https://kf.kobotoolbox.org/api/v2/assets/{uid}/data/?format=json"

    try:
        r = requests.get(
            url,
            headers={"Authorization": f"Token {token}"},
            timeout=20
        )

        if r.status_code != 200:
            return None

        data = r.json()
        return pd.json_normalize(data["results"])

    except Exception as e:
        logging.error(str(e))
        return None

# ==============================
# LOAD DATA
# ==============================
with st.spinner("Fetching data..."):
    df = fetch_data(FORM_UID, KOBO_TOKEN)

if df is None:
    st.error("❌ Failed to fetch data. Check UID or token.")
    st.stop()

if df.empty:
    st.warning("No data found")
    st.stop()

# ==============================
# NUMERIC
# ==============================
num_cols = df.select_dtypes(include=["number"]).columns

# ==============================
# ANOMALY
# ==============================
if len(num_cols) > 0:
    z = np.abs((df[num_cols] - df[num_cols].mean()) / df[num_cols].std().replace(0,1))
    df["anomaly_flag"] = z.max(axis=1) > 4
else:
    df["anomaly_flag"] = False

# ==============================
# AI
# ==============================
if len(num_cols) > 2:
    try:
        model = IsolationForest(contamination=0.01)
        df["ai_flag"] = model.fit_predict(df[num_cols].fillna(0)) == -1
    except:
        df["ai_flag"] = False
else:
    df["ai_flag"] = False

# ==============================
# FINAL FLAG
# ==============================
df["final_flag"] = df["anomaly_flag"] | df["ai_flag"]

clean_df = df[~df["final_flag"]]
flag_df = df[df["final_flag"]]

# ==============================
# KPIs
# ==============================
total = len(df)
valid = len(clean_df)
bad = len(flag_df)
score = (valid / total * 100) if total else 0

# ==============================
# DASHBOARD
# ==============================
st.title(APP_NAME)

c1, c2, c3, c4 = st.columns(4)

c1.metric("Total", total)
c2.metric("Valid", valid)
c3.metric("Flagged", bad)
c4.metric("Quality %", f"{score:.1f}")

fig = px.bar(
    pd.DataFrame({"Type": ["Valid","Flagged"], "Count":[valid,bad]}),
    x="Type",
    y="Count"
)

st.plotly_chart(fig, use_container_width=True)

# ==============================
# TABLES
# ==============================
tab1, tab2 = st.tabs(["Clean", "Flagged"])

tab1.dataframe(clean_df, use_container_width=True)
tab2.dataframe(flag_df, use_container_width=True)

# ==============================
# DOWNLOADS
# ==============================
def to_excel(data):
    buffer = io.BytesIO()
    data.to_excel(buffer, index=False)
    return buffer.getvalue()

st.download_button("Download Clean", to_excel(clean_df), "clean.xlsx")
st.download_button("Download Flagged", to_excel(flag_df), "flagged.xlsx")

# ==============================
# FOOTER
# ==============================
st.caption(f"{APP_NAME} | {datetime.now()}")
