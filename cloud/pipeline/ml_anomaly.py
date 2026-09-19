"""
CashPulse Cloud Edition - anomaly detection, reading from dbt marts.

Same Isolation Forest approach as the local quickstart (ml/detect_anomalies.py),
but reading from analytics.fct_transactions (a dbt model) instead of a
hand-loaded SQLite table, and writing results into ml.anomaly_flags.

Requires DATABASE_URL to be set, and dbt to have already run successfully.

Run:
    python cloud/pipeline/ml_anomaly.py
"""

import numpy as np
import pandas as pd
import sqlalchemy
from sklearn.ensemble import IsolationForest

from db import get_engine


def load_transactions(engine):
    query = """
        SELECT transaction_id, account_id, category_name, txn_date, amount, txn_type
        FROM analytics.fct_transactions
        WHERE txn_type = 'debit'
    """
    return pd.read_sql_query(query, engine, parse_dates=["txn_date"])


def engineer_features(df):
    df = df.copy()
    df["day_of_week"] = df["txn_date"].dt.dayofweek
    df["day_of_month"] = df["txn_date"].dt.day

    cat_stats = df.groupby("category_name")["amount"].agg(["mean", "std"]).rename(
        columns={"mean": "cat_mean", "std": "cat_std"}
    )
    df = df.merge(cat_stats, on="category_name", how="left")
    df["cat_std"] = df["cat_std"].replace(0, np.nan).fillna(df["amount"].std())
    df["amount_zscore_in_category"] = (df["amount"] - df["cat_mean"]) / df["cat_std"]

    same_day_counts = df.groupby(["account_id", "txn_date"]).size().rename("txns_same_day")
    df = df.merge(same_day_counts, on=["account_id", "txn_date"], how="left")

    features = df[["amount", "amount_zscore_in_category", "txns_same_day", "day_of_week", "day_of_month"]].fillna(0)
    return df, features


def run(engine=None):
    engine = engine or get_engine()
    df = load_transactions(engine)
    if df.empty:
        print("No debit transactions found in analytics.fct_transactions -- run dbt first.")
        return 0

    df, features = engineer_features(df)

    model = IsolationForest(n_estimators=200, contamination=0.02, random_state=42)
    model.fit(features)
    raw_scores = -model.decision_function(features)
    df["anomaly_score"] = (raw_scores - raw_scores.min()) / (raw_scores.max() - raw_scores.min())
    df["is_anomaly"] = model.predict(features) == -1

    flagged = df[df["is_anomaly"]].sort_values("anomaly_score", ascending=False)
    print(f"Flagged {len(flagged)} / {len(df)} debit transactions as anomalous.")

    with engine.begin() as conn:
        conn.execute(sqlalchemy.text("DELETE FROM ml.anomaly_flags"))
        for _, row in flagged.iterrows():
            reason_bits = []
            if abs(row["amount_zscore_in_category"]) > 2:
                reason_bits.append(f"amount {row['amount_zscore_in_category']:.1f} std devs from category norm")
            if row["txns_same_day"] > 3:
                reason_bits.append(f"{int(row['txns_same_day'])} transactions same day (possible duplicate/testing)")
            reason = "; ".join(reason_bits) or "unusual combination of amount/timing features"

            conn.execute(
                sqlalchemy.text(
                    """INSERT INTO ml.anomaly_flags (transaction_id, anomaly_score, reason, model_version)
                       VALUES (:tid, :score, :reason, :version)"""
                ),
                {"tid": int(row["transaction_id"]), "score": float(row["anomaly_score"]),
                 "reason": reason, "version": "isolation_forest_v1"},
            )
    print("Wrote flags to ml.anomaly_flags")
    return len(flagged)


if __name__ == "__main__":
    run()
