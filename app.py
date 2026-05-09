import streamlit as st
import pandas as pd
import numpy as np
import requests
import io
import hashlib
import sqlite3
import random
from datetime import datetime

import plotly.express as px
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

# ==============================
# CONFIG
# ==============================
st.set_page_config(page_title="REDI ADA System", layout="wide")

# ==============================
# UI THEME (BLUE SAAS)
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
# SENDGRID CONFIG (USE SECRETS IN DEPLOYMENT)
# ==============================
SENDGRID_API_KEY = st.secrets["SENDGRID_API_KEY"]
EMAIL_SENDER = st.secrets["EMAIL_SENDER"]

def send_otp(email, otp):
    message = Mail(
        from_email=EMAIL_SENDER,
        to_emails=email,
        subject="REDI ADA Verification OTP",
        html_content=f"<h2>Your OTP is: {otp}</h2>"
    )
    try:
        sg = SendGridAPIClient(SENDGRID_API_KEY)
        sg.send(message)
        return True
    except Exception as e:
        st.error(f"Email error: {e}")
        return False

# ==============================
# DATABASE
# ==============================
conn = sqlite3.connect("redi_users.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    username TEXT PRIMARY KEY,
    password TEXT,
    role TEXT,
    email TEXT
)
""")

conn.commit()

# ==============================
# SESSION STATE
# ==============================
if "auth" not in st.session_state:
    st.session_state.auth = False
    st.session_state.user = None
    st.session_state.role = None

if "otp" not in st.session_state:
    st.session_state.otp = None

if "pending" not in st.session_state:
    st.session_state.pending = None

# ==============================
# SECURITY
# ==============================
def hash_pw(p):
    return hashlib.sha256(p.encode()).hexdigest()

def create_user(u,p,email,role="viewer"):
    try:
        cursor.execute("INSERT INTO users VALUES (?,?,?,?)",
                       (u, hash_pw(p), role, email))
        conn.commit()
        return True
    except:
        return False

def auth(u,p):
    cursor.execute("SELECT password,role FROM users WHERE username=?", (u,))
    r = cursor.fetchone()
    if r and r[0] == hash_pw(p):
        return r[1]
    return None

def login(u,p):
    role = auth(u,p)
    if role:
        st.session_state.auth = True
        st.session_state.user = u
        st.session_state.role = role
        return True
    return False

def logout():
    st.session_state.auth = False

# ==============================
# PASSWORD STRENGTH
# ==============================
def strength(p):
    return sum([
        len(p)>=8,
        any(c.isupper() for c in p),
        any(c.islower() for c in p),
        any(c.isdigit() for c in p),
        any(not c.isalnum() for c in p)
    ])

# ==============================
# AUTH UI
# ==============================
if not st.session_state.auth:

    st.title("📊 REDI ADA System")

    tab1, tab2, tab3 = st.tabs(["Login","Sign Up","Forgot Password"])

    # ================= LOGIN =================
    with tab1:
        u = st.text_input("Username", key="login_user")
        p = st.text_input("Password", type="password", key="login_pass")

        if st.button("Login"):
            if login(u,p):
                st.success("Welcome")
                st.rerun()
            else:
                st.error("Invalid credentials")

    # ================= SIGNUP =================
    with tab2:
        u = st.text_input("Username", key="signup_user")
        email = st.text_input("Email", key="signup_email")
        p = st.text_input("Password", type="password", key="signup_pass")

        st.write("Strength:", "⭐"*strength(p))

        if st.button("Send OTP"):
            otp = str(random.randint(100000,999999))
            st.session_state.otp = otp
            st.session_state.pending = (u,p,email)

            if send_otp(email, otp):
                st.success("OTP sent to email")
            else:
                st.error("Failed to send OTP")

        otp_in = st.text_input("Enter OTP", key="signup_otp")

        if st.button("Create Account"):
            if otp_in == st.session_state.otp:
                u,p,email = st.session_state.pending
                create_user(u,p,email)
                st.success("Account created")
            else:
                st.error("Invalid OTP")

    # ================= FORGOT PASSWORD =================
    with tab3:
        email = st.text_input("Email", key="forgot_email")
        u = st.text_input("Username", key="forgot_user")

        if st.button("Send Reset OTP"):
            otp = str(random.randint(100000,999999))
            st.session_state.otp = otp
            st.session_state.pending = (u,email)

            send_otp(email, otp)
            st.success("OTP sent")

        otp_in = st.text_input("OTP", key="reset_otp")
        new_pass = st.text_input("New Password", type="password", key="new_pass")

        if st.button("Reset Password"):
            if otp_in == st.session_state.otp:
                u,email = st.session_state.pending
                cursor.execute("UPDATE users SET password=? WHERE username=?",
                               (hash_pw(new_pass), u))
                conn.commit()
                st.success("Password updated")
            else:
                st.error("Invalid OTP")

    st.stop()

# ==============================
# SIDEBAR
# ==============================
st.sidebar.title("REDI System")
st.sidebar.success(st.session_state.user)

if st.sidebar.button("Logout"):
    logout()
    st.rerun()

# ==============================
# DATA (PLACEHOLDER SAFE)
# ==============================
st.title("📊 Dashboard")

df = pd.DataFrame({
    "Category": ["Clean","Flagged"],
    "Count": [80, 20]
})

fig = px.bar(df, x="Category", y="Count", color="Category")
st.plotly_chart(fig)

st.dataframe(df)

# ==============================
# EXPORTS
# ==============================
st.subheader("Exports")

def to_excel(data):
    out = io.BytesIO()
    pd.DataFrame(data).to_excel(out, index=False)
    out.seek(0)
    return out

st.download_button("Download Data", to_excel(df), "data.xlsx")
