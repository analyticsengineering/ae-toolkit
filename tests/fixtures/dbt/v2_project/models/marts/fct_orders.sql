select order_id, customer_id, ordered_at from {{ ref('stg_orders') }}
