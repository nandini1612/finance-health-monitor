with source as (
    select * from {{ source('raw', 'raw_merchants') }}
),

renamed as (
    select
        md5(trim(merchant_name)) as merchant_id,
        trim(merchant_name) as merchant_name,
        trim(default_category) as default_category
    from source
)

select * from renamed
