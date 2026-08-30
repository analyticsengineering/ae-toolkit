select
    customer_id,
    order_status,
    sum(order_amount) as revenue
from orders
group by customer_id;
