-- One row per (account, merchant) that has at least one transaction flagged
-- is_recurring -- the "Subscriptions" panel reads this directly. Surfaces
-- the typical charge amount (average across all occurrences) alongside the
-- most recent charge, so the dashboard can flag a merchant whose amount
-- just moved -- the classic "your subscription price went up" signal.

with recurring as (
    select * from {{ ref('fct_transactions') }}
    where is_recurring = true
      and txn_type = 'debit'
),

agg as (
    select
        account_id,
        merchant_name,
        count(*) as occurrence_count,
        round(avg(amount), 2) as typical_amount,
        max(txn_date) as last_txn_date
    from recurring
    group by account_id, merchant_name
),

ranked as (
    select
        account_id,
        merchant_name,
        amount,
        row_number() over (partition by account_id, merchant_name order by txn_date desc) as rn
    from recurring
)

select
    a.account_id,
    a.merchant_name,
    a.occurrence_count,
    a.typical_amount,
    a.last_txn_date,
    r.amount as last_amount
from agg a
join ranked r
    on r.account_id = a.account_id
   and r.merchant_name = a.merchant_name
   and r.rn = 1
