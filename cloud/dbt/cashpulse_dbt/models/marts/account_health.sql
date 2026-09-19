-- Current balance and 30-day average burn rate per account. This is what
-- the dashboard's KPI row and the "runway" calculation both read from.

with accounts as (
    select * from {{ ref('dim_accounts') }}
),

txns as (
    select * from {{ ref('fct_transactions') }}
),

net_by_account as (
    select
        account_id,
        sum(case when txn_type = 'credit' then amount else -amount end) as net_movement,
        max(txn_date) as last_txn_date
    from txns
    group by account_id
),

burn_by_account as (
    select
        t.account_id,
        sum(t.amount) / 30.0 as avg_daily_burn
    from txns t
    join net_by_account n on n.account_id = t.account_id
    where t.txn_type = 'debit'
      and t.txn_date >= n.last_txn_date - interval '30 days'
    group by t.account_id
)

select
    a.account_id,
    a.account_name,
    a.account_type,
    a.opening_balance + coalesce(n.net_movement, 0) as current_balance,
    coalesce(b.avg_daily_burn, 0) as avg_daily_burn
from accounts a
left join net_by_account n on n.account_id = a.account_id
left join burn_by_account b on b.account_id = a.account_id
