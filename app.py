import streamlit as st
import pandas as pd
import io
import requests
from datetime import datetime

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
# SIDEBAR
# ==============================
st.sidebar.markdown("## REDI ADA System")
st.sidebar.markdown("---")

FORM_UID = st.sidebar.text_input(
    "Enter Kobo Form UID",
    value="aQJmYa6Z9mJ5qwdw8RrQcj"
)

page = st.sidebar.radio("Navigation", ["Dashboard", "Data Explorer", "Downloads"])

# ==============================
# 🔐 TOKEN (SET IN STREAMLIT SECRETS)
# ==============================
try:
    KOBO_TOKEN = st.secrets["KOBO_TOKEN"]
except:
    KOBO_TOKEN = None

# ==============================
# FETCH DATA (FIXED VERSION)
# ==============================
@st.cache_data(ttl=60)
def fetch_data(form_uid, token):
    url = f"https://kf.kobotoolbox.org/api/v2/assets/{form_uid}/data/"

    headers = {}
    if token:
        headers["Authorization"] = f"Token {token}"

    try:
        response = requests.get(url, headers=headers)

        if response.status_code != 200:
            st.error(f"❌ API Error {response.status_code}")
            st.error(response.text)
            return pd.DataFrame()

        data = response.json()

        if "results" not in data:
            st.warning("No 'results' field returned from API")
            return pd.DataFrame()

        df = pd.json_normalize(data["results"])

        st.success(f"✅ Loaded {len(df)} records")
        return df

    except Exception as e:
        st.error("❌ Failed to load data")
        st.error(str(e))
        return pd.DataFrame()

# ==============================
# LOAD DATA
# ==============================
df = fetch_data(FORM_UID, KOBO_TOKEN)

if df.empty:
    st.warning("No data available")
    st.stop()

# ==============================
# SIMPLE VALIDATION
# ==============================
clean, flagged = [], []

for _, row in df.iterrows():
    row = row.to_dict()
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
        pass

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
REDI ADA SYSTEM REPORT
Generated: {datetime.now()}

Form UID: {FORM_UID}

Total Records: {total}
Valid: {valid}
Flagged: {bad}
Quality Score: {score:.2f}%
"""

# ==============================
# DASHBOARD
# ==============================
if page == "Dashboard":

    c1, c2, c3, c4 = st.columns(4)

    c1.metric("Total", total)
    c2.metric("Valid", valid)
    c3.metric("Flagged", bad)
    c4.metric("Score", f"{score:.1f}%")

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

    st.download_button(
        "📊 Download Excel (Clean + Flagged)",
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
