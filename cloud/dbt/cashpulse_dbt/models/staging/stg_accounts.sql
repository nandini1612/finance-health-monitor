-- Staging: one-to-one with the raw table, but typed and column-cleaned.
-- No business logic here -- that's what marts/ is for. Keeping staging
-- "dumb" is a deliberate dbt convention: it means every downstream model
-- can trust that types are already correct.

with source as (
    select * from {{ source('raw', 'raw_accounts') }}
),

renamed as (
    select
        account_ref::int                    as account_id,
        trim(account_name)                  as account_name,
        trim(account_type)                  as account_type,
        trim(owner_name)                    as owner_name,
        coalesce(nullif(trim(currency), ''), 'USD') as currency,
        opening_balance::numeric(12, 2)     as opening_balance
    from source
)

select * from renamed
