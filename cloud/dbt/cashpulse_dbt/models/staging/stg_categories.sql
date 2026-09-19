-- Surrogate keys are hand-rolled with md5() rather than pulling in the
-- dbt_utils package, keeping this project dependency-free -- swap in
-- dbt_utils.generate_surrogate_key() if your team already standardizes on it.

with source as (
    select * from {{ source('raw', 'raw_categories') }}
),

renamed as (
    select
        md5(trim(category_name)) as category_id,
        trim(category_name) as category_name,
        trim(category_group) as category_group
    from source
)

select * from renamed
