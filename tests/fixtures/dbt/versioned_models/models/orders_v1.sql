select
    order_id,
    customer_id,
    amount
from {{ source('raw', 'orders') }}
