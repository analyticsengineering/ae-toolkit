with refunds as (

    select * from {{ ref('stg_refunds') }}

)

select
    {{ dbt_utils.generate_surrogate_key(['refund_id']) }} as refund_key
    , refund_id
    , order_id
    , refunded_at
    , refund_amount
from refunds
