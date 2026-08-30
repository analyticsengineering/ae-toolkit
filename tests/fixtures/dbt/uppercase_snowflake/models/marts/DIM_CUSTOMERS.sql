WITH CUSTOMERS AS (

    SELECT * FROM {{ ref('STG_CUSTOMERS') }}

), KEYED AS (

    SELECT
        {{ dbt_utils.generate_surrogate_key(['CUSTOMER_ID']) }} AS CUSTOMER_KEY,
        CUSTOMER_ID,
        CUSTOMER_NAME
    FROM CUSTOMERS

)

SELECT * FROM KEYED
