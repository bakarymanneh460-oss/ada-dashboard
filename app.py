# =========================================
# REDI AUTOMATED DATA QUALITY MONITORING SYSTEM
# FINAL PRODUCTION VERSION
# =========================================

import streamlit as st
import pandas as pd
import io
import requests
import numpy as np
import os
import logging
import yaml
import streamlit_authenticator as stauth

from yaml.loader import SafeLoader
from datetime import datetime
from sklearn.ensemble import IsolationForest

from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle
)

from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet

import plotly.express as px

# =========================================
# PAGE CONFIG
# =========================================
st.set_page_config(
    page_title="REDI Automated Data Quality Monitoring System",
    layout="wide",
    page_icon="📊"
)

# =========================================
# CONFIG
# =========================================
APP_NAME = os.getenv(
    "APP_NAME",
    "REDI Automated Data Quality Monitoring System"
)

ENABLE_AI = True

AI_CONTAMINATION = 0.005

FRAUD_THRESHOLD = 70

# =========================================
# LOGGING
# =========================================
os.makedirs("logs", exist_ok=True)

logging.basicConfig(
    filename="logs/redi.log",
    level=logging.ERROR,
    format="%(asctime)s %(levelname)s %(message)s"
)

# =========================================
# AUTHENTICATION
# =========================================
with open("config.yaml") as file:

    config = yaml.load(
        file,
        Loader=SafeLoader
    )

authenticator = stauth.Authenticate(
    config["credentials"],
    config["cookie"]["name"],
    config["cookie"]["key"],
    config["cookie"]["expiry_days"]
)

name, authentication_status, username = authenticator.login()

if authentication_status is False:

    st.error("Incorrect username or password")

    st.stop()

if authentication_status is None:

    st.warning("Please login")

    st.stop()

authenticator.logout(
    "Logout",
    "sidebar"
)

st.sidebar.success(
    f"Welcome {name}"
)

# =========================================
# USER ROLE
# =========================================
role = config["credentials"]["usernames"][username]["role"]

st.sidebar.info(
    f"Role: {role}"
)

# =========================================
# AUDIT TRAILS
# =========================================
os.makedirs("audit", exist_ok=True)

def log_action(user, action):

    log = pd.DataFrame([{
        "user": user,
        "action": action,
        "time": datetime.now()
    }])

    file = "audit/audit_log.csv"

    if os.path.exists(file):

        old = pd.read_csv(file)

        log = pd.concat([old, log])

    log.to_csv(file, index=False)

log_action(username, "logged_in")

# =========================================
# SESSION
# =========================================
if "loaded" not in st.session_state:
    st.session_state.loaded = True

# =========================================
# STYLE
# =========================================
st.markdown("""
<style>

section[data-testid="stSidebar"] {
    background-color:#1e3a8a !important;
}

section[data-testid="stSidebar"] * {
    color:white !important;
}

section[data-testid="stSidebar"] input {
    background:white !important;
    color:black !important;
}

.kpi-card {
    padding:20px;
    border-radius:14px;
    color:white;
    text-align:center;
    box-shadow:0 4px 10px rgba(0,0,0,0.2);
}

</style>
""", unsafe_allow_html=True)

# =========================================
# SIDEBAR
# =========================================
st.sidebar.title("📊 REDI Universal Data System")

st.sidebar.caption(
    "Field Data Quality Monitoring System"
)

FORM_UID = st.sidebar.text_input(
    "Kobo Form UID"
)

# =========================================
# ROLE-BASED NAVIGATION
# =========================================
page_options = [
    "Dashboard",
    "Explorer",
    "Quality Analytics",
    "Downloads"
]

if role == "enumerator":

    page_options = [
        "Dashboard",
        "Explorer"
    ]

elif role == "supervisor":

    page_options = [
        "Dashboard",
        "Explorer",
        "Quality Analytics"
    ]

page = st.sidebar.radio(
    "Navigation",
    page_options
)

# =========================================
# KOBO TOKEN
# =========================================
KOBO_TOKEN = st.secrets.get(
    "KOBO_TOKEN",
    None
)

# =========================================
# REFRESH
# =========================================
if st.sidebar.button("🔄 Refresh System"):

    log_action(username, "refreshed_system")

    st.cache_data.clear()

    st.rerun()

st.sidebar.success("System Online")

st.sidebar.info(
    f"Updated: {datetime.now().strftime('%H:%M:%S')}"
)

# =========================================
# FETCH DATA
# =========================================
@st.cache_data(ttl=120)
def fetch_data(uid, token):

    if not uid:
        return pd.DataFrame()

    headers = {
        "Authorization": f"Token {token}"
    } if token else {}

    url = f"https://kf.kobotoolbox.org/api/v2/assets/{uid}/data/?format=json&page_size=1000"

    all_data = []

    while url:

        try:

            r = requests.get(
                url,
                headers=headers,
                timeout=30
            )

            if r.status_code != 200:

                logging.error(
                    f"Kobo API Error: {r.status_code}"
                )

                break

            data = r.json()

            all_data.extend(
                data.get("results", [])
            )

            url = data.get("next")

        except Exception as e:

            logging.error(str(e))

            break

    return pd.json_normalize(all_data)

# =========================================
# LOAD DATA
# =========================================
df = fetch_data(
    FORM_UID,
    KOBO_TOKEN
)

if df.empty:

    st.warning("No data found")

    st.stop()

# =========================================
# SMART COLUMN DETECTION
# =========================================
def detect(names):

    for col in df.columns:

        for n in names:

            if n in col.lower():
                return col

    return None

DATE_COL = detect([
    "submission_time",
    "date",
    "time"
])

HH_COL = detect([
    "hh",
    "household",
    "id"
])

ENUM_COL = detect([
    "enum",
    "enumerator",
    "name",
    "user"
])

REGION_COL = detect([
    "region",
    "district",
    "area"
])

GPS_COL = detect([
    "gps",
    "latitude",
    "longitude"
])

if "_submission_time" in df.columns:
    DATE_COL = "_submission_time"

if DATE_COL:

    df[DATE_COL] = pd.to_datetime(
        df[DATE_COL],
        errors="coerce"
    )

# =========================================
# FILTERS
# =========================================
st.sidebar.subheader("Filters")

if DATE_COL:

    c1, c2 = st.sidebar.columns(2)

    start = c1.date_input(
        "Start",
        df[DATE_COL].min()
    )

    end = c2.date_input(
        "End",
        df[DATE_COL].max()
    )

    df = df[
        (df[DATE_COL] >= pd.to_datetime(start)) &
        (df[DATE_COL] <= pd.to_datetime(end))
    ]

if REGION_COL:

    regions = st.sidebar.multiselect(
        "Region Filter",
        df[REGION_COL].dropna().unique()
    )

    if regions:

        df = df[
            df[REGION_COL].isin(regions)
        ]

if ENUM_COL:

    enums = st.sidebar.multiselect(
        "Enumerator Filter",
        df[ENUM_COL].dropna().unique()
    )

    if enums:

        df = df[
            df[ENUM_COL].isin(enums)
        ]

search = st.sidebar.text_input("Search")

if search:

    df = df[
        df.astype(str).apply(
            lambda x: x.str.contains(
                search,
                case=False,
                na=False
            ).any(),
            axis=1
        )
    ]

# =========================================
# MONTH
# =========================================
if DATE_COL:

    df["Month"] = (
        df[DATE_COL]
        .dt.to_period("M")
        .astype(str)
    )

# =========================================
# NUMERIC COLUMNS
# =========================================
num_cols = df.select_dtypes(
    include=["number"]
).columns

# =========================================
# BASIC ANOMALY DETECTION
# =========================================
if len(num_cols) > 0:

    std = df[num_cols].std().replace(0, 1)

    z = np.abs(
        (df[num_cols] - df[num_cols].mean()) / std
    )

    df["anomaly_flag"] = (
        z.max(axis=1) > 4.5
    )

else:

    df["anomaly_flag"] = False

# =========================================
# AI ANOMALY DETECTION
# =========================================
if ENABLE_AI and len(num_cols) > 2:

    try:

        ai_df = df[num_cols].fillna(0)

        model = IsolationForest(
            contamination=AI_CONTAMINATION,
            random_state=42
        )

        pred = model.fit_predict(ai_df)

        df["ai_flag"] = pred == -1

    except Exception as e:

        logging.error(str(e))

        df["ai_flag"] = False

else:

    df["ai_flag"] = False

# =========================================
# ENUMERATOR PERFORMANCE
# =========================================
if ENUM_COL and DATE_COL:

    df = df.sort_values(DATE_COL)

    df["time_diff"] = (
        df.groupby(ENUM_COL)[DATE_COL]
        .diff()
        .dt.total_seconds()
    )

    perf = df.groupby(ENUM_COL).agg(
        total=("time_diff", "count"),

        fast=(
            "time_diff",
            lambda x: (x < 20).sum()
        )
    ).reset_index()

    perf["fraud_score"] = (
        (perf["fast"] / perf["total"])
        .fillna(0) * 100
    ).clip(upper=100)

    df = df.merge(
        perf[[ENUM_COL, "fraud_score"]],
        on=ENUM_COL,
        how="left"
    )

    df["fraud_flag"] = (
        df["fraud_score"] > FRAUD_THRESHOLD
    )

else:

    df["fraud_flag"] = False

# =========================================
# SMART FINAL FLAGS
# =========================================
df["flag_score"] = (
    df["anomaly_flag"].astype(int) +
    df["fraud_flag"].astype(int) +
    df["ai_flag"].astype(int)
)

df["final_flag"] = (
    df["flag_score"] >= 2
)

# =========================================
# SEVERITY LEVELS
# =========================================
df["severity"] = "Low"

df.loc[
    df["flag_score"] == 1,
    "severity"
] = "Medium"

df.loc[
    df["flag_score"] == 2,
    "severity"
] = "High"

df.loc[
    df["flag_score"] >= 3,
    "severity"
] = "Critical"

# =========================================
# REVIEW COLUMNS
# =========================================
df["review_status"] = "Pending"

df["review_comment"] = ""

# =========================================
# CLEAN & FLAGGED
# =========================================
clean_df = df[~df["final_flag"]]

flag_df = df[df["final_flag"]]

# =========================================
# KPIs
# =========================================
total = len(df)

valid = len(clean_df)

bad = len(flag_df)

score = (
    (valid / total) * 100
    if total else 0
)

# =========================================
# DASHBOARD
# =========================================
if page == "Dashboard":

    st.title(APP_NAME)

    c1, c2, c3, c4 = st.columns(4)

    c1.markdown(
        f"""
        <div class="kpi-card"
        style="background:#2563eb">
        <h3>Total Records</h3>
        <h1>{total}</h1>
        </div>
        """,
        unsafe_allow_html=True
    )

    c2.markdown(
        f"""
        <div class="kpi-card"
        style="background:#16a34a">
        <h3>Valid Records</h3>
        <h1>{valid}</h1>
        </div>
        """,
        unsafe_allow_html=True
    )

    c3.markdown(
        f"""
        <div class="kpi-card"
        style="background:#dc2626">
        <h3>Flagged</h3>
        <h1>{bad}</h1>
        </div>
        """,
        unsafe_allow_html=True
    )

    c4.markdown(
        f"""
        <div class="kpi-card"
        style="background:#7c3aed">
        <h3>Quality Score</h3>
        <h1>{score:.1f}%</h1>
        </div>
        """,
        unsafe_allow_html=True
    )

    st.subheader("Data Quality Overview")

    quality_df = pd.DataFrame({
        "Category": ["Valid", "Flagged"],
        "Count": [valid, bad]
    })

    fig = px.bar(
        quality_df,
        x="Category",
        y="Count",
        text="Count"
    )

    st.plotly_chart(
        fig,
        use_container_width=True
    )

    # =====================================
    # ENUMERATOR PERFORMANCE
    # =====================================
    if ENUM_COL:

        st.subheader(
            "Enumerator Performance"
        )

        enum_perf = (
            df.groupby(ENUM_COL)["final_flag"]
            .agg(["count", "sum"])
            .reset_index()
        )

        enum_perf["quality_score"] = (
            1 -
            enum_perf["sum"] /
            enum_perf["count"]
        ) * 100

        st.dataframe(
            enum_perf.sort_values(
                "quality_score",
                ascending=False
            ),
            use_container_width=True
        )

    # =====================================
    # REGIONAL PERFORMANCE
    # =====================================
    if REGION_COL:

        st.subheader(
            "Regional Performance"
        )

        reg = (
            df.groupby(REGION_COL)["final_flag"]
            .agg(["count", "sum"])
            .reset_index()
        )

        reg["quality_score"] = (
            1 -
            reg["sum"] /
            reg["count"]
        ) * 100

        st.dataframe(
            reg,
            use_container_width=True
        )

    # =====================================
    # MONTHLY TREND
    # =====================================
    if "Month" in df.columns:

        st.subheader(
            "Monthly Submission Trend"
        )

        monthly = (
            df.groupby("Month")
            .size()
            .reset_index(name="records")
        )

        fig2 = px.line(
            monthly,
            x="Month",
            y="records",
            markers=True
        )

        st.plotly_chart(
            fig2,
            use_container_width=True
        )

    # =====================================
    # SUPERVISOR REVIEW WORKFLOW
    # =====================================
    if role in ["admin", "supervisor"]:

        st.subheader(
            "Supervisor Review Workflow"
        )

        flagged_cases = df[df["final_flag"]]

        if not flagged_cases.empty:

            selected_case = st.selectbox(
                "Select Flagged Record",
                flagged_cases.index
            )

            decision = st.selectbox(
                "Decision",
                [
                    "Approve",
                    "Reject",
                    "Needs Review"
                ]
            )

            comment = st.text_area(
                "Supervisor Comment"
            )

            if st.button("Save Review"):

                df.loc[
                    selected_case,
                    "review_status"
                ] = decision

                df.loc[
                    selected_case,
                    "review_comment"
                ] = comment

                log_action(
                    username,
                    f"reviewed_case_{selected_case}"
                )

                st.success(
                    "Review saved successfully"
                )

# =========================================
# EXPLORER
# =========================================
elif page == "Explorer":

    st.title("Data Explorer")

    tab1, tab2 = st.tabs([
        "Clean Records",
        "Flagged Records"
    ])

    with tab1:

        st.dataframe(
            clean_df,
            use_container_width=True
        )

    with tab2:

        st.dataframe(
            flag_df,
            use_container_width=True
        )

# =========================================
# QUALITY ANALYTICS
# =========================================
elif page == "Quality Analytics":

    st.title(
        "Advanced Quality Analytics"
    )

    summary = pd.DataFrame({
        "Issue": [
            "Basic Anomalies",
            "AI Flags",
            "Fraud Flags"
        ],
        "Count": [
            df["anomaly_flag"].sum(),
            df["ai_flag"].sum(),
            df["fraud_flag"].sum()
        ]
    })

    st.dataframe(
        summary,
        use_container_width=True
    )

    fig3 = px.pie(
        summary,
        names="Issue",
        values="Count"
    )

    st.plotly_chart(
        fig3,
        use_container_width=True
    )

# =========================================
# DOWNLOADS
# =========================================
elif page == "Downloads":

    st.title("Downloads & Reports")

    def to_excel(data):

        output = io.BytesIO()

        with pd.ExcelWriter(
            output,
            engine="openpyxl"
        ) as writer:

            data.to_excel(
                writer,
                index=False
            )

        output.seek(0)

        return output

    def full_excel():

        output = io.BytesIO()

        with pd.ExcelWriter(
            output,
            engine="openpyxl"
        ) as writer:

            clean_df.to_excel(
                writer,
                index=False,
                sheet_name="Clean"
            )

            flag_df.to_excel(
                writer,
                index=False,
                sheet_name="Flagged"
            )

        output.seek(0)

        return output

    def generate_pdf():

        buffer = io.BytesIO()

        doc = SimpleDocTemplate(buffer)

        styles = getSampleStyleSheet()

        elements = []

        elements.append(
            Paragraph(
                "REDI Data Quality Report",
                styles["Title"]
            )
        )

        elements.append(
            Spacer(1, 12)
        )

        table_data = [
            ["Metric", "Value"],
            ["Total Records", str(total)],
            ["Valid Records", str(valid)],
            ["Flagged Records", str(bad)],
            ["Quality Score", f"{score:.2f}%"]
        ]

        table = Table(table_data)

        table.setStyle(TableStyle([
            (
                "BACKGROUND",
                (0,0),
                (-1,0),
                colors.grey
            ),
            (
                "TEXTCOLOR",
                (0,0),
                (-1,0),
                colors.whitesmoke
            ),
            (
                "GRID",
                (0,0),
                (-1,-1),
                1,
                colors.black
            ),
            (
                "FONTNAME",
                (0,0),
                (-1,0),
                "Helvetica-Bold"
            ),
        ]))

        elements.append(table)

        elements.append(
            Spacer(1, 20)
        )

        elements.append(
            Paragraph(
                f"Generated: {datetime.now()}",
                styles["Normal"]
            )
        )

        doc.build(elements)

        buffer.seek(0)

        return buffer

    c1, c2, c3, c4 = st.columns(4)

    with c1:

        if st.download_button(
            "📊 Download Full Excel",
            full_excel(),
            file_name="redi_full.xlsx"
        ):

            log_action(
                username,
                "downloaded_full_excel"
            )

    with c2:

        if st.download_button(
            "✅ Download Clean",
            to_excel(clean_df),
            file_name="clean.xlsx"
        ):

            log_action(
                username,
                "downloaded_clean_excel"
            )

    with c3:

        if st.download_button(
            "⚠️ Download Flagged",
            to_excel(flag_df),
            file_name="flagged.xlsx"
        ):

            log_action(
                username,
                "downloaded_flagged_excel"
            )

    with c4:

        if st.download_button(
            "📄 Download PDF",
            generate_pdf(),
            file_name="redi_report.pdf"
        ):

            log_action(
                username,
                "downloaded_pdf_report"
            )

# =========================================
# FOOTER
# =========================================
st.caption(
    f"{APP_NAME} | Last Updated: {datetime.now()}"
)
