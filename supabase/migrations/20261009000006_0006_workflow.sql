
create table soap_notes (
  id uuid primary key default gen_random_uuid(),
  encounter_id uuid not null references encounters(id),
  version int not null default 1,
  subjective jsonb, objective jsonb, assessment jsonb, plan jsonb,
  status note_status default 'draft',
  generated_by text,
  signed_by uuid references profiles(id), signed_at timestamptz,
  content_hash text,
  unique (encounter_id, version)
);

create table note_edits (
  id uuid primary key default gen_random_uuid(),
  note_id uuid references soap_notes(id), doctor_id uuid references profiles(id),
  section text, ai_text text, final_text text,
  edit_ratio real,
  created_at timestamptz default now()
);

create table patient_exports (
  id uuid primary key default gen_random_uuid(),
  encounter_id uuid references encounters(id), lang text, template_version text,
  payload jsonb not null,
  rendered_html text, created_at timestamptz default now()
);

create table open_loops (
  id uuid primary key default gen_random_uuid(),
  patient_id uuid references patients(id), encounter_id uuid references encounters(id),
  fact_id uuid references facts(id),
  description text not null,
  due_date date,
  status text default 'open' check (status in ('open','done','cancelled')),
  closed_by_fact_id uuid references facts(id)
);
create view open_loops_v as
  select *, (status='open' and due_date < current_date) as overdue from open_loops;

create table jobs (
  id uuid primary key default gen_random_uuid(),
  kind text not null,
  payload jsonb not null,
  status job_status default 'queued',
  attempts int default 0, error text,
  locked_at timestamptz, created_at timestamptz default now()
);
create index on jobs(status, created_at);

create table eval_runs (
  id uuid primary key default gen_random_uuid(),
  created_at timestamptz default now(), git_sha text, llm_id text, notes text,
  metrics jsonb
);
create table eval_results (
  id uuid primary key default gen_random_uuid(),
  run_id uuid references eval_runs(id) on delete cascade,
  patient_id uuid, category text, expected jsonb, actual jsonb, passed boolean, detail text
);
