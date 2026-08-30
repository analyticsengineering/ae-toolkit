select
    customer_id,
    order_id,
    row_number() over (
        partition by customer_id
        order by ordered_at desc, order_id desc
    ) as recency_rank
from orders;
