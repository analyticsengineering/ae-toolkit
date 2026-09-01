-- Shares its directory name with the last segment of packages-install-path.
select
    vendor_id,
    paid_at
from {{ source('raw', 'orders') }}
