import streamlit as st
import pandas as pd
import io
import requests
from datetime import datetime
import matplotlib.pyplot as plt
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image
from reportlab.lib.styles import getSampleStyleSheet

st.set_page_config(page_title="REDI ADA System", layout="wide")

# ==============================
# UI (BLUE SIDEBAR + BLACK INPUTS)
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
section[data-testid="stSidebar"] label {
    color: black !important;
    font-weight: 600;
}
section[data-testid="stSidebar"] input {
    color: black !important;
    background-color: white !important;
}
section[data-testid="stSidebar"] .stDateInput input {
    color: black !important;
    background-color: white !important;
}
section[data-testid="stSidebar"] input::placeholder {
    color: #6b7280 !important;
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

    return pd.json_normalize(r.json().get("results", []))

df = fetch_data(FORM_UID, KOBO_TOKEN)

if df.empty:
    st.warning("No data available")
    st.stop()

# ==============================
# DATE FILTER (START–END)
# ==============================
if "_submission_time" in df.columns:
    df["_submission_time"] = pd.to_datetime(df["_submission_time"])

    col1, col2 = st.sidebar.columns(2)
    with col1:
        start = st.date_input("Start", df["_submission_time"].min())
    with col2:
        end = st.date_input("End", df["_submission_time"].max())

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
# ENUMERATOR DETECTION
# ==============================
enum_col = None
for col in df.columns:
    if "enumerator" in col.lower() or "name" in col.lower():
        enum_col = col
        break

# ==============================
# SAFE DUPLICATES
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
            elif q > 0:
                unit = p / q
                if unit < 1000:
                    errors.append("low_price")
                elif unit > 50000:
                    errors.append("high_price")
        except:
            pass

    if len(duplicate_indices) < len(df) * 0.5:
        if idx in duplicate_indices:
            errors.append("duplicate")

    for col in numeric_cols:
        try:
            val = float(r.get(col, 0))
            if val > 1e9:
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

    # ENUMERATOR PERFORMANCE (FIXED)
    if enum_col:
        st.subheader("Enumerator Performance")

        perf = df.groupby(enum_col).size().reset_index(name="submissions")

        if not flag_df.empty and enum_col in flag_df.columns:
            flags = flag_df.groupby(enum_col).size().reset_index(name="flags")
            perf = perf.merge(flags, on=enum_col, how="left")
        else:
            perf["flags"] = 0

        if "flags" not in perf.columns:
            perf["flags"] = 0

        perf["flags"] = perf["flags"].fillna(0)

        perf["quality_score"] = perf.apply(
            lambda x: 100 if x["submissions"] == 0 else 100 - (x["flags"] / x["submissions"] * 100),
            axis=1
        )

        # COLOR LOGIC
        def color(val):
            if val >= 85:
                return "background-color:#16a34a; color:white"
            elif val >= 60:
                return "background-color:#facc15; color:black"
            else:
                return "background-color:#dc2626; color:white"

        st.dataframe(perf.style.applymap(color, subset=["quality_score"]))
        st.bar_chart(perf.set_index(enum_col)["quality_score"])

    st.subheader("Flagged Data")
    st.dataframe(flag_df.head(50))

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

    # Excel
    def to_excel():
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            clean_df.to_excel(writer, index=False)
            flag_df.to_excel(writer, sheet_name="Flagged", index=False)
        return output.getvalue()

    st.download_button("Download Excel", to_excel(), "data.xlsx")

    # CSV
    st.download_button("Download Clean CSV", clean_df.to_csv(index=False), "clean.csv")
    st.download_button("Download Flagged CSV", flag_df.to_csv(index=False), "flagged.csv")

    # PDF with charts
    def create_pdf():
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer)
        styles = getSampleStyleSheet()
        content = []

        content.append(Paragraph("REDI ADA REPORT", styles["Title"]))
        content.append(Spacer(1, 10))
        content.append(Paragraph(f"Generated: {datetime.now()}", styles["Normal"]))
        content.append(Spacer(1, 10))

        content.append(Paragraph(f"Total: {total}", styles["Normal"]))
        content.append(Paragraph(f"Valid: {valid}", styles["Normal"]))
        content.append(Paragraph(f"Flagged: {bad}", styles["Normal"]))
        content.append(Paragraph(f"Score: {score:.2f}%", styles["Normal"]))
        content.append(Spacer(1, 20))

        # Chart 1
        fig1 = plt.figure()
        plt.bar(["Valid", "Flagged"], [valid, bad])
        plt.title("Validation Overview")

        img1 = io.BytesIO()
        plt.savefig(img1, format="png")
        plt.close(fig1)
        img1.seek(0)

        content.append(Image(img1, width=400, height=250))

        # Chart 2
        if enum_col:
            perf = df.groupby(enum_col).size().reset_index(name="submissions")
            perf["flags"] = 0
            if not flag_df.empty and enum_col in flag_df.columns:
                f = flag_df.groupby(enum_col).size().reset_index(name="flags")
                perf = perf.merge(f, on=enum_col, how="left").fillna(0)

            perf["quality_score"] = 100 - (perf["flags"]/perf["submissions"]*100)

            fig2 = plt.figure()
            plt.bar(perf[enum_col].astype(str), perf["quality_score"])
            plt.xticks(rotation=45)
            plt.title("Enumerator Performance")

            img2 = io.BytesIO()
            plt.savefig(img2, format="png", bbox_inches="tight")
            plt.close(fig2)
            img2.seek(0)

            content.append(Image(img2, width=400, height=250))

        doc.build(content)
        buffer.seek(0)
        return buffer

    st.download_button("Download PDF Report", create_pdf(), "report.pdf")

# ==============================
# FOOTER
# ==============================
st.caption(f"Updated: {datetime.now()}")
