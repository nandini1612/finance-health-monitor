"""
CashPulse - ETL loader.

Reads the CSVs produced by data/generate_data.py, applies basic cleaning
and validation, and loads them into the SQLite database defined by
sql/schema.sql. This is the "E-T-L" piece of the pipeline: it doesn't just
dump CSVs into tables -- it resolves foreign keys, checks for bad rows,
and logs what it rejects, the way a real ingestion job would.

Run:
    python etl/load_to_db.py
"""

import csv
import sqlite3
from pathlib import Path

ROOT = Path(__file__).parent.parent
DATA_DIR = ROOT / "data"
SCHEMA_PATH = ROOT / "sql" / "schema.sql"
DB_PATH = DATA_DIR / "finance.db"


def read_csv(name):
    with open(DATA_DIR / name, newline="") as f:
        return list(csv.DictReader(f))


def rebuild_schema(conn):
    with open(SCHEMA_PATH) as f:
        conn.executescript(f.read())


def load_accounts(conn, rows):
    ids = []
    for r in rows:
        cur = conn.execute(
            """INSERT INTO accounts (account_name, account_type, owner_name, currency, opening_balance)
               VALUES (?, ?, ?, ?, ?)""",
            (r["account_name"], r["account_type"], r["owner_name"], r["currency"], float(r["opening_balance"])),
        )
        ids.append(cur.lastrowid)
    conn.commit()
    return ids  # index-aligned with rows -> maps account_ref (0-based) to account_id


def load_categories(conn, rows):
    name_to_id = {}
    for r in rows:
        cur = conn.execute(
            "INSERT INTO categories (category_name, category_group) VALUES (?, ?)",
            (r["category_name"], r["category_group"]),
        )
        name_to_id[r["category_name"]] = cur.lastrowid
    conn.commit()
    return name_to_id


def load_merchants(conn, rows, category_lookup):
    name_to_id = {}
    for r in rows:
        cat_id = category_lookup.get(r["default_category"])
        cur = conn.execute(
            "INSERT INTO merchants (merchant_name, default_category_id) VALUES (?, ?)",
            (r["merchant_name"], cat_id),
        )
        name_to_id[r["merchant_name"]] = cur.lastrowid
    conn.commit()
    return name_to_id


def load_transactions(conn, rows, account_ids, category_lookup, merchant_lookup):
    inserted, rejected = 0, 0
    reject_reasons = []
    for r in rows:
        try:
            account_id = account_ids[int(r["account_ref"])]
            category_id = category_lookup[r["category_name"]]
            merchant_id = merchant_lookup.get(r["merchant_name"])
            amount = float(r["amount"])

            # --- basic validation, the "T" in ETL ---
            if amount <= 0:
                raise ValueError(f"non-positive amount: {amount}")
            if r["txn_type"] not in ("credit", "debit"):
                raise ValueError(f"bad txn_type: {r['txn_type']}")
            if not r["txn_date"]:
                raise ValueError("missing txn_date")

            conn.execute(
                """INSERT INTO transactions
                   (account_id, merchant_id, category_id, txn_date, amount, txn_type, description, is_recurring)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (account_id, merchant_id, category_id, r["txn_date"], round(amount, 2),
                 r["txn_type"], r.get("description", ""), int(r.get("is_recurring", 0))),
            )
            inserted += 1
        except (KeyError, ValueError, IndexError) as e:
            rejected += 1
            reject_reasons.append(str(e))
    conn.commit()
    return inserted, rejected, reject_reasons


def load_budgets(conn, rows, account_ids, category_lookup):
    inserted = 0
    for r in rows:
        account_id = account_ids[int(r["account_ref"])]
        category_id = category_lookup.get(r["category_name"])
        if category_id is None:
            continue
        conn.execute(
            """INSERT OR REPLACE INTO budgets (account_id, category_id, month, budgeted_amount)
               VALUES (?, ?, ?, ?)""",
            (account_id, category_id, r["month"], float(r["budgeted_amount"])),
        )
        inserted += 1
    conn.commit()
    return inserted


def main():
    if DB_PATH.exists():
        DB_PATH.unlink()
    conn = sqlite3.connect(DB_PATH)

    print("Rebuilding schema...")
    rebuild_schema(conn)

    print("Loading reference tables...")
    account_rows = read_csv("accounts.csv")
    category_rows = read_csv("categories.csv")
    merchant_rows = read_csv("merchants.csv")

    account_ids = load_accounts(conn, account_rows)
    category_lookup = load_categories(conn, category_rows)
    merchant_lookup = load_merchants(conn, merchant_rows, category_lookup)

    print("Loading transactions...")
    txn_rows = read_csv("transactions.csv")
    inserted, rejected, reasons = load_transactions(conn, txn_rows, account_ids, category_lookup, merchant_lookup)
    print(f"  inserted={inserted}  rejected={rejected}")
    if reasons:
        print("  sample reject reasons:", reasons[:5])

    print("Loading budgets...")
    budget_rows = read_csv("budgets.csv")
    n_budgets = load_budgets(conn, budget_rows, account_ids, category_lookup)
    print(f"  inserted={n_budgets}")

    # Quick sanity check
    total = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
    print(f"\nDatabase ready at {DB_PATH} -- {total} transactions loaded.")
    conn.close()


if __name__ == "__main__":
    main()
