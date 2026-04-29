import streamlit as st
import pandas as pd
import io
import requests
from datetime import datetime
import numpy as np

# ==============================
# SAFE DB IMPORT (NO CRASH)
# ==============================
try:
    from sqlalchemy import create_engine
    DB_URL = st.secrets.get("DATABASE_URL", None)
    engine = create_engine(DB_URL) if DB_URL else None
except:
    engine = None

st.set_page_config(page_title="REDI Data Quality System", layout="wide")

# ==============================
# SIDEBAR
# ==============================
st.sidebar.markdown("## 📊 REDI Data Quality System")

FORM_UID = st.sidebar.text_input("Form UID", "")
page = st.sidebar.radio("Navigation", ["Dashboard", "Explorer", "Downloads"])

KOBO_TOKEN = st.secrets.get("KOBO_TOKEN", None)

if engine:
    st.sidebar.success("🟢 Database connected")
else:
    st.sidebar.info("🟡 Using Kobo API")

# ==============================
# MANUAL REFRESH (SAFE)
# ==============================
if st.sidebar.button("🔄 Refresh Data"):
    st.cache_data.clear()
    st.rerun()

# ==============================
# FETCH DATA (DB FIRST, KOBO FALLBACK)
# ==============================
@st.cache_data(ttl=120)
def fetch_data(uid, token):

    # Try DB first
    if engine:
        try:
            df = pd.read_sql("SELECT * FROM clean_data", engine)
            if not df.empty:
                return df
        except:
            pass

    # Kobo fallback
    if not uid:
        return pd.DataFrame()

    url = f"https://kf.kobotoolbox.org/api/v2/assets/{uid}/data/"
    headers = {"Authorization": f"Token {token}"} if token else {}

    try:
        r = requests.get(url, headers=headers)
        if r.status_code != 200:
            return pd.DataFrame()
        return pd.json_normalize(r.json().get("results", []))
    except:
        return pd.DataFrame()

df = fetch_data(FORM_UID, KOBO_TOKEN)

if df.empty:
    st.warning("No data available")
    st.stop()

# ==============================
# PREP
# ==============================
if "_submission_time" in df.columns:
    df["_submission_time"] = pd.to_datetime(df["_submission_time"], errors="coerce")
    df["Month"] = df["_submission_time"].dt.to_period("M").astype(str)

# ==============================
# ANOMALY DETECTION (SAFE)
# ==============================
numeric_cols = df.select_dtypes(include=["number"]).columns

if len(numeric_cols) > 0:
    std = df[numeric_cols].std().replace(0, 1)
    z = np.abs((df[numeric_cols] - df[numeric_cols].mean()) / std)
    df["anomaly_flag"] = z.max(axis=1) > 3
else:
    df["anomaly_flag"] = False

# ==============================
# SPLIT
# ==============================
clean_df = df[~df["anomaly_flag"]]
flag_df = df[df["anomaly_flag"]]

total = len(df)
valid = len(clean_df)
bad = len(flag_df)
score = (valid / total * 100) if total else 0

# ==============================
# DASHBOARD
# ==============================
if page == "Dashboard":

    st.title("📊 REDI Data Quality Dashboard")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total", total)
    c2.metric("Valid", valid)
    c3.metric("Flagged", bad)
    c4.metric("Quality Score", f"{score:.1f}%")

    st.bar_chart(pd.DataFrame({"Valid":[valid], "Flagged":[bad]}))

    # ==========================
    # ENUMERATOR PERFORMANCE
    # ==========================
    enum_col = next((c for c in df.columns if "enumerator" in c.lower() or "name" in c.lower()), None)

    if enum_col:
        st.subheader("🧑‍💼 Enumerator Performance")

        enum_df = df.groupby(enum_col)["anomaly_flag"].agg(["count","sum"]).reset_index()
        enum_df["score"] = (1 - enum_df["sum"] / enum_df["count"]) * 100
        enum_df["score"] = enum_df["score"].clip(0,100)

        st.dataframe(enum_df.sort_values("score", ascending=False))
        st.bar_chart(enum_df.set_index(enum_col)["score"])

    # ==========================
    # HOUSEHOLD TRACKING
    # ==========================
    if "HH_ID" in df.columns and "Month" in df.columns:

        st.subheader("🏠 Household 12-Month Completeness")

        hh = df.groupby("HH_ID")["Month"].nunique().reset_index(name="months")
        hh["completeness_%"] = (hh["months"] / 12) * 100

        def status(m):
            if m == 12:
                return "Complete"
            elif m >= 6:
                return "Partial"
            else:
                return "Low"

        hh["status"] = hh["months"].apply(status)

        st.dataframe(hh.sort_values("completeness_%", ascending=False))
        st.bar_chart(hh["status"].value_counts())

    # ==========================
    # MONTHLY TREND
    # ==========================
    if "Month" in df.columns:
        st.subheader("📅 Monthly Submissions")
        st.line_chart(df.groupby("Month").size())

    # ==========================
    # FLAGGED DATA
    # ==========================
    st.subheader("⚠️ Flagged Data Sample")
    st.dataframe(flag_df.head(50))

# ==============================
# EXPLORER
# ==============================
elif page == "Explorer":
    st.dataframe(df)

# ==============================
# DOWNLOADS
# ==============================
elif page == "Downloads":

    st.subheader("Download Data")

    st.download_button("📁 Clean CSV", clean_df.to_csv(index=False), "clean.csv")
    st.download_button("⚠️ Flagged CSV", flag_df.to_csv(index=False), "flagged.csv")

st.caption(f"Last updated: {datetime.now()}")
