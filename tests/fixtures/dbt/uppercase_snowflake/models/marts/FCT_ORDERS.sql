WITH ORDERS AS (

    SELECT * FROM {{ ref('STG_ORDERS') }}

), CUSTOMERS AS (

    SELECT * FROM {{ ref('STG_CUSTOMERS') }}

), JOINED AS (

    SELECT
        {{ dbt_utils.generate_surrogate_key(['O.ORDER_ID']) }} AS ORDER_KEY,
        O.ORDER_ID,
        O.CUSTOMER_ID,
        O.ORDER_AMOUNT
    FROM ORDERS AS O
    LEFT JOIN CUSTOMERS AS C
        ON O.CUSTOMER_ID = C.CUSTOMER_ID

)

SELECT * FROM JOINED
