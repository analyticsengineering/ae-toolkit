with source as (

    select * from {{ source('app', 'customers') }}

)

select
    customer_id
    , customer_name
from source
