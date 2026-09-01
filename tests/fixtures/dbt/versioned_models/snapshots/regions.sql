{% snapshot regions %}
{{ config(unique_key='region_id', strategy='check', check_cols=['region_name']) }}
select * from {{ source('raw', 'regions') }}
{% endsnapshot %}
