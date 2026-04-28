import streamlit as st
import pandas as pd
import requests
import os
from datetime import datetime
from spellchecker import SpellChecker

# ==============================
# 🔐 CONFIG (USE SECRETS)
# ==============================
KOBO_TOKEN = os.getenv("KOBO_TOKEN")
FORM_UID = "aQJmYa6Z9mJ5qwdw8RrQcj"

# ==============================
# 🎨 PAGE CONFIG
# ==============================
st.set_page_config(page_title="ADA Dashboard", layout="wide")

# ==============================
# 🎨 STYLE
# ==============================
st.markdown("""
<style>
body {background-color:#f5f7fb;}

.card {
    background:white;
    padding:18px;
    border-radius:12px;
    box-shadow:0 3px 10px rgba(0,0,0,0.05);
    text-align:center;
}

.title {font-size:13px;color:gray;}
.value {font-size:28px;font-weight:bold;}

.green {color:#16a34a;}
.red {color:#dc2626;}
.orange {color:#f59e0b;}
</style>
""", unsafe_allow_html=True)

# ==============================
# 📌 SIDEBAR
# ==============================
st.sidebar.markdown("""
<div style='background:#2563eb;padding:12px;border-radius:10px;text-align:center'>
<h2 style='color:white;margin:0'>REDI</h2>
</div>
""", unsafe_allow_html=True)

st.sidebar.title("Navigation")

page = st.sidebar.radio(
    "Go to",
    ["Dashboard", "Data Explorer", "Downloads"]
)

st.sidebar.markdown("---")
st.sidebar.subheader("Project Info")
st.sidebar.write("Form UID:", FORM_UID)

if st.sidebar.button("🔄 Refresh Data"):
    st.rerun()

st.sidebar.markdown("---")
st.sidebar.caption("ADA System v1.0")

# ==============================
# 🌍 SPELL CHECK
# ==============================
spell = SpellChecker()

CUSTOM_DICT = {
    "tdk": "tidak",
    "yg": "yang",
    "dr": "dari",
    "krn": "karena",
    "utk": "untuk",
    "dapt": "dapat"
}

def correct_text(text):
    if not isinstance(text, str):
        return text

    words = text.split()
    corrected = []

    for w in words:
        lw = w.lower()
        if lw in CUSTOM_DICT:
            corrected.append(CUSTOM_DICT[lw])
        else:
            corrected.append(spell.correction(w) or w)

    return " ".join(corrected)

# ==============================
# 🔢 NUMERIC VALIDATION
# ==============================
def validate_numeric(row):
    errors = []
    try:
        if "quantity" in row and "price" in row:
            q = float(row["quantity"])
            p = float(row["price"])

            if q > 0:
                unit_price = p / q

                if unit_price < 1000:
                    errors.append("price_too_low")
                elif unit_price > 50000:
                    errors.append("price_too_high")

    except:
        errors.append("numeric_error")

    return errors

# ==============================
# 🌐 FETCH DATA (AUTO REFRESH 60s)
# ==============================
@st.cache_data(ttl=60)
def fetch_data():
    if not KOBO_TOKEN:
        st.error("❌ KOBO_TOKEN not set in Secrets")
        return pd.DataFrame()

    url = f"https://kf.kobotoolbox.org/api/v2/assets/{FORM_UID}/data.json"

    headers = {
        "Authorization": f"Token {KOBO_TOKEN.strip()}",
        "Content-Type": "application/json"
    }

    try:
        res = requests.get(url, headers=headers)

        if res.status_code == 200:
            return pd.DataFrame(res.json().get("results", []))

        elif res.status_code == 401:
            st.error("❌ Invalid Kobo Token")
        elif res.status_code == 404:
            st.error("❌ Wrong Form UID")
        else:
            st.error(f"❌ API Error: {res.status_code}")

    except Exception as e:
        st.error(f"❌ Connection error: {e}")

    return pd.DataFrame()

# ==============================
# 📥 LOAD DATA
# ==============================
df = fetch_data()

if df.empty:
    st.warning("No data available")
    st.stop()

# ==============================
# 🧹 CLEAN DATA
# ==============================
clean_data, flagged_data = [], []

for _, row in df.iterrows():
    row = row.to_dict()
    errors = []

    for k, v in row.items():
        if isinstance(v, str):
            row[k] = correct_text(v)

    errors.extend(validate_numeric(row))

    if errors:
        row["errors"] = ", ".join(errors)
        flagged_data.append(row)
    else:
        clean_data.append(row)

clean_df = pd.DataFrame(clean_data)
flag_df = pd.DataFrame(flagged_data)

# ==============================
# 📊 KPI
# ==============================
total = len(df)
valid = len(clean_df)
flagged = len(flag_df)
score = (valid / total) * 100 if total > 0 else 0

# ==============================
# 📄 DASHBOARD
# ==============================
if page == "Dashboard":

    st.title("📊 ADA Dashboard")

    c1, c2, c3, c4 = st.columns(4)

    c1.markdown(f"<div class='card'><div class='title'>Total</div><div class='value'>{total}</div></div>", unsafe_allow_html=True)
    c2.markdown(f"<div class='card'><div class='title'>Valid</div><div class='value green'>{valid}</div></div>", unsafe_allow_html=True)
    c3.markdown(f"<div class='card'><div class='title'>Flagged</div><div class='value red'>{flagged}</div></div>", unsafe_allow_html=True)

    color = "green" if score > 85 else "orange" if score > 60 else "red"
    c4.markdown(f"<div class='card'><div class='title'>Quality</div><div class='value {color}'>{score:.1f}%</div></div>", unsafe_allow_html=True)

    st.subheader("📊 Data Quality Overview")
    chart = pd.DataFrame({
        "Type": ["Valid", "Flagged"],
        "Count": [valid, flagged]
    })
    st.bar_chart(chart.set_index("Type"))

    st.subheader("🚨 Status")
    if flagged > 0:
        st.error(f"{flagged} records need attention")
    else:
        st.success("All data is clean")

# ==============================
# 📄 DATA EXPLORER
# ==============================
elif page == "Data Explorer":

    st.title("📋 Data Explorer")

    t1, t2 = st.tabs(["Clean Data", "Flagged Data"])

    with t1:
        st.dataframe(clean_df, use_container_width=True)

    with t2:
        st.dataframe(flag_df, use_container_width=True)

# ==============================
# 📄 DOWNLOADS
# ==============================
elif page == "Downloads":

    st.title("⬇ Download Data")

    st.download_button("Download Clean Data", clean_df.to_csv(index=False), "clean.csv")
    st.download_button("Download Flagged Data", flag_df.to_csv(index=False), "flagged.csv")

# ==============================
# 🕒 FOOTER
# ==============================
st.caption(f"Last updated: {datetime.now()}")
