with source as (

    select * from {{ source('app', 'orders') }}

)

select
    {{ dbt_utils.generate_surrogate_key(['order_id']) }} as order_key
    , order_id
    , ordered_at
from source
