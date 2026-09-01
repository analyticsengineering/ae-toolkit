select
    product_id,
    product_name
from {{ source('raw', 'products') }}
