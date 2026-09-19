"""
CashPulse - anomaly / fraud-pattern detection.

Reads transactions from the DB, engineers a handful of features that
capture "does this transaction look normal for this account/category",
runs an Isolation Forest, and writes the top anomalies back into
ml_anomaly_flags so the dashboard and BI tool can surface them.

Why Isolation Forest: it doesn't need labeled fraud data (which we don't
have -- nobody labels their own transactions as fraudulent), it handles
mixed-scale numeric features well, and it's fast enough to rerun on every
ETL cycle. This is the standard "unsupervised anomaly detection on
tabular data" approach and is very defensible in an interview.

Run (after etl/load_to_db.py):
    python ml/detect_anomalies.py
"""

import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

DB_PATH = Path(__file__).parent.parent / "data" / "finance.db"


def load_transactions(conn):
    query = """
        SELECT
            t.transaction_id, t.account_id, t.category_id, t.merchant_id,
            t.txn_date, t.amount, t.txn_type, c.category_name
        FROM transactions t
        JOIN categories c ON c.category_id = t.category_id
        WHERE t.txn_type = 'debit'
    """
    df = pd.read_sql_query(query, conn, parse_dates=["txn_date"])
    return df


def engineer_features(df):
    df = df.copy()
    df["day_of_week"] = df["txn_date"].dt.dayofweek
    df["day_of_month"] = df["txn_date"].dt.day

    # z-score of amount within its own category (how unusual is this amount
    # compared to typical spend in that category, across all accounts)
    cat_stats = df.groupby("category_name")["amount"].agg(["mean", "std"]).rename(
        columns={"mean": "cat_mean", "std": "cat_std"}
    )
    df = df.merge(cat_stats, on="category_name", how="left")
    df["cat_std"] = df["cat_std"].replace(0, np.nan).fillna(df["amount"].std())
    df["amount_zscore_in_category"] = (df["amount"] - df["cat_mean"]) / df["cat_std"]

    # how many transactions did this account have on the same day (card-testing /
    # duplicate-charge patterns show up as spikes here)
    same_day_counts = df.groupby(["account_id", "txn_date"]).size().rename("txns_same_day")
    df = df.merge(same_day_counts, on=["account_id", "txn_date"], how="left")

    features = df[["amount", "amount_zscore_in_category", "txns_same_day", "day_of_week", "day_of_month"]].fillna(0)
    return df, features


def main():
    conn = sqlite3.connect(DB_PATH)
    df = load_transactions(conn)
    if df.empty:
        print("No debit transactions found -- did you run the ETL step first?")
        return

    df, features = engineer_features(df)

    model = IsolationForest(n_estimators=200, contamination=0.02, random_state=42)
    model.fit(features)
    # decision_function: lower = more anomalous. Flip sign so higher = more anomalous,
    # matching the anomaly_score convention in the schema.
    raw_scores = -model.decision_function(features)
    df["anomaly_score"] = (raw_scores - raw_scores.min()) / (raw_scores.max() - raw_scores.min())
    df["is_anomaly"] = model.predict(features) == -1

    flagged = df[df["is_anomaly"]].sort_values("anomaly_score", ascending=False)
    print(f"Flagged {len(flagged)} / {len(df)} debit transactions as anomalous.")

    conn.execute("DELETE FROM ml_anomaly_flags")  # idempotent re-run
    for _, row in flagged.iterrows():
        reason_bits = []
        if abs(row["amount_zscore_in_category"]) > 2:
            reason_bits.append(f"amount {row['amount_zscore_in_category']:.1f} std devs from category norm")
        if row["txns_same_day"] > 3:
            reason_bits.append(f"{int(row['txns_same_day'])} transactions same day (possible duplicate/testing)")
        reason = "; ".join(reason_bits) or "unusual combination of amount/timing features"

        conn.execute(
            """INSERT INTO ml_anomaly_flags (transaction_id, anomaly_score, reason, model_version)
               VALUES (?, ?, ?, ?)""",
            (int(row["transaction_id"]), float(row["anomaly_score"]), reason, "isolation_forest_v1"),
        )
    conn.commit()
    print(f"Wrote flags to ml_anomaly_flags in {DB_PATH}")
    conn.close()


if __name__ == "__main__":
    main()
