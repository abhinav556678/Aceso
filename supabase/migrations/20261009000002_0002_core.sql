
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
