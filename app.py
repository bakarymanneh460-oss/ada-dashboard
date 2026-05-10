# =========================================
# REDI ENTERPRISE SAAS FRONTEND (STREAMLIT)
# API-FIRST PRODUCTION CLIENT
# =========================================

import streamlit as st
import requests
import pandas as pd
import plotly.express as px
from datetime import datetime

# =========================================
# CONFIG
# =========================================
st.set_page_config(
    page_title="REDI SaaS Platform",
    layout="wide",
    page_icon="📊"
)

API_URL = st.secrets["API_URL"]
API_KEY = st.secrets["API_KEY"]

HEADERS = {
    "x-api-key": API_KEY
}

# =========================================
# AUTH SIMULATION (SAAS CLIENT SIDE)
# =========================================
st.sidebar.title("REDI SaaS")

page = st.sidebar.radio(
    "Navigation",
    ["Dashboard", "Data Explorer", "Analytics", "Live Monitor"]
)

st.sidebar.info("Connected to REDI SaaS API")

# =========================================
# API FUNCTIONS
# =========================================
def get_data(endpoint):

    try:
        r = requests.get(f"{API_URL}/{endpoint}", headers=HEADERS, timeout=30)
        return pd.DataFrame(r.json())
    except Exception as e:
        st.error(f"API Error: {e}")
        return pd.DataFrame()

# =========================================
# LOAD DATA FROM API
# =========================================
df = get_data("data")

if df.empty:
    st.warning("No data available from API")
    st.stop()

# =========================================
# DASHBOARD (ROLE BASED VIEW)
# =========================================
if page == "Dashboard":

    st.title("📊 REDI SaaS Dashboard")

    c1, c2, c3 = st.columns(3)

    c1.metric("Total Records", len(df))

    if "fraud_score" in df.columns:
        c2.metric("Avg Fraud Score", round(df["fraud_score"].mean(), 2))
        c3.metric("High Risk Cases", len(df[df["fraud_level"] == "High"]))
    else:
        c2.metric("Avg Fraud Score", "N/A")
        c3.metric("High Risk Cases", "N/A")

    st.subheader("Fraud Distribution")

    if "fraud_level" in df.columns:

        fig = px.pie(
            df,
            names="fraud_level",
            title="Risk Levels"
        )

        st.plotly_chart(fig, use_container_width=True)

# =========================================
# DATA EXPLORER
# =========================================
elif page == "Data Explorer":

    st.title("📁 Data Explorer")

    view = st.selectbox(
        "Select View",
        ["All Data", "Clean Data", "Flagged Data"]
    )

    if view == "All Data":
        data = df

    elif view == "Clean Data":
        data = get_data("data/clean")

    else:
        data = get_data("data/flagged")

    st.dataframe(data, use_container_width=True)

# =========================================
# ANALYTICS DASHBOARD
# =========================================
elif page == "Analytics":

    st.title("📈 Advanced Analytics")

    if "fraud_score" in df.columns:

        fig1 = px.histogram(
            df,
            x="fraud_score",
            nbins=20,
            title="Fraud Score Distribution"
        )

        st.plotly_chart(fig1, use_container_width=True)

    if "fraud_level" in df.columns:

        summary = df["fraud_level"].value_counts().reset_index()
        summary.columns = ["Level", "Count"]

        fig2 = px.bar(
            summary,
            x="Level",
            y="Count",
            text="Count",
            title="Risk Breakdown"
        )

        st.plotly_chart(fig2, use_container_width=True)

# =========================================
# LIVE MONITOR (REAL-TIME API POLLING)
# =========================================
elif page == "Live Monitor":

    st.title("🔴 Live Data Monitor")

    placeholder = st.empty()

    import time

    for i in range(5):  # simulate live updates

        live_df = get_data("data")

        with placeholder.container():

            st.metric("Last Update", str(datetime.now()))
            st.metric("Records", len(live_df))

            if "fraud_score" in live_df.columns:
                st.metric("Avg Risk", round(live_df["fraud_score"].mean(), 2))

        time.sleep(5)

# =========================================
# FOOTER
# =========================================
st.caption("REDI SaaS Platform | Powered by API-first architecture")
