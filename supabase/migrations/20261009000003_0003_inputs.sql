
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
