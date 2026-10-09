import os

migrations = {
    '20261009000002_0002_core.sql': """
create table profiles (
  id             uuid primary key references auth.users(id) on delete cascade,
  full_name      text not null,
  role           user_role not null,
  registration_no text,                       -- doctor's medical council no. (dummy in demo)
  preferred_lang text default 'en',
  created_at     timestamptz default now()
);

create table patients (
  id             uuid primary key default gen_random_uuid(),
  mrn            text unique not null,
  full_name      text not null,
  dob            date not null,
  sex            text check (sex in ('M','F','O')) not null,
  phone          text,
  abha_id        text,                         -- dummy values only
  preferred_lang text default 'en',            -- en | ta | hi
  created_at     timestamptz default now()
);

create table encounters (
  id             uuid primary key default gen_random_uuid(),
  patient_id     uuid not null references patients(id),
  doctor_id      uuid references profiles(id),
  started_at     timestamptz default now(),
  ended_at       timestamptz,
  status         text default 'in_progress'
                 check (status in ('in_progress','review','signed')),
  chief_complaint text
);
create index on encounters(patient_id, started_at desc);
""",
    '20261009000003_0003_inputs.sql': """
create table audio_recordings (
  id uuid primary key default gen_random_uuid(),
  encounter_id uuid not null references encounters(id),
  storage_path text not null,                  -- bucket: audio
  duration_ms  int,
  language     text,
  status       text default 'uploaded'         -- uploaded|transcribing|done|failed
);

create table transcript_segments (
  id uuid primary key default gen_random_uuid(),
  recording_id uuid not null references audio_recordings(id) on delete cascade,
  seq          int  not null,
  speaker      text,                           -- doctor | patient | unknown
  start_ms     int  not null,
  end_ms       int  not null,
  text         text not null,
  lang         text,
  confidence   real,
  words        jsonb,                          -- [{w, start_ms, end_ms, p}]
  unique (recording_id, seq)
);

create table source_documents (
  id uuid primary key default gen_random_uuid(),
  patient_id   uuid not null references patients(id),
  encounter_id uuid references encounters(id),
  storage_path text not null,                  -- bucket: documents
  kind         text check (kind in ('lab_pdf','prescription','discharge','other')),
  doc_date     date,
  page_count   int,
  ocr_engine   text,
  status       text default 'uploaded'         -- uploaded|ocr_running|done|failed
);

create table ocr_blocks (
  id uuid primary key default gen_random_uuid(),
  document_id uuid not null references source_documents(id) on delete cascade,
  page_no   int  not null,
  block_idx int  not null,
  kind      text default 'line',               -- line | word | table_cell
  text      text not null,
  confidence real,
  x real not null, y real not null, w real not null, h real not null,
  table_ref jsonb,                             -- {table:1,row:3,col:2,header:"Creatinine"}
  unique (document_id, page_no, block_idx)
);
""",
    '20261009000004_0004_facts.sql': """
create table facts (
  id            uuid primary key default gen_random_uuid(),
  patient_id    uuid not null references patients(id),
  encounter_id  uuid references encounters(id),

  fact_type     fact_type not null,
  assertion     fact_assertion not null default 'present',   -- NEGATION HANDLING
  -- normalised identity
  code_system   text,          -- RxNorm | ATC | LOINC | ICD10 | SNOMED | LOCAL
  code          text,
  display       text not null, -- normalised display name, e.g. "Metformin"
  raw_text      text,          -- exactly what was said/printed, e.g. "Glycomet 500"
  -- value payload
  value_num     numeric,
  value_text    text,
  unit          text,          -- UCUM-style
  dose          jsonb,         -- {amount:500, unit:"mg", freq:"BD", route:"PO", duration_days:30}
  effective_at  timestamptz,   -- when the fact is true/was measured (drives the timeline)

  -- lifecycle
  state         fact_state not null default 'extracted',
  confidence    real,
  confidence_parts jsonb,      -- {ocr:0.97, plausibility:1, verification:1}
  needs_attention boolean default false,   -- review-by-exception flag
  attention_reasons text[],
  superseded_by uuid references facts(id),

  -- PROVENANCE (one of the three must be satisfied)
  source        source_kind not null,
  recording_id  uuid references audio_recordings(id),
  segment_ids   uuid[],
  audio_start_ms int,
  audio_end_ms   int,
  document_id   uuid references source_documents(id),
  block_ids     uuid[],
  page_no       int,
  bbox          jsonb,         -- {x,y,w,h} union of cited blocks, normalised

  -- 3-way verification result
  verification  jsonb,         -- {ocr_match:{ok,detail}, transcript_support:{ok,detail}, omission:{...}}

  created_by    text default 'system:pipeline',
  created_at    timestamptz default now(),
  updated_at    timestamptz default now(),

  constraint provenance_required check (
    (source = 'audio'    and recording_id is not null and audio_start_ms is not null
                         and audio_end_ms is not null and segment_ids is not null) or
    (source = 'document' and document_id is not null and page_no is not null and bbox is not null) or
    (source = 'manual')
  )
);
create index facts_patient_type on facts(patient_id, fact_type, effective_at desc);
create index facts_state        on facts(state) where state in ('extracted','verified');
create index facts_code         on facts(code_system, code);

create table fact_chunks (          -- for natural-language search (pgvector)
  id uuid primary key default gen_random_uuid(),
  patient_id uuid not null references patients(id),
  fact_id    uuid references facts(id) on delete cascade,
  segment_id uuid references transcript_segments(id) on delete cascade,
  document_id uuid references source_documents(id) on delete cascade,
  content    text not null,
  metadata   jsonb,                -- {date, type, source_kind, page_no}
  embedding  extensions.vector(384)
);
create index on fact_chunks using hnsw (embedding extensions.vector_cosine_ops);
create index on fact_chunks (patient_id);
create index on fact_chunks using gin (content extensions.gin_trgm_ops);
""",
    '20261009000005_0005_knowledge.sql': """
create table concepts (
  system text not null, code text not null, display text not null,
  synonyms text[] default '{}', primary key (system, code)
);

create table drug_brands (
  brand text primary key,
  generic text not null,
  rxnorm text, atc text,
  default_strength text
);
create index on drug_brands using gin (brand extensions.gin_trgm_ops);

create table allergy_groups (
  group_name text, member_generic text, primary key (group_name, member_generic)
);

create table reference_ranges (
  loinc text, sex text default 'any', age_min int default 0, age_max int default 120,
  low numeric, high numeric,
  plausible_min numeric, plausible_max numeric,
  unit text, primary key (loinc, sex, age_min)
);

create table drug_interactions (
  id serial primary key,
  drug_a text not null, drug_b text not null,
  severity text check (severity in ('contraindicated','major','moderate','minor')),
  description text,
  source text not null, source_ref text,
  unique (drug_a, drug_b)
);

create table dose_limits (
  generic text, route text default 'PO', population text default 'adult',
  max_single_mg numeric, max_daily_mg numeric,
  source text not null, primary key (generic, route, population)
);

create table safety_rules (
  id text primary key,
  title text not null,
  rule_type text not null,
  guideline_source text not null,
  version text default '1',
  severity text check (severity in ('critical','high','moderate','info')),
  rule jsonb not null,
  clinician_reviewed_by text,
  active boolean default true
);

create table safety_alerts (
  id uuid primary key default gen_random_uuid(),
  patient_id uuid not null references patients(id),
  encounter_id uuid references encounters(id),
  rule_id text references safety_rules(id),
  severity text, message text not null,
  status alert_status default 'open',
  trigger_fact_ids uuid[] not null,
  trace jsonb not null,
  created_at timestamptz default now(),
  resolved_by uuid references profiles(id), resolved_at timestamptz,
  override_reason text
);
create index on safety_alerts(patient_id, status);
""",
    '20261009000006_0006_workflow.sql': """
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
""",
    '20261009000007_0007_audit_lifecycle.sql': """
create table audit_log (
  id          bigserial primary key,
  at          timestamptz not null default now(),
  actor_id    uuid,
  actor_label text,
  actor_role  text,
  action      text not null,
  entity_type text not null, entity_id uuid, patient_id uuid,
  from_state  text, to_state text,
  payload     jsonb,
  prev_hash   text, row_hash text
);

create or replace function audit_chain() returns trigger language plpgsql as $$
declare last_hash text;
begin
  perform pg_advisory_xact_lock(727001);
  select row_hash into last_hash from audit_log order by id desc limit 1;
  new.prev_hash := coalesce(last_hash,'GENESIS');
  new.row_hash  := encode(extensions.digest(
      new.prev_hash || extract(epoch from new.at)::text || coalesce(new.actor_label,'') || new.action ||
      new.entity_type || coalesce(new.entity_id::text,'') || coalesce(new.payload::text,''),
      'sha256'),'hex');
  return new;
end $$;
create trigger audit_chain_t before insert on audit_log
  for each row execute function audit_chain();

create or replace function audit_immutable() returns trigger language plpgsql as $$
begin raise exception 'audit_log is append-only'; end $$;
create trigger audit_no_update before update or delete on audit_log
  for each row execute function audit_immutable();
create trigger audit_no_truncate before truncate on audit_log
  for each statement execute function audit_immutable();

create or replace function public.app_role() returns user_role
language sql stable security definer set search_path = public as
$$ select role from profiles where id = auth.uid() $$;

create or replace function facts_guard() returns trigger language plpgsql as $$
declare r user_role := public.app_role();
begin
  new.updated_at := now();
  if new.state is distinct from old.state then
    if not (
      (old.state='extracted' and new.state in ('verified','rejected')) or
      (old.state='verified'  and new.state in ('clinician_confirmed','rejected')) or
      (old.state='clinician_confirmed' and new.state='superseded') or
      (old.state in ('extracted','verified') and new.state='superseded')
    ) then
      raise exception 'Illegal fact transition % -> %', old.state, new.state;
    end if;
    if new.state='clinician_confirmed' and r is distinct from 'doctor' then
      raise exception 'Only a doctor can confirm a fact';
    end if;
  end if;
  return new;
end $$;
create trigger facts_guard_t before update on facts
  for each row execute function facts_guard();

create or replace function facts_audit() returns trigger language plpgsql as $$
declare v_from text := null; v_action text := 'fact.created';
begin
  if tg_op = 'UPDATE' then v_from := old.state::text; v_action := 'fact.state_change'; end if;
  insert into audit_log(actor_id, actor_label, actor_role, action, entity_type,
                        entity_id, patient_id, from_state, to_state, payload)
  values (auth.uid(),
          coalesce((select full_name from profiles where id=auth.uid()),
                   nullif(current_setting('app.actor', true),''), 'system:pipeline'),
          public.app_role()::text, v_action, 'fact', new.id, new.patient_id,
          v_from, new.state::text,
          jsonb_build_object('type',new.fact_type,'display',new.display,'assertion',new.assertion));
  return new;
end $$;
create trigger facts_audit_ins after insert on facts
  for each row execute function facts_audit();
create trigger facts_audit_upd after update of state on facts
  for each row when (old.state is distinct from new.state) execute function facts_audit();

create or replace function verify_audit_chain() returns table(ok boolean, broken_at bigint)
language plpgsql security definer as $$
declare r record; prev text := 'GENESIS'; h text;
begin
  for r in select * from audit_log order by id loop
    h := encode(extensions.digest(prev || extract(epoch from r.at)::text || coalesce(r.actor_label,'') || r.action ||
         r.entity_type || coalesce(r.entity_id::text,'') || coalesce(r.payload::text,''),'sha256'),'hex');
    if r.prev_hash is distinct from prev or r.row_hash is distinct from h then
      return query select false, r.id; return; end if;
    prev := r.row_hash;
  end loop;
  return query select true, null::bigint;
end $$;
""",
    '20261009000008_0008_rls.sql': """
do $$ declare t text; begin
  foreach t in array array['profiles','patients','encounters','audio_recordings',
   'transcript_segments','source_documents','ocr_blocks','facts','fact_chunks',
   'safety_alerts','soap_notes','note_edits','patient_exports','open_loops',
   'audit_log','jobs','eval_runs','eval_results'] loop
    execute format('alter table %I enable row level security', t);
  end loop; end $$;

create policy read_all on concepts           for select to authenticated using (true);
create policy read_all on drug_brands        for select to authenticated using (true);
create policy read_all on reference_ranges   for select to authenticated using (true);
create policy read_all on drug_interactions  for select to authenticated using (true);
create policy read_all on safety_rules       for select to authenticated using (true);
do $$ declare t text; begin
  foreach t in array array['concepts','drug_brands','allergy_groups','reference_ranges',
                           'drug_interactions','dose_limits','safety_rules'] loop
    execute format('alter table %I enable row level security', t);
  end loop; end $$;
create policy read_all on allergy_groups for select to authenticated using (true);
create policy read_all on dose_limits    for select to authenticated using (true);

create policy profiles_self on profiles for select to authenticated
  using (id = auth.uid() or public.app_role()='admin');

create policy patients_read on patients for select to authenticated using (public.app_role() is not null);
create policy patients_admin_write on patients for all to authenticated
  using (public.app_role()='admin') with check (public.app_role()='admin');

do $$ declare t text; begin
  foreach t in array array['encounters','audio_recordings','transcript_segments',
   'source_documents','ocr_blocks','facts','fact_chunks','safety_alerts','soap_notes',
   'note_edits','patient_exports','open_loops'] loop
    execute format($f$create policy clin_rw on %I for all to authenticated
      using (public.app_role() in ('doctor','nurse'))
      with check (public.app_role() in ('doctor','nurse'))$f$, t);
  end loop; end $$;

create policy audit_admin_read on audit_log for select to authenticated using (public.app_role()='admin');
"""
}

for name, content in migrations.items():
    with open(f'supabase/migrations/{name}', 'w', encoding='utf-8') as f:
        f.write(content)
