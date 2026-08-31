with invoices as (

    select * from {{ ref('stg_invoices') }}

),

adjustments as (

    select * from {{ ref('shared_finance', 'stg_adjustments') }}

)

select
    invoices.invoice_id,
    invoices.customer_id,
    invoices.amount_cents - coalesce(adjustments.amount_cents, 0) as net_amount_cents
from invoices
left join adjustments
    on invoices.invoice_id = adjustments.invoice_id
