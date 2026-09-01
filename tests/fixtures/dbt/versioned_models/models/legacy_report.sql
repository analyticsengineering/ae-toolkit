select
    order_id,
    amount
from {{ ref('orders', v=1) }}
