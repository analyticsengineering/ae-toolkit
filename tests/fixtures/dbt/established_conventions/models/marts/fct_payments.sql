with payments as (

    select * from {{ ref('stg_payments') }}

)

select
    {{ dbt_utils.generate_surrogate_key(['payment_id']) }} as payment_key
    , payment_id
    , order_id
    , paid_at
    , payment_amount
from payments
