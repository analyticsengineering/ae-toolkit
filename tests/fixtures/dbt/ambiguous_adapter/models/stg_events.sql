select
    event_id,
    tenant_id,
    event_date,
    payload
from {{ source('app', 'events') }}
