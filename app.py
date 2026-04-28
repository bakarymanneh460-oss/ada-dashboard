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
# UI
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
        st.error(r.text)
        return pd.DataFrame()

    data = r.json()
    return pd.json_normalize(data.get("results", []))

df = fetch_data(FORM_UID, KOBO_TOKEN)

if df.empty:
    st.warning("No data available")
    st.stop()

# ==============================
# FILTERS
# ==============================
st.sidebar.markdown("### Filters")

if "_submission_time" in df.columns:
    df["_submission_time"] = pd.to_datetime(df["_submission_time"])
    dr = st.sidebar.date_input("Date Range", [df["_submission_time"].min(), df["_submission_time"].max()])
    if len(dr) == 2:
        df = df[(df["_submission_time"] >= pd.to_datetime(dr[0])) &
                (df["_submission_time"] <= pd.to_datetime(dr[1]))]

search = st.sidebar.text_input("Search")
if search:
    df = df[df.astype(str).apply(lambda x: x.str.contains(search, case=False).any(), axis=1)]

# ==============================
# ENUMERATOR COLUMN DETECTION
# ==============================
enum_col = None
for col in df.columns:
    if "enumerator" in col.lower() or "name" in col.lower():
        enum_col = col
        break

# ==============================
# ✅ SAFE DUPLICATE DETECTION
# ==============================
try:
    dup_mask = df.astype(str).duplicated()
except:
    dup_mask = pd.Series([False]*len(df))

duplicate_indices = set(df[dup_mask].index)

# ==============================
# VALIDATION + ANOMALY
# ==============================
clean, flagged = [], []

for idx, row in df.iterrows():
    r = row.to_dict()
    errors = []

    # Price validation
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

    # ✅ Duplicate detection (fixed)
    if idx in duplicate_indices:
        errors.append("duplicate")

    # 🚨 Basic anomaly detection
    if r.get("quantity") in [None, "", 0]:
        errors.append("missing_quantity")

    try:
        if "price" in r and float(r["price"]) > 1000000:
            errors.append("extreme_price")
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

    st.subheader("Validation Overview")
    st.bar_chart(pd.DataFrame({"Valid":[valid], "Flagged":[bad]}))

    # 👤 Enumerator performance
    if enum_col:
        st.subheader("Enumerator Performance")

        perf = df.groupby(enum_col).size().reset_index(name="submissions")

        if not flag_df.empty:
            flag_counts = flag_df.groupby(enum_col).size().reset_index(name="flags")
            perf = perf.merge(flag_counts, on=enum_col, how="left").fillna(0)

        perf["quality_score"] = 100 - (perf["flags"] / perf["submissions"] * 100)

        st.dataframe(perf.sort_values("quality_score", ascending=False))
        st.bar_chart(perf.set_index(enum_col)["quality_score"])

    # 🚨 anomalies
    st.subheader("Flagged / Anomalies")
    st.write(f"Total flagged: {bad}")
    st.dataframe(flag_df.head(50))

    # 📈 Trend
    if "_submission_time" in df.columns:
        trend = df.groupby(df["_submission_time"].dt.date).size()
        st.line_chart(trend)

    # 🗺 Map
    gps = [c for c in df.columns if "lat" in c.lower() or "lon" in c.lower()]
    if len(gps) >= 2:
        try:
            map_df = df.rename(columns={gps[0]: "lat", gps[1]: "lon"})
            st.map(map_df[["lat","lon"]].dropna())
        except:
            pass

# ==============================
# EXPLORER
# ==============================
elif page == "Explorer":
    t1, t2 = st.tabs(["Clean", "Flagged"])
    t1.dataframe(clean_df)
    t2.dataframe(flag_df)

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

# ==============================
# FOOTER
# ==============================
st.caption(f"Updated: {datetime.now()}")
