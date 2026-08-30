select
    payment_id,
    order_id,
    payment_amount
from {{ source('app', 'payments') }}
