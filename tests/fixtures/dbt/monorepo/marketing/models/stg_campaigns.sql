select
    campaign_id,
    campaign_name,
    started_at
from {{ source('ads', 'campaigns') }}
