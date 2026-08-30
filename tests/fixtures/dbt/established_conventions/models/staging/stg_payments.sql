with source as (

    select * from {{ source('app', 'payments') }}

)

select
    payment_id
    , order_id
    , paid_at
    , payment_amount
from source
