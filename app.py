import streamlit as st
import pandas as pd
import numpy as np
import io

from supabase import create_client
import plotly.express as px

# ==============================
# CONFIG
# ==============================
st.set_page_config(page_title="REDI ADA SaaS", layout="wide")

# ==============================
# SUPABASE CLIENT
# ==============================
supabase = create_client(
    st.secrets["SUPABASE_URL"],
    st.secrets["SUPABASE_KEY"]
)

# ==============================
# THEME (BLUE SAAS)
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
section[data-testid="stSidebar"] * {
    color:white !important;
}
</style>
""", unsafe_allow_html=True)

# ==============================
# AUTH FUNCTIONS
# ==============================
def signup(email, password):
    return supabase.auth.sign_up({
        "email": email,
        "password": password
    })

def login(email, password):
    return supabase.auth.sign_in_with_password({
        "email": email,
        "password": password
    })

def logout():
    supabase.auth.sign_out()
    st.session_state.session = None

def get_user():
    return supabase.auth.get_user()

# ==============================
# SESSION STATE
# ==============================
if "session" not in st.session_state:
    st.session_state.session = None

# ==============================
# AUTH UI
# ==============================
if not st.session_state.session:

    st.title("📊 REDI ADA SYSTEM")

    tab1, tab2 = st.tabs(["Login", "Sign Up"])

    # ================= LOGIN =================
    with tab1:
        email = st.text_input("Email", key="login_email")
        password = st.text_input("Password", type="password", key="login_pass")

        if st.button("Login"):
            try:
                res = login(email, password)
                st.session_state.session = res.session
                st.success("Login successful")
                st.rerun()
            except:
                st.error("Invalid credentials")

    # ================= SIGNUP =================
    with tab2:
        email = st.text_input("Email", key="signup_email")
        password = st.text_input("Password", type="password", key="signup_pass")

        if st.button("Create Account"):
            try:
                signup(email, password)
                st.success("Account created. Check email to verify.")
            except:
                st.error("Signup failed")

    st.stop()

# ==============================
# USER SESSION
# ==============================
user = get_user()

st.sidebar.title("REDI SaaS")
st.sidebar.success(user.user.email)

if st.sidebar.button("Logout"):
    logout()
    st.rerun()

# ==============================
# ROLE (ADMIN SIMPLE RULE)
# ==============================
is_admin = user.user.email.endswith("@admin.com")

if is_admin:
    st.sidebar.subheader("🔐 Admin Panel")
    st.sidebar.write("Admin Access Enabled")

# ==============================
# SAMPLE DATA (REPLACE WITH YOUR KOBO DATA IF NEEDED)
# ==============================
df = pd.DataFrame({
    "value": np.random.randint(1, 100, 50)
})

# ==============================
# AI LOGIC (CLEAN / FLAGGED)
# ==============================
df["anomaly"] = df["value"] > 80
df["score"] = 100 - (df["value"] * 0.5)

clean_df = df[df["score"] >= 60]
flagged_df = df[df["score"] < 60]

# ==============================
# 📊 DASHBOARD (RESTORED COLORS)
# ==============================
st.markdown("""
<h1 style='text-align:center; color:white;'>
📊 REDI ADA DASHBOARD
</h1>
""", unsafe_allow_html=True)

col1, col2, col3 = st.columns(3)

col1.markdown(f"""
<div style="background-color:#1f4e9e;padding:20px;border-radius:10px;text-align:center;">
<h3 style="color:white;">Total</h3>
<h2 style="color:white;">{len(df)}</h2>
</div>
""", unsafe_allow_html=True)

col2.markdown(f"""
<div style="background-color:#1f4e9e;padding:20px;border-radius:10px;text-align:center;">
<h3 style="color:white;">Clean</h3>
<h2 style="color:white;">{len(clean_df)}</h2>
</div>
""", unsafe_allow_html=True)

col3.markdown(f"""
<div style="background-color:#1f4e9e;padding:20px;border-radius:10px;text-align:center;">
<h3 style="color:white;">Flagged</h3>
<h2 style="color:white;">{len(flagged_df)}</h2>
</div>
""", unsafe_allow_html=True)

# ==============================
# CHART
# ==============================
chart_df = pd.DataFrame({
    "Category": ["Clean", "Flagged"],
    "Count": [len(clean_df), len(flagged_df)]
})

fig = px.bar(chart_df, x="Category", y="Count", color="Category", text="Count")
st.plotly_chart(fig, use_container_width=True)

# ==============================
# TABLE
# ==============================
st.dataframe(df, use_container_width=True)

# ==============================
# 📦 EXPORT SYSTEM (ONLY CLEAN + FLAGGED)
# ==============================
st.subheader("📦 Export Data")

def to_excel(data):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        data.to_excel(writer, index=False)
    output.seek(0)
    return output

st.download_button(
    "⬇️ Clean Data (Excel)",
    to_excel(clean_df),
    "clean_data.xlsx"
)

st.download_button(
    "⬇️ Flagged Data (Excel)",
    to_excel(flagged_df),
    "flagged_data.xlsx"
)
