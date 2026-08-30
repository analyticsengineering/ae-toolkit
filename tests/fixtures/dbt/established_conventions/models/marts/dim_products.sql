with products as (

    select * from {{ ref('stg_products') }}

)

select
    {{ dbt_utils.generate_surrogate_key(['product_id']) }} as product_key
    , product_id
    , product_name
    , list_price
from products
