with source as (

    select * from {{ source('app', 'refunds') }}

)

select
    refund_id
    , order_id
    , refunded_at
    , refund_amount
from source
