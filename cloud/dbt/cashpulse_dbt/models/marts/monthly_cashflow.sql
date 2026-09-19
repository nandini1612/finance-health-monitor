-- Equivalent to v_monthly_cashflow in the local-quickstart SQLite schema --
-- same business logic, now expressed (and tested) as a dbt model.

select
    account_id,
    to_char(txn_date, 'YYYY-MM') as month,
    sum(case when txn_type = 'credit' then amount else 0 end) as total_income,
    sum(case when txn_type = 'debit'  then amount else 0 end) as total_expense,
    sum(case when txn_type = 'credit' then amount else -amount end) as net_flow
from {{ ref('fct_transactions') }}
group by account_id, to_char(txn_date, 'YYYY-MM')
