
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
