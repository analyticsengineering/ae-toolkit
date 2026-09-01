select 1
from {{ ref('fct_order_summary') }}
having count(*) = 0
