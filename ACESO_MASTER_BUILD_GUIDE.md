# ACESO — Master Build Guide
*AI-Native EMR for Intelligent Clinical Assistance · District 04 · End-to-end build steps, from empty repo to demo*

---

## 0. How to read this document

This is the single source of truth for building ACESO. It merges two inputs:

| Input | What we take from it |
|---|---|
| **Solution Blueprint** (original project context) | The three problems, the three pillars, and the **technical implementation architecture** (ingestion → storage/search/timeline → clinical intelligence/safety → governance/HITL). Its module structure is our build skeleton. |
| **ACESO Master Architecture** (revised) | The **new tech stack and design choices**: Fact-First Generation, claim-level provenance, 3-way verification, longitudinal fact store with fact lifecycle, deterministic safety engine + explainability trace, templated patient export, review-by-exception UI, evaluation harness, secondary features. |
| **This guide's one infrastructure change** | **Supabase replaces a self-hosted PostgreSQL.** Reason: the team works on 3 different machines, so one shared, cloud-hosted database avoids "works on my machine" drift. |

> **A note on Supabase vs PostgreSQL.** Supabase *is* PostgreSQL under the hood, hosted for you, bundled with Auth, Storage, Realtime and `pgvector`. What you are avoiding is *installing and syncing a local Postgres on three machines*. Everything in this guide that says "SQL" runs on the shared Supabase project. Nobody installs Postgres locally.

### Phase map (where everything lives)

| Phase | Section | Topic |
|---|---|---|
| 0 | §4 | Foundations: Supabase project, repo, env, team workflow |
| 1 | §5 | Supabase schema, fact lifecycle triggers, RLS, immutable audit log |
| 2 | §6 | Dummy database: six synthetic scenarios, golden data, ground truth |
| 3 | §7 | Backend skeleton, job queue, speech-to-text, OCR with bounding boxes |
| 4 | §8 | Fact extraction, terminology normalization, negation |
| 5 | §9 | Three-way verification pass, confidence scoring |
| 6 | §10 | Fact store logic, contradiction engine, safety engine, explainability trace |
| 7 | §11 | SOAP generation from verified facts |
| 8 | §12 | **UI/UX design system and every screen** |
| 9 | §13 | Search, timeline, trends, open loops, gap prompts, edit-diff, patient summary |
| 10 | §14 | RBAC, sign-off, FHIR/ABDM, privacy gateway, templated patient summary |
| 11 | §15 | Integration and end-to-end hardening |
| 12 | §16 | Stretch: code-mixed multilingual scribe |
| 13 | §17 | Evaluation harness |
| 14 | §18 | Testing, deployment, demo script |
| — | §19, Appendices | Milestones, risks, API list, coverage matrix, commands, ship checklist |

### Conventions
- **Phase** = a build stage. **Step** = a concrete action. **Done when** = acceptance check you can actually run.
- 🅰 🅱 🅲 mark the suggested owner of each phase (see §4.3). Reassign freely.
- Code blocks are starting points, not finished code. Clinical content (rules, thresholds, templates) **must be reviewed by a clinician** before you present it as real guidance.

---

## 1. Product recap (so every builder shares the same mental model)

### 1.1 Problems → Pillars → Modules

| Problem (Blueprint Part 1) | Pillar (Blueprint Part 2) | ACESO modules that deliver it |
|---|---|---|
| Heavy administrative burden | 1. AI-assisted documentation & workflow automation | Audio scribe, OCR, SOAP generation, open-loop tracker, patient export |
| Fragmented, hard-to-navigate data | 2. Intelligent data organization & advanced search | Longitudinal fact store, timeline, trend analysis, natural-language search |
| Safety, compliance, error risk | 3. Safety, governance & clinical oversight | Deterministic safety engine, explainability trace, contradiction engine, RBAC, audit log, mandatory sign-off |

### 1.2 The Swap Test (design rule for every decision)
> *If a judge swaps our LLM for a different one, does the product still have unique value?*

Therefore: **the LLM does exactly one job (structured extraction, plus constrained note wording).** Everything that creates trust — provenance, verification, fact lifecycle, safety rules, eGFR math, explain traces, templates, audit — is deterministic code and data we own. Never let an LLM decide "is this drug safe?".

### 1.3 Non-negotiable rules (print these)
1. **Facts first, prose second.** Extract and verify facts → *then* generate SOAP from those facts.
2. **Every fact carries provenance** (audio `[start:end]` or document page + bounding box). No provenance → the database rejects the fact.
3. **Safety engine reads only `verified` / `clinician_confirmed` facts.**
4. **Never auto-collapse** allergies, dosages, or new medications in the UI.
5. **Nothing becomes the official record without a doctor's sign-off.**
6. **Patient-facing text is templated from structured data**, never LLM-translated.
7. **Every state change is appended to an immutable audit log.**
8. **PHI is redacted before any external API call.**

---

## 2. Final technology stack

| Layer | Choice | Notes / alternatives |
|---|---|---|
| **Database + Auth + Storage + Realtime + Vector** | **Supabase** (Postgres 15+, `pgvector`, Row Level Security, Storage buckets, Realtime) | One shared cloud project for all 3 machines |
| **Frontend** | Next.js (App Router) + TypeScript + Tailwind CSS + shadcn/ui | `@supabase/ssr` for auth; `recharts` for trends; `react-pdf`/`pdfjs-dist` for bbox overlay; `wavesurfer.js` for audio spans; `@tanstack/react-query` |
| **Backend / AI pipeline** | Python 3.11 + FastAPI + Pydantic | Pipeline stages, safety engine, export, eval harness live here |
| **Job queue** | `jobs` table in Supabase + Python worker (`FOR UPDATE SKIP LOCKED`) | No Redis needed; works from any of the 3 machines |
| **Speech-to-text** | Whisper via `faster-whisper` (word timestamps) · fallback: OpenAI Whisper API | Blueprint: "OpenAI Whisper or medical transcription models" |
| **OCR / document parsing** | Azure Document Intelligence (layout + handwriting) · fallback: Tesseract (`pytesseract.image_to_data`) + vision-language model | Must return **bounding boxes** |
| **LLM** | Behind a thin `LLMClient` adapter (any provider, plus on-prem Ollama fallback) | The adapter *is* the Swap Test |
| **Embeddings** | `intfloat/multilingual-e5-small` (384-dim) | Handles Tamil/Hindi/English; matches `vector(384)` in schema |
| **Terminology** | RxNorm / ATC (drugs), LOINC (labs), ICD-10 / SNOMED CT (diagnoses) + our Indian brand→generic dictionary | Loaded as tables in Supabase |
| **Interaction / dose data** | An open interaction dataset (e.g., DDInter) + hand-curated dose limits, loaded into Supabase tables | **Verify the dataset's license and download terms** before use |
| **Computed metrics** | CKD-EPI 2021 (race-free) eGFR in pure Python | Rules are written against eGFR, not raw creatinine |
| **PHI redaction** | Microsoft Presidio + custom Indian regexes (phone, Aadhaar, ABHA) | Runs inside the Privacy Gateway |
| **Interoperability** | FHIR R4 bundles aligned to ABDM (NRCeS) profiles | Validate with the HAPI FHIR validator; check current ABDM profile versions |
| **Patient export** | Jinja2 templates (en / ta / hi) → HTML → browser print-to-PDF | Avoids heavy PDF system deps across 3 OSes |
| **Testing** | `pytest`, `vitest`, Playwright (E2E) | |
| **Hosting (demo)** | Frontend on Vercel or local; backend in Docker on the demo machine; Supabase cloud | Free-tier Supabase projects can pause when idle — open the dashboard the day before the demo |

---

## 3. System architecture

### 3.1 Master pipeline (ACESO, mapped to Blueprint modules)

```text
 Blueprint Module 1: INGESTION & MULTI-MODAL PROCESSING
 ┌────────────────────────────────────────────────────────────────┐
 │ Raw Input: consult audio · scanned PDFs/images · prescriptions │
 │            │                                                   │
 │            ▼                                                   │
 │ 1. STT / OCR Perception (keep audio spans & bounding boxes)    │
 └────────────────────────────────────────────────────────────────┘
            │
            ▼
 Blueprint Module 3: CLINICAL INTELLIGENCE (fact side)
 ┌────────────────────────────────────────────────────────────────┐
 │ 2. Fact Extraction → Normalization (RxNorm/LOINC) + Negation   │
 │ 3. Three-Way Verification (OCR bbox · transcript · omission)   │
 └────────────────────────────────────────────────────────────────┘
            │
            ▼
 Blueprint Module 2: CORE STORAGE, SEARCH & TIMELINE
 ┌────────────────────────────────────────────────────────────────┐
 │ 4. Longitudinal Fact Store (SUPABASE)                          │
 │    extracted ─► verified ─► clinician_confirmed                │
 │    + pgvector chunks · event timeline · trends                 │
 └────────────────────────────────────────────────────────────────┘
            │
            ▼
 Blueprint Module 3: CLINICAL INTELLIGENCE (safety side)
 ┌────────────────────────────────────────────────────────────────┐
 │ 5. Deterministic Safety Engine → Explainability Trace          │
 │ 6. SOAP Generation (from verified facts) & Review-by-Exception │
 └────────────────────────────────────────────────────────────────┘
            │
            ▼
 Blueprint Module 4: GOVERNANCE, SECURITY & HUMAN OVERSIGHT
 ┌────────────────────────────────────────────────────────────────┐
 │ 7. Doctor Sign-off (HITL) → Official Record (FHIR/ABDM)        │
 │    RBAC (RLS) · immutable audit log                            │
 │ 8. Safe Patient-Facing Export (templated, not LLM-translated)  │
 └────────────────────────────────────────────────────────────────┘
```

### 3.2 Runtime topology (3 machines, 1 database)

```text
   Machine A            Machine B             Machine C
 ┌───────────┐       ┌────────────┐        ┌────────────┐
 │ Next.js   │       │ FastAPI +  │        │ Worker +   │
 │ frontend  │       │ safety eng │        │ eval/seed  │
 └─────┬─────┘       └─────┬──────┘        └─────┬──────┘
       │   (all use the same .env → same project)│
       └───────────────────┬─────────────────────┘
                           ▼
              ┌─────────────────────────┐
              │  SUPABASE (cloud)       │
              │  Postgres + pgvector    │
              │  Auth · Storage · RLS   │
              │  Realtime · Migrations  │
              └─────────────────────────┘
```

---

## 4. Phase 0 — Foundations (do this first, together)

### 4.1 Prerequisites on every machine
| Tool | Version | Check |
|---|---|---|
| Git | any recent | `git --version` |
| Node.js + pnpm | Node 20 LTS | `node -v && pnpm -v` |
| Python | 3.11 | `python --version` |
| Supabase CLI | latest | `supabase --version` |
| Docker Desktop | optional (backend image only) | `docker --version` |
| ffmpeg | any | `ffmpeg -version` (audio handling) |
| Tesseract | 5.x (OCR fallback) | `tesseract --version` |

> Windows teammates: use WSL2 for the Python backend, or run it from Docker, so paths and audio libs behave the same as on macOS/Linux.

### 4.2 Create the Supabase project (one person, once)
1. Go to supabase.com → **New project** → name `aceso`, choose the region closest to the demo venue, set a strong DB password and store it in the team password manager.
2. **Project Settings → API**: copy `Project URL`, `anon` key, `service_role` key (service key is **backend-only**, never ship it to the browser).
3. **Project Settings → Database**: copy the **session-mode pooler** connection string (port 5432). Use session mode for the worker (advisory locks and prepared statements are not reliable in transaction-pooling mode).
4. **Database → Extensions**: enable `vector`, `pgcrypto`, `pg_trgm`.
5. **Storage**: create private buckets `audio` and `documents`.
6. **Authentication → Providers**: enable Email; disable public sign-ups (users are created by the seed script, simulating an admin-managed clinic).
7. Invite the other two teammates as project members.

**Done when:** all three teammates can open the Supabase dashboard's SQL editor on the same project.

### 4.3 Suggested ownership (adjust to your strengths)

| Owner | Responsibility | Phases |
|---|---|---|
| 🅰 **Data & Safety** | Supabase schema, RLS, audit chain, seed data, terminology, safety engine, contradiction engine, FHIR/ABDM export, evaluation harness | 1, 2, 6, 10 (RBAC, sign-off lock, FHIR), 13 |
| 🅱 **AI Pipeline** | Job worker, audio/OCR perception, extraction, normalization, 3-way verification, SOAP generation, search, privacy gateway, stretch scribe | 3, 4, 5, 7, 9 (backend), 10 (privacy gateway), 12 |
| 🅲 **Frontend & UX** | Design system, every screen, review-by-exception, explain-trace UI, timeline/trends, patient-summary templates & preview | 8, 9 (UI), 10 (patient summary UI/templates) |
| **All three** | Foundations, integration, testing, demo | 0, 11, 14 |

Interface contracts between owners are: **(1)** the Supabase schema (§5), **(2)** the FastAPI OpenAPI spec, **(3)** the generated TypeScript DB types. Freeze these early.

### 4.4 Monorepo layout

```text
aceso/
├── README.md
├── .env.example
├── supabase/
│   ├── config.toml
│   ├── migrations/            # 0001_… .sql  (schema, RLS, triggers, functions)
│   └── seed/                  # SQL seeds that are safe to re-run
├── apps/
│   └── web/                   # Next.js frontend
│       ├── app/               # routes (see §12)
│       ├── components/
│       ├── lib/supabase/      # browser + server clients
│       └── types/db.ts        # generated by `supabase gen types`
├── services/
│   └── api/                   # FastAPI backend + pipeline
│       ├── aceso/
│       │   ├── main.py
│       │   ├── config.py
│       │   ├── db.py                  # psycopg pool + supabase client
│       │   ├── llm/                   # LLMClient adapter, prompts, schemas
│       │   ├── perception/            # stt.py, ocr.py
│       │   ├── extraction/            # extract.py, normalize.py, negation.py
│       │   ├── verification/          # ocr_match.py, transcript_support.py, omission.py
│       │   ├── factstore/             # lifecycle.py, contradictions.py
│       │   ├── safety/                # metrics.py, engine.py, rules/, trace.py
│       │   ├── soap/                  # generate.py, validate.py
│       │   ├── search/                # hybrid.py, answer.py
│       │   ├── export/                # fhir.py, patient_templates/
│       │   ├── privacy/               # gateway.py
│       │   ├── workers/               # worker.py, handlers.py
│       │   └── routes/                # FastAPI routers
│       ├── tests/
│       └── pyproject.toml
├── data/
│   ├── terminology/           # brand map, LOINC subset, ATC, reference ranges
│   ├── interactions/          # open interaction dataset (processed)
│   └── synthetic/             # patients, PDFs, audio, ground truth (see §6)
├── eval/
│   ├── run.py
│   └── reports/
└── docs/
    ├── ACESO_MASTER_BUILD_GUIDE.md   # this file
    └── clinical_review_log.md        # who clinically reviewed which rule/template
```

### 4.5 Environment variables (`.env.example`)

```bash
# --- Supabase (same values on all 3 machines) ---
SUPABASE_URL=https://<ref>.supabase.co
SUPABASE_ANON_KEY=...
SUPABASE_SERVICE_ROLE_KEY=...        # backend only
SUPABASE_DB_URL=postgresql://postgres.<ref>:<pw>@aws-0-<region>.pooler.supabase.com:5432/postgres

# --- Frontend (NEXT_PUBLIC_ = visible to browser) ---
NEXT_PUBLIC_SUPABASE_URL=${SUPABASE_URL}
NEXT_PUBLIC_SUPABASE_ANON_KEY=${SUPABASE_ANON_KEY}
NEXT_PUBLIC_API_URL=http://localhost:8000

# --- AI providers ---
LLM_MODE=external                    # external | onprem
LLM_PROVIDER=...                     # adapter key
LLM_API_KEY=...
OLLAMA_URL=http://localhost:11434    # used when LLM_MODE=onprem
STT_ENGINE=faster_whisper            # faster_whisper | openai
OCR_ENGINE=azure                     # azure | tesseract
AZURE_DI_ENDPOINT=...
AZURE_DI_KEY=...
EMBED_MODEL=intfloat/multilingual-e5-small
```

### 4.6 Team workflow for 3 machines (avoid schema drift)
1. `git init`, push to a shared remote. Protect `main`; work on short-lived branches.
2. **Schema changes only via migration files** in `supabase/migrations/` (never edit tables in the dashboard). Name them with timestamps: `supabase migration new add_open_loops`.
3. Only the **Data & Safety owner (🅰)** applies migrations to the shared project: `supabase link --project-ref <ref>` then `supabase db push`. Others open a PR with the migration file.
4. After every migration: `supabase gen types typescript --linked > apps/web/types/db.ts` and commit it.
5. Seed scripts must be **idempotent** (`insert … on conflict do nothing/update`) so any teammate can re-run them.
6. One shared dev dataset; if someone needs to experiment destructively, use a `scratch_` prefixed patient, never the scenario patients (§6).
7. Daily 10-minute sync: "what changed in schema / API / types?"

**Phase 0 Done when:** repo cloned on all 3 machines; `pnpm dev` shows a blank Next.js page; `uvicorn aceso.main:app` returns `{"status":"ok"}` at `/health`; both can read one row from Supabase using the `.env` values.

---

## 5. Phase 1 — Supabase database: schema, RLS, audit 🅰

> Blueprint link: *Module 2 (Core Storage, Search & Timeline)* and *Module 4 (RBAC + audit logs)*.
> This phase produces the **shared contract** every other phase builds on. Do it before anything else.

### 5.1 Table map

| Group | Tables |
|---|---|
| Identity & access | `profiles` (extends `auth.users`) |
| Clinical context | `patients`, `encounters` |
| Raw inputs | `audio_recordings`, `transcript_segments`, `source_documents`, `ocr_blocks` |
| **Fact store (core IP)** | `facts`, `fact_chunks` (pgvector) |
| Terminology | `concepts`, `drug_brands`, `allergy_groups`, `reference_ranges` |
| Safety | `drug_interactions`, `dose_limits`, `safety_rules`, `safety_alerts` |
| Documentation | `soap_notes`, `note_edits`, `patient_exports` |
| Workflow | `open_loops`, `jobs` |
| Governance | `audit_log` (append-only, hash-chained) |
| Evaluation | `eval_runs`, `eval_results` |

### 5.2 Step 1 — extensions & enums
`supabase/migrations/0001_base.sql`

```sql
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
```

### 5.3 Step 2 — identity, patients, encounters
`0002_core.sql`

```sql
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
```

### 5.4 Step 3 — raw inputs (what provenance points at)
`0003_inputs.sql`

```sql
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

-- bbox is NORMALISED 0..1 relative to page width/height so it survives zoom/resolution
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
```

### 5.5 Step 4 — the Longitudinal Fact Store (core)
`0004_facts.sql`

```sql
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

-- hybrid-search helper (semantic part)
create or replace function match_chunks(
  p_patient uuid, p_query extensions.vector(384), p_k int default 10)
returns table (id uuid, content text, fact_id uuid, segment_id uuid, document_id uuid,
               metadata jsonb, similarity float)
language sql stable as $$
  select c.id, c.content, c.fact_id, c.segment_id, c.document_id, c.metadata,
         1 - (c.embedding <=> p_query) as similarity
  from fact_chunks c
  where c.patient_id = p_patient
  order by c.embedding <=> p_query
  limit p_k;
$$;
```

### 5.6 Step 5 — terminology & clinical knowledge tables
`0005_knowledge.sql`

```sql
create table concepts (                      -- LOINC / ICD-10 / RxNorm / ATC subsets
  system text not null, code text not null, display text not null,
  synonyms text[] default '{}', primary key (system, code)
);

create table drug_brands (                   -- Indian brand → generic (proprietary dictionary)
  brand text primary key,                    -- lower-case, e.g. 'glycomet'
  generic text not null,                     -- 'metformin'
  rxnorm text, atc text,
  default_strength text
);
create index on drug_brands using gin (brand extensions.gin_trgm_ops);

create table allergy_groups (                -- cross-reactivity groups
  group_name text, member_generic text, primary key (group_name, member_generic)
);

create table reference_ranges (
  loinc text, sex text default 'any', age_min int default 0, age_max int default 120,
  low numeric, high numeric,                 -- normal range
  plausible_min numeric, plausible_max numeric,   -- physiologically possible (OCR sanity)
  unit text, primary key (loinc, sex, age_min)
);

create table drug_interactions (
  id serial primary key,
  drug_a text not null, drug_b text not null,        -- generics, alphabetically ordered a<b
  severity text check (severity in ('contraindicated','major','moderate','minor')),
  description text,
  source text not null, source_ref text,             -- dataset name + record id
  unique (drug_a, drug_b)
);

create table dose_limits (
  generic text, route text default 'PO', population text default 'adult',
  max_single_mg numeric, max_daily_mg numeric,
  source text not null, primary key (generic, route, population)
);

create table safety_rules (                   -- rules are DATA, evaluated by deterministic code
  id text primary key,                        -- 'KDIGO-METFORMIN-EGFR30'
  title text not null,
  rule_type text not null,                    -- lab_contraindication|interaction|duplicate|dose|allergy|contradiction
  guideline_source text not null,
  version text default '1',
  severity text check (severity in ('critical','high','moderate','info')),
  rule jsonb not null,                        -- DSL, see §10.3
  clinician_reviewed_by text,                 -- fill this in! ties to docs/clinical_review_log.md
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
  trace jsonb not null,                       -- explainability trace (§10.5)
  created_at timestamptz default now(),
  resolved_by uuid references profiles(id), resolved_at timestamptz,
  override_reason text
);
create index on safety_alerts(patient_id, status);
```

### 5.7 Step 6 — documentation, workflow, evaluation tables
`0006_workflow.sql`

```sql
create table soap_notes (
  id uuid primary key default gen_random_uuid(),
  encounter_id uuid not null references encounters(id),
  version int not null default 1,
  -- each section: [{ "text": "...", "fact_ids": ["uuid", ...] }, ...]
  subjective jsonb, objective jsonb, assessment jsonb, plan jsonb,
  status note_status default 'draft',
  generated_by text,                          -- model/adapter id + prompt version
  signed_by uuid references profiles(id), signed_at timestamptz,
  content_hash text,                          -- sha256 of the signed content
  unique (encounter_id, version)
);

create table note_edits (                     -- Edit-Diff Learning
  id uuid primary key default gen_random_uuid(),
  note_id uuid references soap_notes(id), doctor_id uuid references profiles(id),
  section text, ai_text text, final_text text,
  edit_ratio real,                            -- normalised Levenshtein
  created_at timestamptz default now()
);

create table patient_exports (
  id uuid primary key default gen_random_uuid(),
  encounter_id uuid references encounters(id), lang text, template_version text,
  payload jsonb not null,                     -- the structured plan that was templated
  rendered_html text, created_at timestamptz default now()
);

create table open_loops (
  id uuid primary key default gen_random_uuid(),
  patient_id uuid references patients(id), encounter_id uuid references encounters(id),
  fact_id uuid references facts(id),          -- the plan_item fact it came from
  description text not null,
  due_date date,
  status text default 'open' check (status in ('open','done','cancelled')),
  closed_by_fact_id uuid references facts(id)
);
-- "overdue" is computed, never stored:
create view open_loops_v as
  select *, (status='open' and due_date < current_date) as overdue from open_loops;

create table jobs (
  id uuid primary key default gen_random_uuid(),
  kind text not null,                         -- perceive_audio|perceive_document|extract|verify|safety|soap|embed
  payload jsonb not null,
  status job_status default 'queued',
  attempts int default 0, error text,
  locked_at timestamptz, created_at timestamptz default now()
);
create index on jobs(status, created_at);

create table eval_runs (
  id uuid primary key default gen_random_uuid(),
  created_at timestamptz default now(), git_sha text, llm_id text, notes text,
  metrics jsonb                               -- {extraction_f1:…, unsupported_claim_rate:…, …}
);
create table eval_results (
  id uuid primary key default gen_random_uuid(),
  run_id uuid references eval_runs(id) on delete cascade,
  patient_id uuid, category text, expected jsonb, actual jsonb, passed boolean, detail text
);
```

### 5.8 Step 7 — fact lifecycle enforcement + immutable, hash-chained audit log
`0007_audit_lifecycle.sql`

```sql
create table audit_log (
  id          bigserial primary key,
  at          timestamptz not null default now(),
  actor_id    uuid,                           -- auth user, null for system
  actor_label text,                           -- 'system:pipeline' | 'dr.rao' …
  actor_role  text,
  action      text not null,                  -- fact.state_change | note.sign | alert.override | …
  entity_type text not null, entity_id uuid, patient_id uuid,
  from_state  text, to_state text,
  payload     jsonb,
  prev_hash   text, row_hash text
);

-- tamper-evident chain (epoch, not ::text, so the hash doesn't depend on session timezone)
create or replace function audit_chain() returns trigger language plpgsql as $$
declare last_hash text;
begin
  perform pg_advisory_xact_lock(727001);                 -- serialise chain writes
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

-- append-only: block UPDATE / DELETE even for the service role
create or replace function audit_immutable() returns trigger language plpgsql as $$
begin raise exception 'audit_log is append-only'; end $$;
create trigger audit_no_update before update or delete on audit_log
  for each row execute function audit_immutable();
create trigger audit_no_truncate before truncate on audit_log
  for each statement execute function audit_immutable();

-- helper: who is acting?
create or replace function public.app_role() returns user_role
language sql stable security definer set search_path = public as
$$ select role from profiles where id = auth.uid() $$;

-- ALLOWED fact transitions (state machine) + role rule
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
    -- only a doctor may confirm. (service_role has auth.uid() = null → r is null → system only verifies)
    if new.state='clinician_confirmed' and r is distinct from 'doctor' then
      raise exception 'Only a doctor can confirm a fact';
    end if;
  end if;
  return new;
end $$;
create trigger facts_guard_t before update on facts
  for each row execute function facts_guard();

-- every INSERT and every real state change on facts is audited
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

-- tamper check callable from the admin UI
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
```

> Backend tip: the pipeline writes with the service role. Before a transaction run `select set_config('app.actor','system:pipeline',true)` so audit rows are labelled. Doctor actions should go through the user's own JWT so `auth.uid()` is recorded.

### 5.9 Step 8 — RBAC via Row Level Security
`0008_rls.sql`

Role matrix (Blueprint: *doctors, nurses, administrators*):

| Capability | Doctor | Nurse | Admin |
|---|:--:|:--:|:--:|
| View patient demographics | ✅ | ✅ | ✅ |
| View clinical facts, notes, documents, audio | ✅ | ✅ | ❌ |
| Upload documents / record vitals | ✅ | ✅ | ❌ |
| Edit / reject facts | ✅ | ✅ (own draft only in UI) | ❌ |
| **Confirm** facts, **sign** notes, override alerts | ✅ | ❌ | ❌ |
| Manage users, view audit log, run chain check | ❌ | ❌ | ✅ |

```sql
do $$ declare t text; begin
  foreach t in array array['profiles','patients','encounters','audio_recordings',
   'transcript_segments','source_documents','ocr_blocks','facts','fact_chunks',
   'safety_alerts','soap_notes','note_edits','patient_exports','open_loops',
   'audit_log','jobs','eval_runs','eval_results'] loop
    execute format('alter table %I enable row level security', t);
  end loop; end $$;

-- knowledge tables: readable by any signed-in user
create policy read_all on concepts           for select to authenticated using (true);
create policy read_all on drug_brands        for select to authenticated using (true);
create policy read_all on reference_ranges   for select to authenticated using (true);
create policy read_all on drug_interactions  for select to authenticated using (true);
create policy read_all on safety_rules       for select to authenticated using (true);
-- RLS must be ON for the knowledge tables too, or the policies above do nothing
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

-- clinical tables: doctor + nurse only
do $$ declare t text; begin
  foreach t in array array['encounters','audio_recordings','transcript_segments',
   'source_documents','ocr_blocks','facts','fact_chunks','safety_alerts','soap_notes',
   'note_edits','patient_exports','open_loops'] loop
    execute format($f$create policy clin_rw on %I for all to authenticated
      using (public.app_role() in ('doctor','nurse'))
      with check (public.app_role() in ('doctor','nurse'))$f$, t);
  end loop; end $$;

-- audit log: admin reads; nobody writes via API (triggers write)
create policy audit_admin_read on audit_log for select to authenticated using (public.app_role()='admin');
```

Also:
- Storage policies: keep buckets private; the browser fetches via **signed URLs** minted by the API after a role check.
- Signing a note and overriding an alert go through **API endpoints** that check `role='doctor'`, then write using the doctor's JWT so the audit row names the doctor.

### 5.10 Step 9 — Auth users & types
1. Write `supabase/seed/00_users.ts` (or Python with the admin API) creating: `dr.rao@aceso.demo` (doctor), `nurse.priya@aceso.demo` (nurse), `admin.kumar@aceso.demo` (admin), plus matching `profiles` rows.
2. Generate TS types and commit.

### 5.11 Phase 1 — Done when
- [ ] `supabase db push` succeeds from a clean project.
- [ ] Inserting an `audio`-sourced fact **without** a time span fails (constraint).
- [ ] Updating a fact `extracted → clinician_confirmed` fails (illegal jump); as a nurse, `verified → clinician_confirmed` fails; as doctor it works and an `audit_log` row appears.
- [ ] `update audit_log …` and `delete from audit_log` fail even with the service-role key.
- [ ] `select * from verify_audit_chain()` returns `ok = true`; manually corrupt a row in a scratch copy and it returns `false`.
- [ ] A nurse JWT cannot read `audit_log`; an admin JWT cannot read `facts`.

---

## 6. Phase 2 — Dummy database & synthetic patient set (Supabase) 🅰

> Why this phase is second: the frontend (🅲) and the pipeline (🅱) are blocked without realistic data. We seed **two levels** so nobody waits.
>
> - **Level A — "Golden" data:** hand-written, already-verified facts with fake-but-valid provenance. Lets the UI be built *today*.
> - **Level B — "Raw" inputs:** synthetic PDFs, audio and transcripts with **ground truth**. These are fed through the real pipeline and double as the evaluation dataset (§17).
>
> All data is fictional. Never put a real patient's information into this project.

### 6.1 The six synthetic scenarios
Each scenario is a *planted test* for one feature. Dates are generated **relative to the seeding day** so "overdue" stays overdue.

| Key | Patient (fictional) | What is planted | Expected ACESO behaviour |
|---|---|---|---|
| **S1_metformin_ckd** | Meena Rajan, 50 F, MRN `ACE-0001` | T2DM; old Rx lists **"Glycomet 500 BD"**; lab PDF shows **Creatinine 2.1 mg/dL**; doctor plans to continue it | Brand→generic (Glycomet→metformin); computed **eGFR ≈ 28.2**; **critical alert** `KDIGO-METFORMIN-EGFR30` with explain trace |
| **S2_allergy_contradiction** | Arjun Menon, 45 M, `ACE-0002` | 2024 discharge PDF: **"Allergy: Penicillin (rash)"**; today the patient says *"no allergies"*; doctor prescribes **Mox (amoxicillin)** | **Contradiction alert** (record says allergy, today says none) + **allergy-conflict alert** (amoxicillin ∈ penicillin group) |
| **S3_negation** | Lakshmi Narayanan, 58 F, `ACE-0003` | Says *"no diabetes, **not** allergic to sulfa, no chest pain"*; prescribed **Septran** (co-trimoxazole) | Three `denied` facts stored; **zero** false allergy alarms (negation test) |
| **S4_duplicate_dose_interaction** | Suresh Babu, 72 M, `ACE-0004` | Meds: **Ecosprin 75 + Warf** ; **Dolo 650 QID + Crocin 650 TDS** | Aspirin–warfarin **major interaction**; **duplicate therapy** (paracetamol ×2); **dose-range** alert (7×650 = 4550 mg/day > 4000) |
| **S5_trend_open_loop** | Fatima Begum, 55 F, `ACE-0005` | HbA1c 8.9 → 8.2 → 7.6 over 3 prior visits; plan *"repeat HbA1c in 3 months"* never done; **code-mixed Tamil-English** transcript | Trend chart; **open loop overdue**; (stretch) multilingual transcript |
| **S6_control** | Karthik S, 34 M, `ACE-0006` | Healthy; viral URI; paracetamol | **Zero alerts** — measures false-positive rate |

Verified math for the safety tests (CKD-EPI 2021): `(Cr 2.1, 50 F) → 28.2` · `(Cr 2.4, 68 M) → 28.7` · `(Cr 1.1, 58 F) → 58.2` · `(Cr 1.6, 72 M) → 45.5` · `(Cr 1.0, 45 M) → 94.6`. Use these as unit-test oracles.

### 6.2 Seed order & files

```text
supabase/seed/
├── 00_users.ts              # 3 auth users + profiles
├── 10_terminology.sql       # concepts, drug_brands, allergy_groups, reference_ranges
├── 20_knowledge.sql         # drug_interactions, dose_limits, safety_rules
├── 30_patients.sql          # 6 patients + historical encounters
├── 40_golden_facts.sql      # Level A: verified facts with provenance
└── 50_raw_inputs.py         # Level B: uploads PDFs/audio to Storage, creates rows, enqueues jobs
data/synthetic/
├── S1_metformin_ckd/{labs_2026.pdf, rx_2024.pdf, visit.wav, transcript.json, truth.json}
├── …
└── make_docs.py             # generates PDFs + exact ground-truth bboxes
```

Run order: `pnpm seed:users` → `psql`/Supabase SQL editor (or `supabase db push` with seed) for `.sql` → `python seed/50_raw_inputs.py`. Every file is idempotent.

### 6.3 Terminology & knowledge seeds (illustrative — clinically verify before demo)

`10_terminology.sql`
```sql
insert into drug_brands(brand,generic,rxnorm,atc,default_strength) values
 ('glycomet','metformin','6809','A10BA02','500 mg'),
 ('dolo 650','paracetamol','161','N02BE01','650 mg'),
 ('crocin','paracetamol','161','N02BE01','650 mg'),
 ('ecosprin','aspirin','1191','B01AC06','75 mg'),
 ('warf','warfarin','11289','B01AA03',null),
 ('mox','amoxicillin','723','J01CA04','500 mg'),
 ('augmentin','amoxicillin+clavulanate',null,'J01CR02','625 mg'),
 ('septran','co-trimoxazole','10180','J01EE01',null),
 ('telma','telmisartan','73494','C09CA07','40 mg'),
 ('pantocid','pantoprazole','40790','A02BC02','40 mg'),
 ('amaryl','glimepiride','25789','A10BB12','1 mg')
on conflict (brand) do update set generic=excluded.generic;

insert into concepts(system,code,display,synonyms) values
 ('LOINC','2160-0','Creatinine [Mass/volume] in Serum or Plasma','{creatinine,s.creatinine,scr}'),
 ('LOINC','4548-4','Hemoglobin A1c/Hemoglobin.total in Blood','{hba1c,a1c,glycated hemoglobin}'),
 ('LOINC','1558-6','Fasting glucose [Mass/volume] in Serum or Plasma','{fbs,fasting blood sugar}'),
 ('LOINC','718-7','Hemoglobin [Mass/volume] in Blood','{hb,haemoglobin}'),
 ('LOINC','2823-3','Potassium [Moles/volume] in Serum or Plasma','{k,potassium}'),
 ('LOINC','62238-1','eGFR (CKD-EPI) — computed','{egfr}'),
 ('LOINC','8480-6','Systolic blood pressure','{sbp,bp systolic}'),
 ('LOINC','8462-4','Diastolic blood pressure','{dbp,bp diastolic}'),
 ('ICD10','E11','Type 2 diabetes mellitus','{t2dm,diabetes,sugar}'),
 ('ICD10','N18.4','Chronic kidney disease, stage 4','{ckd 4}'),
 ('ICD10','I10','Essential hypertension','{htn,bp}'),
 ('ICD10','J06.9','Acute upper respiratory infection, unspecified','{uri,cold}')
on conflict do nothing;

insert into allergy_groups values
 ('penicillins','penicillin'),('penicillins','amoxicillin'),('penicillins','ampicillin'),
 ('penicillins','amoxicillin+clavulanate'),
 ('sulfonamide_antibiotics','sulfamethoxazole'),('sulfonamide_antibiotics','co-trimoxazole')
on conflict do nothing;

insert into reference_ranges(loinc,sex,age_min,age_max,low,high,plausible_min,plausible_max,unit) values
 ('2160-0','M',18,120,0.7,1.3,0.1,20,'mg/dL'),
 ('2160-0','F',18,120,0.6,1.1,0.1,20,'mg/dL'),
 ('4548-4','any',0,120,4.0,5.6,3,20,'%'),
 ('1558-6','any',0,120,70,100,20,800,'mg/dL')
on conflict do nothing;
```

`20_knowledge.sql`
```sql
insert into drug_interactions(drug_a,drug_b,severity,description,source,source_ref) values
 ('aspirin','warfarin','major','Increased bleeding risk','SEED-CURATED','manual-001')
on conflict do nothing;
-- Then bulk-load the open interaction dataset: normalise names → generics (alphabetical a<b),
-- keep its record id in source_ref, keep its licence note in docs/clinical_review_log.md.

insert into dose_limits(generic,route,population,max_single_mg,max_daily_mg,source) values
 ('paracetamol','PO','adult',1000,4000,'SEED-CURATED label limit'),
 ('metformin','PO','adult',1000,2550,'SEED-CURATED label limit')
on conflict do nothing;
```
(Safety rules are seeded in §10.3.)

### 6.4 Patients & Level A "golden" facts

`30_patients.sql` (fixed UUIDs make cross-file seeding simple)
```sql
insert into patients(id,mrn,full_name,dob,sex,preferred_lang) values
 ('00000000-0000-4000-8000-000000000001','ACE-0001','Meena Rajan',        current_date - interval '50 years','F','ta'),
 ('00000000-0000-4000-8000-000000000002','ACE-0002','Arjun Menon',        current_date - interval '45 years','M','en'),
 ('00000000-0000-4000-8000-000000000003','ACE-0003','Lakshmi Narayanan',  current_date - interval '58 years','F','ta'),
 ('00000000-0000-4000-8000-000000000004','ACE-0004','Suresh Babu',        current_date - interval '72 years','M','ta'),
 ('00000000-0000-4000-8000-000000000005','ACE-0005','Fatima Begum',       current_date - interval '55 years','F','ta'),
 ('00000000-0000-4000-8000-000000000006','ACE-0006','Karthik S',          current_date - interval '34 years','M','en')
on conflict (id) do nothing;
```

`40_golden_facts.sql` — one hand-built example per scenario so every UI state exists. Example (S1), showing a document-sourced fact with a real-looking bounding box:
```sql
-- a lab PDF + one OCR block + the verified creatinine fact pointing at it
insert into source_documents(id,patient_id,storage_path,kind,doc_date,page_count,ocr_engine,status) values
 ('d0000000-0000-4000-8000-000000000001','00000000-0000-4000-8000-000000000001',
  'documents/S1/labs_2026.pdf','lab_pdf', current_date - 14, 1,'golden','done')
on conflict do nothing;

insert into ocr_blocks(id,document_id,page_no,block_idx,kind,text,confidence,x,y,w,h) values
 ('b0000000-0000-4000-8000-000000000001','d0000000-0000-4000-8000-000000000001',1,12,'table_cell','2.1',0.97,0.52,0.31,0.06,0.022)
on conflict do nothing;

insert into facts(id,patient_id,fact_type,assertion,code_system,code,display,raw_text,
                  value_num,unit,effective_at,state,confidence,confidence_parts,
                  source,document_id,block_ids,page_no,bbox,verification) values
 ('f0000000-0000-4000-8000-000000000001','00000000-0000-4000-8000-000000000001',
  'lab_result','present','LOINC','2160-0','Creatinine, serum','2.1',
  2.1,'mg/dL', now() - interval '14 days','verified',0.96,
  '{"ocr":0.97,"plausibility":1,"verification":1}',
  'document','d0000000-0000-4000-8000-000000000001','{b0000000-0000-4000-8000-000000000001}',
  1,'{"x":0.52,"y":0.31,"w":0.06,"h":0.022}',
  '{"ocr_match":{"ok":true},"transcript_support":{"ok":null},"omission":{"ok":true}}')
on conflict (id) do nothing;
```
Add at least these golden facts so the UI shows **every** visual state: one `extracted` (amber, needs attention), one `verified` (collapsed), one `clinician_confirmed`, one `rejected`, one `denied` allergy (S3), one audio-sourced fact with a span, one `safety_alerts` row with a full trace (copy the example in §10.5), and one overdue `open_loops` row (S5).

### 6.5 Level B — raw synthetic inputs with ground truth

**Documents (PDFs).** Generate with `reportlab`/HTML→PDF so you **know the exact bounding box of every value**. `make_docs.py` writes each PDF and a `truth.json` with those coordinates (normalised 0..1). Produce each document at three quality levels so the evaluation can show where the system degrades:
| Variant | How |
|---|---|
| `clean` | direct render |
| `scan` | rasterise at 150 dpi, slight rotation (±1.5°), JPEG compression |
| `bad` | 100 dpi, noise, uneven shading, one handwritten-style font for the Rx |

**Audio.** Write short scripted consult dialogues (60–120 s) per scenario, record them (teammates, or any open TTS), export 16 kHz mono WAV. Keep the script text as ground-truth transcript and mark **which phrase supports which fact** (this gives the audio span truth).
- S3 must contain explicit negations ("no diabetes", "not allergic to sulfa").
- S2 must contain "no allergies" spoken by the patient.
- S5 includes a code-mixed Tamil-English segment (stretch goal §16).
- Deliberately make one **omission trap**: the patient mentions a drug or allergy in passing that a lazy extractor would skip.

**Ground truth format** (`truth.json`):
```json
{
  "scenario": "S1_metformin_ckd",
  "inputs": { "audio": "visit.wav", "documents": ["labs_2026.pdf", "rx_2024.pdf"] },
  "expected_facts": [
    { "type": "medication", "code": "6809", "assertion": "present", "source": "audio", "span_ms": [41200, 44800] },
    { "type": "lab_result", "code": "2160-0", "value": 2.1, "unit": "mg/dL",
      "source": "document", "doc": "labs_2026.pdf", "page": 1, "bbox": [0.52, 0.31, 0.06, 0.022] }
  ],
  "expected_alerts": [ { "rule_id": "KDIGO-METFORMIN-EGFR30", "must_fire": true } ],
  "expected_contradictions": [],
  "expected_omission_traps": [ { "phrase": "sometimes I take an ibuprofen", "should_be_flagged_or_extracted": true } ],
  "must_not_fire": []
}
```

`50_raw_inputs.py` does: upload files to Storage → insert `source_documents` / `audio_recordings` → enqueue `perceive_*` jobs → pipeline runs end-to-end.

### 6.6 Phase 2 — Done when
- [ ] All six patients appear in the Supabase table editor with the right MRNs.
- [ ] The frontend can list patients and show golden facts in all lifecycle states (no pipeline needed).
- [ ] `make_docs.py` produces PDFs whose `truth.json` bboxes visibly line up with the values (overlay check in a notebook).
- [ ] Re-running every seed file twice creates no duplicates.
- [ ] Each scenario folder has `truth.json`, and S6 has an empty `expected_alerts`.

---

## 7. Phase 3 — Backend skeleton, job queue & perception (STT + OCR) 🅱

> Blueprint link: *Module 1 — Ingestion & Multi-Modal Processing Pipeline.*
> Goal: raw audio/PDF in → **transcript segments with timestamps** and **OCR blocks with bounding boxes** in Supabase. Nothing "clinical" happens yet.

### 7.1 Step 1 — FastAPI skeleton
1. `services/api/pyproject.toml` deps: `fastapi uvicorn[standard] pydantic psycopg[binary,pool] supabase faster-whisper pytesseract pdf2image pillow rapidfuzz presidio-analyzer presidio-anonymizer sentence-transformers jinja2 python-multipart httpx tenacity pytest`.
2. `config.py` (Pydantic `BaseSettings`) reads `.env`.
3. `db.py`: a `psycopg_pool.ConnectionPool` on `SUPABASE_DB_URL` (session mode) + a `supabase` client with the service-role key for Storage access.
4. Auth middleware: verify the Supabase JWT from `Authorization: Bearer`, load the role from `profiles`; expose `require_role("doctor")` dependency.
5. `GET /health`.

### 7.2 Step 2 — Job queue worker (no Redis)
```python
# workers/worker.py
CLAIM = """
update jobs set status='running', locked_at=now(), attempts=attempts+1
where id = (select id from jobs where status='queued'
            order by created_at for update skip locked limit 1)
returning id, kind, payload;
"""
def run_forever():
    while True:
        row = claim_one(CLAIM)
        if not row: time.sleep(1.0); continue
        try:
            HANDLERS[row.kind](row.payload)       # handlers.py
            mark(row.id, 'done')
        except Exception as e:
            mark(row.id, 'failed' if row.attempts >= 3 else 'queued', error=str(e))
```
Pipeline chaining: each handler enqueues the next job (`perceive_audio → extract → verify → safety → soap`). Any teammate can run `python -m aceso.workers.worker`; `SKIP LOCKED` prevents double-processing.

### 7.3 Step 3 — Audio scribing (STT)
`perception/stt.py`
1. Download audio from Storage (signed URL) → normalise with ffmpeg to 16 kHz mono WAV.
2. Run `faster-whisper` with `word_timestamps=True`, `vad_filter=True`. Model: `small` on CPU for dev, `medium`/`large-v3` if a GPU machine is available. Set `language=None` to auto-detect (needed for code-mixed audio later).
3. Convert to **segments of ≤ ~15 s** (merge by sentence/pause). For each: `seq, start_ms, end_ms, text, lang, confidence, words[]`.
4. **Speaker labelling (MVP):** if the clip has two channels, label by channel; otherwise run a simple heuristic or leave `unknown`. Diarization via `pyannote.audio` is a stretch goal (§16).
5. Insert into `transcript_segments`; set `audio_recordings.status='done'`; enqueue `extract` and `embed` jobs.
6. **Live mode (after MVP works):** browser `MediaRecorder` sends 8-second chunks over a WebSocket (`/ws/consult/{encounter_id}`); the API transcribes each chunk with a time offset and inserts segments as they arrive. Supabase Realtime pushes new `transcript_segments` rows to the UI (powers live gap prompts, §13.2).

**Done when:** a 90-second S1 recording yields ≥ 90% of words correct vs. the script (spot check) and every segment has valid `[start_ms,end_ms]` within the audio duration.

### 7.4 Step 4 — Document OCR & layout
`perception/ocr.py`
1. Convert PDF pages to images (`pdf2image`, 200 dpi).
2. **Primary:** Azure Document Intelligence (`prebuilt-layout` for tables, `prebuilt-read` for handwriting). Map each returned polygon to a normalised rectangle: `x = min(xs)/page_w`, `y = min(ys)/page_h`, `w = (max(xs)-min(xs))/page_w`, `h = …`.
3. **Fallback (offline / no key):** `pytesseract.image_to_data(output_type=DICT, config='--psm 6')` → words with `left, top, width, height, conf`; group into lines by `block_num/par_num/line_num`; detect table cells by clustering x-positions into columns.
4. Persist **one row per line/word/table cell** in `ocr_blocks` with `table_ref` (`{table, row, col, header}`) where available. The table header is crucial: it lets extraction know "2.1" belongs under *Creatinine*.
5. For vision-language handwriting (prescriptions): send the page image to a VLM through the **Privacy Gateway** (§14.4), ask for *transcription only*, then **re-align** each returned token to the nearest OCR block by fuzzy text + position. Anything that cannot be aligned to a bounding box is stored with `needs_attention` (no box → no provenance → no auto-trust).
6. Set `source_documents.status='done'`; enqueue `extract`, `embed`.

**Done when:** on the `clean` S1 lab PDF, the block containing "2.1" has an IoU ≥ 0.7 with the ground-truth box; on `bad` quality you can *see* the degradation (this is evidence for the eval report, not a failure).

---

## 8. Phase 4 — Fact extraction, normalization & negation 🅱

> The LLM's **only** core job. Everything around it is deterministic.

### 8.1 Step 1 — The LLM adapter (Swap Test)
```python
# llm/client.py
class LLMClient(Protocol):
    def extract_json(self, system: str, user: str, schema: dict, *, temperature=0) -> dict: ...
    def complete(self, system: str, user: str, *, temperature=0.2, max_tokens=800) -> str: ...
```
Implement `ExternalLLM` (provider API) and `OllamaLLM` (on-prem). Choose with `LLM_MODE`. **No other module imports a provider SDK.** To prove the Swap Test, run the eval harness (§17) with two different adapters and show the pipeline metrics barely move.

### 8.2 Step 2 — Evidence packaging (so spans come from IDs, not from the LLM)
Give the LLM **numbered evidence units**, and require it to cite unit IDs:
```text
[S12] (doctor, 00:41.2–00:44.8) "Continue Glycomet 500 twice daily."
[S13] (patient, 00:45.0–00:47.3) "No, no allergies."
[B7]  (page 1, table "Lab results", row "Creatinine", col "Value") "2.1"
```
Output schema (JSON, validated by Pydantic):
```json
{ "facts": [ {
    "fact_type": "medication",
    "assertion": "present",                 // present | denied | uncertain
    "raw_text": "Glycomet 500",
    "dose": {"amount":500,"unit":"mg","freq":"BD","route":"PO"},
    "value_num": null, "unit": null,
    "effective_date": "2026-10-09",
    "evidence_ids": ["S12"]
} ] }
```
**Server-side rules (reject, don't repair):**
- Every fact needs ≥ 1 `evidence_ids` that exist in the packet.
- Audio span = `min(start_ms)…max(end_ms)` of cited segments. Document bbox = union of cited blocks' boxes. *These are computed by our code.*
- Drop facts whose `raw_text` isn't a (fuzzy) substring of the cited evidence text (stops invented facts).
- Prompt rules: "Extract only what is explicitly stated. Record explicit denials as `assertion: denied`. If something is not mentioned, output nothing. Never infer a diagnosis."
- Extract per chunk (a window of ~40 segments, or one document page) so provenance stays tight.

### 8.3 Step 3 — Terminology normalization (deterministic)
`extraction/normalize.py`
| Fact type | Procedure |
|---|---|
| medication | lower-case → strip strengths/forms → exact match in `drug_brands` → else `rapidfuzz.process.extractOne` (token-set ratio ≥ 90) over brands + generics → set `code_system=RxNorm`, `code`, `display = generic`. Unmatched → `needs_attention` with reason `unmapped_drug`. Never guess silently. |
| lab_result | synonym match against `concepts.synonyms` (LOINC); convert units (e.g., µmol/L→mg/dL for creatinine: ÷ 88.4) to a canonical unit; keep the original in `raw_text`. |
| diagnosis | synonym → ICD-10; unresolved → `needs_attention`. |
| allergy | map substance → generic → `allergy_groups` membership (stored in `dose`/`value_text` as `{"group":"penicillins"}`). |
| vital | direct LOINC map (`8480-6` etc.) |
Also parse frequency shorthand (`OD, BD, TDS, QID, HS, SOS`) into `{times_per_day:n}` — the dose-range check needs it.

### 8.4 Step 4 — Negation & assertion cross-check
LLM assertion is **cross-validated** by a rule-based NegEx-style detector on the cited span:
- Cues: *no, not, denies, without, never, negative for, "no history of", "n/o"*; scope = the 4–5 tokens after the cue (stop at "but", ".", ";").
- If the LLM says `present` but a cue's scope covers the entity → set `assertion='uncertain'`, `needs_attention=true`, reason `negation_conflict`.
- If the LLM says `denied` and no cue exists → same flag.
- Store `denied` facts normally (they matter: "denied allergy" must outrank "not mentioned").
(For Tamil/Hindi cues see §16.)

### 8.5 Step 5 — Persist
Insert into `facts` with `state='extracted'`, `source`, provenance fields, `effective_at` (encounter date for audio; document date for PDFs). Enqueue `verify`.

**Done when (unit tests, `pytest`):**
- "I'm not allergic to sulfa" → `allergy, denied, sulfonamide_antibiotics`.
- "Glycomet 500 BD" → `medication, metformin, RxNorm 6809, times_per_day=2`.
- A fact citing a nonexistent evidence ID is rejected.
- Computed audio span of a fact equals the cited segments' min/max exactly.

---

## 9. Phase 5 — Three-way verification pass 🅱

> Before a fact may enter `verified`, three **independent** checks run. Disagreement is not an error — it becomes a *review-by-exception flag*.

`verification/` — each check returns `{ok: true|false|null, detail: "...", score: 0..1}` (`null` = not applicable). Results are saved in `facts.verification`.

### 9.1 Check 1 — OCR match (document facts)
Does the text **inside the bounding box** equal the extracted value?
1. Crop the page image to `bbox` (+2% padding).
2. Re-read the crop with a **different configuration** (e.g., Tesseract `--psm 7` on the crop if the primary was Azure, or vice-versa).
3. Normalise both strings (strip spaces, `,`→`.`, case) and compare. Numeric facts: exact numeric equality after unit conversion.
4. Also run: *reference-range plausibility* — value within `plausible_min..plausible_max`; outside → `ok=false` (probably an OCR error such as `21` for `2.1`).

### 9.2 Check 2 — Transcript support (audio facts)
Is the extracted claim supported by the cited transcript span?
1. Deterministic first: the drug/lab/condition term (or a brand/synonym from our dictionaries) and every numeric dose value must literally appear in the span text.
2. Negation re-check (§8.4) on the span.
3. Optional second opinion: a **constrained yes/no entailment** call ("Does this text support the claim? Answer SUPPORTED / NOT_SUPPORTED / CONTRADICTED"). It may only *downgrade* a fact, never upgrade it. Log the model id.

### 9.3 Check 3 — Omission check (recall)
A diff for things said that were **not** extracted.
1. Run a **separate, dumb, high-recall detector** over the transcript/OCR text: dictionary NER for every brand/generic/lab/diagnosis term, regex for `number + unit`, allergy keywords (*allergy, allergic, reaction, rash*), negation cues.
2. For each detection not covered by any extracted fact's span (overlap < 50%), create a `possible_omission` record. Store as an `extracted` fact with `needs_attention=true`, reason `possible_omission`, so it appears in the review queue.
3. Surface the count per encounter ("2 possible omissions").

### 9.4 Confidence scoring (defensible, documented)
```text
confidence = 0.30 * ocr_conf            (document facts; for audio use whisper word confidence)
           + 0.20 * plausibility        (1 in range, 0 out of range, 0.5 no range known)
           + 0.50 * verification_score  (mean of applicable checks: pass=1, null skipped, fail=0)
```
Store the three parts in `confidence_parts`. **State transition:**
- All applicable checks pass **and** confidence ≥ 0.90 → `state = 'verified'` (system actor).
- Anything else → stays `extracted`, `needs_attention=true`, `attention_reasons` lists *why* (this text is shown to the doctor).

> **Calibration step (do not skip):** after the eval set runs, plot confidence vs. actual correctness and adjust the 0.90 threshold so high-confidence facts are correct ≥ 98% of the time. Report this chart — it is what makes the confidence "defensible".

**Done when:** on the S1 `bad` PDF with an injected OCR error (`2.1`→`21`), the fact stays `extracted` with reason `out_of_plausible_range` or `ocr_mismatch`; on the `clean` PDF it becomes `verified`.

---

## 10. Phase 6 — Longitudinal fact store logic & contradiction engine 🅰

### 10.1 Step 1 — Fact lifecycle service (`factstore/lifecycle.py`)
Thin functions over the DB triggers from §5.8:
- `verify(fact_id)` — system only.
- `confirm(fact_id, user_jwt)` — doctor only; used by the review UI.
- `reject(fact_id, reason)`; `edit(fact_id, patch)` → creates a **new fact** (`created_by='dr.x'`, `state='clinician_confirmed'`, supersedes the old one via `superseded_by`). Never mutate clinical values in place — history must stay reconstructable.
- `supersede(old_id, new_id)`.

### 10.2 Step 2 — Contradiction engine (`factstore/contradictions.py`)
Runs after each `verify` batch, per patient, over `verified`/`clinician_confirmed` facts:
| Check | Logic |
|---|---|
| Allergy contradiction | Same substance/group has `present` in one source and `denied` in a newer one (e.g., 2024 PDF *Penicillin* vs today's "no allergies"). Also: a blanket "no allergies" statement vs. any `present` allergy on file. |
| Medication contradiction | "Not taking X" (`denied` medication) vs. X on the current list. |
| Value contradiction | Same LOINC, same date, different values across documents. |
| Diagnosis contradiction | "No history of diabetes" vs. active E11 on file. |
Each hit creates a `safety_alerts` row (`rule_id='RECORD-CONTRADICTION'`) whose trace lists both facts **with their sources** (PDF page + bbox, audio span). Resolution UI: the doctor picks which is true → the other fact is `superseded`, the alert `resolved` (audited).

> Negation is what prevents false alarms: *"not mentioned"* never contradicts anything; only an explicit `denied` can.

### 10.3 Step 3 — Safety rule DSL (rules are data)
Rules live in `safety_rules.rule` and are evaluated by one generic engine. Example:

```json
{
  "id": "KDIGO-METFORMIN-EGFR30",
  "type": "lab_contraindication",
  "all": [
    { "fact": { "type": "medication", "generic": "metformin", "assertion": "present" } },
    { "metric": "egfr", "op": "<", "value": 30 }
  ],
  "message": "Metformin is contraindicated when eGFR < 30 mL/min/1.73 m²",
  "source": "KDIGO guideline (metformin in CKD) · metformin product labelling"
}
```
Seed with `insert into safety_rules(id,title,rule_type,guideline_source,severity,rule) values (…)`. Add `clinician_reviewed_by` and log it in `docs/clinical_review_log.md`. Starter rule list (aligned to the scenarios):

| Rule id | Type | Fires when |
|---|---|---|
| `KDIGO-METFORMIN-EGFR30` | lab_contraindication | metformin present AND eGFR < 30 |
| `INT-PAIR` | interaction | any two current medications form a row in `drug_interactions` (severity ≥ moderate) |
| `DUP-THERAPY` | duplicate | two current meds share a generic (or ATC level-5 code) |
| `DOSE-MAX-DAILY` | dose | Σ(amount × times_per_day) per generic > `dose_limits.max_daily_mg` |
| `ALLERGY-CONFLICT` | allergy | prescribed generic ∈ an `allergy_groups` group of a `present` allergy |
| `RECORD-CONTRADICTION` | contradiction | §10.2 |
| `UNVERIFIED-GATE` | info | facts still `extracted` exist for this encounter (banner, see below) |

### 10.4 Step 4 — Deterministic metrics (`safety/metrics.py`)
```python
def egfr_ckdepi_2021(scr_mg_dl: float, age: int, sex: str) -> float:
    k = 0.7 if sex == "F" else 0.9
    a = -0.241 if sex == "F" else -0.302
    v = 142 * min(scr_mg_dl / k, 1) ** a * max(scr_mg_dl / k, 1) ** -1.200 * 0.9938 ** age
    return v * 1.012 if sex == "F" else v
```
- Inputs come from facts (latest *verified/confirmed* creatinine within a configurable window, e.g., 90 days) and `patients` (age at the date of the creatinine, sex).
- If any input is missing/stale → return `None` and record `"metric_unavailable"` in the trace (do **not** fire, do **not** silently pass; show "eGFR cannot be computed: no creatinine in 90 days").
- Unit tests: oracles in §6.1 (`28.2`, `28.7`, `58.2`, `45.5`, `94.6`, tolerance ±0.1).
- Persist the computed value as a derived fact (`LOINC 62238-1`, `created_by='system:metric'`, with `dose={"formula":"CKD-EPI 2021","inputs":[fact ids]}`) so it appears on trends and in provenance.

### 10.5 Step 5 — Engine & Explainability Trace (`safety/engine.py`, `trace.py`)
1. Load active rules; load the patient's `verified`/`clinician_confirmed` facts (**only these**).
2. Evaluate each rule; for every condition record *inputs, comparison, result*.
3. On fire → insert `safety_alerts` with `trigger_fact_ids` and the trace:
```json
{
  "rule": { "id": "KDIGO-METFORMIN-EGFR30", "version": "1",
            "source": "KDIGO guideline (metformin in CKD)" },
  "steps": [
    { "label": "Medication on list", "result": true,
      "fact_id": "…", "evidence": "\"Glycomet 500\" → metformin (dictionary: glycomet→metformin)" },
    { "label": "Computed eGFR", "value": 28.2, "unit": "mL/min/1.73 m²",
      "formula": "CKD-EPI 2021", "inputs": [
        {"name":"creatinine","value":2.1,"unit":"mg/dL","fact_id":"…","source":"labs_2026.pdf p1"},
        {"name":"age","value":50},{"name":"sex","value":"F"}] },
    { "label": "eGFR < 30", "result": true }
  ],
  "conclusion": "Metformin is contraindicated when eGFR < 30"
}
```
4. **Unverified gate:** if there are `extracted` (unverified) facts in the encounter, show *"N facts are not yet verified and were not evaluated by the safety engine"* — never imply "no alerts = safe".
5. **Idempotency:** re-running must not duplicate alerts (unique key: rule + trigger fact set + open status).
6. **Alert handling:** `acknowledge` or `override` require doctor role and a free-text reason (`override_reason`), both audited.
7. API: `GET /patients/{id}/alerts`, `POST /alerts/{id}/ack|override|resolve`, `GET /alerts/{id}/trace`.

**Done when:** S1 fires `KDIGO-METFORMIN-EGFR30` with the exact trace above; S3 fires nothing; S4 fires interaction + duplicate + dose-max; S2 fires contradiction + allergy-conflict; S6 fires nothing. All six asserted in `pytest`.

---

## 11. Phase 7 — SOAP generation from verified facts 🅱

> Blueprint: audio → structured SOAP. ACESO: **facts → SOAP**, so every sentence is traceable.

1. **Select inputs:** facts for the encounter in `verified`/`clinician_confirmed`, mapped to sections:
   | Section | Fact types |
   |---|---|
   | **S**ubjective | `symptom`, `history`, patient-reported `medication`, `allergy` (present *and* denied) |
   | **O**bjective | `vital`, `lab_result`, exam findings |
   | **A**ssessment | `diagnosis` |
   | **P**lan | `plan_item`, prescribed `medication` |
2. **Prompt the LLM** with fact IDs + normalised values only (no raw transcript). Instruction: *write concise clinical sentences; each sentence must list the `fact_ids` it uses; do not add anything not in the facts; preserve negations.*
3. **Output schema:** `{subjective:[{text, fact_ids[]}], objective:[…], assessment:[…], plan:[…]}`.
4. **Validator (`soap/validate.py`) — hard gates:**
   - Every sentence has ≥ 1 `fact_id`, all belonging to this encounter.
   - **Number guard:** every number/unit in a sentence must appear in the cited facts (blocks changed doses).
   - **Negation guard:** a sentence citing a `denied` fact must contain a negation cue.
   - **Coverage guard:** all `never-collapse` facts (allergies, doses, new medications) are cited somewhere in the note.
   - Fail → one regeneration with the violations listed; still failing → **deterministic template fallback** (`"Allergy: Penicillin — present"`, `"Metformin 500 mg BD"`). The note is never blocked by the LLM.
5. Insert into `soap_notes` (`status='draft'`, `generated_by = adapter id + prompt version`); Realtime notifies the review UI.
6. Unsupported-claim rate for this step is measured by the eval harness (§17).

**Done when:** every sentence in the S1 draft is clickable to its source in the UI; deleting one fact from the input makes the corresponding sentence disappear (proves it's fact-driven).

---

## 12. Phase 8 — UI/UX design system & frontend build 🅲

> Start this phase **right after Phase 2**: the golden data (§6.4) lets you build every screen before the pipeline works. Replace golden data with live data as phases 3–7 land.

### 12.1 Design principles
1. **Clinician time is the scarcest resource.** Default views are calm and short; effort is requested only where risk lives.
2. **Provenance is one click away.** Any fact, sentence or alert opens its exact source (PDF box or audio span).
3. **Never rely on colour alone.** Every state has an icon *and* a text label (colour-blind safe, glanceable).
4. **Loud only for danger.** Reserve red/high-contrast for critical safety alerts; everything else is quiet.
5. **Never hide risk.** Allergies, doses and new medications are never collapsed.
6. **Keyboard-first review.** The review flow must be completable without the mouse.
7. **Honest uncertainty.** Show "not verified", "cannot compute", "no evidence found" — never a silent blank.

### 12.2 Design tokens (Tailwind + CSS variables)
```css
:root {
  /* fact lifecycle */
  --state-extracted:  #B45309;  /* amber  — icon ◔  "Unverified"        */
  --state-verified:   #1D4ED8;  /* blue   — icon ✓   "Verified"          */
  --state-confirmed:  #15803D;  /* green  — icon ✔✔  "Doctor-confirmed"  */
  --state-rejected:   #6B7280;  /* grey   — icon ✕   "Rejected" (strike) */
  /* alert severity */
  --sev-critical: #B91C1C;  --sev-high: #C2410C;  --sev-moderate: #A16207;  --sev-info: #475569;
  /* surfaces */
  --bg: #F8FAFC; --surface: #FFFFFF; --ink: #0F172A; --muted: #64748B; --border: #E2E8F0;
  --focus: #2563EB;
}
```
- Fonts: **Inter** for UI; **Noto Sans Tamil** and **Noto Sans Devanagari** for patient content (self-host the font files so the demo works offline).
- Body 15–16 px; data tables 14 px with 36–40 px row height; touch targets ≥ 40 px.
- Contrast: WCAG AA minimum (check every token pair).
- Optional dark mode via `prefers-color-scheme` — only after core screens are done.

### 12.3 Information architecture & routes (Next.js App Router)

| Route | Roles | Purpose |
|---|---|---|
| `/login` | all | Email/password; **demo role switcher** (3 buttons that auto-fill seeded accounts) |
| `/` | all | Role-based dashboard (doctor: review queue + alerts + overdue loops; nurse: today's patients + vitals entry; admin: users + audit) |
| `/patients` | doctor, nurse, admin* | Search/list patients (*admin sees demographics only) |
| `/patients/[id]` | doctor, nurse | **Chart** — tabs: Overview · Timeline · Trends · Facts · Documents · Search · Alerts |
| `/patients/[id]/consult/[encId]` | doctor | Live scribe + gap prompts |
| `/patients/[id]/review/[encId]` | doctor | **Review-by-exception + sign-off** |
| `/patients/[id]/export/[encId]` | doctor | Patient-facing summary preview + print |
| `/documents/[id]` | doctor, nurse | PDF viewer with OCR/fact overlay |
| `/admin/users` · `/admin/audit` | admin | User management; audit log + "Verify chain" |
| `/eval` | doctor, admin | Evaluation dashboard (§17) |

Route protection: Next.js middleware checks session; each page wraps content in `<RoleGuard allow={[...]}>`; **RLS is the real enforcement** — UI guards are only for UX.

### 12.4 Screen specifications

**A. Patient chart header (persistent on every chart tab)** — the safety banner is always visible.
```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ Meena Rajan · 50 F · MRN ACE-0001 · தமிழ்                    [Start consult] │
│ ⚠ ALLERGIES: Penicillin (rash) ✔✔ confirmed      ⛔ 1 critical alert         │
│ Active meds: Metformin 500 mg BD ✔✔ · Telmisartan 40 mg OD ✓                 │
└──────────────────────────────────────────────────────────────────────────────┘
 Overview | Timeline | Trends | Facts | Documents | Search | Alerts(1)
```

**B. Consult screen (live scribe + gap prompts)**
```text
┌─ Recording ● 03:41  [Pause] [End consult] ───────────────────────────────────┐
├───────────────────────────────┬─────────────────────────┬────────────────────┤
│ LIVE TRANSCRIPT               │ FACTS CAPTURED (live)   │ GAP PROMPTS        │
│ Dr: How is the sugar control? │ ◔ Symptom: polyuria     │ ✅ Chief complaint │
│ Pt: Passing urine a lot…      │ ◔ Med: Glycomet 500 BD  │ ⬜ Allergies asked │
│ Dr: Continue Glycomet 500…    │                         │ ⬜ Vitals recorded │
│ (new lines slide in; click a  │ click a fact → highlights│ ⚠ Pending from last│
│  line → jumps to audio)       │ its transcript line     │   visit: HbA1c     │
└───────────────────────────────┴─────────────────────────┴────────────────────┘
```
Gap prompts are **suggestions**, dismissible, never blocking.

**C. Review-by-Exception + Sign-off (the signature screen)**
```text
┌─ Review · Meena Rajan · 09 Oct 2026 ────────────────── Progress 4/7 resolved ┐
│ NEEDS YOUR ATTENTION (7)   │ SOAP DRAFT                  │ SOURCE              │
│ ⛔ Alert: Metformin/eGFR   │ S: Patient reports polyuria │ ┌───────────────┐   │
│ ⚠ Allergy: Penicillin      │   [f1]                      │ │ labs_2026.pdf │   │
│ ⚠ Dose: Metformin 500 BD   │ O: Creatinine 2.1 mg/dL [f4]│ │  p.1          │   │
│ ◔ Low conf: "K+ 5.9"       │   eGFR 28.2 (computed) [f9] │ │  ┌─────┐      │   │
│ ◔ Possible omission:       │ A: T2DM [f2]                │ │  │ 2.1 │◄ box │   │
│   "ibuprofen sometimes"    │ P: Continue metformin 500   │ │  └─────┘      │   │
│ …                          │   BD [f7] ← ⛔ blocked      │ └───────────────┘   │
│ ▸ 12 verified items hidden │ (every sentence clickable)  │ ▶ audio 00:41–00:45 │
│   (labs, vitals, history)  │                             │ [Explain ▾]         │
├────────────────────────────┴─────────────────────────────┴─────────────────────┤
│ [Confirm (Enter)] [Edit (E)] [Reject (X)]        ☐ 3 never-collapse items open │
│                                           [ Sign off & finalise ] (disabled)   │
└────────────────────────────────────────────────────────────────────────────────┘
```
**Exactly what is collapsed** — a fact is collapsible only if **all** hold: `state='verified'`, `confidence ≥ 0.90`, no `needs_attention`, and `fact_type`/dose is **not** one of: allergy, medication dose, **new** medication (a medication with no earlier `clinician_confirmed` match for this patient). Collapsed facts live in expandable groups ("12 verified items — labs, vitals, history").

**Sign-off gating** (button enabled only when all true; the API re-checks them server-side):
1. Every item in "Needs your attention" is confirmed, edited or rejected.
2. Every never-collapse fact is **explicitly** confirmed (no bulk-confirm for these).
3. Every critical/high alert is acknowledged or overridden **with a reason**.
4. No unresolved `possible_omission`.
On sign-off a summary dialog shows counts ("5 confirmed · 2 edited · 1 rejected · 1 override") and requires a final click. Result: facts → `clinician_confirmed`, note → `signed`, audit rows written, the encounter turns read-only.

**D. Alert card + Explain drawer**
```text
⛔ CRITICAL · Metformin is contraindicated when eGFR < 30      [Acknowledge] [Override…]
   ┌─ Explain ───────────────────────────────────────────────────────────────┐
   │ Rule: KDIGO guideline (Metformin in CKD)                                │
   │   ├─ Medication on list: Metformin   ← "Glycomet 500" (brand→generic)   │
   │   ├─ Computed eGFR = 28.2 mL/min/1.73m²  [CKD-EPI 2021]                 │
   │   │      ├─ Creatinine 2.1 mg/dL  → labs_2026.pdf p.1 [view box]        │
   │   │      ├─ Age 50 · Sex F                                              │
   │   └─ eGFR < 30 → TRUE   ⇒  CONTRAINDICATED                              │
   └─────────────────────────────────────────────────────────────────────────┘
```
Each leaf with a `fact_id` is a link into the source viewer. Override opens a modal requiring a reason (min 10 chars).

**E. Timeline tab** — vertical, month-grouped, filter chips (Visits · Labs · Meds · Diagnoses · Alerts · Documents); each row shows icon, date, title, state badge, and a source link.

**F. Trends tab** — one small chart per lab (HbA1c, creatinine, eGFR, BP…): line + points, shaded **reference range band**, out-of-range points flagged, vertical **medication start/stop markers**, table toggle for accessibility, and a one-line deterministic summary ("HbA1c fell from 8.9% to 7.6% over 6 months").

**G. Search tab** — one search box; results as a short answer with **citation chips** `[1] [2]`; below it, the evidence list (date · type · snippet · source). Empty result → "No supporting record found in this patient's chart." Never a guess.

**H. Document viewer** — PDF page with an overlay layer: hover an OCR block to see its text/confidence; facts drawn as coloured boxes by lifecycle state; toggle "show all OCR". Deep link `?fact=<id>` scrolls to and pulses the box.

**I. Patient-facing summary preview** — language switcher (EN/TA/HI), large type, medicines as a table (name · dose · when · how long), follow-up date, doctor-approved warning signs; a **"Generated from verified data only"** footer; Print button.

**J. Admin → Audit** — filterable table (time · actor · role · action · entity · from→to), expandable payload, **Verify chain** button showing ✅ intact / ❌ broken at row N.

**K. Empty / loading / error states** — every list has a skeleton, an empty message that says what to do next, and an error state with retry. Pipeline jobs show progress ("Transcribing… Extracting facts… Verifying 14/20").

### 12.5 Component inventory
`AppShell` · `RoleGuard` · `PatientHeader` · `AllergyBanner` · `StateBadge` · `FactChip` · `FactTable` · `ExceptionQueue` · `CollapsedGroup` · `SoapSentence` (clickable, shows `[fN]` chips) · `SourceViewer` = `PdfBBoxViewer` + `AudioSpanPlayer` · `AlertCard` · `ExplainTrace` (tree) · `OverrideDialog` · `SignOffBar` + `SignOffDialog` · `LiveTranscript` · `GapPanel` · `Timeline` · `LabTrendChart` · `OpenLoopList` · `SearchBox` + `CitationChip` · `ExportPreview` · `AuditTable` · `ChainVerifyButton` · `EvalDashboard`.

### 12.6 Build steps (in this order)
1. **Scaffold:** `pnpm create next-app apps/web --ts --tailwind --app`; add `shadcn/ui`, `@supabase/ssr`, `@tanstack/react-query`, `recharts`, `react-pdf`, `wavesurfer.js`, `lucide-react`, `zod`.
2. **Tokens & primitives:** CSS variables above; build `StateBadge`, `FactChip`, `AlertCard` in isolation (Storybook optional) using hard-coded props. Review contrast.
3. **Auth & shell:** Supabase SSR client; login page with role switcher; `AppShell` with role-aware nav; middleware redirect.
4. **Patient list & chart header** reading golden data via Supabase (RLS active — test as each role).
5. **Source viewer (hardest component — do it early).**
   - `PdfBBoxViewer`: render page to canvas with pdf.js; overlay an absolutely-positioned `<div>` per highlighted fact at `left = x·W, top = y·H, width = w·W, height = h·H` (bbox is normalised, so zoom/resize "just works"); on `?fact=` scroll the box into view and pulse it.
   - `AudioSpanPlayer`: wavesurfer.js with the Regions plugin; given `[start_ms,end_ms]` create a region, seek to start, play the span, loop optional; show the transcript lines in range.
   - A single `<SourceViewer fact={…}/>` chooses the viewer by `fact.source`.
6. **Facts tab:** table with filters (type, state, needs-attention), `StateBadge`, source link on every row.
7. **Review screen:** `ExceptionQueue` + `CollapsedGroup` + `SoapSentence` + `SourceViewer` + `SignOffBar`. Implement the collapse predicate as one pure, unit-tested function `isCollapsible(fact, patientHistory)`. Keyboard shortcuts via a `useHotkeys` hook; show a `?` help overlay.
8. **Alerts + Explain drawer:** render `trace.steps` as a tree; each leaf `fact_id` opens `SourceViewer`.
9. **Timeline & Trends** (data from §13.3 view); table toggle for every chart.
10. **Consult screen:** subscribe via Supabase Realtime to `transcript_segments` and `facts` filtered by `encounter_id`; append lines; call `GET /encounters/{id}/gaps` on each batch to refresh `GapPanel`. Audio capture with `MediaRecorder` (8-second chunks → API).
11. **Search tab**, **Export preview**, **Admin audit**, **Eval dashboard**.
12. **Polish pass:** skeletons, empty/error states, focus order, `aria-label`s, Tamil/Hindi font rendering check, print stylesheet for the export page.
13. **E2E (Playwright):** one test per role plus the full "S1 consult → alert → override → sign-off" flow.

### 12.7 Data access pattern
- **Reads:** Supabase client (RLS-protected) for lists/charts; Realtime for `transcript_segments`, `facts`, `safety_alerts`, `soap_notes`, `jobs`.
- **Writes that need rules** (confirm, sign, override, resolve contradiction, upload): call the **FastAPI** endpoints (they re-check role, gating and write audit rows). Don't let the browser update `facts.state` directly.
- Shared TS types from `supabase gen types`; API types from FastAPI's OpenAPI (`openapi-typescript`).

### 12.8 Phase 8 — Done when
- [ ] Every screen renders from golden data with no pipeline running.
- [ ] A doctor can complete the whole review for S1 using only the keyboard.
- [ ] Allergy, dose and new-medication facts can never be hidden inside a collapsed group (unit test on `isCollapsible` + Playwright assertion).
- [ ] Clicking any SOAP sentence, fact or alert leaf opens the exact PDF box or audio span.
- [ ] Nurse and admin views hide forbidden actions *and* the API/RLS refuses them when forced.
- [ ] Lighthouse accessibility score ≥ 90 on chart and review pages.

---

## 13. Phase 9 — Search, timeline, trends & workflow features 🅱 (backend) + 🅲 (UI)

> Blueprint link: *Pillar 2 — Intelligent Data Organization & Advanced Search* and the *Timeline / Trend* modules, plus the master architecture's high-impact secondary features.

### 13.1 Natural-language search (hybrid, citation-only)
**Indexing (`embed` job, runs after `verify`):**
1. Create one chunk per **fact** as a short canonical sentence, e.g. `"2026-09-25 · Lab · Creatinine, serum 2.1 mg/dL · verified · labs_2026.pdf p.1"`.
2. Create chunks per transcript **window** (3–4 segments) and per OCR **table row**.
3. Embed with `multilingual-e5-small` using the `passage: ` prefix; store in `fact_chunks` with `metadata {date, type, source_kind, page_no}`.

**Query path (`search/hybrid.py`):**
1. **Intent parse** (rules first, LLM only if needed) → filters `{fact_types, loinc, date_from, date_to, assertion}`. "Last HbA1c" and "any penicillin allergy?" resolve to **pure SQL** — no LLM and no embedding needed.
2. **Structured retrieval:** SQL on `facts` (only `verified`/`clinician_confirmed` by default; toggle to include `extracted`, shown labelled).
3. **Semantic retrieval:** embed the query with the `query: ` prefix → `match_chunks(patient_id, vec, 10)`.
4. **Lexical retrieval:** trigram `ILIKE`/`similarity()` on `fact_chunks.content`.
5. **Fuse** with Reciprocal Rank Fusion: `score = Σ 1/(60 + rank_i)`; keep the top 8.
6. **Answer composer:** the LLM sees *only* the retrieved evidence (with IDs) and must answer in 1–3 sentences with `[evidence_id]` citations. Validator: every sentence has ≥ 1 valid citation; numbers must appear in cited evidence; otherwise return the evidence list without a prose answer.
7. Nothing retrieved → `"No supporting record found in this patient's chart."`
8. Log each query to `audit_log` (`action='search.query'`) — a search through a medical record is an access event.

**API:** `POST /patients/{id}/search {q}` → `{answer, citations[], evidence[]}`.
**Done when:** "What was her creatinine last month?" returns *2.1 mg/dL* with a citation chip that opens the PDF box; "Does he have a sulfa allergy?" (S3) returns a *denied* answer citing the audio span; a question about something absent returns the "no supporting record" message.

### 13.2 Live gap prompts
Computed by `GET /encounters/{id}/gaps` (deterministic; no LLM):

| Checklist item | Captured when |
|---|---|
| Chief complaint | a `symptom`/`history` fact or `encounters.chief_complaint` exists |
| **Allergies asked** | an `allergy` fact (present *or* denied) in this encounter, or a segment matching allergy cues |
| Current medications reviewed | ≥ 1 `medication` fact in this encounter |
| Vitals recorded | `vital` facts (BP, HR, weight…) today |
| **Pending from last visit** | `open_loops` for this patient that are open and have no resulting fact (e.g., "HbA1c due") |
| Follow-up plan stated | a `plan_item` fact in this encounter |
Response: `[{key, label, status: "captured"|"missing"|"pending_from_history", detail}]`. The UI refreshes it on every Realtime event (§12.6 step 10). Prompts are dismissible and logged (not clinical facts).

### 13.3 Timeline & trend analysis
**Timeline view (SQL, `0009_timeline.sql`):**
```sql
create or replace view patient_timeline_v as
  select patient_id, started_at as at, 'encounter' as kind, id as ref_id,
         coalesce(chief_complaint,'Visit') as title, null::text as state from encounters
  union all
  select patient_id, coalesce(doc_date::timestamptz, now()), 'document', id,
         kind || ' document', status from source_documents
  union all
  select patient_id, effective_at, 'fact:'||fact_type::text, id,
         display || coalesce(' '||value_num::text||' '||unit,''), state::text
  from facts where effective_at is not null and state not in ('rejected','superseded')
  union all
  select patient_id, created_at, 'alert', id, message, status::text from safety_alerts;
```
**Trend endpoint:** `GET /patients/{id}/trends?loinc=4548-4` →
`{points:[{at,value,unit,fact_id,state}], range:{low,high}, events:[{at,type:'med_start'|'med_stop',label}], summary}`.
- Points: `lab_result` facts for that LOINC in `verified`/`clinician_confirmed`, ordered by `effective_at`.
- Range from `reference_ranges` by sex/age.
- Med markers from `medication` facts' start/stop dates.
- **Deterministic summary** (no LLM required): compare first vs. last point and the slope sign → *"HbA1c fell from 8.9 % to 7.6 % over 6 months"* / *"stable"* / *"rising"*; flag the latest out-of-range. (An LLM may rephrase only under the number guard of §11.)
- Include the computed **eGFR** as a derived series (§10.4).
**Done when:** S5 shows three HbA1c points with the downward summary and the band; clicking any point opens its source.

### 13.4 Open-loop tracker
1. **Detect:** when a `plan_item` fact is confirmed, parse follow-up commitments with a regex first — `(repeat|recheck|review|follow[- ]?up|test)\s+(.*?)\s+in\s+(\d+)\s*(day|week|month)s?` — fallback to the LLM (`{task, due_in_days}`) behind the number guard.
2. `due_date = encounter_date + N` → insert into `open_loops` (`fact_id` = the plan fact).
3. **Close:** when a later verified lab/vital fact has the same LOINC (or an encounter with matching task) → suggest `closed_by_fact_id`; the doctor confirms (one click on the dashboard).
4. **Surface:** doctor dashboard widget "Overdue (n)" from `open_loops_v.overdue`; patient chart badge; feeds the *Pending from last visit* gap prompt.
**Done when:** S5's *"repeat HbA1c in 3 months"* shows as overdue and disappears (after confirmation) when a new HbA1c fact is verified.

### 13.5 Edit-diff learning
1. At sign-off, for each SOAP sentence compare `ai_text` vs. `final_text`; store in `note_edits` with `edit_ratio` (normalised Levenshtein).
2. **Adapt style only, never clinical values:** per doctor, (a) keep a small phrase-replacement map learned from frequent edits (applied as deterministic post-processing), (b) include their 3–5 most recent accepted edits as few-shot style examples in the SOAP prompt, (c) adapt verbosity (average sentence length) and section ordering.
3. **Guardrail:** any edit that changes a number, unit, drug or assertion is **excluded** from learning and is instead logged as a *correction* (a signal for the eval harness).
4. Expose "doctor edit rate" over time on the eval page.
**Done when:** after three simulated edits (e.g., doctor always shortens "Patient reports" → "Pt c/o"), the next draft applies that style and edit rate on those sentences drops.

### 13.6 Patient summary card (concise summarization)
Shown at the top of the chart **Overview** tab; assembled **deterministically** from `clinician_confirmed` (and clearly labelled `verified`) facts:
1. **Blocks:** active problems (diagnoses) · current medications (with dose) · allergies (present and explicitly denied) · latest key labs with trend arrows (↑ ↓ →) · open alerts count · overdue loops · last visit date and plan.
2. **Optional narrative line:** the LLM may turn the blocks into a 2–3 sentence summary under the same rules as §11 (every sentence cites `fact_ids`; number and negation guards; template fallback). Without the LLM the blocks alone are still a complete summary.
3. Each item links to its source. Items from `extracted`-only facts are excluded and counted ("3 unverified items not shown").
4. API: `GET /patients/{id}/summary`. Cache per patient and invalidate on any fact state change.
**Done when:** S1's card lists metformin, the penicillin allergy (if present), creatinine/eGFR with arrows, and the critical alert, each clickable to source.

---

## 14. Phase 10 — Governance, privacy, export & patient-facing output 🅰 🅱 🅲

### 14.1 RBAC & app-layer enforcement
1. Database: RLS policies (§5.9) are the source of truth.
2. API: `require_role()` dependency on every route; **doctor-only** endpoints: confirm fact, override alert, sign note, resolve contradiction. **Admin-only:** user management, audit read, chain verification.
3. Test matrix (`pytest` parametrised over doctor/nurse/admin × endpoint × expected status 200/403) — generate it from the table in §5.9 so docs and tests can't drift.

### 14.2 Human-in-the-loop sign-off (server side)
`POST /encounters/{id}/sign` (doctor JWT):
1. Re-check the four gating rules of §12.4-C **on the server**.
2. In **one transaction:** bulk-confirm the collapsed `verified` facts referenced by the note (each emits its own audit row), confirm the explicitly reviewed facts, set `soap_notes.status='signed'`, `signed_by`, `signed_at`, `content_hash = sha256(canonical_json(note))`, set `encounters.status='signed'`, create `open_loops` (§13.4), write `audit_log` `note.sign`.
3. **Lock** signed content:
```sql
create or replace function lock_signed_note() returns trigger language plpgsql as $$
begin
  if old.status='signed' and (new.subjective,new.objective,new.assessment,new.plan)
        is distinct from (old.subjective,old.objective,old.assessment,old.plan) then
    raise exception 'Signed note is immutable; create an amendment (new version)';
  end if; return new; end $$;
create trigger lock_signed_note_t before update on soap_notes
  for each row execute function lock_signed_note();
```
4. **Amendments:** a new `soap_notes` row with `version+1` and a mandatory reason, re-entering review → sign.

### 14.3 FHIR R4 / ABDM export (official record)
Only **`clinician_confirmed`** facts leave the system.

| ACESO | FHIR resource |
|---|---|
| `patients` | `Patient` (identifier: MRN; ABHA number/address if present) |
| doctor profile | `Practitioner` (registration no.) |
| `encounters` | `Encounter` |
| `allergy` | `AllergyIntolerance` (`verificationStatus=confirmed`; `denied` allergies → recorded as *no known allergy* only if explicitly stated) |
| `medication` | `MedicationRequest` (prescribed today) / `MedicationStatement` (reported) with RxNorm/ATC coding |
| `lab_result`, `vital` | `Observation` (LOINC, UCUM units, `effectiveDateTime`, `referenceRange`) |
| `diagnosis` | `Condition` (ICD-10/SNOMED) |
| signed SOAP note | `Composition` with sections S/O/A/P + `DocumentReference` |
| everything | a `Bundle` of `type=document`, first entry = `Composition` |
Steps: (1) write mappers in `export/fhir.py` using `fhir.resources` Pydantic models; (2) generate the bundle; (3) validate with the **HAPI FHIR validator** (JAR, run from CI/CLI); (4) layer ABDM-specific profiles (e.g., OP consultation record) per the current NRCeS implementation guides — **check the latest version before the demo**; (5) endpoint `GET /encounters/{id}/fhir` + "Download FHIR bundle" button; (6) store provenance as `Provenance` resources or `meta.extension` so the audio span / bbox travel with the record.
**Done when:** the S1 bundle validates with zero errors and re-importing it into a scratch HAPI server round-trips the patient, labs and medication.

### 14.4 Privacy-first Model Gateway
All outbound LLM/VLM/OCR calls pass through `privacy/gateway.py`.
1. **Detect PHI:** Presidio analyzers (PERSON, PHONE, EMAIL, LOCATION, DATE_TIME of birth) + custom recognisers: Indian mobile (`(\+91[\- ]?)?[6-9]\d{9}`), Aadhaar (12 digits, optionally spaced), ABHA (14 digits), MRN pattern `ACE-\d{4}`.
2. **Tokenise:** replace with stable placeholders (`<PERSON_1>`, `<MRN_1>`); keep the mapping **in memory for that request only**.
3. **Call** the model with the redacted text; **rehydrate** placeholders in the response.
4. **Audit:** log an `audit_log` row per external call with `{model, bytes_out, entities_redacted_count}` — **never** the text itself.
5. **On-prem switch:** `LLM_MODE=onprem` routes everything to Ollama (no data leaves the machine) — a visible toggle in the admin page.
6. **Fail closed:** if redaction throws, the call is **not made**.
7. **Known limitation to state honestly:** page images sent to a VLM cannot be text-redacted. For images, either redact regions by OCR-detected PHI boxes before sending, or use the on-prem VLM. Document which one the demo uses.
**Done when:** a unit test sends S1 text containing name + phone + MRN and asserts none appear in the captured outbound payload.

### 14.5 Safe patient-facing summary (structured templating)
**Principle:** the LLM is not involved. Input is the **structured plan** from `clinician_confirmed` facts.
1. **Build the payload** (`patient_exports.payload`):
```json
{ "patient": {"name":"Meena Rajan","lang":"ta"},
  "medications":[{"generic":"telmisartan","display_name":"Telma","dose_mg":40,"freq":"OD","timing":"morning","duration_days":30}],
  "stopped":[{"generic":"metformin"}],
  "followups":[{"task":"repeat_hba1c","due":"2027-01-09"}],
  "warning_signs":["WS_HYPO","WS_BREATHLESS"] }
```
2. **Templates** (`export/patient_templates/{en,ta,hi}/summary.html.j2`) are written **once** and **reviewed by a native speaker and a clinician**. Medicine names stay in Latin script *and* local script; doses/frequencies come from lookup tables, not free text:
   `freq_map = {"OD": {"en":"Once a day","ta":"தினமும் ஒரு முறை","hi":"दिन में एक बार"}, "BD": {...}, "TDS": {...}}`
   Warning signs are a fixed, doctor-approved list keyed by code (`WS_HYPO`, …) — never generated.
3. **Render** with Jinja2 → HTML (Noto fonts) → browser **Print to PDF**.
4. **Round-trip check (automatic, blocks export on failure):** parse the rendered HTML back for every dose number, frequency code and date, and assert they equal the payload. Any mismatch → refuse to render and log.
5. Footer: *"Prepared from your doctor's verified record on <date>. Ask your doctor if anything is unclear."*
6. Only the signed encounter can be exported.
**Done when:** the S1 summary renders in en/ta/hi; changing a dose in the payload changes it in all three languages with no other edits; the round-trip check catches a deliberately corrupted template.

---

## 15. Phase 11 — Integration & end-to-end hardening (everyone)

### 15.1 End-to-end sequence for one scenario (S1)
```text
Upload labs_2026.pdf ─► job perceive_document ─► ocr_blocks
Record visit.wav     ─► job perceive_audio    ─► transcript_segments
        │                          │
        └────────► job extract (LLM + normalise + negation) ─► facts[extracted]
                                   │
                          job verify (3-way) ─► facts[verified | needs_attention]
                                   │
        ┌──────────────────────────┼───────────────────────────┐
   job embed (search)      job safety (engine+contradictions)   job soap (fact-driven)
                                   │
                       Review screen (doctor) ─► confirm / edit / override
                                   │
                           Sign-off ─► FHIR bundle + patient summary + open loops
```
### 15.2 Steps
1. Write `scripts/run_scenario.py <key>` that seeds inputs, runs all jobs to completion, and prints a one-page report (facts by state, alerts fired, note validity). Run all six scenarios.
2. **Idempotency:** re-running a stage must not duplicate facts/alerts (natural keys: `(source, span/bbox, code, assertion)`).
3. **Failure handling table** — each row must be tested:

| Failure | Expected behaviour |
|---|---|
| STT/OCR/LLM timeout | Job retries ×3, then `failed`; UI shows retry button; **no partial facts without provenance** |
| LLM returns invalid JSON | One repair attempt, then job `failed` with logged raw output |
| Unmapped drug | Fact kept, `needs_attention: unmapped_drug`, excluded from safety until resolved (shown in "not evaluated" banner) |
| eGFR cannot be computed | Rule not fired; trace states why; banner shows "metric unavailable" |
| Supabase unreachable | UI read-only banner; API returns 503; worker backs off |
| Redaction error | External call blocked (fail closed) |
4. **Performance budget:** 2-minute consult → draft ready ≤ 90 s on the demo machine (record actual numbers; precompute a warm run as a fallback for the live demo).
5. **Security pass:** service-role key only on the backend; storage buckets private; no PHI in logs; CORS limited to the web origin; rate limit upload endpoints.

---

## 16. Phase 12 — Stretch: code-mixed multilingual scribe 🅱
*Only start after Phases 1–11 and the eval harness are green.* Treat as an experiment and **report results honestly** (including failures).
1. **Language-aware transcription:** run Whisper with per-segment language detection; for Tamil-English code-mixing, compare `medium`/`large-v3` against a fine-tuned or Indic-specialised model if available; record WER on S5's code-mixed script.
2. **Speaker diarization:** `pyannote.audio` to separate doctor/patient on single-channel audio; evaluate diarization error on the scripted dialogues.
3. **Dynamic vocabulary normalization:** build a lexicon mapping colloquial/transliterated terms ("sakkarai" ↔ sugar, "BP tablet", brand names in Tamil script) to canonical concepts; apply *after* STT and *before* extraction; flag unmapped tokens.
4. **Multilingual negation cues:** add Tamil/Hindi negation markers (e.g., Tamil *illai*, Hindi *nahi*) to §8.4 with native-speaker review; test on S5/S3 variants.
5. **Reporting:** add a "Multilingual" section to the eval report with WER, extraction F1 and failure examples.
**Done when:** you can show a measured improvement (or a documented, explained failure) on the code-mixed set.

---

## 17. Phase 13 — Evaluation harness 🅰

> *"A wrapper demo says it works. We say it works this well, and here is where it fails."* This phase turns that sentence into numbers. Build the skeleton **early (right after the S1 vertical slice)** and grow it with every scenario.

### 17.1 Layout & run flow
```text
eval/
├── run.py                # python -m eval.run --scenarios all --llm <adapter> --variant clean,scan,bad
├── metrics.py            # pure functions, unit-tested
├── inject.py             # synthetic error injection (OCR digit swaps, unit swaps, dropped sentences)
├── baseline_wrapper.py   # "LLM writes SOAP directly from transcript" — the strawman we compare against
├── cache/                # recorded LLM responses for deterministic CI replays
└── reports/
    ├── REPORT.md         # headline table + charts (auto-generated)
    └── FAILURES.md       # every miss, categorised, with links to the source span/box
```
Flow: for each scenario × quality variant → run the real pipeline → compare outputs to `truth.json` → write `eval_runs` / `eval_results` rows → render `REPORT.md` and the `/eval` dashboard. Use temperature 0 and record/replay LLM calls so CI results are reproducible.

### 17.2 Metric definitions (write these into the report so judges can audit them)

| Metric | Definition | Target (set honestly, then report actuals) |
|---|---|---|
| **Extraction F1** | A predicted fact is a true positive if `(type, normalised code, assertion, value within tolerance, source)` matches a ground-truth fact. Precision = TP/(TP+FP), Recall = TP/(TP+FN). Report overall, **per fact type**, and **per quality variant**. | ≥ 0.90 on `clean`; show the drop on `scan`/`bad` |
| **Unsupported-claim rate** (hallucination) | `# SOAP sentences not supported by their cited facts ÷ # sentences`. Judged automatically (number/negation guards) **and** by a manual read of all synthetic notes (the set is small enough to review fully). Also report `# extracted facts absent from ground truth`. | ≤ 2 % (target 0 % after guards) |
| **Citation precision** | Of all provenance links shown to the user, the share that are correct: audio span with temporal IoU ≥ 0.5 vs. truth, or bbox IoU ≥ 0.5 vs. truth. | ≥ 0.95 |
| **Interaction recall** | `planted safety issues caught ÷ planted` across S1, S2, S4 (+ contradictions). Also **alert precision** = `correct alerts ÷ all alerts` and false-alert count on S3/S6 (`must_not_fire`). | recall = 1.0 on planted set; 0 false alerts on S3/S6 |
| **Doctor edit rate** | Mean normalised edit distance between AI draft and the doctor's final text; plus the % of sentences accepted unchanged. Collect from a **review session with a clinician/teammate acting as doctor** on all six drafts. | report the number whatever it is |
| **Verification-pass catch rate** | `injected errors caught (fact left unverified/flagged) ÷ errors injected` using `inject.py`. | ≥ 0.9 |
| **Confidence calibration** | Reliability plot: bins of confidence vs. actual correctness; choose the "verified" threshold so ≥ 98 % of verified facts are correct. | chart in report |
| **Latency** | p50/p95 per stage; end-to-end per consult. | §15.2 budget |

### 17.3 Experiments that make the pitch land
1. **Wrapper vs. ACESO:** run `baseline_wrapper.py` (LLM writes the SOAP from the transcript, then we attach citations afterwards) and compare *unsupported-claim rate* and *citation precision* against fact-first generation. Expect the gap to be the headline.
2. **Swap Test:** run the whole harness with two different LLM adapters; present a table of metric deltas. Small deltas = the IP is in the pipeline, not the model.
3. **Ablations:** disable (a) the 3-way verification, (b) negation handling, (c) the unverified gate — show which errors reappear (e.g., false allergy alarms on S3 without negation handling).
4. **Degradation sweep:** `clean → scan → bad` on every document; plot F1 vs. quality.
5. **Error injection:** corrupt OCR digits and units; show the verification pass catching them.

### 17.4 `FAILURES.md` (the honesty section)
Auto-generate, for every miss: scenario, fact, category (`ocr_error`, `unmapped_drug`, `negation`, `omission`, `wrong_span`, `llm_invalid`, `metric_unavailable`), expected vs. actual, and a deep link to the source. Group by category and write 2–3 sentences of analysis per group. **Do not hide failures** — a short, understood failure list is more credible than a perfect score on six patients. State clearly that the synthetic set is small and is not a clinical validation.

### 17.5 Done when
- [ ] `python -m eval.run --scenarios all` completes and writes `REPORT.md`, `FAILURES.md` and DB rows.
- [ ] `/eval` page shows the metric table, per-scenario drill-down, and the wrapper-vs-ACESO comparison.
- [ ] Metric functions have unit tests with hand-computed tiny examples.
- [ ] CI runs the harness on cached LLM outputs and fails if any headline metric regresses by > 3 points.

---

## 18. Phase 14 — Testing, deployment & demo 🅰 🅱 🅲

### 18.1 Test pyramid
| Level | What | Tools |
|---|---|---|
| Unit | eGFR oracles, normalisation, negation cues, `isCollapsible`, SOAP validators, metric functions, template round-trip | `pytest`, `vitest` |
| Database | state-machine triggers, immutability, hash chain, RLS per role (use real JWTs for doctor/nurse/admin) | `pytest` + Supabase client |
| Integration | each job handler on fixture inputs; idempotency | `pytest` |
| Scenario | six scenarios end-to-end vs. `truth.json` | `eval/run.py` |
| E2E UI | role flows; S1 consult→override→sign; keyboard-only review | Playwright |
| Security | no service key in the browser bundle; forbidden-action matrix returns 403; no PHI in logs; redaction test | scripted checks |

### 18.2 Deployment (demo-grade)
1. **Supabase:** already shared; run `supabase db push` for the final migration set; confirm RLS is **enabled on every table** (`select relname from pg_class where relrowsecurity=false and relkind='r' and relnamespace='public'::regnamespace;` should list none you care about).
2. **Backend:** `docker compose up api worker` on the demo machine (GPU if available for Whisper). Provide a `docker-compose.yml` with the two services and the `.env` file mounted.
3. **Frontend:** deploy to Vercel *or* `pnpm build && pnpm start` locally; set `NEXT_PUBLIC_API_URL`.
4. **Reset script:** `scripts/reset_demo.sh` → deletes `scratch_*` data, re-runs all idempotent seeds, pre-warms the pipeline for S1 so the live run has cached fallbacks.
5. **Keep Supabase awake:** open the project the day before and run one query on the morning of the demo.
6. **Offline fallback:** `LLM_MODE=onprem`, `STT_ENGINE=faster_whisper`, `OCR_ENGINE=tesseract` — rehearse a full run with Wi-Fi off, except the Supabase connection (or have a pre-recorded video of the live parts).

### 18.3 Demo script (≈ 8 minutes)
| # | Time | Beat | Shows |
|---|---|---|---|
| 1 | 0:30 | The three problems in one sentence each | Blueprint framing |
| 2 | 1:30 | **S1:** drop in the lab PDF; play the consult; facts stream in with ◔ → ✓ states | STT/OCR, fact-first, verification |
| 3 | 1:00 | **Metformin critical alert → Explain** (eGFR = 28.2 from creatinine 2.1 → rule) → click *2.1* → PDF box lights up | Deterministic safety + explainability + provenance |
| 4 | 1:00 | **Review-by-exception:** "12 verified items hidden", allergies/doses never collapsed; edit the plan; override with reason; sign-off | HITL, review UX |
| 5 | 0:45 | **S2:** 2024 PDF says penicillin allergy, patient says none → contradiction + amoxicillin conflict. **S3:** negation → no false alarm | Longitudinal store, negation |
| 6 | 0:45 | **S5:** HbA1c trend, overdue open loop, NL search with citation chip | Pillar 2 |
| 7 | 0:45 | Patient summary in Tamil (templated) + FHIR bundle download | Safe export, interoperability |
| 8 | 0:30 | Admin: audit log → **Verify chain** ✅ (optionally tamper in a scratch copy → ❌) | Governance |
| 9 | 0:45 | **Eval slide:** headline metrics, wrapper-vs-ACESO, Swap Test table, **where it fails** | The pitch line |
**Rehearse 3×.** Keep a recorded backup of every step with live dependencies (audio, OCR, LLM).

### 18.4 Likely judge questions — prepare crisp answers
- *"What stops the LLM hallucinating?"* → It never writes unsupported content: facts need provenance (DB constraint), pass 3 checks, and SOAP sentences must cite fact IDs with number/negation guards; metrics prove it.
- *"Why not plain RAG?"* → RAG cites whole documents; we cite exact boxes/audio spans and keep a time-aware fact store with lifecycle and contradiction detection.
- *"Who decides a drug is unsafe?"* → Versioned, clinician-reviewed rules over computed metrics; the LLM is not involved.
- *"What if you swap the model?"* → Show the Swap Test table.
- *"You said not PostgreSQL — what's Supabase?"* → Hosted Postgres + Auth + Storage + Realtime; chosen so three machines share one database with no local installs.
- *"Is this clinically validated?"* → No: synthetic set, honest failure analysis, clinician review of rules/templates is logged; next step would be a supervised pilot.

---

## 19. Master build order, milestones & risks

### 19.1 Principle: **vertical slice first, then widen**
Build **S1 (metformin + CKD)** end-to-end *thinly* — audio + PDF → facts → verification → eGFR alert → review screen → sign-off — before adding other scenarios or secondary features. Every layer then gets integration-tested on day one instead of at the end.

### 19.2 Milestones (compress or stretch to your real deadline)

| Milestone | Outcome | 🅰 Data & Safety | 🅱 AI Pipeline | 🅲 Frontend & UX |
|---|---|---|---|---|
| **M0 Foundations** (§4) | Repo, Supabase, env on 3 machines | Supabase project, CLI, CI skeleton | FastAPI skeleton, `/health` | Next.js scaffold |
| **M1 Contract freeze** (§5–6) | Schema, RLS, seeds, golden data, OpenAPI stubs | Migrations 0001–0008, seeds, types | LLM adapter, job worker, API stubs | Tokens, primitives, auth shell |
| **M2 S1 vertical slice** (§7–11) | Thin end-to-end for S1 | eGFR, rule engine, trace | STT, OCR, extract, verify, SOAP | Chart, source viewer, review screen |
| **M3 Safety complete** | S2, S3, S4, S6 pass; sign-off & audit live | Contradictions, dup/dose/interaction rules, sign-off API | Negation, normalisation breadth, omission check | Alert/Explain UI, sign-off gating |
| **M4 Pillar 2 & export** (§13–14) | Search, timeline, trends, loops, gaps, FHIR, patient summary | FHIR mappers, loop logic | Hybrid search, embeddings, privacy gateway | Timeline/trend/search/export/consult screens |
| **M5 Proof** (§17) | Eval report, calibration, ablations, hardening | Harness, ground truth, metrics | Error injection, latency tuning | Eval dashboard, polish, a11y |
| **M6 Demo** (§18) | Rehearsed, backed-up demo | Reset script, backups | Warm caches, offline mode | Demo flow polish |
| *(Stretch)* (§16) | Code-mixed scribe experiment | — | Diarization, Tamil-English | — |

### 19.3 Dependency view
```text
Phase 0 ─► Phase 1 (schema) ─► Phase 2 (seed) ──┬──► Phase 8 UI (golden data)  ─┐
                    │                            │                              │
                    └─► Phase 3 (STT/OCR) ─► 4 (extract) ─► 5 (verify) ─► 6 (store+safety) ─► 7 (SOAP)
                                                                         │                      │
                                                                         └──► 9 (search/timeline/loops) ─► 10 (RBAC/sign-off/FHIR/privacy/export)
                                                                                                │
                                                       Phase 11 integration ─► 13 eval ─► 14 demo   (12 stretch last)
```

### 19.4 Risk register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Three machines drift (schema, env, versions) | High | High | Migrations-only schema, one DB owner, generated types, shared `.env.example`, daily sync (§4.6) |
| OCR bounding boxes misaligned / low quality on handwriting | Med | High | Normalised boxes, dual-engine OCR, IoU checks in §7.4, never trust a fact without a box |
| LLM extraction invents or misses facts | Med | High | Evidence-ID citation, substring check, omission pass, eval harness |
| Rules are clinically wrong or outdated | Med | High | Clinician review logged per rule, versioned rules, "source" shown in trace, say "not clinically validated" |
| Open interaction dataset licence/coverage issues | Med | Med | Check licence early; ship a curated seed list for demo scenarios; document coverage |
| Whisper too slow on CPU / poor on Tamil-English | High | Med | Smaller model for dev, GPU machine for demo, pre-warmed caches, stretch goal clearly separated |
| Supabase free tier pausing / rate limits | Low–Med | High | Wake before demo, batch writes, pooled connection, local cache of seed for reset |
| Scope creep into secondary features | High | High | Vertical slice first; secondary features only after M3; each has a "Done when" |
| Live demo dependency failure (network/API) | Med | High | On-prem fallbacks, cached pipeline results, recorded backup video |

---

## Appendix A — API surface (FastAPI)

| Area | Endpoints |
|---|---|
| Auth/Profile | `GET /me` |
| Patients | `GET /patients` · `GET /patients/{id}` |
| Ingest | `POST /encounters` · `POST /encounters/{id}/audio` · `WS /ws/consult/{id}` · `POST /patients/{id}/documents` · `GET /jobs/{id}` |
| Facts | `GET /patients/{id}/facts` · `POST /facts/{id}/confirm` · `POST /facts/{id}/reject` · `POST /facts/{id}/edit` |
| Safety | `GET /patients/{id}/alerts` · `GET /alerts/{id}/trace` · `POST /alerts/{id}/ack` · `POST /alerts/{id}/override` · `POST /alerts/{id}/resolve` |
| Note | `GET /encounters/{id}/note` · `POST /encounters/{id}/note/regenerate` · `POST /encounters/{id}/sign` · `POST /encounters/{id}/amend` |
| Workflow | `GET /encounters/{id}/gaps` · `GET /patients/{id}/loops` · `POST /loops/{id}/close` |
| Insight | `GET /patients/{id}/timeline` · `GET /patients/{id}/trends?loinc=` · `GET /patients/{id}/summary` · `POST /patients/{id}/search` |
| Export | `GET /encounters/{id}/fhir` · `POST /encounters/{id}/patient-summary?lang=` |
| Admin | `GET /admin/audit` · `POST /admin/audit/verify` · `POST /admin/users` · `POST /admin/llm-mode` |
| Eval | `POST /eval/run` · `GET /eval/runs` · `GET /eval/runs/{id}` |

## Appendix B — Coverage matrix: Blueprint requirement → where it is built

| Blueprint requirement | Built in |
|---|---|
| AI clinical scribing → structured notes (SOAP) | §7.3 (STT), §8 (facts), §11 (SOAP) |
| OCR extraction from documents & prescriptions | §7.4, §9.1 |
| Automated healthcare workflows | §13.2 gap prompts, §13.4 open loops, §15 job pipeline |
| Intelligent patient histories & timelines | §13.3, §12.4-E |
| Concise patient data summarization | §13.6 patient summary card, §12.4-A |
| Clinical & laboratory trend analysis | §13.3, §12.4-F |
| Natural-language search across all records | §13.1, §12.4-G |
| Medication & record consistency checks | §10 (rules, contradictions), §10.4 (eGFR) |
| Evidence-backed AI responses linked to sources | §5.5 provenance, §9, §12.4-H/D, §13.1 citations |
| Role-based access control & auditability | §5.8–5.9, §14.1, §12.4-J |
| Mandatory human clinical oversight / sign-off | §12.4-C, §14.2 |
| Vector DB for semantic search | §5.5 (`pgvector` on Supabase), §13.1 |
| Event-store timeline | §13.3 view |
| Review/Edit/Sign-off dashboard | §12.4-C |
| *(Master)* Fact lifecycle, 3-way verification, explain trace, templated export, evaluation harness, secondary features | §5.5, §9, §10.5, §14.5, §17, §13 |

## Appendix C — Command cheat-sheet

```bash
# one-time
supabase login && supabase link --project-ref <ref>
pnpm install                                   # in apps/web
python -m venv .venv && source .venv/bin/activate && pip install -e services/api

# database
supabase migration new <name>                  # create migration
supabase db push                               # apply (DB owner only)
supabase gen types typescript --linked > apps/web/types/db.ts

# seed (idempotent)
pnpm seed:users && psql "$SUPABASE_DB_URL" -f supabase/seed/10_terminology.sql   # …20,30,40
python supabase/seed/50_raw_inputs.py

# run
uvicorn aceso.main:app --reload --port 8000    # API
python -m aceso.workers.worker                 # job worker
pnpm --filter web dev                          # frontend

# test & evaluate
pytest services/api/tests -q
pnpm --filter web test && pnpm --filter web exec playwright test
python -m eval.run --scenarios all --variant clean,scan,bad
```

## Appendix D — Final "ship" checklist

- [ ] Phase 1: schema, triggers, RLS, audit chain pass every test in §5.11
- [ ] Phase 2: six scenarios seeded; golden + raw inputs; ground truth present
- [ ] Phases 3–7: S1…S6 pass `truth.json`; every fact has provenance; SOAP validated
- [ ] Phase 8: all screens; keyboard-only review; never-collapse rule enforced and tested
- [ ] Phase 9–10: search with citations, timeline/trends, open loops, gap prompts, sign-off lock, FHIR validates, redaction test, templated patient summary round-trips
- [ ] Phase 13: `REPORT.md` + `FAILURES.md` generated; wrapper-vs-ACESO and Swap Test tables ready
- [ ] Phase 14: reset script, offline fallback rehearsed, backup video recorded, clinician review log filled in
- [ ] Every rule and patient-facing template has a named clinical reviewer in `docs/clinical_review_log.md`
- [ ] The demo says plainly: **synthetic data, not clinically validated, decision support only — the doctor decides.**
