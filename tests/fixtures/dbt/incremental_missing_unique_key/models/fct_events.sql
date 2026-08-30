{{ config(materialized='incremental') }}

select
    event_id,
    event_type,
    occurred_at
from {{ ref('stg_events') }}
{% if is_incremental() %}
where occurred_at >= (select max(occurred_at) from {{ this }})
{% endif %}
