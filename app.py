import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import io

# ==============================
# PAGE CONFIG
# ==============================
st.set_page_config(page_title="REDI ADA System (Recovery Mode)", layout="wide")

# ==============================
# THEME (BLUE UI RESTORED)
# ==============================
st.markdown("""
<style>
[data-testid="stAppViewContainer"] {
    background-color: #0b3d91;
}
h1,h2,h3,h4,h5,p,div {
    color:white !important;
}
section[data-testid="stSidebar"] {
    background-color:#062a63 !important;
}
</style>
""", unsafe_allow_html=True)

# ==============================
# SIMPLE LOGIN (LOCAL - TEMPORARY)
# ==============================
USERS = {
    "admin": "admin123",
    "user": "user123"
}

if "auth" not in st.session_state:
    st.session_state.auth = False
    st.session_state.user = None

if not st.session_state.auth:

    st.title("🔐 REDI ADA Login")

    username = st.text_input("Username")
    password = st.text_input("Password", type="password")

    if st.button("Login"):
        if username in USERS and USERS[username] == password:
            st.session_state.auth = True
            st.session_state.user = username
            st.success("Login successful")
            st.rerun()
        else:
            st.error("Invalid credentials")

    st.stop()

# ==============================
# USER HEADER
# ==============================
st.sidebar.title("REDI System")
st.sidebar.success(f"User: {st.session_state.user}")

if st.sidebar.button("Logout"):
    st.session_state.auth = False
    st.rerun()

# ==============================
# SAMPLE DATA (RESTORED SYSTEM)
# ==============================
df = pd.DataFrame({
    "value": np.random.randint(1, 100, 80)
})

# ==============================
# CLEAN / FLAGGED LOGIC
# ==============================
df["score"] = 100 - (df["value"] * 0.6)
df["status"] = np.where(df["score"] < 40, "Flagged", "Clean")

clean_df = df[df["status"] == "Clean"]
flagged_df = df[df["status"] == "Flagged"]

# ==============================
# DASHBOARD
# ==============================
st.title("📊 REDI ADA DASHBOARD")

col1, col2, col3 = st.columns(3)

col1.metric("Total", len(df))
col2.metric("Clean", len(clean_df))
col3.metric("Flagged", len(flagged_df))

chart_df = pd.DataFrame({
    "Category": ["Clean", "Flagged"],
    "Count": [len(clean_df), len(flagged_df)]
})

fig = px.bar(
    chart_df,
    x="Category",
    y="Count",
    color="Category",
    color_discrete_map={
        "Clean": "#2ecc71",
        "Flagged": "#e74c3c"
    },
    text="Count"
)

st.plotly_chart(fig, use_container_width=True)

st.dataframe(df, use_container_width=True)

# ==============================
# EXPORT SYSTEM (WORKING)
# ==============================
st.subheader("📦 Export Data")

def to_excel(data):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        data.to_excel(writer, index=False)
    output.seek(0)
    return output

st.download_button("⬇️ Clean Data", to_excel(clean_df), "clean.xlsx")
st.download_button("⬇️ Flagged Data", to_excel(flagged_df), "flagged.xlsx")
