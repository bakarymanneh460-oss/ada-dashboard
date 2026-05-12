# =========================================
# REDI AUTOMATED DATA QUALITY MONITORING SYSTEM
# =========================================

import streamlit as st
import pandas as pd
import io
import requests
import numpy as np
import os
import logging
import yaml
import streamlit_authenticator as stauth

from yaml.loader import SafeLoader
from datetime import datetime
from sklearn.ensemble import IsolationForest

from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet

import plotly.express as px

# =========================================
# CONFIG
# =========================================
st.set_page_config(
    page_title="REDI Automated Data Quality Monitoring System",
    layout="wide",
    page_icon="📊"
)

# ✅ FIXED (this was missing before)
APP_NAME = "REDI Automated Data Quality Monitoring System"

# =========================================
# STYLING
# =========================================
st.markdown("""
<style>
.stApp {background: linear-gradient(135deg,#f3f7ff,#dbeafe);}
section[data-testid="stSidebar"] {background:#1e3a8a !important;}
section[data-testid="stSidebar"] * {color:white !important;}
section[data-testid="stSidebar"] input {
    background:white !important; color:black !important; font-weight:700 !important;
}
section[data-testid="stSidebar"] .stDateInput input {color:black !important;}

.kpi-card {padding:20px;border-radius:14px;color:white;text-align:center;}

.btn-blue {background:#2563eb;color:white;padding:12px;border-radius:10px;}
.btn-green {background:#16a34a;color:white;padding:12px;border-radius:10px;}
.btn-red {background:#dc2626;color:white;padding:12px;border-radius:10px;}
.btn-purple {background:#7c3aed;color:white;padding:12px;border-radius:10px;}
</style>
""", unsafe_allow_html=True)

# =========================================
# AUTH
# =========================================
with open("config.yaml") as file:
    config = yaml.load(file, Loader=SafeLoader)

authenticator = stauth.Authenticate(
    config["credentials"],
    config["cookie"]["name"],
    config["cookie"]["key"],
    config["cookie"]["expiry_days"]
)

authenticator.login()

auth = st.session_state.get("authentication_status")
username = st.session_state.get("username")
name = st.session_state.get("name")

if auth is False:
    st.error("Incorrect username or password")
    st.stop()

if auth is None:
    st.warning("Please login")
    st.stop()

authenticator.logout("Logout", "sidebar")

st.sidebar.success(f"Welcome {name}")
role = config["credentials"]["usernames"][username]["role"]
st.sidebar.info(f"Role: {role}")

# =========================================
# KOBO TOKEN
# =========================================
KOBO_TOKEN = st.secrets.get("KOBO_TOKEN")
if not KOBO_TOKEN:
    st.error("Missing KoBo token")
    st.stop()

# =========================================
# SIDEBAR
# =========================================
st.sidebar.title("📊 REDI ADA System")
FORM_UID = st.sidebar.text_input("KoBo Form UID")

pages = ["Dashboard","Explorer","Quality Analytics","Downloads"]
if role == "enumerator":
    pages = ["Dashboard","Explorer"]
elif role == "supervisor":
    pages = ["Dashboard","Explorer","Quality Analytics"]

page = st.sidebar.radio("Navigation", pages)

# =========================================
# FETCH (FULL PAGINATION)
# =========================================
@st.cache_data(ttl=60)
def fetch(uid, token):

    if not uid:
        st.warning("UID is empty")
        return pd.DataFrame()

    servers = [
        "https://kf.kobotoolbox.org",
        "https://kc.kobotoolbox.org"
    ]

    headers = {"Authorization": f"Token {token}"}

    for base in servers:
        try:
            url = f"{base}/api/v2/assets/{uid}/data/"
            params = {"format": "json", "page_size": 1000}

            all_data = []

            while url:
                r = requests.get(url, headers=headers, params=params, timeout=30)

                if r.status_code in [401, 403, 404]:
                    break

                if r.status_code != 200:
                    st.warning(f"{base} error: {r.status_code}")
                    break

                data = r.json()
                results = data.get("results", [])
                all_data.extend(results)

                url = data.get("next")
                params = None

            if len(all_data) > 0:
                st.success(f"Fetched {len(all_data)} records from {base}")
                return pd.json_normalize(all_data)

        except Exception as e:
            st.warning(f"{base} failed: {e}")
            continue

    st.error("No data fetched. Possible reasons: wrong UID, no permission, or wrong server.")
    return pd.DataFrame()

# =========================================
# CLEAN COLUMN NAMES
# =========================================
df.columns = (
    df.columns
    .str.strip()
    .str.replace("\n", "", regex=False)
)

# =========================================
# DETECT DATE COLUMN FUNCTION
# =========================================
def detect(df, names):
    if df is None or df.empty:
        return None

    for c in df.columns:
        for n in names:
            if n in c.lower():
                return c
    return None
    
# =========================================
# CACHE CONTROL (MUST COME FIRST)
# =========================================
FORM_UID = FORM_UID.strip()

if "last_uid" not in st.session_state:
    st.session_state.last_uid = None

if FORM_UID != st.session_state.last_uid:
    st.cache_data.clear()   # 🔥 clear old cached data
    st.session_state.last_uid = FORM_UID

# =========================================
# FETCH (ONLY CALL ONCE)
# =========================================
df = fetch(FORM_UID, KOBO_TOKEN)

# =========================================
# SAFETY CHECK
# =========================================
if df is None or df.empty:
    st.warning("No data found")
    st.stop()

# =========================================
# CLEAN COLUMN NAMES
# =========================================
df.columns = (
    df.columns
    .str.strip()
    .str.replace("\n", "", regex=False)
)

# =========================================
# DATE FILTER (SAFE — NEVER ZERO OUT DATA)
# =========================================
DATE_COL = detect(df, ["submission_time", "date", "time"])
if "_submission_time" in df.columns:
    DATE_COL = "_submission_time"

if DATE_COL and DATE_COL in df.columns:

    df[DATE_COL] = pd.to_datetime(df[DATE_COL], errors="coerce")

    # Use only valid dates to build the picker
    valid_dates = df[DATE_COL].dropna()

    if len(valid_dates) > 0:
        st.sidebar.subheader("Filters")

        min_date = valid_dates.min()
        max_date = valid_dates.max()

        c1, c2 = st.sidebar.columns(2)
        start = c1.date_input("Start", min_date)
        end = c2.date_input("End", max_date)

        mask = (
            (df[DATE_COL] >= pd.to_datetime(start)) &
            (df[DATE_COL] <= pd.to_datetime(end))
        )

        filtered = df[mask]

        # 🔴 Only apply if it keeps data
        if len(filtered) > 0:
            df = filtered
        else:
            st.warning("Date filter removed all data — ignoring filter")
    else:
        st.warning("No valid dates in this dataset — skipping date filter")

# =========================================
# SAFE NUMERIC CONVERSION
# =========================================

numeric_cols = [
    "Age",
    "Household Size",
    "Monthly Income",
    "Secondary Income",
    "Total Household Income",
    "Monthly Health Expenditure",
    "Number of phones"
]

# normalize column names (VERY IMPORTANT)
df.columns = df.columns.str.strip()

existing_numeric_cols = [c for c in numeric_cols if c in df.columns]

for col in existing_numeric_cols:
    df[col] = pd.to_numeric(df[col], errors="coerce")

# only fill valid columns
if existing_numeric_cols:
    df[existing_numeric_cols] = df[existing_numeric_cols].fillna(0)

# =========================================
# ANOMALY
# =========================================
num_cols = df.select_dtypes(include="number").columns

if len(num_cols)>0:
    z = np.abs((df[num_cols]-df[num_cols].mean())/df[num_cols].std().replace(0,1))
    df["anomaly_flag"] = (z > 2.5).any(axis=1)
else:
    df["anomaly_flag"] = False

# =========================================
# AI
# =========================================
if len(num_cols)>2:
    model = IsolationForest(contamination=0.2, random_state=42)
    df["ai_flag"] = model.fit_predict(df[num_cols].fillna(0))==-1
else:
    df["ai_flag"] = False

# =========================================
# QUALITATIVE
# =========================================
df["qualitative_flag"] = False
df["qualitative_issue"] = ""

for col in df.columns:
    if any(k in col.lower() for k in ["name","age","gender"]):
        mask = df[col].isna() | (df[col].astype(str).str.strip()=="")
        df.loc[mask,"qualitative_flag"]=True
        df.loc[mask,"qualitative_issue"]+=f"Missing {col}; "

# =========================================
# VALIDATION
# =========================================

validation_cols = [
    "income_mismatch",
    "age_mismatch",
    "income_repeat_mismatch",
    "phone_mismatch",
    "education_mismatch",
    "marital_age_issue"
]

existing = [c for c in validation_cols if c in df.columns]

if existing:
    df[existing] = df[existing].apply(pd.to_numeric, errors="coerce").fillna(0)

    # 🔥 IMPORTANT FIX (NOT binary anymore)
    df["validation_flag"] = df[existing].sum(axis=1) >= 2
else:
    df["validation_flag"] = False

# =========================================
# RULE ENGINE
# =========================================

df["rule_flag"] = False
df["rule_reason"] = ""

# normalize key columns safely
def get_col(possible_names):
    for c in df.columns:
        if any(name.lower() in c.lower() for name in possible_names):
            return c
    return None


age_col = get_col(["age"])
marital_col = get_col(["marital"])
phone_col = get_col(["phone"])
income_col = get_col(["income"])


# AGE RULE
if age_col:
    df[age_col] = pd.to_numeric(df[age_col], errors="coerce")
    mask = df[age_col].between(0, 120) == False
    df.loc[mask, "rule_flag"] = True
    df.loc[mask, "rule_reason"] += "Invalid age; "

# MARITAL AGE RULE
if age_col and marital_col:
    mask = (
        df[age_col] < 18
    ) & (
        df[marital_col].astype(str).str.lower().str.contains("married")
    )
    df.loc[mask, "rule_flag"] = True
    df.loc[mask, "rule_reason"] += "Underage married; "

# PHONE RULE
if phone_col:
    df[phone_col] = pd.to_numeric(df[phone_col], errors="coerce")
    mask = df[phone_col] > 10
    df.loc[mask, "rule_flag"] = True
    df.loc[mask, "rule_reason"] += "Too many phones; "

# INCOME RULE
if income_col:
    df[income_col] = pd.to_numeric(df[income_col], errors="coerce")
    mask = df[income_col] > 1e8
    df.loc[mask, "rule_flag"] = True
    df.loc[mask, "rule_reason"] += "Extreme income; "

# =========================================
# VALIDATION ENGINE
# =========================================

validation_cols = [
    "income_mismatch",
    "age_mismatch",
    "income_repeat_mismatch",
    "phone_mismatch",
    "education_mismatch",
    "marital_age_issue"
]

existing = [c for c in validation_cols if c in df.columns]

if existing:
    df[existing] = df[existing].apply(pd.to_numeric, errors="coerce").fillna(0)

    # weighted logic (prevents over-flagging)
    df["validation_score"] = df[existing].sum(axis=1)

    df["validation_flag"] = df["validation_score"] >= 2
else:
    df["validation_flag"] = False
    df["validation_score"] = 0

# =========================================
# FINAL FLAG
# =========================================
df["final_flag"] = (
    df["qualitative_flag"].fillna(False) |
    df["anomaly_flag"].fillna(False) |
    df["ai_flag"].fillna(False) |
    df["rule_flag"].fillna(False) |
    df["validation_flag"].fillna(False)
)

# =========================================
# WHY FLAGGED (MULTI-UID SAFE)
# =========================================

def safe_str(x):
    if pd.isna(x):
        return ""
    return str(x)

def explain_row(row):
    reasons = []

    # --- QUALITATIVE ---
    if bool(row.get("qualitative_flag", False)):
        q_issue = safe_str(row.get("qualitative_issue", "")).strip()
        if q_issue:
            reasons.append(q_issue)
        else:
            reasons.append("Qualitative issue")

    # --- STATISTICAL ---
    if bool(row.get("anomaly_flag", False)):
        reasons.append("Stat anomaly")

    # --- AI ---
    if bool(row.get("ai_flag", False)):
        reasons.append("AI anomaly")

    # --- RULE ---
    if bool(row.get("rule_flag", False)):
        reasons.append(safe_str(row.get("rule_reason", "")))

    # --- VALIDATION ---
    if bool(row.get("validation_flag", False)):
        reasons.append("Form validation mismatch")

    # --- FINAL ---
    if not reasons:
        return "No issues"

    return " | ".join(reasons)


# ✅ APPLY
df["why_flagged"] = df.apply(explain_row, axis=1)

# =========================================
# SPLIT
# =========================================
clean = df[~df["final_flag"]]
flag = df[df["final_flag"]]

total=len(df)
valid=len(clean)
bad=len(flag)
score=(valid/total)*100 if total else 0

# =========================================
# DASHBOARD
# =========================================
if page=="Dashboard":
    st.title(APP_NAME)

    c1,c2,c3,c4=st.columns(4)

    c1.markdown(f"<div class='kpi-card' style='background:#2563eb'><h3>Total</h3><h1>{total}</h1></div>",unsafe_allow_html=True)
    c2.markdown(f"<div class='kpi-card' style='background:#16a34a'><h3>Valid</h3><h1>{valid}</h1></div>",unsafe_allow_html=True)
    c3.markdown(f"<div class='kpi-card' style='background:#dc2626'><h3>Flagged</h3><h1>{bad}</h1></div>",unsafe_allow_html=True)
    c4.markdown(f"<div class='kpi-card' style='background:#7c3aed'><h3>Score</h3><h1>{score:.1f}%</h1></div>",unsafe_allow_html=True)

# =========================================
# EXPLORER
# =========================================
elif page=="Explorer":
    t1,t2=st.tabs(["Clean","Flagged"])
    with t1: st.dataframe(clean)
    with t2: st.dataframe(flag)

# =========================================
# QUALITY ANALYTICS
# =========================================
elif page=="Quality Analytics":
    summary=pd.DataFrame({
        "Category":["Quantitative","Qualitative"],
        "Count":[int(df["anomaly_flag"].sum()+df["ai_flag"].sum()),
                 int(df["qualitative_flag"].sum())]
    })
    st.dataframe(summary)
    st.plotly_chart(px.pie(summary,names="Category",values="Count"))

# =========================================
# DOWNLOADS
# =========================================
elif page=="Downloads":

    def to_excel(d):
        o=io.BytesIO()
        with pd.ExcelWriter(o,engine="openpyxl") as w:
            d.to_excel(w,index=False)
        o.seek(0)
        return o

    def full_excel():
        o=io.BytesIO()
        with pd.ExcelWriter(o,engine="openpyxl") as w:
            clean.to_excel(w,index=False,sheet_name="Clean")
            flag.to_excel(w,index=False,sheet_name="Flagged")
        o.seek(0)
        return o

    def pdf():
        b=io.BytesIO()
        doc=SimpleDocTemplate(b)
        styles=getSampleStyleSheet()
        elems=[Paragraph("REDI Report",styles["Title"]),Spacer(1,12)]

        data=[["Metric","Value"],["Total",total],["Valid",valid],["Flagged",bad]]
        t=Table(data)
        t.setStyle(TableStyle([("GRID",(0,0),(-1,-1),1,colors.black)]))
        elems.append(t)

        doc.build(elems)
        b.seek(0)
        return b

    c1,c2,c3,c4=st.columns(4)

    with c1:
        st.markdown('<div class="btn-blue">📊 Full Dataset</div>',True)
        st.download_button("Download",full_excel(),"full.xlsx")

    with c2:
        st.markdown('<div class="btn-green">✅ Clean Data</div>',True)
        st.download_button("Download",to_excel(clean),"clean.xlsx")

    with c3:
        st.markdown('<div class="btn-red">⚠️ Flagged Data</div>',True)
        st.download_button("Download",to_excel(flag),"flagged.xlsx")

    with c4:
        st.markdown('<div class="btn-purple">📄 PDF Report</div>',True)
        st.download_button("Download",pdf(),"report.pdf")

# =========================================
# FOOTER
# =========================================
st.caption(f"{APP_NAME} | {datetime.now()}")
