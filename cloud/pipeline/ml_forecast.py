"""
CashPulse Cloud Edition - cash-flow forecasting, reading from dbt marts.

Same gradient-boosted approach as the local quickstart
(ml/forecast_cashflow.py), reading from analytics.fct_transactions and
analytics.account_health, writing into ml.cashflow_forecast.

Run:
    python cloud/pipeline/ml_forecast.py
"""

import numpy as np
import pandas as pd
import sqlalchemy
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.metrics import mean_absolute_error

from db import get_engine

FORECAST_HORIZON_DAYS = 30
N_LAGS = 7


def load_daily_net_flow(engine, account_id):
    query = sqlalchemy.text("""
        SELECT txn_date,
               SUM(CASE WHEN txn_type = 'credit' THEN amount ELSE -amount END) AS net_flow
        FROM analytics.fct_transactions
        WHERE account_id = :account_id
        GROUP BY txn_date
        ORDER BY txn_date
    """)
    df = pd.read_sql_query(query, engine, params={"account_id": account_id}, parse_dates=["txn_date"])
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
    return df.dropna().reset_index(drop=True)


def train_and_backtest(df):
    feature_cols = [c for c in df.columns if c.startswith("lag_") or c in ("dow", "day_of_month", "rolling_mean_7")]
    split = int(len(df) * 0.85)
    train, test = df.iloc[:split], df.iloc[split:]
    if len(test) == 0 or len(train) < 30:
        return None, None, feature_cols

    model = GradientBoostingRegressor(random_state=42, n_estimators=150, max_depth=3, learning_rate=0.05)
    model.fit(train[feature_cols], train["net_flow"])

    preds = model.predict(test[feature_cols])
    mae_model = mean_absolute_error(test["net_flow"], preds)
    mae_baseline = mean_absolute_error(test["net_flow"], test["lag_7"])
    return model, {"mae_model": mae_model, "mae_baseline": mae_baseline}, feature_cols


def forecast_forward(model, df, feature_cols, horizon, starting_balance):
    history = df["net_flow"].tolist()
    last_date = df["txn_date"].max()
    results, running_balance = [], starting_balance

    for step in range(1, horizon + 1):
        forecast_date = last_date + pd.Timedelta(days=step)
        row = {f"lag_{lag}": history[-lag] for lag in range(1, N_LAGS + 1)}
        row.update({"dow": forecast_date.dayofweek, "day_of_month": forecast_date.day,
                     "rolling_mean_7": np.mean(history[-7:])})
        pred = float(model.predict(pd.DataFrame([row])[feature_cols])[0])
        history.append(pred)
        running_balance += pred
        results.append((forecast_date.date().isoformat(), pred, running_balance))
    return results


def get_current_balance(engine, account_id):
    with engine.connect() as conn:
        row = conn.execute(
            sqlalchemy.text("SELECT current_balance FROM analytics.account_health WHERE account_id = :aid"),
            {"aid": account_id},
        ).fetchone()
    return float(row[0]) if row else 0.0


def run(engine=None):
    engine = engine or get_engine()
    with engine.connect() as conn:
        account_ids = [r[0] for r in conn.execute(sqlalchemy.text("SELECT account_id FROM analytics.dim_accounts"))]

    metrics_by_account = {}
    with engine.begin() as conn:
        conn.execute(sqlalchemy.text("DELETE FROM ml.cashflow_forecast"))

        for account_id in account_ids:
            daily = load_daily_net_flow(engine, account_id)
            featured = make_features(daily)
            if len(featured) < 45:
                print(f"account {account_id}: not enough history to forecast, skipping")
                continue

            model, metrics, feature_cols = train_and_backtest(featured)
            if model is None:
                print(f"account {account_id}: not enough history for a train/test split, skipping")
                continue

            metrics_by_account[account_id] = metrics
            print(f"account {account_id}: backtest MAE model={metrics['mae_model']:.2f} "
                  f"vs naive baseline={metrics['mae_baseline']:.2f} "
                  f"({'better' if metrics['mae_model'] < metrics['mae_baseline'] else 'worse'} than baseline)")

            model.fit(featured[feature_cols], featured["net_flow"])
            starting_balance = get_current_balance(engine, account_id)
            forecast = forecast_forward(model, featured, feature_cols, FORECAST_HORIZON_DAYS, starting_balance)

            for forecast_date, predicted_net_flow, predicted_balance in forecast:
                conn.execute(
                    sqlalchemy.text(
                        """INSERT INTO ml.cashflow_forecast
                           (account_id, forecast_date, predicted_net_flow, predicted_balance, model_version)
                           VALUES (:aid, :fdate, :pnf, :pbal, :version)"""
                    ),
                    {"aid": account_id, "fdate": forecast_date, "pnf": round(predicted_net_flow, 2),
                     "pbal": round(predicted_balance, 2), "version": "gbr_lag_features_v1"},
                )
    print("Wrote forecasts to ml.cashflow_forecast")
    return metrics_by_account


if __name__ == "__main__":
    run()
