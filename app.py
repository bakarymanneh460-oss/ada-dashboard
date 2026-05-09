import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import io

# ==============================
# PAGE CONFIG
# ==============================
st.set_page_config(page_title="REDI ADA UID System", layout="wide")

# ==============================
# UI THEME (BLUE RESTORED)
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
# UID FORM INPUT
# ==============================
st.title("📊 REDI ADA UID FORM SYSTEM")

uid = st.text_input("Enter Form UID")

if not uid:
    st.warning("Please enter a Form UID to continue")
    st.stop()

st.success(f"Loaded Form UID: {uid}")

# ==============================
# SIMULATED DATA PER UID
# (replace later with real Kobo API if needed)
# ==============================
np.random.seed(abs(hash(uid)) % 10000)

df = pd.DataFrame({
    "value": np.random.randint(1, 100, 80)
})

# ==============================
# ANALYTICS ENGINE
# ==============================
df["score"] = 100 - (df["value"] * 0.6)
df["status"] = np.where(df["score"] < 40, "Flagged", "Clean")

clean_df = df[df["status"] == "Clean"]
flagged_df = df[df["status"] == "Flagged"]

# ==============================
# DASHBOARD
# ==============================
st.markdown(f"""
<h1 style='text-align:center;color:#00ff88;'>
📊 UID DASHBOARD: {uid}
</h1>
""", unsafe_allow_html=True)

col1, col2, col3 = st.columns(3)

col1.metric("Total Records", len(df))
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
# EXPORT SYSTEM (UID-BASED)
# ==============================
st.subheader("📦 Export UID Data")

def to_excel(data):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        data.to_excel(writer, index=False)
    output.seek(0)
    return output

st.download_button(
    "⬇️ Full UID Dataset",
    to_excel(df),
    f"{uid}_full.xlsx"
)

st.download_button(
    "⬇️ Clean Data",
    to_excel(clean_df),
    f"{uid}_clean.xlsx"
)

st.download_button(
    "⬇️ Flagged Data",
    to_excel(flagged_df),
    f"{uid}_flagged.xlsx"
)
