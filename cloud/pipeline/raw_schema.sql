-- ============================================================================
-- CashPulse Cloud Edition - raw landing zone (Postgres / AWS RDS)
--
-- This is deliberately loose: raw tables accept whatever the source system
-- sends, with minimal typing and no foreign keys. Cleaning, typing, and
-- relationships are dbt's job (see cloud/dbt/), not the loader's. This
-- "land it raw, transform it in the warehouse" split is the ELT pattern
-- real data teams use -- ETL did transform-before-load; ELT loads raw and
-- transforms in SQL where it's easier to test, version, and re-run.
-- ============================================================================

-- CREATE ... IF NOT EXISTS throughout, deliberately -- this file is re-run
-- on every pipeline invocation (see load_raw.py), and by the second run,
-- dbt's staging views already depend on these tables. A DROP TABLE here
-- (even IF EXISTS) would fail with "cannot drop table because other
-- objects depend on it" once that happens. load_raw.py TRUNCATEs these
-- tables before reloading instead -- that clears data without touching
-- the table (and therefore the dependent views) at all.

CREATE SCHEMA IF NOT EXISTS raw;

CREATE TABLE IF NOT EXISTS raw.raw_accounts (
    account_ref     INTEGER,
    account_name    TEXT,
    account_type    TEXT,
    owner_name      TEXT,
    currency        TEXT,
    opening_balance TEXT,   -- loaded as text on purpose: raw zones don't assume the source
    loaded_at       TIMESTAMPTZ DEFAULT now()  -- always sent clean numbers; dbt casts it.
);

CREATE TABLE IF NOT EXISTS raw.raw_categories (
    category_name  TEXT,
    category_group TEXT,
    loaded_at      TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS raw.raw_merchants (
    merchant_name     TEXT,
    default_category  TEXT,
    loaded_at         TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS raw.raw_transactions (
    source_txn_id INTEGER,  -- stable id from the source system; see stg_transactions.sql
    account_ref   INTEGER,
    txn_date      TEXT,
    merchant_name TEXT,
    category_name TEXT,
    amount        TEXT,
    txn_type      TEXT,
    description   TEXT,
    is_recurring  TEXT,
    loaded_at     TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS raw.raw_budgets (
    account_ref     INTEGER,
    category_name   TEXT,
    month           TEXT,
    budgeted_amount TEXT,
    loaded_at       TIMESTAMPTZ DEFAULT now()
);

-- Output schema for ML models -- written by cloud/pipeline/ml_*.py, read by
-- the dashboard and by Power BI / Tableau. Kept separate from dbt's own
-- output schema (analytics) so it's obvious which tables dbt owns vs. which
-- the ML jobs own.
CREATE SCHEMA IF NOT EXISTS ml;

CREATE TABLE IF NOT EXISTS ml.anomaly_flags (
    flag_id        SERIAL PRIMARY KEY,
    transaction_id BIGINT NOT NULL,
    anomaly_score  NUMERIC(6, 4) NOT NULL,
    reason         TEXT,
    model_version  TEXT NOT NULL DEFAULT 'isolation_forest_v1',
    flagged_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ml.cashflow_forecast (
    forecast_id         SERIAL PRIMARY KEY,
    account_id          BIGINT NOT NULL,
    forecast_date       DATE NOT NULL,
    predicted_net_flow  NUMERIC(12, 2) NOT NULL,
    predicted_balance   NUMERIC(12, 2) NOT NULL,
    model_version       TEXT NOT NULL DEFAULT 'gbr_lag_features_v1',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
