-- Ticket 10: Timeline and Trends Views

create or replace view patient_timeline_events as
select 
    id as event_id,
    patient_id,
    effective_at as event_time,
    'fact' as event_type,
    fact_type::text as subtype,
    display as title,
    raw_text as description,
    value_num,
    unit,
    state::text
from facts

union all

select
    id as event_id,
    patient_id,
    started_at as event_time,
    'encounter' as event_type,
    'visit' as subtype,
    'Encounter' as title,
    chief_complaint as description,
    null as value_num,
    null as unit,
    status as state
from encounters;
