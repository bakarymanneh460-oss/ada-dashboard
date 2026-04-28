import streamlit as st
import pandas as pd
import io
import requests
from datetime import datetime
import matplotlib.pyplot as plt
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image
from reportlab.lib.styles import getSampleStyleSheet
import base64
import numpy as np

st.set_page_config(page_title="REDI Data Quality System", layout="wide")

# ==============================
# 🎨 UI (FIXED + CLEAN)
# ==============================
st.markdown("""
<style>
section[data-testid="stSidebar"] {
    background-color: #1e3a8a !important;
}

section[data-testid="stSidebar"] label,
section[data-testid="stSidebar"] h1,
section[data-testid="stSidebar"] h2,
section[data-testid="stSidebar"] h3,
section[data-testid="stSidebar"] p {
    color: white !important;
}

section[data-testid="stSidebar"] input,
section[data-testid="stSidebar"] textarea {
    background-color: white !important;
    color: black !important;
}

section[data-testid="stSidebar"] div[data-baseweb="input"] input {
    color: black !important;
}

.kpi-card {
    padding: 20px;
    border-radius: 12px;
    color: white;
    text-align: center;
}
</style>
""", unsafe_allow_html=True)

# ==============================
# 🧭 SIDEBAR (UPDATED BRANDING ONLY)
# ==============================
st.sidebar.markdown("## 📊 REDI Data Quality System")
st.sidebar.caption("Field Data Quality & Monitoring Tool")

FORM_UID = st.sidebar.text_input("Form UID", "aQJmYa6Z9mJ5qwdw8RrQcj")
page = st.sidebar.radio("Navigation", ["Dashboard", "Explorer", "Downloads"])

KOBO_TOKEN = st.secrets.get("KOBO_TOKEN", None)

# ==============================
# 📥 FETCH DATA
# ==============================
@st.cache_data(ttl=60)
def fetch_data(uid, token):
    url = f"https://kf.kobotoolbox.org/api/v2/assets/{uid}/data/"
    headers = {"Authorization": f"Token {token}"} if token else {}
    r = requests.get(url, headers=headers)

    if r.status_code != 200:
        st.error(f"API Error {r.status_code}")
        return pd.DataFrame()

    return pd.json_normalize(r.json().get("results", []))

df = fetch_data(FORM_UID, KOBO_TOKEN)

if df.empty:
    st.warning("No data available")
    st.stop()

# ==============================
# FILTERS
# ==============================
if "_submission_time" in df.columns:
    df["_submission_time"] = pd.to_datetime(df["_submission_time"])
    c1, c2 = st.sidebar.columns(2)
    start = c1.date_input("Start", df["_submission_time"].min())
    end = c2.date_input("End", df["_submission_time"].max())

    df = df[
        (df["_submission_time"] >= pd.to_datetime(start)) &
        (df["_submission_time"] <= pd.to_datetime(end))
    ]

search = st.sidebar.text_input("Search")
if search:
    df = df[df.astype(str).apply(lambda x: x.str.contains(search, case=False).any(), axis=1)]

enum_col = next((c for c in df.columns if "enumerator" in c.lower() or "name" in c.lower()), None)

# ==============================
# GPS DETECTION
# ==============================
lat_col = next((c for c in df.columns if "lat" in c.lower()), None)
lon_col = next((c for c in df.columns if "lon" in c.lower() or "long" in c.lower()), None)

# ==============================
# ANOMALY DETECTION (UNCHANGED)
# ==============================
numeric_cols = df.select_dtypes(include=["number"]).columns

if len(numeric_cols) > 0:
    z_scores = np.abs((df[numeric_cols] - df[numeric_cols].mean()) / df[numeric_cols].std())
    df["anomaly_score"] = z_scores.max(axis=1)
    df["anomaly_flag"] = df["anomaly_score"] > 3
else:
    df["anomaly_flag"] = False

# ==============================
# VALIDATION (UNCHANGED)
# ==============================
clean, flagged = [], []

for _, row in df.iterrows():
    r = row.to_dict()
    errors = []

    if r.get("anomaly_flag"):
        errors.append("anomaly")

    if "quantity" in df.columns and "price" in df.columns:
        try:
            q = float(r.get("quantity", 0))
            p = float(r.get("price", 0))
            if q == 0:
                errors.append("missing_quantity")
            else:
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
score = (valid / total * 100) if total else 0

# ==============================
# 📊 DASHBOARD (UNCHANGED)
# ==============================
if page == "Dashboard":

    st.title("📊 REDI Data Quality Dashboard")

    c1, c2, c3, c4 = st.columns(4)
    c1.markdown(f'<div class="kpi-card" style="background:#2563eb"><h3>Total</h3><h1>{total}</h1></div>', unsafe_allow_html=True)
    c2.markdown(f'<div class="kpi-card" style="background:#16a34a"><h3>Valid</h3><h1>{valid}</h1></div>', unsafe_allow_html=True)
    c3.markdown(f'<div class="kpi-card" style="background:#dc2626"><h3>Flagged</h3><h1>{bad}</h1></div>', unsafe_allow_html=True)
    c4.markdown(f'<div class="kpi-card" style="background:#7c3aed"><h3>Score</h3><h1>{score:.1f}%</h1></div>', unsafe_allow_html=True)

    st.bar_chart(pd.DataFrame({"Valid":[valid], "Flagged":[bad]}))

    if lat_col and lon_col:
        st.subheader("🗺️ GPS Map")
        st.map(df[[lat_col, lon_col]].dropna())

        if not flag_df.empty:
            st.subheader("⚠️ Flagged Locations")
            st.map(flag_df[[lat_col, lon_col]].dropna())

    if enum_col and lat_col and lon_col:
        st.subheader("🚶 Enumerator Tracking")
        st.dataframe(df.groupby(enum_col).size().reset_index(name="points"))

    st.subheader("🧠 Insights")
    if df["anomaly_flag"].sum() > 0:
        st.warning(f"{df['anomaly_flag'].sum()} anomalies detected")
    else:
        st.success("No anomalies detected")

    st.subheader("⚠️ Flagged Data")
    st.dataframe(flag_df.head(50))

# ==============================
# 🔍 EXPLORER
# ==============================
elif page == "Explorer":
    t1, t2 = st.tabs(["Clean", "Flagged"])
    t1.dataframe(clean_df)
    t2.dataframe(flag_df)

# ==============================
# 📥 DOWNLOADS (UNCHANGED)
# ==============================
elif page == "Downloads":

    st.subheader("Download Center")

    def to_excel():
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            clean_df.to_excel(writer, index=False)
            flag_df.to_excel(writer, sheet_name="Flagged", index=False)
        return output.getvalue()

    def to_pdf():
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer)
        styles = getSampleStyleSheet()
        content = []

        content.append(Paragraph("REDI DATA QUALITY REPORT", styles["Title"]))
        content.append(Spacer(1, 10))
        content.append(Paragraph(f"Generated: {datetime.now()}", styles["Normal"]))

        fig = plt.figure()
        plt.bar(["Valid","Flagged"], [valid,bad])
        img = io.BytesIO()
        plt.savefig(img, format="png")
        plt.close(fig)
        img.seek(0)

        content.append(Image(img, width=400, height=250))
        doc.build(content)

        buffer.seek(0)
        return buffer.getvalue()

    excel_b64 = base64.b64encode(to_excel()).decode()
    pdf_b64 = base64.b64encode(to_pdf()).decode()
    clean_b64 = base64.b64encode(clean_df.to_csv(index=False).encode()).decode()
    flagged_b64 = base64.b64encode(flag_df.to_csv(index=False).encode()).decode()

    c1, c2, c3, c4 = st.columns(4)

    c1.markdown(f'<a href="data:application/octet-stream;base64,{excel_b64}" download="data.xlsx"><button style="width:100%;background:#16a34a;color:white;padding:12px;border-radius:10px;">📊 Excel</button></a>', unsafe_allow_html=True)
    c2.markdown(f'<a href="data:text/csv;base64,{clean_b64}" download="clean.csv"><button style="width:100%;background:#2563eb;color:white;padding:12px;border-radius:10px;">📁 Clean</button></a>', unsafe_allow_html=True)
    c3.markdown(f'<a href="data:text/csv;base64,{flagged_b64}" download="flagged.csv"><button style="width:100%;background:#dc2626;color:white;padding:12px;border-radius:10px;">⚠️ Flagged</button></a>', unsafe_allow_html=True)
    c4.markdown(f'<a href="data:application/pdf;base64,{pdf_b64}" download="report.pdf"><button style="width:100%;background:#1d4ed8;color:white;padding:12px;border-radius:10px;">📄 PDF</button></a>', unsafe_allow_html=True)

st.caption(f"Updated: {datetime.now()}")
