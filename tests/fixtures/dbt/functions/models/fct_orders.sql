select
    order_id,
    {{ ref('stg_orders') }}.amount_cents,
    cents_to_dollars(amount_cents) as amount
from {{ ref('stg_orders') }}
