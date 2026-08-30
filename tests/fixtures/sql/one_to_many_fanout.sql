-- Expected grain: one row per order.
-- order_items is one-to-many from orders; joining before aggregation fans out order_amount.
select
    o.customer_id,
    sum(o.order_amount) as reported_revenue
from orders as o
join order_items as i
    on o.order_id = i.order_id
group by o.customer_id;
