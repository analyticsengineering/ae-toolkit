with source as (

    select * from {{ source('app', 'orders') }}

)

select
    order_id
    , customer_id
    , ordered_at
    , order_amount
from source
