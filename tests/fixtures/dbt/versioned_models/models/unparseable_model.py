def model(dbt, session):
    dbt.config(materialized="table")
    orders = dbt.ref("orders"
    return orders
