"""
CashPulse Cloud Edition - raw zone loader.

Loads the CSVs from data/generate_data.py (same generator as the local
quickstart -- in a real company this step would instead be an extractor
hitting a source system's API/DB) into the `raw` schema of Postgres,
completely unvalidated. Validation is dbt's job now (see cloud/dbt/
models/staging + schema.yml tests) -- this is the ELT split described in
raw_schema.sql.

Requires DATABASE_URL to be set (see cloud/.env.example).

Run:
    python cloud/pipeline/load_raw.py
"""

import csv
from pathlib import Path

import sqlalchemy

from db import get_engine

ROOT = Path(__file__).parent.parent.parent
DATA_DIR = ROOT / "data"
SCHEMA_PATH = Path(__file__).parent / "raw_schema.sql"


def read_csv(name):
    with open(DATA_DIR / name, newline="") as f:
        return list(csv.DictReader(f))


RAW_TABLES = [
    "raw.raw_accounts", "raw.raw_categories", "raw.raw_merchants",
    "raw.raw_transactions", "raw.raw_budgets",
]


def ensure_raw_schema(conn):
    """Create the raw/ml schemas and tables if they don't exist yet (safe to
    run every time -- see the comment at the top of raw_schema.sql)."""
    with open(SCHEMA_PATH) as f:
        conn.execute(sqlalchemy.text(f.read()))


def truncate_raw_tables(conn):
    """Clear out the previous load without dropping the tables -- dbt's
    staging views depend on them after the first run, so dropping would fail."""
    for table in RAW_TABLES:
        conn.execute(sqlalchemy.text(f"TRUNCATE TABLE {table}"))


def bulk_insert(conn, table, rows, columns):
    if not rows:
        print(f"  no rows for {table}, skipping")
        return
    stmt = sqlalchemy.text(
        f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({', '.join(':' + c for c in columns)})"
    )
    conn.execute(stmt, rows)
    print(f"  loaded {len(rows)} rows -> {table}")


def main():
    engine = get_engine()
    with engine.begin() as conn:
        print("Ensuring raw schema exists...")
        ensure_raw_schema(conn)
        print("Truncating previous load...")
        truncate_raw_tables(conn)

        print("Loading accounts...")
        bulk_insert(
            conn, "raw.raw_accounts",
            [{"account_ref": i, **r} for i, r in enumerate(read_csv("accounts.csv"))],
            ["account_ref", "account_name", "account_type", "owner_name", "currency", "opening_balance"],
        )

        print("Loading categories...")
        bulk_insert(conn, "raw.raw_categories", read_csv("categories.csv"),
                    ["category_name", "category_group"])

        print("Loading merchants...")
        bulk_insert(conn, "raw.raw_merchants", read_csv("merchants.csv"),
                    ["merchant_name", "default_category"])

        print("Loading transactions (raw, unvalidated)...")
        bulk_insert(conn, "raw.raw_transactions", read_csv("transactions.csv"),
                    ["source_txn_id", "account_ref", "txn_date", "merchant_name", "category_name", "amount",
                     "txn_type", "description", "is_recurring"])

        print("Loading budgets...")
        bulk_insert(conn, "raw.raw_budgets", read_csv("budgets.csv"),
                    ["account_ref", "category_name", "month", "budgeted_amount"])

    print("\nRaw zone loaded. Run `dbt run && dbt test` next (see cloud/dbt/).")


if __name__ == "__main__":
    main()
