with source as (

    select * from {{ source('app', 'customers') }}

)

select
    customer_id
    , customer_name
    , signed_up_at
from source
