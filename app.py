import streamlit as st
import pandas as pd
import numpy as np
import io

from supabase import create_client
import plotly.express as px

from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image
from reportlab.lib.styles import getSampleStyleSheet
import matplotlib.pyplot as plt

# ==============================
# CONFIG
# ==============================
st.set_page_config(page_title="REDI ADA Enterprise SaaS v3", layout="wide")

# ==============================
# SUPABASE
# ==============================
supabase = create_client(
    st.secrets["SUPABASE_URL"],
    st.secrets["SUPABASE_KEY"]
)

# ==============================
# GREEN / GRAY / RED THEME
# ==============================
st.markdown("""
<style>
[data-testid="stAppViewContainer"] {
    background-color: #0b2e1f; /* dark green base */
}
h1,h2,h3,h4,h5,p,div {
    color:white !important;
}
section[data-testid="stSidebar"] {
    background-color:#1f1f1f !important;
}
</style>
""", unsafe_allow_html=True)

# ==============================
# AUTH
# ==============================
def signup(email, password):
    return supabase.auth.sign_up({"email": email, "password": password})

def login(email, password):
    return supabase.auth.sign_in_with_password({"email": email, "password": password})

def logout():
    supabase.auth.sign_out()
    st.session_state.session = None

def get_user():
    return supabase.auth.get_user()

if "session" not in st.session_state:
    st.session_state.session = None

# ==============================
# AUTH UI
# ==============================
if not st.session_state.session:

    st.title("🏢 REDI Enterprise SaaS v3")

    tab1, tab2 = st.tabs(["Login", "Sign Up"])

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
                st.error("Invalid login")

    with tab2:
        email = st.text_input("Email", key="signup_email")
        password = st.text_input("Password", type="password", key="signup_pass")

        if st.button("Create Account"):
            try:
                signup(email, password)
                st.success("Account created")
            except:
                st.error("Signup failed")

    st.stop()

# ==============================
# USER
# ==============================
user = get_user()

st.sidebar.title("Enterprise SaaS")
st.sidebar.success(user.user.email)

if st.sidebar.button("Logout"):
    logout()
    st.rerun()

# ==============================
# SAMPLE DATA (replace with real dataset later)
# ==============================
df = pd.DataFrame({
    "value": np.random.randint(1, 100, 80)
})

# ==============================
# AI SCORING SYSTEM
# ==============================
df["score"] = 100 - (df["value"] * 0.6)

df["status"] = "Clean"
df.loc[df["score"] < 40, "status"] = "Flagged"

clean_df = df[df["status"] == "Clean"]
flagged_df = df[df["status"] == "Flagged"]

# ==============================
# DASHBOARD (GREEN / GRAY / RED)
# ==============================
st.markdown("""
<h1 style='text-align:center;color:#00ff88;'>
🏢 REDI ENTERPRISE DASHBOARD
</h1>
""", unsafe_allow_html=True)

col1, col2, col3 = st.columns(3)

col1.markdown(f"""
<div style="background-color:#2ecc71;padding:20px;border-radius:10px;text-align:center;">
<h3>Total</h3>
<h2>{len(df)}</h2>
</div>
""", unsafe_allow_html=True)

col2.markdown(f"""
<div style="background-color:#95a5a6;padding:20px;border-radius:10px;text-align:center;">
<h3>Clean</h3>
<h2>{len(clean_df)}</h2>
</div>
""", unsafe_allow_html=True)

col3.markdown(f"""
<div style="background-color:#e74c3c;padding:20px;border-radius:10px;text-align:center;">
<h3>Flagged</h3>
<h2>{len(flagged_df)}</h2>
</div>
""", unsafe_allow_html=True)

# ==============================
# CHART
# ==============================
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
# EXPORT SYSTEM
# ==============================
st.subheader("📦 Enterprise Export System")

def to_excel(data):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        data.to_excel(writer, index=False)
    output.seek(0)
    return output

# EXCEL DOWNLOADS
st.download_button("⬇️ Full Dataset (Excel)", to_excel(df), "full.xlsx")
st.download_button("⬇️ Clean Dataset (Excel)", to_excel(clean_df), "clean.xlsx")
st.download_button("⬇️ Flagged Dataset (Excel)", to_excel(flagged_df), "flagged.xlsx")

# ==============================
# PDF REPORT (ENTERPRISE)
# ==============================
def generate_chart():
    plt.figure(figsize=(5,3))
    plt.bar(["Clean","Flagged"], [len(clean_df), len(flagged_df)], color=["#2ecc71","#e74c3c"])
    plt.title("Enterprise Data Report")

    path = "chart.png"
    plt.savefig(path)
    plt.close()
    return path


def generate_pdf():
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer)

    styles = getSampleStyleSheet()
    content = []

    content.append(Paragraph("REDI ENTERPRISE SaaS REPORT", styles["Title"]))
    content.append(Spacer(1, 12))

    content.append(Paragraph(f"Total Records: {len(df)}", styles["Normal"]))
    content.append(Paragraph(f"Clean Records: {len(clean_df)}", styles["Normal"]))
    content.append(Paragraph(f"Flagged Records: {len(flagged_df)}", styles["Normal"]))
    content.append(Spacer(1, 12))

    img = generate_chart()
    content.append(Image(img, width=300, height=180))

    doc.build(content)
    buffer.seek(0)
    return buffer


st.download_button(
    "📄 Download PDF Report",
    generate_pdf(),
    "enterprise_report.pdf"
)
