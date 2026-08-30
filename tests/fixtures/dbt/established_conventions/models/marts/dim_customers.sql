with customers as (

    select * from {{ ref('stg_customers') }}

)

select
    {{ dbt_utils.generate_surrogate_key(['customer_id']) }} as customer_key
    , customer_id
    , customer_name
    , signed_up_at
from customers
