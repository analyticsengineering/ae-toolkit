select
    order_id,
    customer_id,
    order_amount
from {{ source('app', 'orders') }}
