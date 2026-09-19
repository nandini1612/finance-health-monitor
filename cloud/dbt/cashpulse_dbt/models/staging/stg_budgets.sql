with source as (
    select * from {{ source('raw', 'raw_budgets') }}
),

renamed as (
    select
        account_ref::int               as account_id,
        trim(category_name)            as category_name,
        month                           as month,
        budgeted_amount::numeric(12, 2) as budgeted_amount
    from source
)

select * from renamed
