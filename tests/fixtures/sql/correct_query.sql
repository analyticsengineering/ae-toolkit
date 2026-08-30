with item_totals as (
    select
        order_id,
        sum(quantity * unit_price) as item_revenue
    from order_items
    group by order_id
)
select
    o.order_id,
    o.customer_id,
    coalesce(i.item_revenue, 0) as item_revenue
from orders as o
left join item_totals as i
    on o.order_id = i.order_id;
