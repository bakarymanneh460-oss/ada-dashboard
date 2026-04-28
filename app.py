import streamlit as st
import pandas as pd
import requests
import os
import io
from datetime import datetime

# ==============================
# SAFE SPELLCHECKER
# ==============================
try:
    from spellchecker import SpellChecker
    spell = SpellChecker()
except:
    spell = None

# ==============================
# CONFIG
# ==============================
KOBO_TOKEN = os.getenv("KOBO_TOKEN")
FORM_UID = "aQJmYa6Z9mJ5qwdw8RrQcj"

st.set_page_config(page_title="REDI ADA System", layout="wide")

# ==============================
# AUTO REFRESH (60s)
# ==============================
st.markdown("""
<script>
setTimeout(function(){
   window.location.reload();
}, 60000);
</script>
""", unsafe_allow_html=True)

# ==============================
# STYLE (POWER BI LOOK)
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
# 🔵 SIDEBAR LOGO
# ==============================
st.sidebar.markdown("""
<div style='background:linear-gradient(135deg,#1e3a8a,#2563eb);
            padding:18px;
            border-radius:14px;
            text-align:center;
            box-shadow:0 6px 18px rgba(0,0,0,0.2);'>

    <h2 style='color:white;
               margin:0;
               font-size:20px;
               font-weight:600;'>
        REDI ADA System
    </h2>

</div>
""", unsafe_allow_html=True)

# ==============================
# NAVIGATION
# ==============================
page = st.sidebar.radio("Navigation", ["Dashboard", "Data Explorer", "Downloads"])

if st.sidebar.button("🔄 Refresh Data"):
    st.rerun()

# ==============================
# TEXT CORRECTION
# ==============================
def correct_text(text):
    if not isinstance(text, str):
        return text
    if spell is None:
        return text
    return " ".join([spell.correction(w) or w for w in text.split()])

# ==============================
# NUMERIC VALIDATION
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
                    errors.append("price_too_low")
                elif unit > 50000:
                    errors.append("price_too_high")
    except:
        errors.append("numeric_error")
    return errors

# ==============================
# FETCH KOBO DATA
# ==============================
@st.cache_data(ttl=60)
def fetch_data():
    if not KOBO_TOKEN:
        st.error("❌ KOBO_TOKEN not set in Secrets")
        return pd.DataFrame()

    url = f"https://kf.kobotoolbox.org/api/v2/assets/{FORM_UID}/data/?format=json"
    headers = {"Authorization": f"Token {KOBO_TOKEN.strip()}"}

    try:
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
# CLEANING PROCESS
# ==============================
clean, flagged = [], []

for _, row in df.iterrows():
    row = row.to_dict()
    errors = []

    # Text correction
    for k, v in row.items():
        if isinstance(v, str):
            row[k] = correct_text(v)

    # Numeric validation
    errors.extend(validate_numeric(row))

    if errors:
        row["errors"] = ", ".join(errors)
        flagged.append(row)
    else:
        clean.append(row)

clean_df = pd.DataFrame(clean)
flag_df = pd.DataFrame(flagged)

# ==============================
# KPI METRICS
# ==============================
total = len(df)
valid = len(clean_df)
bad = len(flag_df)
score = (valid / total) * 100 if total else 0

# ==============================
# EXPORT FUNCTIONS
# ==============================
def export_excel():
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        clean_df.to_excel(writer, sheet_name='Clean Data', index=False)
        flag_df.to_excel(writer, sheet_name='Flagged Data', index=False)
    return output.getvalue()

def export_report():
    return f"""
ADA SYSTEM REPORT
Generated: {datetime.now()}

Total Records: {total}
Valid Records: {valid}
Flagged Records: {bad}
Quality Score: {score:.2f}%
"""

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

    st.subheader("Data Quality Overview")
    st.bar_chart(pd.DataFrame({"Valid":[valid], "Flagged":[bad]}))

# ==============================
# DATA EXPLORER
# ==============================
elif page == "Data Explorer":

    t1, t2 = st.tabs(["Clean Data", "Flagged Data"])

    with t1:
        st.dataframe(clean_df, use_container_width=True)

    with t2:
        st.dataframe(flag_df, use_container_width=True)

# ==============================
# DOWNLOADS
# ==============================
elif page == "Downloads":

    excel_file = export_excel()
    report_file = export_report()

    st.download_button(
        "📊 Download Full Excel (Multi-Sheet)",
        excel_file,
        f"ADA_Report_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
    )

    st.download_button(
        "📄 Download Summary Report",
        report_file,
        f"ADA_Summary_{datetime.now().strftime('%Y%m%d_%H%M')}.txt"
    )

# ==============================
# FOOTER
# ==============================
st.caption(f"Last updated: {datetime.now()}")
