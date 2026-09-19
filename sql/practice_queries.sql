-- ============================================================================
-- SQL practice set for CashPulse
--
-- You said SQL is a weaker area -- work through these yourself against
-- data/finance.db (sqlite3 data/finance.db) BEFORE looking at the dashboard
-- or ML code, which use similar logic. Each one builds on the last.
-- Answers/approach hints are in comments; try writing the query first.
-- ============================================================================

-- 1. Warm-up: list all accounts with their current type and opening balance.
-- SELECT account_id, account_name, account_type, opening_balance FROM accounts;

-- 2. JOIN: show the 10 most recent transactions with category and merchant names
--    instead of raw ids.
-- SELECT t.txn_date, a.account_name, m.merchant_name, c.category_name, t.amount, t.txn_type
-- FROM transactions t
-- JOIN accounts a ON a.account_id = t.account_id
-- LEFT JOIN merchants m ON m.merchant_id = t.merchant_id
-- JOIN categories c ON c.category_id = t.category_id
-- ORDER BY t.txn_date DESC
-- LIMIT 10;

-- 3. GROUP BY + aggregate: total spend per category, across all accounts.
-- SELECT c.category_name, SUM(t.amount) AS total_spend
-- FROM transactions t JOIN categories c ON c.category_id = t.category_id
-- WHERE t.txn_type = 'debit'
-- GROUP BY c.category_name
-- ORDER BY total_spend DESC;

-- 4. Subquery / HAVING: which accounts had average monthly expenses above $3000?
-- SELECT account_id, AVG(total_expense) AS avg_monthly_expense
-- FROM v_monthly_cashflow
-- GROUP BY account_id
-- HAVING AVG(total_expense) > 3000;

-- 5. Window function: month-over-month change in net cash flow per account.
--    (This is the kind of query BI tools expect you to be able to write by hand.)
-- SELECT
--   account_id, month, net_flow,
--   net_flow - LAG(net_flow) OVER (PARTITION BY account_id ORDER BY month) AS mom_change
-- FROM v_monthly_cashflow
-- ORDER BY account_id, month;

-- 6. Window function: 7-day rolling average of daily spend per account
--    (useful for smoothing noisy daily data before charting it).
-- SELECT
--   account_id, txn_date, daily_spend,
--   AVG(daily_spend) OVER (
--     PARTITION BY account_id ORDER BY txn_date
--     ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
--   ) AS rolling_7day_avg
-- FROM (
--   SELECT account_id, txn_date, SUM(amount) AS daily_spend
--   FROM transactions
--   WHERE txn_type = 'debit'
--   GROUP BY account_id, txn_date
-- ) daily;

-- 7. CTE + ranking: top 3 highest-spend categories per account, per month.
-- WITH ranked AS (
--   SELECT
--     account_id, month, category_name, total_amount,
--     RANK() OVER (PARTITION BY account_id, month ORDER BY total_amount DESC) AS rnk
--   FROM v_category_spend_monthly
-- )
-- SELECT * FROM ranked WHERE rnk <= 3;

-- 8. Anomaly review: join flagged transactions back to full detail, most
--    suspicious first.
-- SELECT f.anomaly_score, f.reason, t.txn_date, a.account_name, t.amount, c.category_name
-- FROM ml_anomaly_flags f
-- JOIN transactions t ON t.transaction_id = f.transaction_id
-- JOIN accounts a ON a.account_id = t.account_id
-- JOIN categories c ON c.category_id = t.category_id
-- ORDER BY f.anomaly_score DESC
-- LIMIT 20;

-- 9. Budget vs actual: how far over/under budget was each category last month?
-- SELECT
--   b.account_id, b.month, c.category_name, b.budgeted_amount,
--   COALESCE(s.total_amount, 0) AS actual_amount,
--   COALESCE(s.total_amount, 0) - b.budgeted_amount AS variance
-- FROM budgets b
-- JOIN categories c ON c.category_id = b.category_id
-- LEFT JOIN v_category_spend_monthly s
--   ON s.account_id = b.account_id AND s.month = b.month AND s.category_name = c.category_name
-- ORDER BY variance DESC;

-- 10. Stretch goal: "runway" query -- given avg_daily_burn from v_account_health,
--     compute days until current_balance hits zero for each account.
-- SELECT
--   account_name, current_balance, avg_daily_burn,
--   CASE WHEN avg_daily_burn > 0 THEN current_balance / avg_daily_burn ELSE NULL END AS runway_days
-- FROM v_account_health
-- ORDER BY runway_days ASC;
