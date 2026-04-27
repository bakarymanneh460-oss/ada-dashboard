import streamlit as st
import pandas as pd
import requests
from datetime import datetime
from streamlit_autorefresh import st_autorefresh

# ===============================
# CONFIG
# ===============================
st.set_page_config(
    page_title="ADA System",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ===============================
# AUTO REFRESH (30s)
# ===============================
st_autorefresh(interval=30000, key="refresh")

# ===============================
# KOBO SETTINGS (HARDCODED FOR DEMO)
# ===============================
KOBO_TOKEN = "a2ab18a6fc3c16ae848742bfa03058b15a0d6538"
FORM_UID = "aQJmYa6Z9mJ5qwdw8RrQcj"

# ===============================
# FETCH DATA
# ===============================
@st.cache_data
def fetch_data():
    url = f"https://kf.kobotoolbox.org/api/v2/assets/{FORM_UID}/data/?format=json"

    headers = {
        "Authorization": f"Token {KOBO_TOKEN}"
    }

    response = requests.get(url, headers=headers)

    if response.status_code != 200:
        raise Exception(f"API Error: {response.status_code}")

    data = response.json().get("results", [])
    df = pd.json_normalize(data)

    return df

# ===============================
# LOAD DATA
# ===============================
try:
    df = fetch_data()
    st.success(f"✅ Live data loaded ({len(df)} records)")
except Exception as e:
    st.error(f"❌ Failed to load Kobo data: {e}")
    st.stop()

# ===============================
# VALIDATION
# ===============================
def validate(row):
    errors = []

    if "age" in row:
        try:
            if row["age"] < 15 or row["age"] > 60:
                errors.append("invalid_age")
        except:
            errors.append("invalid_age")

    return errors

df["errors"] = df.apply(validate, axis=1)
df["is_valid"] = df["errors"].apply(lambda x: len(x) == 0)

clean_df = df[df["is_valid"]]
flagged_df = df[~df["is_valid"]]

total = len(df)
valid = len(clean_df)
flagged = len(flagged_df)
score = (valid / total) * 100 if total > 0 else 0

# ===============================
# 🚨 LIVE ALERT SYSTEM
# ===============================
if flagged > 0:
    st.markdown(
        f"<h3 style='color:red;'>🚨 ALERT: {flagged} problematic records detected!</h3>",
        unsafe_allow_html=True
    )

    error_counts = flagged_df["errors"].explode().value_counts()
    top_issue = error_counts.idxmax()

    st.warning(f"⚠️ Most common issue: {top_issue}")

    if "enumerator" in flagged_df.columns:
        top_enum = (
            flagged_df.groupby("enumerator")
            .size()
            .sort_values(ascending=False)
            .index[0]
        )
        st.warning(f"👤 Highest errors from: {top_enum}")

else:
    st.success("✅ No data quality issues detected")

# ===============================
# SIDEBAR
# ===============================
st.sidebar.title("📊 ADA System")
st.sidebar.caption("Real-Time Monitoring")

page = st.sidebar.radio(
    "Navigation",
    ["🏠 Overview", "📋 Data Tables", "📊 Analytics"]
)

st.sidebar.markdown("---")
st.sidebar.info("🔄 Auto-refresh enabled (30s)")

# ===============================
# HEADER
# ===============================
st.markdown("""
<div style='display:flex; align-items:center; gap:15px;'>
    <div style='
        width:60px;height:60px;border-radius:50%;
        background: linear-gradient(135deg,#2E86C1,#28B463);
        display:flex;align-items:center;justify-content:center;
        color:white;font-weight:bold;font-size:22px;'>
        ADA
    </div>
    <div>
        <h2 style='margin:0;'>ADA System Dashboard</h2>
        <p style='margin:0;color:gray;'>Automated Data Auditing & Monitoring</p>
    </div>
</div>
""", unsafe_allow_html=True)

st.caption(f"🕒 Last Updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
st.divider()

# ===============================
# OVERVIEW
# ===============================
if page == "🏠 Overview":

    st.subheader("📊 System Overview")

    col1, col2, col3, col4 = st.columns(4)

    col1.metric("Total Records", total)
    col2.metric("Valid Records", valid)
    col3.metric("Flagged Records", flagged)
    col4.metric("Quality Score", f"{score:.1f}%")

    st.progress(score / 100)

# ===============================
# DATA TABLES
# ===============================
elif page == "📋 Data Tables":

    st.subheader("📋 Data Explorer")

    tab1, tab2 = st.tabs(["✅ Clean Data", "🚨 Flagged Data"])

    with tab1:
        st.dataframe(clean_df, use_container_width=True)

    with tab2:
        st.dataframe(flagged_df, use_container_width=True)

    st.download_button(
        "⬇ Download Clean Data",
        clean_df.to_csv(index=False),
        "clean_data.csv"
    )

    st.download_button(
        "⬇ Download Flagged Data",
        flagged_df.to_csv(index=False),
        "flagged_data.csv"
    )

# ===============================
# ANALYTICS
# ===============================
elif page == "📊 Analytics":

    st.subheader("📊 Data Insights")

    if not flagged_df.empty:

        error_counts = flagged_df["errors"].explode().value_counts()

        col1, col2 = st.columns(2)

        with col1:
            st.write("📌 Error Summary")
            st.bar_chart(error_counts)

        with col2:
            st.write("📈 Error Distribution")
            st.line_chart(error_counts)

        st.info(f"🧠 Top issue: {error_counts.idxmax()}")

        # Enumerator performance
        if "enumerator" in df.columns:
            st.subheader("👤 Enumerator Performance")

            perf = flagged_df.groupby("enumerator").size().reset_index(name="Errors")

            st.bar_chart(perf.set_index("enumerator"))
            st.dataframe(perf, use_container_width=True)

            if len(perf["Errors"].unique()) == 1:
                st.info("ℹ️ Equal performance across all enumerators")
            else:
                worst = perf.sort_values("Errors", ascending=False).iloc[0]
                best = perf.sort_values("Errors", ascending=True).iloc[0]

                st.warning(f"⚠️ Needs Attention: {worst['enumerator']} ({worst['Errors']} errors)")
                st.success(f"🏆 Best Performer: {best['enumerator']} ({best['Errors']} errors)")

    else:
        st.success("🎉 No issues found — excellent data quality!")

# ===============================
# FOOTER
# ===============================
st.markdown("---")
st.caption("ADA System • Live Kobo Integration • Auto Alerts Enabled")