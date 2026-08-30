select
    md5(product_id || '-' || vendor_id) as product_key,
    product_id,
    vendor_id,
    product_name
from {{ source('app', 'products') }}
