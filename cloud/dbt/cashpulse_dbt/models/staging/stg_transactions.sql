-- The one staging model with real cleaning logic, because the raw
-- transaction feed is the messiest input (this mirrors real ingestion:
-- amounts and flags often arrive as strings). Bad rows are dropped here
-- and counted, rather than silently propagating a NULL amount downstream.
--
-- transaction_id comes straight from source_txn_id (the source system's own
-- id, carried through from data/generate_data.py). We deliberately do NOT
-- derive it from a hash of the other columns: several intentional test
-- transactions share identical amount/merchant/date (that's the duplicate-
-- charge anomaly pattern by design), so a content hash would collide, and a
-- row_number()-based id would silently reshuffle on every rebuild since this
-- model is a view. A real source system's primary key is the right anchor;
-- we synthesize one here because our generator is standing in for that system.

with source as (
    select * from {{ source('raw', 'raw_transactions') }}
),

cleaned as (
    select
        source_txn_id::bigint     as transaction_id,
        account_ref::int          as account_id,
        txn_date::date            as txn_date,
        trim(merchant_name)       as merchant_name,
        trim(category_name)       as category_name,
        amount::numeric(12, 2)    as amount,
        lower(trim(txn_type))     as txn_type,
        description,
        (is_recurring = '1')      as is_recurring
    from source
    where amount ~ '^[0-9.]+$'                       -- drop rows where amount isn't numeric
      and lower(trim(txn_type)) in ('credit', 'debit') -- drop rows with a bad txn_type
      and txn_date is not null
)

select * from cleaned
