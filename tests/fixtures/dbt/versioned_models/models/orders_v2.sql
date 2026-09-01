select
    order_id,
    customer_id,
    amount,
    ordered_at
from {{ source('raw', 'orders') }}
