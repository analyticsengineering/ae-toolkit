select unique_id
from {{ info_schema('models') }}
where description = ''
