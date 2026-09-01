select
    event_id,
    _loaded_at
from {{ source('app', 'events') }}
