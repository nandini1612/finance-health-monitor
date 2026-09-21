"""
Unit tests for etl/load_to_db.py's per-table loaders -- and especially the
validation logic inside load_transactions(), which is the actual "T" in
this ETL step. Before this file, that logic was only ever checked visually
(read the printed "inserted=X rejected=Y" line and eyeball it) -- exactly
the kind of business logic the roadmap flagged as needing real coverage,
separate from the dbt tests that only ever look at the Postgres/cloud tier.

Everything here runs against an in-memory SQLite connection with
sql/schema.sql applied fresh -- no CSVs, no on-disk database, no fixtures
shared with the real data/ directory, so these tests can't be accidentally
made to pass by a stale generated file.

Run:
    pytest -v          (from anywhere -- module resolution matches the
                         existing cloud/pipeline/test_pipeline.py pattern)
"""

import sqlite3

import load_to_db


def make_conn():
    conn = sqlite3.connect(":memory:")
    load_to_db.rebuild_schema(conn)
    return conn


def _seed_reference_data(conn):
    """One account, one category, one merchant -- the minimum every
    transaction/budget test below needs to have something valid to point
    at."""
    account_ids = load_to_db.load_accounts(conn, [
        {"account_name": "Test Checking", "account_type": "personal", "owner_name": "Alice",
         "currency": "USD", "opening_balance": "100.00"},
    ])
    category_lookup = load_to_db.load_categories(conn, [
        {"category_name": "Groceries", "category_group": "variable_expense"},
    ])
    merchant_lookup = load_to_db.load_merchants(conn, [
        {"merchant_name": "Trader Joe's", "default_category": "Groceries"},
    ], category_lookup)
    return account_ids, category_lookup, merchant_lookup


def _valid_txn_row(**overrides):
    row = {
        "account_ref": "0", "category_name": "Groceries", "merchant_name": "Trader Joe's",
        "amount": "42.50", "txn_type": "debit", "txn_date": "2026-01-05",
        "description": "", "is_recurring": "0",
    }
    row.update(overrides)
    return row


# --------------------------------------------------------------------------
# Reference tables
# --------------------------------------------------------------------------

def test_load_accounts_returns_ids_aligned_with_input_rows():
    conn = make_conn()
    ids = load_to_db.load_accounts(conn, [
        {"account_name": "Test Checking", "account_type": "personal", "owner_name": "Alice",
         "currency": "USD", "opening_balance": "100.00"},
        {"account_name": "Test Business", "account_type": "small_business", "owner_name": "Bob",
         "currency": "USD", "opening_balance": "500.00"},
    ])
    assert len(ids) == 2
    assert ids[0] != ids[1]
    name = conn.execute("SELECT account_name FROM accounts WHERE account_id = ?", (ids[0],)).fetchone()[0]
    assert name == "Test Checking"


def test_load_merchants_resolves_default_category_id():
    conn = make_conn()
    category_lookup = load_to_db.load_categories(conn, [
        {"category_name": "Groceries", "category_group": "variable_expense"},
    ])
    merchant_lookup = load_to_db.load_merchants(conn, [
        {"merchant_name": "Trader Joe's", "default_category": "Groceries"},
    ], category_lookup)
    row = conn.execute(
        "SELECT default_category_id FROM merchants WHERE merchant_id = ?",
        (merchant_lookup["Trader Joe's"],),
    ).fetchone()
    assert row[0] == category_lookup["Groceries"]


# --------------------------------------------------------------------------
# load_transactions() validation -- the part worth actually testing
# --------------------------------------------------------------------------

def test_load_transactions_accepts_a_valid_row():
    conn = make_conn()
    account_ids, category_lookup, merchant_lookup = _seed_reference_data(conn)
    inserted, rejected, reasons = load_to_db.load_transactions(
        conn, [_valid_txn_row()], account_ids, category_lookup, merchant_lookup)
    assert (inserted, rejected) == (1, 0)


def test_load_transactions_rejects_non_positive_amount():
    conn = make_conn()
    account_ids, category_lookup, merchant_lookup = _seed_reference_data(conn)
    inserted, rejected, reasons = load_to_db.load_transactions(
        conn, [_valid_txn_row(amount="0")], account_ids, category_lookup, merchant_lookup)
    assert (inserted, rejected) == (0, 1)
    assert "non-positive amount" in reasons[0]


def test_load_transactions_rejects_negative_amount():
    conn = make_conn()
    account_ids, category_lookup, merchant_lookup = _seed_reference_data(conn)
    inserted, rejected, reasons = load_to_db.load_transactions(
        conn, [_valid_txn_row(amount="-12.34")], account_ids, category_lookup, merchant_lookup)
    assert (inserted, rejected) == (0, 1)


def test_load_transactions_rejects_bad_txn_type():
    conn = make_conn()
    account_ids, category_lookup, merchant_lookup = _seed_reference_data(conn)
    inserted, rejected, reasons = load_to_db.load_transactions(
        conn, [_valid_txn_row(txn_type="refund")], account_ids, category_lookup, merchant_lookup)
    assert (inserted, rejected) == (0, 1)
    assert "bad txn_type" in reasons[0]


def test_load_transactions_rejects_missing_date():
    conn = make_conn()
    account_ids, category_lookup, merchant_lookup = _seed_reference_data(conn)
    inserted, rejected, reasons = load_to_db.load_transactions(
        conn, [_valid_txn_row(txn_date="")], account_ids, category_lookup, merchant_lookup)
    assert (inserted, rejected) == (0, 1)
    assert "missing txn_date" in reasons[0]


def test_load_transactions_rejects_unknown_category():
    conn = make_conn()
    account_ids, category_lookup, merchant_lookup = _seed_reference_data(conn)
    inserted, rejected, reasons = load_to_db.load_transactions(
        conn, [_valid_txn_row(category_name="NotARealCategory")],
        account_ids, category_lookup, merchant_lookup)
    assert (inserted, rejected) == (0, 1)


def test_load_transactions_rejects_out_of_range_account_ref():
    conn = make_conn()
    account_ids, category_lookup, merchant_lookup = _seed_reference_data(conn)
    inserted, rejected, reasons = load_to_db.load_transactions(
        conn, [_valid_txn_row(account_ref="99")], account_ids, category_lookup, merchant_lookup)
    assert (inserted, rejected) == (0, 1)


def test_load_transactions_allows_unrecognized_merchant_as_null_not_a_rejection():
    # A transaction with no recognized merchant should still load --
    # merchant_id is nullable in the schema on purpose (cash spend,
    # one-off payees that never repeat). Not-found should not be a reject.
    conn = make_conn()
    account_ids, category_lookup, merchant_lookup = _seed_reference_data(conn)
    inserted, rejected, reasons = load_to_db.load_transactions(
        conn, [_valid_txn_row(merchant_name="Some Unknown Shop")],
        account_ids, category_lookup, merchant_lookup)
    assert (inserted, rejected) == (1, 0)
    merchant_id = conn.execute("SELECT merchant_id FROM transactions").fetchone()[0]
    assert merchant_id is None


def test_load_transactions_reports_mixed_batch_correctly():
    conn = make_conn()
    account_ids, category_lookup, merchant_lookup = _seed_reference_data(conn)
    rows = [_valid_txn_row(txn_date="2026-01-05"), _valid_txn_row(amount="-5.00", txn_date="2026-01-06")]
    inserted, rejected, reasons = load_to_db.load_transactions(
        conn, rows, account_ids, category_lookup, merchant_lookup)
    assert (inserted, rejected) == (1, 1)
    assert len(reasons) == 1


def test_load_transactions_rounds_amount_to_cents():
    conn = make_conn()
    account_ids, category_lookup, merchant_lookup = _seed_reference_data(conn)
    load_to_db.load_transactions(
        conn, [_valid_txn_row(amount="19.999")], account_ids, category_lookup, merchant_lookup)
    stored = conn.execute("SELECT amount FROM transactions").fetchone()[0]
    assert stored == 20.0


# --------------------------------------------------------------------------
# load_budgets()
# --------------------------------------------------------------------------

def test_load_budgets_skips_rows_with_unknown_category_without_raising():
    conn = make_conn()
    account_ids, category_lookup, merchant_lookup = _seed_reference_data(conn)
    rows = [
        {"account_ref": "0", "category_name": "Groceries", "month": "2026-01", "budgeted_amount": "300"},
        {"account_ref": "0", "category_name": "NotReal", "month": "2026-01", "budgeted_amount": "100"},
    ]
    inserted = load_to_db.load_budgets(conn, rows, account_ids, category_lookup)
    assert inserted == 1


def test_load_budgets_upserts_on_conflict():
    # INSERT OR REPLACE means re-running the loader (as a redeploy would)
    # updates the budget instead of erroring or duplicating it.
    conn = make_conn()
    account_ids, category_lookup, merchant_lookup = _seed_reference_data(conn)
    row = {"account_ref": "0", "category_name": "Groceries", "month": "2026-01", "budgeted_amount": "300"}
    load_to_db.load_budgets(conn, [row], account_ids, category_lookup)
    load_to_db.load_budgets(conn, [{**row, "budgeted_amount": "450"}], account_ids, category_lookup)
    count, amount = conn.execute(
        "SELECT COUNT(*), MAX(budgeted_amount) FROM budgets"
    ).fetchone()
    assert (count, amount) == (1, 450.0)
