{{
    config(
        materialized='incremental',
        incremental_strategy='merge',
        partition_by='session_date'
    )
}}

select
    session_id,
    tenant_id,
    session_date
from {{ ref('stg_sessions') }}
