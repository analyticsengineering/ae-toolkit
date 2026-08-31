def model(dbt, session):
    dbt.config(materialized="table")
    revenue = dbt.ref("fct_revenue", v=2)
    invoices = dbt.ref("stg_invoices")
    adjustments = dbt.source("billing", "refunds")

    joined = revenue.join(invoices, on="invoice_id", how="left")
    return joined.join(adjustments, on="invoice_id", how="left")
