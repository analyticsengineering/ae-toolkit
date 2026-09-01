select
    order_id,
    amount_cents
from {{ source('raw', 'orders') }}
