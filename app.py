import streamlit as st
import pandas as pd
import requests
import os
import io
from datetime import datetime

# ==============================
# OPTIONAL SPELLCHECK (SAFE)
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

# 👉 ADD YOUR KOBO FORMS HERE
PROJECTS = {
    "Main Survey": "aQJmYa6Z9mJ5qwdw8RrQcj",
    # Add more like:
    # "Economic Survey": "YOUR_FORM_UID",
    # "Health Survey": "YOUR_FORM_UID"
}

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
# CSS THEME (POWER BI STYLE)
# ==============================
st.markdown("""
<style>
body {background-color:#f5f7fb;}

section[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #1e3a8a, #2563eb);
}
section[data-testid="stSidebar"] * {
    color:white !important;
}

.metric-card {
    background:white;
    padding:18px;
    border-radius:14px;
    box-shadow:0 4px 14px rgba(0,0,0,0.08);
    text-align:center;
}

.metric-title {font-size:13px;color:#6b7280;}
.metric-value {font-size:28px;font-weight:bold;}

.green {color:#16a34a;}
.red {color:#dc2626;}
.orange {color:#f59e0b;}

.stButton > button {
    background:#2563eb;
    color:white;
    border-radius:8px;
}

.stDownloadButton > button {
    background:#16a34a;
    color:white;
}

</style>
""", unsafe_allow_html=True)

# ==============================
# SIDEBAR
# ==============================
st.sidebar.markdown("## REDI ADA System")
st.sidebar.markdown("---")

# 🔁 PROJECT SWITCHER
selected_project = st.sidebar.selectbox("Select Project", list(PROJECTS.keys()))
FORM_UID = PROJECTS[selected_project]

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
# VALIDATION
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
                    errors.append("low_price")
                elif unit > 50000:
                    errors.append("high_price")
    except:
        errors.append("numeric_error")
    return errors

# ==============================
# FETCH DATA
# ==============================
@st.cache_data(ttl=60)
def fetch_data(form_uid):
    if not KOBO_TOKEN:
        st.error("❌ KOBO_TOKEN not set in Secrets")
        return pd.DataFrame()

    url = f"https://kf.kobotoolbox.org/api/v2/assets/{form_uid}/data/?format=json"
    headers = {"Authorization": f"Token {KOBO_TOKEN.strip()}"}

    try:
        res = requests.get(url, headers=headers)

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
# LOAD
# ==============================
df = fetch_data(FORM_UID)

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
# METRICS
# ==============================
total = len(df)
valid = len(clean_df)
bad = len(flag_df)
score = (valid / total) * 100 if total else 0

# ==============================
# EXPORT
# ==============================
def export_excel():
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        clean_df.to_excel(writer, sheet_name='Clean Data', index=False)
        flag_df.to_excel(writer, sheet_name='Flagged Data', index=False)
    return output.getvalue()

def export_report():
    return f"""
ADA REPORT
Project: {selected_project}
Generated: {datetime.now()}

Total: {total}
Valid: {valid}
Flagged: {bad}
Score: {score:.2f}%
"""

# ==============================
# DASHBOARD
# ==============================
if page == "Dashboard":

    c1, c2, c3, c4 = st.columns(4)

    c1.markdown(f"<div class='metric-card'><div class='metric-title'>Total</div><div class='metric-value'>{total}</div></div>", unsafe_allow_html=True)
    c2.markdown(f"<div class='metric-card'><div class='metric-title'>Valid</div><div class='metric-value green'>{valid}</div></div>", unsafe_allow_html=True)
    c3.markdown(f"<div class='metric-card'><div class='metric-title'>Flagged</div><div class='metric-value red'>{bad}</div></div>", unsafe_allow_html=True)

    color = "green" if score > 85 else "orange" if score > 60 else "red"

    c4.markdown(f"<div class='metric-card'><div class='metric-title'>Score</div><div class='metric-value {color}'>{score:.1f}%</div></div>", unsafe_allow_html=True)

    st.bar_chart(pd.DataFrame({"Valid":[valid], "Flagged":[bad]}))

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
# DOWNLOADS
# ==============================
elif page == "Downloads":

    st.download_button(
        "📊 Download Excel",
        export_excel(),
        "ADA_Data.xlsx"
    )

    st.download_button(
        "📄 Download Report",
        export_report(),
        "ADA_Report.txt"
    )

# ==============================
# FOOTER
# ==============================
st.caption(f"Last updated: {datetime.now()}")
