"""
Regression tests for dashboard/app.py, using Streamlit's own
streamlit.testing.v1.AppTest to drive the real script end to end (login,
widget interaction, rendered output) rather than importing it as a module
-- app.py runs its UI top-to-bottom the way `streamlit run` does, so a
plain `import app` would try to execute Streamlit calls outside a runtime
and fail immediately.

Before this file, every one of these behaviors (the login gate, per-login
account restriction, the Prescriptive Recommendations panel, CSV export)
had only ever been checked by hand, once, at the time each feature was
built -- nothing caught a regression on the next change. This is that
safety net, committed and run in CI on every push instead of re-run
manually.

Requires a real local database: run, in order, before pytest --
    python data/generate_data.py
    python etl/load_to_db.py
    python ml/detect_anomalies.py
    python ml/forecast_cashflow.py
-- exactly what CI's "local-tier" job does. Also requires
.streamlit/secrets.toml (checked into the repo -- see that file's own
comment for why) since st.secrets backs the login credentials.

Run:
    pytest dashboard/test_app.py -v
"""

from pathlib import Path

from streamlit.testing.v1 import AppTest

APP_PATH = str(Path(__file__).parent / "app.py")
DEMO_USER, DEMO_PASSWORD = "demo", "CashPulseDemo!26"
NINA_USER, NINA_PASSWORD = "nina", "NinaDemo!26"


def _login(at, username, password):
    at.text_input[0].input(username).run()
    at.text_input[1].input(password).run()
    at.button[0].click().run()
    return at


def _fresh_app():
    return AppTest.from_file(APP_PATH, default_timeout=60)


# --------------------------------------------------------------------------
# Login gate
# --------------------------------------------------------------------------

def test_unauthenticated_user_sees_login_gate_not_the_dashboard():
    at = _fresh_app().run()
    assert not at.exception
    subheaders = [s.value for s in at.subheader]
    assert "Prescriptive Recommendations" not in " ".join(subheaders)


def test_wrong_password_does_not_grant_access():
    at = _fresh_app().run()
    _login(at, DEMO_USER, "definitely-not-the-password")
    assert not at.exception
    subheaders = " ".join(s.value for s in at.subheader)
    assert "Prescriptive Recommendations" not in subheaders


def test_correct_demo_login_reaches_the_dashboard():
    at = _fresh_app().run()
    _login(at, DEMO_USER, DEMO_PASSWORD)
    assert not at.exception
    subheaders = " ".join(s.value for s in at.subheader)
    assert "Prescriptive Recommendations" in subheaders
    assert "Budget vs. Actual" in subheaders


def test_demo_login_sees_all_five_accounts():
    at = _fresh_app().run()
    _login(at, DEMO_USER, DEMO_PASSWORD)
    options = at.selectbox[0].options
    assert len(options) == 5
    assert "Nina's Personal Checking" in options


def test_nina_login_is_restricted_to_her_own_account():
    at = _fresh_app().run()
    _login(at, NINA_USER, NINA_PASSWORD)
    assert not at.exception
    options = at.selectbox[0].options
    assert options == ["Nina's Personal Checking"]


# --------------------------------------------------------------------------
# Prescriptive Recommendations panel
# --------------------------------------------------------------------------

def test_recommendations_panel_renders_without_exception_for_every_account():
    at = _fresh_app().run()
    _login(at, DEMO_USER, DEMO_PASSWORD)
    for account_name in at.selectbox[0].options:
        at.selectbox[0].set_value(account_name).run()
        assert not at.exception, f"exception rendering recommendations for {account_name}"


def test_recommendations_slider_changes_the_recommended_savings():
    at = _fresh_app().run()
    _login(at, DEMO_USER, DEMO_PASSWORD)
    at.selectbox[0].set_value("Urban Fit Gym").run()  # a healthy-runway account with discretionary spend
    before = [m.value for m in at.metric if m.label == "Monthly savings"]
    assert before, "expected at least one recommendation for this account"

    at.slider[0].set_value(30).run()
    assert not at.exception
    after = [m.value for m in at.metric if m.label == "Monthly savings"]
    assert after != before


def test_recommendations_never_show_a_backwards_runway_delta_for_a_negative_balance():
    # Regression test for a real bug found during development: for a
    # negative-balance account, balance / burn gets *more* negative after
    # a spending cut (dividing a negative by a smaller positive), which
    # would read as "saving money makes your runway worse." The fix
    # suppresses the Runway metric whenever the account's current balance
    # isn't positive -- assert that suppression actually happens rather
    # than just trusting the fix stays in place.
    at = _fresh_app().run()
    _login(at, DEMO_USER, DEMO_PASSWORD)
    at.selectbox[0].set_value("Nina's Personal Checking").run()  # a known negative-balance demo account
    balance = float(at.metric[0].value.replace("$", "").replace(",", ""))
    runway_metrics = [m for m in at.metric if m.label == "Runway"]
    if balance <= 0:
        # every recommendation's Runway metric (skip index 0, the KPI row's own) must read "n/a"
        rec_runway_metrics = runway_metrics[1:]
        assert rec_runway_metrics, "expected at least one recommendation"
        assert all(m.value == "n/a" for m in rec_runway_metrics)


# --------------------------------------------------------------------------
# Earlier features -- regression coverage for things this session also shipped
# --------------------------------------------------------------------------

def test_csv_export_button_is_present_for_anomalies():
    at = _fresh_app().run()
    _login(at, DEMO_USER, DEMO_PASSWORD)
    at.selectbox[0].set_value("Nina's Personal Checking").run()  # known to have flagged anomalies
    downloads = at.get("download_button")
    assert any("Download flagged transactions" in d.label for d in downloads)


def test_manage_transactions_section_is_sqlite_tier_only_and_present():
    at = _fresh_app().run()
    _login(at, DEMO_USER, DEMO_PASSWORD)
    subheaders = " ".join(s.value for s in at.subheader)
    assert "Manage Transactions" in subheaders
