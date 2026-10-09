-- Prototype additions: file storage in-DB, job progress, alert idempotency,
-- signed-note lock, and the timeline view from the build guide (§13.3).

alter table source_documents
  add column if not exists original_name text,
  add column if not exists error text,
  add column if not exists created_at timestamptz default now();

alter table audio_recordings
  add column if not exists original_name text,
  add column if not exists error text,
  add column if not exists created_at timestamptz default now();

alter table jobs
  add column if not exists patient_id uuid,
  add column if not exists encounter_id uuid,
  add column if not exists stage text,
  add column if not exists result jsonb;

-- Uploaded PDFs/audio live in the database so all three machines see the same
-- files without configuring Storage buckets. Swap for Supabase Storage later.
create table if not exists file_blobs (
  owner_id   uuid primary key,                -- source_documents.id or audio_recordings.id
  owner_kind text not null check (owner_kind in ('document','audio')),
  mime       text,
  content    bytea not null,
  created_at timestamptz default now()
);
alter table file_blobs enable row level security;

-- Idempotent alerts: one live alert per (patient, rule, trigger fact set).
alter table safety_alerts add column if not exists dedupe_key text;
create unique index if not exists safety_alerts_dedupe
  on safety_alerts(patient_id, dedupe_key) where status <> 'resolved';

-- A signed note is immutable (§14.2).
create or replace function lock_signed_note() returns trigger language plpgsql as $$
begin
  if old.status='signed' and (new.subjective,new.objective,new.assessment,new.plan)
        is distinct from (old.subjective,old.objective,old.assessment,old.plan) then
    raise exception 'Signed note is immutable; create an amendment (new version)';
  end if;
  return new;
end $$;
drop trigger if exists lock_signed_note_t on soap_notes;
create trigger lock_signed_note_t before update on soap_notes
  for each row execute function lock_signed_note();

-- Timeline: visits, documents, facts and alerts in one stream.
drop view if exists patient_timeline_events;
create or replace view patient_timeline_v with (security_invoker = true) as
  select patient_id, started_at as at, 'encounter' as kind, id as ref_id,
         coalesce(chief_complaint,'Visit') as title, status as state from encounters
  union all
  select patient_id, coalesce(doc_date::timestamptz, created_at), 'document', id,
         coalesce(original_name, kind || ' document'), status from source_documents
  union all
  select patient_id, effective_at, 'fact:'||fact_type::text, id,
         case when assertion = 'denied' then 'Denied: ' else '' end || display ||
         coalesce(' '||value_num::text||' '||coalesce(unit,''),''),
         state::text
  from facts where effective_at is not null and state not in ('rejected','superseded')
  union all
  select patient_id, created_at, 'alert', id, message, status::text from safety_alerts;

alter view open_loops_v set (security_invoker = true);
