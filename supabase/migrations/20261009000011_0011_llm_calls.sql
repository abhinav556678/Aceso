-- What left the machine: one row per language-model call, holding the exact
-- prompt that was handed to the model adapter (after redaction). The SHA-256 is
-- also written to the hash-chained audit log (action llm.call), so an edited
-- payload no longer matches its audit row.

create table if not exists llm_calls (
  id             uuid primary key default gen_random_uuid(),
  job_id         uuid not null references jobs(id) on delete cascade,
  patient_id     uuid,
  seq            int  not null,
  model          text not null,
  prompt_version text,
  system_prompt  text not null,
  user_message   text not null,
  sha256         text not null,                -- of system_prompt || E'\n\n' || user_message
  units          jsonb not null,               -- [{unit:"B3", kind, ref:<source row id>, sent, spans:[[start,end,label]]}]
  redacted       jsonb,                        -- {"PERSON":2,"MRN":1}
  error          text,
  created_at     timestamptz default now(),
  unique (job_id, seq)
);
alter table llm_calls enable row level security;
