"""
Unit tests for the local (SQLite-tier) ML scripts: ml/detect_anomalies.py
and ml/forecast_cashflow.py.

These mirror cloud/pipeline/test_pipeline.py's tests for the cloud-tier
equivalents (ml_anomaly.py / ml_forecast.py) -- until this file, the local
tier's ML logic had zero test coverage of its own, even though it's the
tier that's actually deployed and used at
https://finance-health-monitor.streamlit.app/. dbt tests only ever look
at the Postgres/cloud tier, so they were never going to catch a regression
here.

Run:
    pytest -v          (pure unit tests, no database needed)
"""

import numpy as np
import pandas as pd
import pytest

import detect_anomalies
import forecast_cashflow


# --------------------------------------------------------------------------
# detect_anomalies.engineer_features
# --------------------------------------------------------------------------

def test_engineer_features_adds_expected_columns():
    df = pd.DataFrame({
        "transaction_id": [1, 2, 3, 4],
        "account_id": [1, 1, 1, 1],
        "category_name": ["Groceries", "Groceries", "Dining Out", "Dining Out"],
        "txn_date": pd.to_datetime(["2026-01-01", "2026-01-01", "2026-01-02", "2026-01-03"]),
        "amount": [50.0, 55.0, 400.0, 12.0],
        "txn_type": ["debit"] * 4,
    })
    out, features = detect_anomalies.engineer_features(df)

    assert "amount_zscore_in_category" in out.columns
    assert "txns_same_day" in out.columns
    # the two same-day Groceries transactions should both show txns_same_day == 2
    same_day = out.loc[out["category_name"] == "Groceries", "txns_same_day"]
    assert (same_day == 2).all()
    assert not features.isnull().values.any()


def test_engineer_features_flags_the_obvious_outlier():
    # nine normal $50 charges and one $5,000 charge in the same category --
    # the isolation forest downstream should have an easy time with this.
    df = pd.DataFrame({
        "transaction_id": range(10),
        "account_id": [1] * 10,
        "category_name": ["Shopping"] * 10,
        "txn_date": pd.date_range("2026-01-01", periods=10),
        "amount": [50.0] * 9 + [5000.0],
        "txn_type": ["debit"] * 10,
    })
    out, _ = detect_anomalies.engineer_features(df)
    zscores = out["amount_zscore_in_category"]
    assert zscores.iloc[-1] == zscores.max()
    assert zscores.iloc[-1] > 2  # the $5,000 charge should be several std devs out


def test_engineer_features_handles_single_transaction_category_without_nan_std():
    # A category with exactly one transaction has an undefined (NaN) std
    # dev -- engineer_features() falls back to the whole dataset's std for
    # that case. This used to be an easy way to silently produce a NaN
    # feature that the model would then choke on.
    df = pd.DataFrame({
        "transaction_id": [1, 2, 3],
        "account_id": [1, 1, 1],
        "category_name": ["Rare Category", "Common", "Common"],
        "txn_date": pd.date_range("2026-01-01", periods=3),
        "amount": [75.0, 20.0, 22.0],
        "txn_type": ["debit"] * 3,
    })
    _, features = detect_anomalies.engineer_features(df)
    assert not features.isnull().values.any()


# --------------------------------------------------------------------------
# forecast_cashflow.make_features / train_and_backtest
# --------------------------------------------------------------------------

def test_make_features_produces_lag_columns_without_leaking_nans():
    daily = pd.DataFrame({
        "txn_date": pd.date_range("2026-01-01", periods=30),
        "net_flow": np.random.default_rng(42).normal(0, 100, size=30),
    })
    featured = forecast_cashflow.make_features(daily)

    for lag in range(1, forecast_cashflow.N_LAGS + 1):
        assert f"lag_{lag}" in featured.columns
    assert not featured.isnull().values.any()
    # first N_LAGS rows get dropped because they can't have a full lag window
    assert len(featured) == len(daily) - forecast_cashflow.N_LAGS


def test_train_and_backtest_beats_or_reports_against_baseline():
    rng = np.random.default_rng(7)
    daily = pd.DataFrame({
        "txn_date": pd.date_range("2026-01-01", periods=120),
        "net_flow": rng.normal(0, 150, size=120),
    })
    featured = forecast_cashflow.make_features(daily)
    model, metrics, feature_cols = forecast_cashflow.train_and_backtest(featured)

    assert model is not None
    assert "mae_model" in metrics and "mae_baseline" in metrics
    assert metrics["mae_model"] >= 0


def test_train_and_backtest_returns_none_when_history_too_short():
    # Fewer than 30 rows in the training split should be reported as "not
    # enough data" rather than silently fitting a useless model on a
    # handful of points -- forecast_cashflow.main() relies on this None to
    # decide whether to skip an account.
    daily = pd.DataFrame({
        "txn_date": pd.date_range("2026-01-01", periods=10),
        "net_flow": np.random.default_rng(1).normal(0, 50, size=10),
    })
    featured = forecast_cashflow.make_features(daily)
    model, metrics, feature_cols = forecast_cashflow.train_and_backtest(featured)
    assert model is None
    assert metrics is None


def test_forecast_forward_produces_requested_horizon_and_running_balance():
    rng = np.random.default_rng(3)
    daily = pd.DataFrame({
        "txn_date": pd.date_range("2026-01-01", periods=60),
        "net_flow": rng.normal(0, 50, size=60),
    })
    featured = forecast_cashflow.make_features(daily)
    model, _, feature_cols = forecast_cashflow.train_and_backtest(featured)
    model.fit(featured[feature_cols], featured["net_flow"])

    horizon = 30
    starting_balance = 1000.0
    results = forecast_cashflow.forecast_forward(model, featured, feature_cols, horizon, starting_balance)

    assert len(results) == horizon
    dates = [r[0] for r in results]
    assert len(set(dates)) == horizon  # every forecast date is distinct
    # running balance is starting_balance plus the cumulative predicted net flow
    predicted_flows = [r[1] for r in results]
    final_balance = results[-1][2]
    assert final_balance == pytest.approx(starting_balance + sum(predicted_flows))
