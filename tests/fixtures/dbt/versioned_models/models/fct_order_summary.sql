-- The old shape lived in ref('orders_legacy_export') before the version cutover.
{# and ref('orders_scratch') was a temporary experiment #}
/* ref('orders_archive') was dropped in 2024 */
select
    o.order_id,
    c.customer_name,
    o.amount
from {{ ref('orders') }} as o
inner join {{ ref('customers', v='beta') }} as c
    on o.customer_id = c.customer_id
