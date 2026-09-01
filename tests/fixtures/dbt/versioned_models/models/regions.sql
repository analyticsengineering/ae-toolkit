select
    region_id,
    region_name
from {{ source('raw', 'regions') }}
