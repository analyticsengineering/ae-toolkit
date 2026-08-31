select *
from {{ ref('fct_revenue', v=2) }}
where net_amount_cents < 0
