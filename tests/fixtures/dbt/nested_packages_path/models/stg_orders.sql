select
    order_id,
    amount
from {{ source('raw', 'orders') }}
