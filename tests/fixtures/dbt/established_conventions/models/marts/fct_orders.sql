with orders as (

    select * from {{ ref('stg_orders') }}

)

select
    {{ dbt_utils.generate_surrogate_key(['order_id']) }} as order_key
    , order_id
    , customer_id
    , ordered_at
    , order_amount
from orders
