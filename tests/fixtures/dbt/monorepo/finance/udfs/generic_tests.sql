{% test positive_amount(model, column_name) %}

select *
from {{ model }}
where {{ column_name }} < 0

{% endtest %}

{% macro cents_to_dollars(column_name) %}
    ({{ column_name }} / 100.0)
{% endmacro %}
