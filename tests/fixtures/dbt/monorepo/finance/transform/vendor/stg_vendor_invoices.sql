-- A model about vendors. The directory name matches packages-install-path,
-- but this file is the team's own code and must be validated as such.
select
    vendor_id,
    invoice_id,
    amount
from {{ source('billing', 'invoices') }}
