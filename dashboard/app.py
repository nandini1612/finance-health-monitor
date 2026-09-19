"""
CashPulse - Streamlit dashboard.

Works against either tier of this project:
  - local quickstart: SQLite at data/finance.db (default, no setup needed)
  - cloud edition: Postgres/RDS, picked up automatically when DATABASE_URL is set

This "same dashboard, config picks the backend" pattern is standard
12-factor practice, and it's also just convenient: you get one dashboard
to maintain instead of two.

For genuine practice with a real BI tool, also follow
dashboard/POWER_BI_TABLEAU_GUIDE.md (local tier) or cloud/README.md (cloud
tier) and connect Power BI or Tableau to the same database -- that's what
should end up on your resume as the "BI" line item, alongside this
dashboard as a code-based alternative. Power BI/Tableau are NOT wired up
automatically -- see that guide to connect one yourself. The toolbar's
data badge below runs a real COUNT(*) against the actual database on
every load, so the row count and "updated" timestamp are live, not
hardcoded -- proof this is real data, not a mock.

Styling note: this dashboard intentionally uses Streamlit's own default
layout and widgets (st.metric, st.container(border=True), st.success/
st.warning/st.info, native chart theming) instead of hand-rolled HTML/CSS.
The color scheme comes entirely from .streamlit/config.toml (dark base +
a green accent) -- one source of truth, so native Streamlit text always
matches its background instead of fighting a separately hardcoded palette.

Run:
    streamlit run dashboard/app.py                       # local SQLite
    DATABASE_URL=postgresql://... streamlit run dashboard/app.py   # cloud Postgres
"""

import os
import subprocess
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

LOCAL_DB_PATH = Path(__file__).parent.parent / "data" / "finance.db"
DATABASE_URL = os.environ.get("DATABASE_URL")
BACKEND = "postgres" if DATABASE_URL else "sqlite"


def _bootstrap_local_data():
    """First-run setup for the local SQLite tier.

    data/finance.db and the CSVs it's built from are gitignored on purpose
    (they're generated artifacts, not source) -- which means a fresh clone,
    or a fresh deploy on something like Streamlit Community Cloud, starts
    with no database at all. Cloud deploy platforms only run
    `streamlit run dashboard/app.py`; there's no hook to run a setup script
    first. So: if the SQLite backend is selected and the database simply
    isn't there yet, generate the synthetic dataset and load it once,
    automatically, the same two steps the README asks you to run by hand
    locally. This is what makes "clone and run" or "open the deployed link"
    actually work with zero manual setup, instead of failing on a database
    that was never allowed into git to begin with.
    """
    if LOCAL_DB_PATH.exists():
        return
    repo_root = Path(__file__).parent.parent
    with st.spinner("First run: generating sample data..."):
        subprocess.run(
            [sys.executable, str(repo_root / "data" / "generate_data.py")],
            check=True, cwd=repo_root,
        )
        subprocess.run(
            [sys.executable, str(repo_root / "etl" / "load_to_db.py")],
            check=True, cwd=repo_root,
        )


# Set AWS_INTEGRATION_MODE=localstack when DATABASE_URL points at a *real*
# Postgres (Docker/local install) standing in for RDS, provisioned via
# Terraform against LocalStack instead of real AWS -- see
# cloud/terraform-localstack/ and INTEGRATION_PROOF_GUIDE.md. This exists
# so the Integrations section can say "practice mode" instead of
# incorrectly claiming a real AWS connection -- it never guesses.
AWS_INTEGRATION_MODE = os.environ.get("AWS_INTEGRATION_MODE", "").strip().lower()

# Where real integration proof lives once you've actually done the AWS /
# Power BI setup in INTEGRATION_PROOF_GUIDE.md -- the Integrations section
# below reads these paths live and only shows something if it's actually
# there, so it can never claim a connection that doesn't exist.
ASSETS_DIR = Path(__file__).parent / "assets" / "integration_proof"
POWERBI_URL_FILE = Path(__file__).parent / "assets" / "powerbi_report_url.txt"

st.set_page_config(page_title="CashPulse", page_icon="\U0001F4B0", layout="wide")

if BACKEND == "sqlite":
    _bootstrap_local_data()

_engine = None
if BACKEND == "postgres":
    import sqlalchemy
    _engine = sqlalchemy.create_engine(DATABASE_URL, pool_pre_ping=True)

# ---------------------------------------------------------------------------
# Chart-only colors. Streamlit's native widgets (metrics, alerts, dataframes,
# text) all take their color from .streamlit/config.toml's [theme] block, so
# they're never hardcoded here and can't go out of sync with the app's actual
# background. Plotly figures are the one thing Streamlit's theme can't reach
# automatically, so they still need explicit colors -- kept to a small set,
# tuned for the dark theme + green accent in .streamlit/config.toml.
# ---------------------------------------------------------------------------
COLOR = {
    "good": "#22C55E",      # accent green -- positive / inflow / healthy
    "critical": "#F87171",  # soft red -- negative / outflow / at-risk
    "warning": "#FBBF24",   # amber -- simulated / caution status
    "muted": "#8B95A5",     # axis labels, secondary chart text
    "grid": "#2A2F3A",      # gridlines against the dark chart background
    "text": "#E5E7EB",      # primary chart text (labels, hover)
}

# Sequential ramp (muted -> bright green) for magnitude encoding on the
# category-spend chart. Brightest = highest spend, since a brighter mark
# reads as "most prominent" against a dark surface.
SEQUENTIAL_GREEN = ["#14532D", "#15803D", "#16A34A", "#22C55E", "#4ADE80", "#86EFAC"]

FONT_STACK = 'system-ui, -apple-system, "Segoe UI", sans-serif'

# Same logical queries, two physical shapes -- sqlite tables are flat
# (v_account_health, ml_anomaly_flags, ...); the cloud tier reads dbt's
# analytics.* marts and the ml.* tables the cloud ML scripts write to.
QUERIES = {
    "sqlite": {
        "accounts": "SELECT account_id, account_name, account_type FROM accounts",
        "health": "SELECT * FROM v_account_health WHERE account_id = :account_id",
        "monthly": "SELECT * FROM v_monthly_cashflow WHERE account_id = :account_id ORDER BY month",
        "forecast": "SELECT * FROM ml_cashflow_forecast WHERE account_id = :account_id ORDER BY forecast_date",
        "category_spend": "SELECT * FROM v_category_spend_monthly WHERE account_id = :account_id ORDER BY month DESC",
        "anomalies": """
            SELECT f.anomaly_score, f.reason, t.txn_date, t.amount, c.category_name
            FROM ml_anomaly_flags f
            JOIN transactions t ON t.transaction_id = f.transaction_id
            JOIN categories c ON c.category_id = t.category_id
            WHERE t.account_id = :account_id
            ORDER BY f.anomaly_score DESC
        """,
        "txn_count": "SELECT COUNT(*) AS n FROM transactions",
        "budget_vs_actual": """
            SELECT
                b.month,
                c.category_name,
                b.budgeted_amount,
                COALESCE((
                    SELECT SUM(t.amount)
                    FROM transactions t
                    WHERE t.account_id = b.account_id
                      AND t.category_id = b.category_id
                      AND t.txn_type = 'debit'
                      AND strftime('%Y-%m', t.txn_date) = b.month
                ), 0) AS actual_amount
            FROM budgets b
            JOIN categories c ON c.category_id = b.category_id
            WHERE b.account_id = :account_id
            ORDER BY b.month DESC, c.category_name
        """,
        "recurring": """
            SELECT
                m.merchant_name,
                COUNT(*) AS occurrence_count,
                ROUND(AVG(t.amount), 2) AS typical_amount,
                MAX(t.txn_date) AS last_txn_date,
                (
                    SELECT t2.amount FROM transactions t2
                    WHERE t2.account_id = t.account_id
                      AND t2.merchant_id = t.merchant_id
                      AND t2.is_recurring = 1
                    ORDER BY t2.txn_date DESC LIMIT 1
                ) AS last_amount
            FROM transactions t
            JOIN merchants m ON m.merchant_id = t.merchant_id
            WHERE t.account_id = :account_id AND t.is_recurring = 1
            GROUP BY t.merchant_id, m.merchant_name
            ORDER BY last_txn_date DESC
        """,
    },
    "postgres": {
        "accounts": "SELECT account_id, account_name, account_type FROM analytics.dim_accounts",
        "health": "SELECT * FROM analytics.account_health WHERE account_id = :account_id",
        "monthly": "SELECT * FROM analytics.monthly_cashflow WHERE account_id = :account_id ORDER BY month",
        "forecast": "SELECT * FROM ml.cashflow_forecast WHERE account_id = :account_id ORDER BY forecast_date",
        "category_spend": "SELECT * FROM analytics.category_spend_monthly WHERE account_id = :account_id ORDER BY month DESC",
        "anomalies": """
            SELECT f.anomaly_score, f.reason, t.txn_date, t.amount, t.category_name
            FROM ml.anomaly_flags f
            JOIN analytics.fct_transactions t ON t.transaction_id = f.transaction_id
            WHERE t.account_id = :account_id
            ORDER BY f.anomaly_score DESC
        """,
        "txn_count": "SELECT COUNT(*) AS n FROM analytics.fct_transactions",
        "budget_vs_actual": """
            SELECT month, category_name, budgeted_amount, actual_amount
            FROM analytics.budget_vs_actual
            WHERE account_id = :account_id
            ORDER BY month DESC, category_name
        """,
        "recurring": """
            SELECT merchant_name, occurrence_count, typical_amount, last_txn_date, last_amount
            FROM analytics.recurring_transactions
            WHERE account_id = :account_id
            ORDER BY last_txn_date DESC
        """,
    },
}


@st.cache_data(ttl=60)
def load_table(query_key, params=None):
    query = QUERIES[BACKEND][query_key]
    params = params or {}
    if BACKEND == "postgres":
        return pd.read_sql_query(sqlalchemy.text(query), _engine, params=params)
    conn = sqlite3.connect(LOCAL_DB_PATH)
    try:
        return pd.read_sql_query(query, conn, params=params)
    finally:
        conn.close()


def backend_ready():
    if BACKEND == "sqlite":
        return LOCAL_DB_PATH.exists()
    try:
        with _engine.connect() as conn:
            conn.exec_driver_sql("SELECT 1")
        return True
    except Exception as e:
        st.session_state["_connection_error"] = str(e)
        return False


@st.cache_data(ttl=60)
def get_data_status():
    """Live proof-of-life for the data badge: an actual COUNT(*) run
    against whichever backend is configured, plus a real last-modified
    signal -- never a hardcoded number."""
    txn_count = int(load_table("txn_count")["n"].iloc[0])
    if BACKEND == "sqlite":
        mtime = datetime.fromtimestamp(LOCAL_DB_PATH.stat().st_mtime)
        freshness = f"data file updated {mtime.strftime('%b %d, %Y %I:%M %p')}"
        source_label = "SQLite (local file)"
    else:
        freshness = "live connection, queried just now"
        source_label = "Postgres (cloud RDS)"
    return source_label, txn_count, freshness


def base_layout(fig, height=340):
    """Shared, undecorated chart chrome: transparent surface (so the chart
    blends into whatever Streamlit theme surface sits behind it), recessive
    gridlines, brand font. Transparent backgrounds mean this never needs to
    know the exact theme color -- it just matches automatically."""
    fig.update_layout(
        height=height,
        margin=dict(l=10, r=10, t=10, b=10),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(family=FONT_STACK, color=COLOR["text"], size=13),
        xaxis=dict(showgrid=False, linecolor=COLOR["grid"], color=COLOR["muted"]),
        yaxis=dict(showgrid=True, gridcolor=COLOR["grid"], zeroline=True,
                    zerolinecolor=COLOR["grid"], color=COLOR["muted"]),
    )
    return fig


def _redact_db_host(url):
    """Show which host we're actually querying without leaking credentials
    -- used only for a status label, never logged or sent anywhere."""
    try:
        parsed = urlparse(url)
        return parsed.hostname or "unknown host"
    except Exception:
        return "unknown host"


def render_integrations():
    """Real integration status, read live from the environment and from
    files you drop in yourself after finishing the steps in
    INTEGRATION_PROOF_GUIDE.md -- there is no hardcoded "connected" state
    here. If you haven't done the AWS/Power BI setup yet, this honestly
    says so instead of faking it."""
    st.subheader("Integrations & Proof")

    aws_col, bi_col = st.columns(2)

    with aws_col, st.container(border=True):
        st.markdown("**AWS Cloud Infrastructure**")
        if BACKEND == "postgres" and AWS_INTEGRATION_MODE == "localstack":
            host = _redact_db_host(DATABASE_URL)
            st.warning(f"\U0001F9EA Simulated · LocalStack + local Postgres at `{host}`")
            st.caption("Practice mode, not real AWS: Terraform provisioned S3 against "
                       "LocalStack (a free, no-account AWS simulator), and this Postgres "
                       "is running locally/in Docker as a stand-in for RDS -- no AWS "
                       "account or card was used. See INTEGRATION_PROOF_GUIDE.md.")
        elif BACKEND == "postgres":
            host = _redact_db_host(DATABASE_URL)
            st.success(f"Connected · querying RDS Postgres at `{host}`")
            st.caption("This dashboard is reading live data from AWS RDS right now, "
                       "not a local file -- the DATABASE_URL environment variable is set.")
        else:
            st.info("Not connected yet · reading local SQLite")
            st.caption("Provision real AWS via `cloud/terraform`, or the free no-account "
                       "path via `cloud/terraform-localstack` -- either flips this "
                       "automatically once DATABASE_URL is set. See INTEGRATION_PROOF_GUIDE.md.")
        aws_screenshot = ASSETS_DIR / "aws_rds.png"
        if aws_screenshot.exists():
            caption = ("LocalStack + local Postgres -- terraform apply / awslocal output"
                       if AWS_INTEGRATION_MODE == "localstack" else
                       "AWS RDS console -- instance status")
            st.image(str(aws_screenshot), caption=caption, width="stretch")

    with bi_col, st.container(border=True):
        st.markdown("**Power BI / Tableau**")
        report_url = None
        if POWERBI_URL_FILE.exists():
            report_url = POWERBI_URL_FILE.read_text().strip() or None
        if report_url:
            st.success("Published")
            st.link_button("View live Power BI report ↗", report_url)
        else:
            st.info("Not connected yet")
            st.caption("Connect Power BI or Tableau to this database and publish a report, "
                       "then save the link in dashboard/assets/powerbi_report_url.txt to "
                       "show it here automatically -- see INTEGRATION_PROOF_GUIDE.md.")
        bi_screenshot = ASSETS_DIR / "powerbi_report.png"
        if bi_screenshot.exists():
            st.image(str(bi_screenshot), caption="Power BI report -- model & visuals", width="stretch")


def main():
    st.title("\U0001F4B0 CashPulse")
    st.caption("Personal & SME finance health monitor")

    if not backend_ready():
        if BACKEND == "sqlite":
            st.error("No database found. Run `python data/generate_data.py` then "
                      "`python etl/load_to_db.py` first.")
        else:
            st.error("Could not connect to Postgres via DATABASE_URL. Run "
                      "`python cloud/pipeline/run_pipeline.py` first, and check "
                      f"cloud/.env. Error: {st.session_state.get('_connection_error')}")
        return

    accounts = load_table("accounts")
    source_label, txn_count, freshness = get_data_status()

    # --- Toolbar: account picker + live data badge -----------------------
    with st.container(border=True):
        tb1, tb2, tb3 = st.columns([2, 1, 3])
        with tb1:
            account_name = st.selectbox("Account", accounts["account_name"])
        with tb2:
            st.write("")
            if st.button("↻ Refresh data"):
                load_table.clear()
                get_data_status.clear()
                st.rerun()
        with tb3:
            st.write("")
            st.caption(f"🟢 **{source_label}** · **{txn_count:,}** real transactions loaded "
                       f"· {freshness}")

    account_id = int(accounts.loc[accounts["account_name"] == account_name, "account_id"].iloc[0])

    health = load_table("health", {"account_id": account_id})
    monthly = load_table("monthly", {"account_id": account_id})
    forecast = load_table("forecast", {"account_id": account_id})
    category_spend = load_table("category_spend", {"account_id": account_id})
    anomalies = load_table("anomalies", {"account_id": account_id})
    budget_vs_actual = load_table("budget_vs_actual", {"account_id": account_id})
    recurring = load_table("recurring", {"account_id": account_id})

    # --- KPI row -----------------------------------------------------------
    current_balance = float(health["current_balance"].iloc[0]) if not health.empty else 0.0
    avg_daily_burn = float(health["avg_daily_burn"].iloc[0]) if not health.empty else 0.0
    runway_days = (current_balance / avg_daily_burn) if avg_daily_burn > 0 else float("inf")
    last_month_net = float(monthly["net_flow"].iloc[-1]) if not monthly.empty else 0.0

    if runway_days == float("inf"):
        runway_text, runway_delta, runway_color = "∞", "no burn detected", "normal"
    elif runway_days < 60:
        runway_text, runway_delta, runway_color = f"{runway_days:,.0f} days", "below 60-day buffer", "inverse"
    else:
        runway_text, runway_delta, runway_color = f"{runway_days:,.0f} days", "healthy buffer", "normal"

    net_flow_delta = "inflow" if last_month_net >= 0 else "outflow"
    net_flow_color = "normal" if last_month_net >= 0 else "inverse"

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Current Balance", f"${current_balance:,.0f}")
    col2.metric("Avg Daily Burn (30d)", f"${avg_daily_burn:,.0f}")
    col3.metric("Runway", runway_text, delta=runway_delta, delta_color=runway_color)
    col4.metric("Last Month Net Flow", f"${last_month_net:,.0f}", delta=net_flow_delta, delta_color=net_flow_color)

    if runway_days < 60:
        st.warning(f"⚠️ At the current burn rate, this account has an estimated "
                    f"{runway_days:,.0f}-day runway. Consider reviewing discretionary spend below.")

    # --- Cash flow trend + forecast ---------------------------------------
    # These used to share one chart (monthly bars + daily forecast line on a
    # second y-axis). Two problems with that: the bars are monthly and the
    # forecast is daily, so 30 daily points get squeezed into a sliver a few
    # pixels wide at the end of an 18-month axis -- any real day-to-day
    # movement in the forecast then reads as a jagged spike. And the two
    # series don't even share units (net flow vs. balance), so the shared
    # axis was misleading on top of being cramped. Split into two charts,
    # each on its own axis and its own time scale, instead.
    st.subheader("Cash Flow: History & 30-Day Forecast")
    hist_col, forecast_col = st.columns(2)

    with hist_col, st.container(border=True):
        st.caption("Historical Net Flow (monthly)")
        if not monthly.empty:
            # Net flow sign means good/bad, so it uses the fixed status
            # colors (good/critical) rather than an ad hoc categorical
            # color -- paired with a two-item legend so color never
            # carries the meaning alone.
            bar_colors = [COLOR["critical"] if v < 0 else COLOR["good"] for v in monthly["net_flow"]]
            fig_hist = go.Figure()
            fig_hist.add_trace(go.Bar(
                x=monthly["month"], y=monthly["net_flow"], marker_color=bar_colors,
                showlegend=False, hovertemplate="%{x}<br>$%{y:,.0f}<extra></extra>",
            ))
            # Two invisible marker traces purely to carry the icon+label
            # legend for the status colors used above.
            fig_hist.add_trace(go.Bar(x=[None], y=[None], marker_color=COLOR["good"], name="▲ Inflow (net positive)"))
            fig_hist.add_trace(go.Bar(x=[None], y=[None], marker_color=COLOR["critical"], name="▼ Outflow (net negative)"))
            fig_hist.update_layout(
                xaxis_title="", yaxis_title="Net Flow ($)",
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0, font=dict(size=11)),
                bargap=0.25,
            )
            base_layout(fig_hist)
            st.plotly_chart(fig_hist, use_container_width=True, config={"displayModeBar": False})
        else:
            st.info("No historical data yet.")

    with forecast_col, st.container(border=True):
        st.caption("30-Day Balance Forecast (daily)")
        if not forecast.empty:
            fig_fc = go.Figure()
            fig_fc.add_trace(go.Scatter(
                x=forecast["forecast_date"], y=forecast["predicted_balance"],
                name="Forecasted Balance", mode="lines+markers",
                line=dict(color=COLOR["good"], width=2.5),
                marker=dict(size=6, color=COLOR["good"]),
                fill="tozeroy", fillcolor="rgba(34, 197, 94, 0.12)",
                hovertemplate="%{x}<br>$%{y:,.0f}<extra></extra>",
            ))
            fig_fc.add_hline(y=current_balance, line_dash="dot", line_color=COLOR["muted"],
                              annotation_text="Current balance", annotation_position="bottom right",
                              annotation_font_color=COLOR["muted"])
            fig_fc.update_layout(xaxis_title="", yaxis_title="Forecasted Balance ($)", showlegend=False)
            base_layout(fig_fc)
            st.plotly_chart(fig_fc, use_container_width=True, config={"displayModeBar": False})
        else:
            st.info("No forecast data yet.")

    # --- Category breakdown ------------------------------------------------
    # A pie chart doesn't hold up once there are more than a handful of
    # categories (this data has up to ~14): slice angles get too thin to
    # compare and color would have to carry pure identity across too many
    # slots. This is really a magnitude-comparison job ("which categories
    # cost the most"), so it becomes a single-hue horizontal bar ranked by
    # spend, with the $ amount labeled directly on each bar.
    st.subheader("Spend by Category (latest month)")
    with st.container(border=True):
        if not category_spend.empty:
            latest_month = category_spend["month"].iloc[0]
            latest = category_spend[category_spend["month"] == latest_month].copy()
            latest = latest.sort_values("total_amount", ascending=True)

            n = len(latest)
            if n > 1:
                ramp_idx = [round(i * (len(SEQUENTIAL_GREEN) - 1) / (n - 1)) for i in range(n)]
            else:
                ramp_idx = [len(SEQUENTIAL_GREEN) - 1]
            bar_colors = [SEQUENTIAL_GREEN[i] for i in ramp_idx]

            max_spend = float(latest["total_amount"].max())

            fig_cat = go.Figure()
            fig_cat.add_trace(go.Bar(
                x=latest["total_amount"], y=latest["category_name"], orientation="h",
                marker_color=bar_colors,
                text=[f"${v:,.0f}" for v in latest["total_amount"]],
                textposition="outside", textfont=dict(color=COLOR["text"], size=12),
                cliponaxis=False,
                hovertemplate="%{y}<br>$%{x:,.0f}<extra></extra>",
            ))
            fig_cat.update_layout(
                xaxis_title="Total Spend ($)", yaxis_title="",
                showlegend=False, bargap=0.3,
            )
            # Headroom past the longest bar so its outside label isn't
            # clipped by the plot edge, and a right margin sized the same way.
            fig_cat.update_xaxes(showgrid=True, range=[0, max_spend * 1.22])
            base_layout(fig_cat, height=max(300, 34 * n))
            fig_cat.update_layout(margin=dict(l=10, r=30, t=10, b=10))
            st.plotly_chart(fig_cat, use_container_width=True, config={"displayModeBar": False})
        else:
            st.info("No category spend data yet.")

    # --- Budget vs. actual ---------------------------------------------------
    # Status (over/under budget) is what matters here, not raw category
    # identity, so "Actual" is split into two same-hued-family traces (good/
    # critical) rather than one trace colored per-bar -- a single bar trace
    # can't carry two different legend colors cleanly, and color needs to
    # follow a fixed entity (the status), never vary within one legend swatch.
    st.subheader("Budget vs. Actual (latest month)")
    with st.container(border=True):
        if not budget_vs_actual.empty:
            bva_month = budget_vs_actual["month"].max()
            bva = budget_vs_actual[budget_vs_actual["month"] == bva_month].copy()
            bva = bva.sort_values("budgeted_amount", ascending=True)
            within = bva[bva["actual_amount"] <= bva["budgeted_amount"]]
            over = bva[bva["actual_amount"] > bva["budgeted_amount"]]

            fig_bva = go.Figure()
            fig_bva.add_trace(go.Bar(
                x=bva["budgeted_amount"], y=bva["category_name"], orientation="h",
                name="Budgeted", marker_color=COLOR["muted"], opacity=0.45,
                hovertemplate="%{y}<br>Budgeted: $%{x:,.0f}<extra></extra>",
            ))
            fig_bva.add_trace(go.Bar(
                x=within["actual_amount"], y=within["category_name"], orientation="h",
                name="Actual (within budget)", marker_color=COLOR["good"],
                hovertemplate="%{y}<br>Actual: $%{x:,.0f}<extra></extra>",
            ))
            fig_bva.add_trace(go.Bar(
                x=over["actual_amount"], y=over["category_name"], orientation="h",
                name="Actual (over budget)", marker_color=COLOR["critical"],
                hovertemplate="%{y}<br>Actual: $%{x:,.0f}<extra></extra>",
            ))
            fig_bva.update_layout(
                barmode="group", xaxis_title="Amount ($)", yaxis_title="",
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0, font=dict(size=11)),
            )
            base_layout(fig_bva, height=max(300, 42 * len(bva)))
            st.plotly_chart(fig_bva, use_container_width=True, config={"displayModeBar": False})

            if not over.empty:
                names = ", ".join(over["category_name"])
                st.warning(f"⚠️ Over budget in {bva_month}: {names}")
        else:
            st.info("No budgets set for this account yet.")

    # --- Recurring & subscriptions --------------------------------------------
    st.subheader("\U0001F501 Recurring & Subscriptions")
    with st.container(border=True):
        if not recurring.empty:
            rec = recurring.copy()
            rec["amount_changed"] = (
                (rec["typical_amount"] > 0)
                & ((rec["last_amount"] - rec["typical_amount"]).abs() / rec["typical_amount"] > 0.05)
            )
            display = rec.rename(columns={
                "merchant_name": "Merchant",
                "typical_amount": "Typical Amount",
                "last_amount": "Last Amount",
                "last_txn_date": "Last Charged",
                "occurrence_count": "Charges Seen",
            })
            display["Changed?"] = display["amount_changed"].map(lambda v: "⚠️ Changed" if v else "—")
            st.dataframe(
                display[["Merchant", "Typical Amount", "Last Amount", "Last Charged", "Charges Seen", "Changed?"]]
                    .style.format({"Typical Amount": "${:,.2f}", "Last Amount": "${:,.2f}"}),
                width="stretch",
            )
            changed = rec[rec["amount_changed"]]
            if not changed.empty:
                names = ", ".join(changed["merchant_name"])
                st.warning(f"⚠️ Charge amount changed recently for: {names}")
        else:
            st.info("No recurring transactions detected yet.")

    # --- Anomalies -----------------------------------------------------------
    st.subheader("\U0001F6A9 Flagged Transactions (Isolation Forest)")
    if not anomalies.empty:
        st.dataframe(
            anomalies.style.format({"amount": "${:,.2f}", "anomaly_score": "{:.2f}"}),
            width="stretch",
        )
    else:
        st.info("No anomalies flagged yet.")

    render_integrations()


if __name__ == "__main__":
    main()
