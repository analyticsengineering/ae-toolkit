"""Customer lifetime value.

An earlier draft read dbt.ref("orders_snapshot"), which no longer exists.
"""


def model(dbt, session):
    dbt.config(materialized="table")
    # dbt.ref("orders_backup") was removed when the backup table was dropped.
    customers = dbt.ref("customers", v="beta")
    payments = dbt.source("raw", "payments")
    return customers.join(payments, "customer_id")
