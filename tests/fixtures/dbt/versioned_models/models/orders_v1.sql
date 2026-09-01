-- Only this version still reads the legacy payments feed. Version 2 dropped it,
-- so a change to that source must not select every version of orders.
select
    orders.order_id,
    orders.customer_id,
    orders.amount,
    payments.paid_at
from {{ source('raw', 'orders') }} as orders
left join {{ source('raw', 'payments') }} as payments
    on payments.order_id = orders.order_id
