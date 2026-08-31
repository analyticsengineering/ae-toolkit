select *
from {{ source('jaffle_shop', 'raw_stores') }}
