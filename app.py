import streamlit as st
import pandas as pd
import io
import requests
from datetime import datetime

st.set_page_config(page_title="REDI ADA System", layout="wide")

# ==============================
# AUTO REFRESH
# ==============================
st.markdown("""
<script>
setTimeout(function(){
    window.location.reload();
}, 60000);
</script>
""", unsafe_allow_html=True)

# ==============================
# 🎨 UI
# ==============================
st.markdown("""
<style>
body {background-color:#f5f7fb;}

section[data-testid="stSidebar"] {
    background-color: #2563eb !important;
}
section[data-testid="stSidebar"] * {
    color: white !important;
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
FORM_UID = st.sidebar.text_input("Form UID", "aQJmYa6Z9mJ5qwdw8RrQcj")
page = st.sidebar.radio("Navigation", ["Dashboard", "Explorer", "Downloads"])

# ==============================
# TOKEN
# ==============================
try:
    KOBO_TOKEN = st.secrets["KOBO_TOKEN"]
except:
    KOBO_TOKEN = None

# ==============================
# FETCH DATA
# ==============================
@st.cache_data(ttl=60)
def fetch_data(uid, token):
    url = f"https://kf.kobotoolbox.org/api/v2/assets/{uid}/data/"
    headers = {"Authorization": f"Token {token}"} if token else {}

    r = requests.get(url, headers=headers)
    if r.status_code != 200:
        st.error(f"API Error {r.status_code}")
        return pd.DataFrame()

    data = r.json()
    return pd.json_normalize(data.get("results", []))

df = fetch_data(FORM_UID, KOBO_TOKEN)

if df.empty:
    st.warning("No data available")
    st.stop()

# ==============================
# 🔎 FILTERS (NEW)
# ==============================
st.sidebar.markdown("### Filters")

# Date filter (if exists)
if "_submission_time" in df.columns:
    df["_submission_time"] = pd.to_datetime(df["_submission_time"])
    min_date = df["_submission_time"].min()
    max_date = df["_submission_time"].max()

    date_range = st.sidebar.date_input(
        "Date Range",
        [min_date, max_date]
    )

    if len(date_range) == 2:
        df = df[
            (df["_submission_time"] >= pd.to_datetime(date_range[0])) &
            (df["_submission_time"] <= pd.to_datetime(date_range[1]))
        ]

# Keyword filter
search = st.sidebar.text_input("Search keyword")
if search:
    df = df[df.astype(str).apply(lambda row: row.str.contains(search, case=False).any(), axis=1)]

# ==============================
# VALIDATION
# ==============================
clean, flagged = [], []

for _, row in df.iterrows():
    r = row.to_dict()
    errors = []

    try:
        if "quantity" in r and "price" in r:
            q = float(r["quantity"])
            p = float(r["price"])
            if q > 0:
                unit = p / q
                if unit < 1000:
                    errors.append("low_price")
                elif unit > 50000:
                    errors.append("high_price")
    except:
        pass

    if errors:
        r["errors"] = ", ".join(errors)
        flagged.append(r)
    else:
        clean.append(r)

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
# DASHBOARD
# ==============================
if page == "Dashboard":

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total", total)
    c2.metric("Valid", valid)
    c3.metric("Flagged", bad)
    c4.metric("Score", f"{score:.1f}%")

    # 📊 Chart
    st.subheader("Validation Overview")
    st.bar_chart(pd.DataFrame({"Valid":[valid], "Flagged":[bad]}))

    # 📈 Trend chart (NEW)
    if "_submission_time" in df.columns:
        st.subheader("Submissions Over Time")
        trend = df.groupby(df["_submission_time"].dt.date).size()
        st.line_chart(trend)

    # 🗺 Map (NEW)
    gps_cols = [c for c in df.columns if "lat" in c.lower() or "lon" in c.lower()]
    if len(gps_cols) >= 2:
        try:
            st.subheader("Submission Map")
            map_df = df.rename(columns={
                gps_cols[0]: "lat",
                gps_cols[1]: "lon"
            })
            st.map(map_df[["lat","lon"]].dropna())
        except:
            pass

# ==============================
# EXPLORER
# ==============================
elif page == "Explorer":

    t1, t2 = st.tabs(["Clean", "Flagged"])
    t1.dataframe(clean_df, use_container_width=True)
    t2.dataframe(flag_df, use_container_width=True)

# ==============================
# DOWNLOADS
# ==============================
elif page == "Downloads":

    def to_excel():
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            clean_df.to_excel(writer, index=False)
            flag_df.to_excel(writer, sheet_name="Flagged", index=False)
        return output.getvalue()

    st.download_button("Download Excel", to_excel(), "data.xlsx")

    report = f"""
REDI ADA REPORT
Date: {datetime.now()}
Total: {total}
Valid: {valid}
Flagged: {bad}
Score: {score:.2f}%
"""
    st.download_button("Download Report", report, "report.txt")

# ==============================
# FOOTER
# ==============================
st.caption(f"Updated: {datetime.now()}")
