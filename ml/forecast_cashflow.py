"""
CashPulse - cash-flow forecasting.

For each account, aggregates daily net cash flow, builds lag + calendar
features, trains a small gradient-boosted regressor, and forecasts the
next 30 days of net flow and running balance. Also computes a naive
seasonal baseline (same weekday last week) so you can report a lift over
baseline -- reviewers/interviewers will ask "compared to what?" and this
answers it.

Run (after etl/load_to_db.py):
    python ml/forecast_cashflow.py
"""

import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.metrics import mean_absolute_error

DB_PATH = Path(__file__).parent.parent / "data" / "finance.db"
FORECAST_HORIZON_DAYS = 30
N_LAGS = 7


def load_daily_net_flow(conn, account_id):
    query = """
        SELECT txn_date,
               SUM(CASE WHEN txn_type = 'credit' THEN amount ELSE -amount END) AS net_flow
        FROM transactions
        WHERE account_id = ?
        GROUP BY txn_date
        ORDER BY txn_date
    """
    df = pd.read_sql_query(query, conn, params=(account_id,), parse_dates=["txn_date"])
    full_range = pd.date_range(df["txn_date"].min(), df["txn_date"].max(), freq="D")
    df = df.set_index("txn_date").reindex(full_range, fill_value=0).rename_axis("txn_date").reset_index()
    return df


def make_features(df):
    df = df.copy()
    for lag in range(1, N_LAGS + 1):
        df[f"lag_{lag}"] = df["net_flow"].shift(lag)
    df["dow"] = df["txn_date"].dt.dayofweek
    df["day_of_month"] = df["txn_date"].dt.day
    df["rolling_mean_7"] = df["net_flow"].shift(1).rolling(7).mean()
    df = df.dropna().reset_index(drop=True)
    return df


def train_and_backtest(df):
    feature_cols = [c for c in df.columns if c.startswith("lag_") or c in
                    ("dow", "day_of_month", "rolling_mean_7")]
    split = int(len(df) * 0.85)
    train, test = df.iloc[:split], df.iloc[split:]
    if len(test) == 0 or len(train) < 30:
        return None, None, feature_cols

    model = GradientBoostingRegressor(random_state=42, n_estimators=150, max_depth=3, learning_rate=0.05)
    model.fit(train[feature_cols], train["net_flow"])

    preds = model.predict(test[feature_cols])
    mae_model = mean_absolute_error(test["net_flow"], preds)

    # naive baseline: predict the same value as 7 days ago
    baseline_preds = test["lag_7"]
    mae_baseline = mean_absolute_error(test["net_flow"], baseline_preds)

    return model, {"mae_model": mae_model, "mae_baseline": mae_baseline}, feature_cols


def forecast_forward(model, df, feature_cols, horizon, starting_balance):
    history = df["net_flow"].tolist()
    last_date = df["txn_date"].max()
    results = []
    running_balance = starting_balance

    for step in range(1, horizon + 1):
        forecast_date = last_date + pd.Timedelta(days=step)
        lags = {f"lag_{lag}": history[-lag] for lag in range(1, N_LAGS + 1)}
        row = {
            **lags,
            "dow": forecast_date.dayofweek,
            "day_of_month": forecast_date.day,
            "rolling_mean_7": np.mean(history[-7:]),
        }
        X = pd.DataFrame([row])[feature_cols]
        pred = float(model.predict(X)[0])
        history.append(pred)
        running_balance += pred
        results.append((forecast_date.date().isoformat(), pred, running_balance))

    return results


def get_current_balance(conn, account_id):
    row = conn.execute(
        "SELECT current_balance FROM v_account_health WHERE account_id = ?", (account_id,)
    ).fetchone()
    return row[0] if row else 0.0


def main():
    conn = sqlite3.connect(DB_PATH)
    account_ids = [r[0] for r in conn.execute("SELECT account_id FROM accounts").fetchall()]

    conn.execute("DELETE FROM ml_cashflow_forecast")  # idempotent re-run

    for account_id in account_ids:
        daily = load_daily_net_flow(conn, account_id)
        featured = make_features(daily)
        if len(featured) < 45:
            print(f"account {account_id}: not enough history to forecast, skipping")
            continue

        model, metrics, feature_cols = train_and_backtest(featured)
        if model is None:
            print(f"account {account_id}: not enough history for a train/test split, skipping")
            continue

        print(f"account {account_id}: backtest MAE model={metrics['mae_model']:.2f} "
              f"vs naive baseline={metrics['mae_baseline']:.2f} "
              f"({'better' if metrics['mae_model'] < metrics['mae_baseline'] else 'worse'} than baseline)")

        # refit on all data before forecasting forward
        model.fit(featured[feature_cols], featured["net_flow"])
        starting_balance = get_current_balance(conn, account_id)
        forecast = forecast_forward(model, featured, feature_cols, FORECAST_HORIZON_DAYS, starting_balance)

        for forecast_date, predicted_net_flow, predicted_balance in forecast:
            conn.execute(
                """INSERT INTO ml_cashflow_forecast
                   (account_id, forecast_date, predicted_net_flow, predicted_balance, model_version)
                   VALUES (?, ?, ?, ?, ?)""",
                (account_id, forecast_date, round(predicted_net_flow, 2), round(predicted_balance, 2),
                 "gbr_lag_features_v1"),
            )
    conn.commit()
    print(f"\nForecasts written to ml_cashflow_forecast in {DB_PATH}")
    conn.close()


if __name__ == "__main__":
    main()
