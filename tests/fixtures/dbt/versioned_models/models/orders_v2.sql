-- A versioned model that is itself a consumer of another versioned model.
select
    orders.order_id,
    orders.customer_id,
    orders.amount,
    orders.ordered_at,
    customers.customer_name
from {{ source('raw', 'orders') }} as orders
left join {{ ref('customers', v='beta') }} as customers
    on customers.customer_id = orders.customer_id
