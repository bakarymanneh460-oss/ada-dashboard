import streamlit as st
import pandas as pd
import requests
import os
from datetime import datetime

# Safe spellchecker (won’t crash)
try:
    from spellchecker import SpellChecker
    spell = SpellChecker()
except:
    spell = None

# ==============================
# 🔐 CONFIG
# ==============================
KOBO_TOKEN = os.getenv("KOBO_TOKEN")
FORM_UID = "aQJmYa6Z9mJ5qwdw8RrQcj"

# ==============================
# PAGE CONFIG
# ==============================
st.set_page_config(page_title="ADA Dashboard", layout="wide")

# ==============================
# STYLE
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
# SIDEBAR
# ==============================
st.sidebar.markdown("""
<div style='background:#2563eb;padding:12px;border-radius:10px;text-align:center'>
<h2 style='color:white;margin:0'>REDI</h2>
</div>
""", unsafe_allow_html=True)

page = st.sidebar.radio("Navigation", ["Dashboard", "Data Explorer", "Downloads"])

if st.sidebar.button("🔄 Refresh Data"):
    st.rerun()

# ==============================
# TEXT CLEANING
# ==============================
def correct_text(text):
    if not isinstance(text, str):
        return text
    if spell is None:
        return text
    return " ".join([spell.correction(w) or w for w in text.split()])

# ==============================
# NUMERIC CHECK
# ==============================
def validate_numeric(row):
    errors = []
    try:
        if "quantity" in row and "price" in row:
            q = float(row["quantity"])
            p = float(row["price"])
            if q > 0:
                unit = p / q
                if unit < 1000:
                    errors.append("price_low")
                elif unit > 50000:
                    errors.append("price_high")
    except:
        errors.append("numeric_error")
    return errors

# ==============================
# FETCH DATA (FINAL FIX)
# ==============================
@st.cache_data(ttl=60)
def fetch_data():
    if not KOBO_TOKEN:
        st.error("❌ KOBO_TOKEN not set in Secrets")
        return pd.DataFrame()

    url = f"https://kf.kobotoolbox.org/api/v2/assets/{FORM_UID}/data/?format=json"

    headers = {
        "Authorization": f"Token {KOBO_TOKEN.strip()}",
    }

    try:
        with st.spinner("⏳ Fetching data from Kobo..."):
            res = requests.get(url, headers=headers, timeout=20)

        if res.status_code == 200:
            data = res.json().get("results", [])
            st.success(f"✅ Loaded {len(data)} records")
            return pd.DataFrame(data)

        elif res.status_code == 401:
            st.error("❌ Invalid Kobo Token")
        elif res.status_code == 404:
            st.error("❌ Wrong Form UID")
        else:
            st.error(f"❌ API Error: {res.status_code}")

    except requests.exceptions.Timeout:
        st.error("❌ Request timed out")
    except Exception as e:
        st.error(f"❌ Error: {e}")

    return pd.DataFrame()

# ==============================
# LOAD DATA
# ==============================
df = fetch_data()

if df.empty:
    st.warning("No data available")
    st.stop()

# ==============================
# CLEAN
# ==============================
clean, flagged = [], []

for _, row in df.iterrows():
    row = row.to_dict()
    errors = []

    for k, v in row.items():
        if isinstance(v, str):
            row[k] = correct_text(v)

    errors.extend(validate_numeric(row))

    if errors:
        row["errors"] = ", ".join(errors)
        flagged.append(row)
    else:
        clean.append(row)

clean_df = pd.DataFrame(clean)
flag_df = pd.DataFrame(flagged)

# ==============================
# KPI
# ==============================
total = len(df)
valid = len(clean_df)
bad = len(flag_df)
score = (valid / total) * 100 if total else 0

# ==============================
# DASHBOARD
# ==============================
if page == "Dashboard":

    c1, c2, c3, c4 = st.columns(4)

    c1.markdown(f"<div class='card'><div class='title'>Total</div><div class='value'>{total}</div></div>", unsafe_allow_html=True)
    c2.markdown(f"<div class='card'><div class='title'>Valid</div><div class='value green'>{valid}</div></div>", unsafe_allow_html=True)
    c3.markdown(f"<div class='card'><div class='title'>Flagged</div><div class='value red'>{bad}</div></div>", unsafe_allow_html=True)

    color = "green" if score > 85 else "orange" if score > 60 else "red"
    c4.markdown(f"<div class='card'><div class='title'>Quality</div><div class='value {color}'>{score:.1f}%</div></div>", unsafe_allow_html=True)

    st.bar_chart(pd.DataFrame({
        "Valid": [valid],
        "Flagged": [bad]
    }))

# ==============================
# DATA
# ==============================
elif page == "Data Explorer":

    t1, t2 = st.tabs(["Clean", "Flagged"])

    with t1:
        st.dataframe(clean_df, use_container_width=True)

    with t2:
        st.dataframe(flag_df, use_container_width=True)

# ==============================
# DOWNLOAD
# ==============================
elif page == "Downloads":

    st.download_button("Download Clean", clean_df.to_csv(index=False), "clean.csv")
    st.download_button("Download Flagged", flag_df.to_csv(index=False), "flagged.csv")

# ==============================
# FOOTER
# ==============================
st.caption(f"Last updated: {datetime.now()}")
