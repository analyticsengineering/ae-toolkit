-- This excludes NULL statuses because SQL uses three-valued logic.
select order_id, order_status
from orders
where order_status <> 'cancelled';
