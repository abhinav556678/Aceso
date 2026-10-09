
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
