import streamlit as st
import pandas as pd
import requests
import plotly.express as px

# ==============================
# CONFIG
# ==============================
st.set_page_config(page_title="REDI Enterprise UID SaaS", layout="wide")

# ==============================
# THEME (BLUE)
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
# USERS (MULTI-USER SYSTEM)
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
    },
    "user2": {
        "password": "user456",
        "role": "user",
        "uids": ["demoUID123"]
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

    st.title("🔐 REDI Enterprise Login")

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

st.sidebar.title("Enterprise Panel")
st.sidebar.success(st.session_state.user)

if st.sidebar.button("Logout"):
    st.session_state.auth = False
    st.rerun()

# ==============================
# ADMIN DASHBOARD
# ==============================
if user["role"] == "admin":
    st.sidebar.subheader("🔐 Admin Dashboard")
    st.write("Users in system:")
    st.dataframe(pd.DataFrame(USERS).T)

# ==============================
# UID ACCESS CONTROL
# ==============================
st.title("📊 UID Data Dashboard")

if user["uids"][0] == "ALL":
    uid = st.text_input("Enter ANY UID (Admin Access)")
else:
    uid = st.selectbox("Select Your UID", user["uids"])

# ==============================
# FETCH KOBO DATA
# ==============================
def fetch_kobo(uid):
    url = f"https://kf.kobotoolbox.org/api/v2/assets/{uid}/data/"
    r = requests.get(url)
    if r.status_code != 200:
        return pd.DataFrame()
    data = r.json().get("results", [])
    return pd.json_normalize(data)

df = fetch_kobo(uid)

if df.empty:
    st.warning("No data found for this UID")
    st.stop()

# ==============================
# AI EXPLANATION ENGINE
# ==============================
def explain(row):
    reasons = []
    if "value" in row and row["value"] > 80:
        reasons.append("High value detected")
    if len(reasons) == 0:
        return "Normal record"
    return " | ".join(reasons)

# ==============================
# ANALYTICS
# ==============================
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

# ==============================
# DATA VIEW
# ==============================
st.dataframe(df)

# ==============================
# AI EXPLANATION VIEW
# ==============================
st.subheader("🧠 AI Explanation (Why Flagged)")

st.dataframe(df[["status", "AI_Explanation"]])

# ==============================
# EXPORTS
# ==============================
st.subheader("📦 Exports")

st.download_button("Full Data", df.to_csv(index=False), "full.csv")
st.download_button("Clean Data", clean_df.to_csv(index=False), "clean.csv")
st.download_button("Flagged Data", flagged_df.to_csv(index=False), "flagged.csv")
