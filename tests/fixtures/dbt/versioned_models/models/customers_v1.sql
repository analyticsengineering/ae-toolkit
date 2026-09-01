select
    customer_id,
    customer_name
from {{ source('raw', 'customers') }}
