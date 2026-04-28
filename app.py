import streamlit as st
import pandas as pd
import io
import requests
from datetime import datetime
import matplotlib.pyplot as plt
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image
from reportlab.lib.styles import getSampleStyleSheet
import base64

st.set_page_config(page_title="REDI ADA System", layout="wide")

# ==============================
# UI STYLE (PROFESSIONAL LOOK)
# ==============================
st.markdown("""
<style>
section[data-testid="stSidebar"] {
    background-color: #2563eb !important;
}
section[data-testid="stSidebar"] * {
    color: white !important;
}
section[data-testid="stSidebar"] label {
    color: black !important;
}
section[data-testid="stSidebar"] input {
    color: black !important;
    background: white !important;
}
button {
    font-size: 14px;
    cursor: pointer;
}
</style>
""", unsafe_allow_html=True)

# ==============================
# SIDEBAR
# ==============================
st.sidebar.title("REDI ADA System")
FORM_UID = st.sidebar.text_input("Form UID", "aQJmYa6Z9mJ5qwdw8RrQcj")
page = st.sidebar.radio("Navigation", ["Dashboard", "Explorer", "Downloads"])

# ==============================
# TOKEN
# ==============================
KOBO_TOKEN = st.secrets.get("KOBO_TOKEN", None)

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

    return pd.json_normalize(r.json().get("results", []))

df = fetch_data(FORM_UID, KOBO_TOKEN)

if df.empty:
    st.warning("No data available")
    st.stop()

# ==============================
# DATE FILTER
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

# ==============================
# SEARCH
# ==============================
search = st.sidebar.text_input("Search")
if search:
    df = df[df.astype(str).apply(lambda x: x.str.contains(search, case=False).any(), axis=1)]

# ==============================
# ENUMERATOR
# ==============================
enum_col = next((c for c in df.columns if "enumerator" in c.lower() or "name" in c.lower()), None)

# ==============================
# DUPLICATES
# ==============================
try:
    dup_mask = df.astype(str).duplicated()
except:
    dup_mask = pd.Series([False]*len(df))

duplicate_indices = set(df[dup_mask].index)

# ==============================
# VALIDATION
# ==============================
clean, flagged = [], []
numeric_cols = df.select_dtypes(include=["number"]).columns.tolist()

for idx, row in df.iterrows():
    r = row.to_dict()
    errors = []

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

    if len(duplicate_indices) < len(df)*0.5 and idx in duplicate_indices:
        errors.append("duplicate")

    for col in numeric_cols:
        try:
            if float(r.get(col, 0)) > 1e9:
                errors.append(f"extreme_{col}")
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
# DASHBOARD
# ==============================
if page == "Dashboard":

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total", total)
    c2.metric("Valid", valid)
    c3.metric("Flagged", bad)
    c4.metric("Score", f"{score:.1f}%")

    st.bar_chart(pd.DataFrame({"Valid":[valid], "Flagged":[bad]}))

    # ENUMERATOR PERFORMANCE
    if enum_col:
        st.subheader("Enumerator Performance")

        perf = df.groupby(enum_col).size().reset_index(name="submissions")

        if not flag_df.empty and enum_col in flag_df.columns:
            flags = flag_df.groupby(enum_col).size().reset_index(name="flags")
            perf = perf.merge(flags, on=enum_col, how="left")
        else:
            perf["flags"] = 0

        perf["flags"] = perf["flags"].fillna(0)

        perf["quality_score"] = perf.apply(
            lambda x: 100 if x["submissions"] == 0 else 100 - (x["flags"]/x["submissions"]*100),
            axis=1
        )

        def highlight_row(row):
            v = row["quality_score"]
            if v >= 85:
                return ["background-color:#16a34a; color:white"]*len(row)
            elif v >= 60:
                return ["background-color:#facc15; color:black"]*len(row)
            else:
                return ["background-color:#dc2626; color:white"]*len(row)

        st.dataframe(perf.style.apply(highlight_row, axis=1), use_container_width=True)
        st.bar_chart(perf.set_index(enum_col)["quality_score"])

    st.subheader("Flagged Data")
    st.dataframe(flag_df.head(50))

# ==============================
# EXPLORER
# ==============================
elif page == "Explorer":
    t1, t2 = st.tabs(["Clean", "Flagged"])
    t1.dataframe(clean_df)
    t2.dataframe(flag_df)

# ==============================
# DOWNLOADS (PRO UI)
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

        content.append(Paragraph("REDI ADA REPORT", styles["Title"]))
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
