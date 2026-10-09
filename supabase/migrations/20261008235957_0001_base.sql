create extension if not exists pgcrypto  with schema extensions;
create extension if not exists vector    with schema extensions;
create extension if not exists pg_trgm   with schema extensions;

create type user_role      as enum ('doctor','nurse','admin');
create type fact_type      as enum ('allergy','medication','lab_result','diagnosis',
                                    'vital','symptom','history','plan_item');
create type fact_assertion as enum ('present','denied','uncertain');  -- "not mentioned" = no row
create type fact_state     as enum ('extracted','verified','clinician_confirmed',
                                    'rejected','superseded');
create type source_kind    as enum ('audio','document','manual');
create type job_status     as enum ('queued','running','done','failed');
create type alert_status   as enum ('open','acknowledged','overridden','resolved');
create type note_status    as enum ('draft','in_review','signed');
