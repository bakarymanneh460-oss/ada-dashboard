import streamlit as st
import pandas as pd
import requests
import plotly.express as px

# ==============================
# CONFIG
# ==============================
st.set_page_config(page_title="REDI ADA System", layout="wide")

# ==============================
# THEME
# ==============================
st.markdown("""
<style>
[data-testid="stAppViewContainer"] {
    background-color: #0b3d91;
}
h1,h2,h3,h4,p,div {
    color:white !important;
}
section[data-testid="stSidebar"] {
    background-color:#062a63 !important;
}
</style>
""", unsafe_allow_html=True)

# ==============================
# USERS (SIMPLE RBAC)
# ==============================
USERS = {
    "admin": {
        "password": "admin123",
        "role": "admin",
        "uids": ["ALL"]
    },
    "user1": {
        "password": "user123",
        "role": "user",
        "uids": ["aQJmYa6Z9mJ5qwdw8RrQcj"]
    }
}

# ==============================
# SESSION
# ==============================
if "auth" not in st.session_state:
    st.session_state.auth = False
    st.session_state.user = None

# ==============================
# LOGIN
# ==============================
if not st.session_state.auth:

    st.title("🔐 REDI ADA Login System")

    username = st.text_input("Username")
    password = st.text_input("Password", type="password")

    if st.button("Login"):
        if username in USERS and USERS[username]["password"] == password:
            st.session_state.auth = True
            st.session_state.user = username
            st.rerun()
        else:
            st.error("Invalid credentials")

    st.stop()

# ==============================
# USER INFO
# ==============================
user = USERS[st.session_state.user]

st.sidebar.title("REDI ADA System")
st.sidebar.success(st.session_state.user)

if st.sidebar.button("Logout"):
    st.session_state.auth = False
    st.rerun()

# ==============================
# ADMIN PANEL
# ==============================
if user["role"] == "admin":
    st.sidebar.subheader("🔐 Admin Dashboard")
    st.dataframe(pd.DataFrame(USERS).T)

# ==============================
# UID ACCESS
# ==============================
st.title("📊 REDI ADA UID Dashboard")

if user["uids"][0] == "ALL":
    uid = st.text_input("Enter UID")
else:
    uid = st.selectbox("Select UID", user["uids"])

# ==============================
# KOBO DATA FETCH
# ==============================
def fetch_kobo(uid):
    url = f"https://kf.kobotoolbox.org/api/v2/assets/{uid}/data/"
    r = requests.get(url)
    if r.status_code != 200:
        return pd.DataFrame()
    return pd.json_normalize(r.json().get("results", []))

df = fetch_kobo(uid)

if df.empty:
    st.warning("No data found for this UID")
    st.stop()

# ==============================
# AI ENGINE
# ==============================
def explain(row):
    reasons = []
    if "value" in row and row["value"] > 80:
        reasons.append("High value detected")
    if not reasons:
        return "Normal record"
    return " | ".join(reasons)

if "value" in df.columns:
    df["score"] = 100 - df["value"]
else:
    df["score"] = df.select_dtypes(include='number').mean(axis=1)

df["status"] = df["score"].apply(lambda x: "Flagged" if x < 40 else "Clean")
df["AI_Explanation"] = df.apply(explain, axis=1)

clean_df = df[df["status"] == "Clean"]
flagged_df = df[df["status"] == "Flagged"]

# ==============================
# DASHBOARD
# ==============================
st.markdown(f"## 📊 UID: {uid}")

col1, col2, col3 = st.columns(3)

col1.metric("Total", len(df))
col2.metric("Clean", len(clean_df))
col3.metric("Flagged", len(flagged_df))

chart = pd.DataFrame({
    "Category": ["Clean", "Flagged"],
    "Count": [len(clean_df), len(flagged_df)]
})

fig = px.bar(
    chart,
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

st.dataframe(df)

# ==============================
# AI EXPLANATION
# ==============================
st.subheader("🧠 AI Explanation Engine")
st.dataframe(df[["status", "AI_Explanation"]])

# ==============================
# EXPORTS
# ==============================
st.subheader("📦 Export Data")

st.download_button("Full Data", df.to_csv(index=False), "full.csv")
st.download_button("Clean Data", clean_df.to_csv(index=False), "clean.csv")
st.download_button("Flagged Data", flagged_df.to_csv(index=False), "flagged.csv")
