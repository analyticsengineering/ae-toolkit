-- Anti-pattern: a mart bypasses staging and reads a raw source directly.
select
    payment_id,
    order_id,
    amount
from {{ source('raw_payments', 'payments') }}
