"""
Unit + light integration tests for the pipeline task functions.

Run standalone (unit tests only, no DB needed):
    pytest -v -k "not integration"

Run the full suite (needs DATABASE_URL pointed at a Postgres with dbt
already applied -- exactly the state the CI workflow and run_pipeline.py
leave it in):
    pytest -v
"""

import os

import numpy as np
import pandas as pd
import pytest

import ml_anomaly
import ml_forecast


# --------------------------------------------------------------------------
# Unit tests: pure functions, no database needed
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
    out, features = ml_anomaly.engineer_features(df)

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
    out, _ = ml_anomaly.engineer_features(df)
    zscores = out["amount_zscore_in_category"]
    assert zscores.iloc[-1] == zscores.max()
    assert zscores.iloc[-1] > 2  # the $5,000 charge should be several std devs out


def test_make_features_produces_lag_columns_without_leaking_nans():
    daily = pd.DataFrame({
        "txn_date": pd.date_range("2026-01-01", periods=30),
        "net_flow": np.random.default_rng(42).normal(0, 100, size=30),
    })
    featured = ml_forecast.make_features(daily)

    for lag in range(1, ml_forecast.N_LAGS + 1):
        assert f"lag_{lag}" in featured.columns
    assert not featured.isnull().values.any()
    # first N_LAGS rows get dropped because they can't have a full lag window
    assert len(featured) == len(daily) - ml_forecast.N_LAGS


def test_train_and_backtest_beats_or_reports_against_baseline():
    rng = np.random.default_rng(7)
    daily = pd.DataFrame({
        "txn_date": pd.date_range("2026-01-01", periods=120),
        "net_flow": rng.normal(0, 150, size=120),
    })
    featured = ml_forecast.make_features(daily)
    model, metrics, feature_cols = ml_forecast.train_and_backtest(featured)

    assert model is not None
    assert "mae_model" in metrics and "mae_baseline" in metrics
    assert metrics["mae_model"] >= 0


# --------------------------------------------------------------------------
# Integration test: only runs if DATABASE_URL is set and dbt has been applied
# --------------------------------------------------------------------------

@pytest.mark.skipif("DATABASE_URL" not in os.environ, reason="needs a live Postgres with dbt models applied")
def test_marts_have_data():
    from db import get_engine
    engine = get_engine()
    with engine.connect() as conn:
        count = conn.exec_driver_sql("SELECT COUNT(*) FROM analytics.fct_transactions").scalar()
    assert count > 0
