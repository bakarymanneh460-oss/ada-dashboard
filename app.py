import streamlit as st
import pandas as pd
import numpy as np
import requests
import io
import hashlib
import sqlite3
import random
import smtplib
from email.mime.text import MIMEText
from datetime import datetime

import plotly.express as px
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet

# ==============================
# CONFIG
# ==============================
st.set_page_config(page_title="REDI ADA System", layout="wide")

# ==============================
# UI THEME
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
# EMAIL CONFIG
# ==============================
EMAIL_SENDER = "your_email@gmail.com"
EMAIL_PASSWORD = "your_app_password"

def send_otp(email, otp):
    msg = MIMEText(f"Your REDI OTP code is: {otp}")
    msg["Subject"] = "REDI Verification"
    msg["From"] = EMAIL_SENDER
    msg["To"] = email

    server = smtplib.SMTP("smtp.gmail.com", 587)
    server.starttls()
    server.login(EMAIL_SENDER, EMAIL_PASSWORD)
    server.sendmail(EMAIL_SENDER, email, msg.as_string())
    server.quit()

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
    form_uid TEXT
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
    st.session_state.form_uid = None

if "otp" not in st.session_state:
    st.session_state.otp = None

if "pending" not in st.session_state:
    st.session_state.pending = None

# ==============================
# SECURITY
# ==============================
def hash_pw(p):
    return hashlib.sha256(p.encode()).hexdigest()

def create_user(u,p,role,uid):
    try:
        cursor.execute("INSERT INTO users VALUES (?,?,?,?)",
                       (u, hash_pw(p), role, uid))
        conn.commit()
        return True
    except:
        return False

def auth(u,p):
    cursor.execute("SELECT password,role,form_uid FROM users WHERE username=?", (u,))
    r = cursor.fetchone()
    if r and r[0] == hash_pw(p):
        return r[1], r[2]
    return None,None

def login(u,p):
    role, uid = auth(u,p)
    if role:
        st.session_state.auth = True
        st.session_state.user = u
        st.session_state.role = role
        st.session_state.form_uid = uid
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
# SIGNUP FUNCTION
# ==============================
def register_user(u,p):
    return create_user(u,p,"viewer","")

# ==============================
# AUTH UI (FIXED KEYS HERE)
# ==============================
if not st.session_state.auth:

    st.title("📊 REDI ADA System")

    tab1, tab2, tab3 = st.tabs(["Login","Sign Up","Forgot Password"])

    # ================= LOGIN =================
    with tab1:
        u = st.text_input("Username", key="login_user")
        p = st.text_input("Password", type="password", key="login_pass")

        if st.button("Login", key="login_btn"):
            if login(u,p):
                st.success("Welcome")
                st.rerun()
            else:
                st.error("Invalid credentials")

    # ================= SIGNUP =================
    with tab2:
        email = st.text_input("Email", key="signup_email")
        u = st.text_input("Username", key="signup_user")
        p = st.text_input("Password", type="password", key="signup_pass")

        st.write("Password strength:", "⭐"*strength(p))

        if st.button("Send OTP", key="signup_send_otp"):
            otp = str(random.randint(100000,999999))
            st.session_state.otp = otp
            st.session_state.pending = (u,p,email)
            send_otp(email, otp)
            st.success("OTP sent")

        otp_in = st.text_input("Enter OTP", key="signup_otp")

        if st.button("Verify", key="signup_verify"):
            if otp_in == st.session_state.otp:
                u,p,_ = st.session_state.pending
                register_user(u,p)
                st.success("Account created")
            else:
                st.error("Wrong OTP")

    # ================= FORGOT =================
    with tab3:
        email = st.text_input("Email", key="forgot_email")
        u = st.text_input("Username", key="forgot_user")

        if st.button("Send Reset OTP", key="reset_send"):
            otp = str(random.randint(100000,999999))
            st.session_state.otp = otp
            st.session_state.pending = u
            send_otp(email, otp)
            st.success("OTP sent")

        otp_in = st.text_input("OTP", key="reset_otp")
        new_pass = st.text_input("New Password", type="password", key="reset_pass")

        if st.button("Reset Password", key="reset_btn"):
            if otp_in == st.session_state.otp:
                cursor.execute("UPDATE users SET password=? WHERE username=?",
                               (hash_pw(new_pass), st.session_state.pending))
                conn.commit()
                st.success("Password reset done")
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
# DATA FETCH
# ==============================
@st.cache_data(ttl=120)
def fetch(uid):
    url = f"https://kf.kobotoolbox.org/api/v2/assets/{uid}/data/?format=json&page_size=1000"
    data = []

    while url:
        try:
            r = requests.get(url)
            j = r.json()
            data.extend(j.get("results", []))
            url = j.get("next")
        except:
            break

    return pd.json_normalize(data)

df = fetch(st.session_state.form_uid)

if df.empty:
    st.stop()

# ==============================
# ANALYTICS
# ==============================
num = df.select_dtypes(include=["number"]).columns

df["anomaly"] = False
if len(num):
    z = np.abs((df[num]-df[num].mean())/df[num].std().replace(0,1))
    df["anomaly"] = z.max(axis=1) > 2.5

text_cols = df.select_dtypes(include=["object"]).columns
col = text_cols[0] if len(text_cols) else None

def sentiment(x):
    x = str(x).lower()
    if "bad" in x or "hate" in x: return "negative"
    if "good" in x or "yes" in x: return "positive"
    return "neutral"

df["sentiment"] = df[col].apply(sentiment) if col else "neutral"

# ==============================
# SCORE
# ==============================
df["score"] = 100
df.loc[df["anomaly"], "score"] -= 40
df.loc[df["sentiment"]=="negative","score"] -= 10
df["score"] = df["score"].clip(0,100)

clean = df[df["score"]>=60]
flagged = df[df["score"]<60]

# ==============================
# DASHBOARD
# ==============================
st.title("📊 REDI ADA System")

c1,c2,c3 = st.columns(3)

c1.metric("Total", len(df))
c2.metric("Clean", len(clean))
c3.metric("Flagged", len(flagged))

fig = px.bar(x=["Clean","Flagged"], y=[len(clean),len(flagged)])
st.plotly_chart(fig)

st.dataframe(df)

# ==============================
# EXPORTS
# ==============================
st.subheader("Outputs")

def to_excel(d):
    out = io.BytesIO()
    with pd.ExcelWriter(out, engine="openpyxl") as w:
        d.to_excel(w,index=False)
    out.seek(0)
    return out

def pdf():
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf)
    s = getSampleStyleSheet()

    e = [
        Paragraph("REDI REPORT", s["Title"]),
        Spacer(1,10),
        Paragraph(f"Total {len(df)}", s["Normal"]),
        Paragraph(f"Clean {len(clean)}", s["Normal"]),
        Paragraph(f"Flagged {len(flagged)}", s["Normal"])
    ]

    doc.build(e)
    buf.seek(0)
    return buf

st.download_button("Full Excel", to_excel(df), "full.xlsx")
st.download_button("Clean Excel", to_excel(clean), "clean.xlsx")
st.download_button("Flagged Excel", to_excel(flagged), "flagged.xlsx")
st.download_button("PDF Report", pdf(), "report.pdf")
