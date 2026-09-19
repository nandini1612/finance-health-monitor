-- ============================================================================
-- CashPulse: Personal & SME Finance Health Monitor
-- Database schema (SQLite-flavored; portable to PostgreSQL with minor tweaks
-- noted inline as comments).
--
-- Design notes for your own learning / interview talking points:
--   - Normalized to 3NF: categories, merchants, and accounts are looked up by
--     id from transactions rather than repeating text everywhere.
--   - ml_anomaly_flags and ml_cashflow_forecast are OUTPUT tables written by
--     the ML layer, not by the app -- this is what makes it "MLOps-flavored"
--     rather than just a notebook: predictions live in the database, so the
--     BI layer (dashboard / Power BI / Tableau) can just query them.
--   - Views (v_*) exist so your BI tool talks to a clean, pre-joined surface
--     instead of five raw tables -- this is standard practice in real BI work.
-- ============================================================================

PRAGMA foreign_keys = ON;

DROP VIEW IF EXISTS v_account_health;
DROP VIEW IF EXISTS v_category_spend_monthly;
DROP VIEW IF EXISTS v_monthly_cashflow;
DROP TABLE IF EXISTS ml_cashflow_forecast;
DROP TABLE IF EXISTS ml_anomaly_flags;
DROP TABLE IF EXISTS budgets;
DROP TABLE IF EXISTS transactions;
DROP TABLE IF EXISTS merchants;
DROP TABLE IF EXISTS categories;
DROP TABLE IF EXISTS accounts;

-- ----------------------------------------------------------------------------
-- Core reference tables
-- ----------------------------------------------------------------------------

CREATE TABLE accounts (
    account_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    account_name    TEXT NOT NULL,
    account_type    TEXT NOT NULL CHECK (account_type IN ('personal', 'small_business')),
    owner_name      TEXT NOT NULL,
    currency        TEXT NOT NULL DEFAULT 'USD',
    opening_balance NUMERIC(12, 2) NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE categories (
    category_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    category_name  TEXT NOT NULL UNIQUE,
    category_group TEXT NOT NULL CHECK (
        category_group IN ('income', 'fixed_expense', 'variable_expense', 'discretionary', 'transfer')
    )
);

CREATE TABLE merchants (
    merchant_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    merchant_name      TEXT NOT NULL UNIQUE,
    default_category_id INTEGER REFERENCES categories(category_id)
);

-- ----------------------------------------------------------------------------
-- Transactions: the fact table everything else hangs off of
-- ----------------------------------------------------------------------------

CREATE TABLE transactions (
    transaction_id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id     INTEGER NOT NULL REFERENCES accounts(account_id),
    merchant_id    INTEGER REFERENCES merchants(merchant_id),
    category_id    INTEGER NOT NULL REFERENCES categories(category_id),
    txn_date       TEXT NOT NULL,              -- ISO date 'YYYY-MM-DD'
    amount         NUMERIC(12, 2) NOT NULL,    -- always positive; sign comes from txn_type
    txn_type       TEXT NOT NULL CHECK (txn_type IN ('credit', 'debit')),
    description    TEXT,
    is_recurring   INTEGER NOT NULL DEFAULT 0, -- 0/1 boolean
    created_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_transactions_account_date ON transactions(account_id, txn_date);
CREATE INDEX idx_transactions_category ON transactions(category_id);
CREATE INDEX idx_transactions_merchant ON transactions(merchant_id);

CREATE TABLE budgets (
    budget_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id      INTEGER NOT NULL REFERENCES accounts(account_id),
    category_id     INTEGER NOT NULL REFERENCES categories(category_id),
    month           TEXT NOT NULL,              -- 'YYYY-MM'
    budgeted_amount NUMERIC(12, 2) NOT NULL,
    UNIQUE (account_id, category_id, month)
);

-- ----------------------------------------------------------------------------
-- ML output tables -- written by the ml/ scripts, read by the dashboard/BI tool
-- ----------------------------------------------------------------------------

CREATE TABLE ml_anomaly_flags (
    flag_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    transaction_id INTEGER NOT NULL REFERENCES transactions(transaction_id),
    anomaly_score  NUMERIC(6, 4) NOT NULL,   -- higher = more anomalous
    reason         TEXT,
    model_version  TEXT NOT NULL DEFAULT 'isolation_forest_v1',
    flagged_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE ml_cashflow_forecast (
    forecast_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id         INTEGER NOT NULL REFERENCES accounts(account_id),
    forecast_date       TEXT NOT NULL,          -- 'YYYY-MM-DD', a future week/day
    predicted_net_flow NUMERIC(12, 2) NOT NULL,
    predicted_balance  NUMERIC(12, 2) NOT NULL,
    model_version      TEXT NOT NULL DEFAULT 'rf_lag_features_v1',
    created_at         TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ----------------------------------------------------------------------------
-- Views -- the "BI-ready" layer
-- ----------------------------------------------------------------------------

CREATE VIEW v_monthly_cashflow AS
SELECT
    t.account_id,
    strftime('%Y-%m', t.txn_date) AS month,
    SUM(CASE WHEN t.txn_type = 'credit' THEN t.amount ELSE 0 END) AS total_income,
    SUM(CASE WHEN t.txn_type = 'debit'  THEN t.amount ELSE 0 END) AS total_expense,
    SUM(CASE WHEN t.txn_type = 'credit' THEN t.amount ELSE -t.amount END) AS net_flow
FROM transactions t
GROUP BY t.account_id, strftime('%Y-%m', t.txn_date);

CREATE VIEW v_category_spend_monthly AS
SELECT
    t.account_id,
    strftime('%Y-%m', t.txn_date) AS month,
    c.category_name,
    c.category_group,
    SUM(t.amount) AS total_amount,
    COUNT(*) AS txn_count
FROM transactions t
JOIN categories c ON c.category_id = t.category_id
WHERE t.txn_type = 'debit'
GROUP BY t.account_id, strftime('%Y-%m', t.txn_date), c.category_name, c.category_group;

CREATE VIEW v_account_health AS
SELECT
    a.account_id,
    a.account_name,
    a.account_type,
    a.opening_balance + COALESCE(SUM(
        CASE WHEN t.txn_type = 'credit' THEN t.amount ELSE -t.amount END
    ), 0) AS current_balance,
    -- Average daily burn over the last 30 days of data present for this account
    (
        SELECT COALESCE(SUM(t2.amount), 0) / 30.0
        FROM transactions t2
        WHERE t2.account_id = a.account_id
          AND t2.txn_type = 'debit'
          AND t2.txn_date >= date((SELECT MAX(txn_date) FROM transactions WHERE account_id = a.account_id), '-30 days')
    ) AS avg_daily_burn
FROM accounts a
LEFT JOIN transactions t ON t.account_id = a.account_id
GROUP BY a.account_id, a.account_name, a.account_type, a.opening_balance;

-- Note for PostgreSQL portability:
--   - AUTOINCREMENT -> GENERATED ALWAYS AS IDENTITY
--   - datetime('now') -> now()
--   - strftime('%Y-%m', col) -> to_char(col, 'YYYY-MM')
--   - date(col, '-30 days') -> (col::date - interval '30 days')
