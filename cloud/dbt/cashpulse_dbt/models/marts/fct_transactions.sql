-- The fact table everything else in marts/ rolls up from.

with transactions as (
    select * from {{ ref('stg_transactions') }}
),

categories as (
    select * from {{ ref('stg_categories') }}
)

select
    t.transaction_id,
    t.account_id,
    t.txn_date,
    t.merchant_name,
    t.category_name,
    c.category_group,
    t.amount,
    t.txn_type,
    t.description,
    t.is_recurring
from transactions t
left join categories c on c.category_name = t.category_name
