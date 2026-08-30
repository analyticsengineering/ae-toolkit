with source as (

    select * from {{ source('app', 'products') }}

)

select
    product_id
    , product_name
    , list_price
from source
