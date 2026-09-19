select
    account_id,
    to_char(txn_date, 'YYYY-MM') as month,
    category_name,
    category_group,
    sum(amount) as total_amount,
    count(*) as txn_count
from {{ ref('fct_transactions') }}
where txn_type = 'debit'
group by account_id, to_char(txn_date, 'YYYY-MM'), category_name, category_group
