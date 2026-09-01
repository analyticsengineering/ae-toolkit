select
    customer_id,
    customer_name,
    signed_up_at
from {{ source('raw', 'customers') }}
