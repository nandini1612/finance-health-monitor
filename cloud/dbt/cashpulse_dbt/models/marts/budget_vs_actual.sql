-- Budgeted vs. actual debit spend, per account/category/month. The
-- `budgets` table (via stg_budgets) is the spine here -- a category with no
-- budget set simply doesn't appear, which is the right default: this mart
-- answers "how am I doing against the budgets I set," not "show me every
-- category."

with budgets as (
    select * from {{ ref('stg_budgets') }}
),

actual_spend as (
    select
        account_id,
        to_char(txn_date, 'YYYY-MM') as month,
        category_name,
        sum(amount) as actual_amount
    from {{ ref('fct_transactions') }}
    where txn_type = 'debit'
    group by account_id, to_char(txn_date, 'YYYY-MM'), category_name
)

select
    b.account_id,
    b.month,
    b.category_name,
    b.budgeted_amount,
    coalesce(a.actual_amount, 0) as actual_amount
from budgets b
left join actual_spend a
    on a.account_id = b.account_id
   and a.month = b.month
   and a.category_name = b.category_name
