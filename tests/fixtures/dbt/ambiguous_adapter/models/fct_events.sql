{{
    config(
        materialized='incremental',
        incremental_strategy='append',
        partition_by='event_date',
        cluster_by=['tenant_id']
    )
}}

select
    event_id,
    tenant_id,
    event_date,
    payload
from {{ ref('stg_events') }}

{% if is_incremental() %}
where event_date > (select max(event_date) from {{ this }})
{% endif %}
