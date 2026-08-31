{% macro dbt_utils_surrogate_key(field_list) %}
SELECT MD5(CONCAT({{ field_list | join(', ') }}))
{% endmacro %}
