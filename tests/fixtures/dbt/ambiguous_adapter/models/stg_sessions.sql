select
    session_id,
    tenant_id,
    session_date
from {{ source('app', 'sessions') }}
