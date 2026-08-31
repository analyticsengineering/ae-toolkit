with source as (

    select * from {{ source('billing', 'invoices') }}

),

renamed as (

    select
        invoice_id,
        customer_id,
        issued_at,
        amount_cents
    from source

)

select * from renamed
