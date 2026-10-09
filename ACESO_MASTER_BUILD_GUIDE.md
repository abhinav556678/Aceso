# ACESO — Master Build Guide (as built)

*AI-native EMR for intelligent clinical assistance · hackathon prototype · synthetic patients only*

This document describes what is actually in this repository: what was built, how each part works, how to run it, what is known to be missing, and what we plan to build next. It replaces the original phase-by-phase build plan, which is still available in git history (`git show 7209a06:ACESO_MASTER_BUILD_GUIDE.md`). The product concept lives in `ACESO_Master_Architecture.md`.

> **Clinical disclaimer.** Every rule, dose limit, code mapping and translation in this repository is illustrative. None of it has been reviewed by a clinician or a native speaker. All patients are fictional. Do not use this with real patient data.

---

## 1. What ACESO is

ACESO turns raw clinical inputs (a lab PDF, a prescription, a consult recording) into a reviewed, signed clinical record, and checks that record for safety problems on the way.

### 1.1 The idea in one paragraph

Most "AI scribe" products ask a language model to write a note and hope it is right. ACESO does the opposite. The model has exactly one job: pull out individual facts and point at the evidence for each. Everything that creates trust is ordinary deterministic code that we own: where each fact came from, whether the source really says it, whether a drug is safe given the patient's kidney function, what the doctor signed, and who changed what. If the model is swapped for a different one, the product still works (the "Swap Test").

### 1.2 The rules, and where each one is enforced

| Rule | Enforced by |
|---|---|
| Facts first, prose second | The SOAP note is rendered from fact rows (`soap.py`); there is no free-text generation step |
| Every fact carries provenance | Database check constraint `provenance_required` on `facts`; an audio fact without a time span or a document fact without a box cannot be inserted |
| The safety engine reads only trusted facts | `safety/engine.py` loads only `verified` and `clinician_confirmed` facts |
| Allergies and medications are never auto-collapsed | `collapsible()` in `routes/patients.py`; sign-off requires each to be explicitly confirmed |
| Nothing is official without a doctor's sign-off | `facts_guard` trigger (only a doctor can confirm); `POST /encounters/{id}/sign` is doctor-only and gated |
| Patient-facing text is templated, not model-written | `routes/export.py` renders from structured data through fixed per-language label tables |
| Every state change is audited | `facts_audit` trigger plus explicit audit rows; `audit_log` is append-only and hash-chained |
| PHI is redacted before any external call | `privacy.py` `Redactor`, applied to every evidence unit sent to the model (audio cannot be redacted; see §14) |

---

## 2. Architecture

```text
 Browser (Next.js)  ──HTTP──►  FastAPI backend  ──SQL──►  Postgres (Supabase or embedded local)
                                    │
                                    ├── Groq API: LLM extraction (text, redacted)
                                    └── Groq API: Whisper transcription (audio)

 Upload ─► perception ─► extraction ─► verification ─► fact store ─► safety engine ─► SOAP draft
           (PDF text      (LLM cites    (source match,   (extracted /   (rules as data,   (template,
            layer /        evidence      plausibility,    verified)      explain trace)    one fact per
            Whisper)       IDs)          omissions)                                        sentence)
                                                             │
                                             doctor review ─► sign-off ─► FHIR bundle + patient summary
```

Design decisions that differ from the original plan:

- **The browser never talks to the database.** All reads and writes go through the API. There is no Supabase client in the frontend.
- **No job queue worker.** Each upload runs the pipeline in a FastAPI background task and writes progress to its `jobs` row; the UI polls.
- **Files are stored in the database** (`file_blobs` table), not in Supabase Storage, so three machines sharing one database see the same files with no bucket setup.
- **Demo authentication.** A role switcher replaces password login (§8.1).

### 2.1 Technology actually used

| Layer | Choice |
|---|---|
| Database | Postgres. Supabase (project in `ap-northeast-1`, session pooler) for shared use; embedded `pgserver` Postgres for offline use and tests |
| Backend | Python 3.12, FastAPI, psycopg 3 with a connection pool, Pydantic |
| PDF reading | PyMuPDF (text layer and page rendering) |
| LLM | Groq, OpenAI-compatible API, model `openai/gpt-oss-120b`; Ollama adapter for on-prem |
| Speech-to-text | Groq `whisper-large-v3-turbo` with word timestamps |
| Fuzzy matching | rapidfuzz |
| Frontend | Next.js 16 (App Router), React 19, TypeScript, Tailwind 4 |
| Tests | pytest against a real Postgres |

Installed on the schema but not used at runtime: `pgvector` (the `fact_chunks` table is empty) and `pg_trgm`.

---

## 3. Repository layout

```text
.env.example                 template for .env (never commit .env)
ACESO_MASTER_BUILD_GUIDE.md  this file
ACESO_Master_Architecture.md product concept and differentiators
scripts/
  setup_db.py                migrations + reference seed + demo scenarios (one command)
  local_db.py                starts the embedded local Postgres
  local_shim.sql             makes plain Postgres look enough like Supabase
supabase/
  migrations/                10 SQL migrations (schema, triggers, RLS, views)
  seed.sql                   demo users, terminology, safety knowledge, six patients
services/api/
  pyproject.toml
  aceso/
    main.py                  FastAPI app, CORS, router wiring
    config.py                settings from .env; picks Supabase or local database
    db.py                    pool, tx() with acting identity, audit() helper
    auth.py                  demo role authentication and role dependencies
    privacy.py               PHI redactor
    pipeline.py              the ingestion pipeline and job progress
    soap.py                  SOAP note generation and guards
    demo.py                  synthetic PDFs/transcripts and scenario seeding
    llm/client.py            the only module that calls a language model
    perception/pdf.py        PDF rows with bounding boxes, page images, date/kind detection
    perception/stt.py        Whisper transcription, typed-transcript parser
    extraction/extract.py    prompt, validation, normalisation, negation cross-check
    extraction/terminology.py brand/generic, concept codes, dose parsing, omission detector
    extraction/negation.py   NegEx-style negation scope
    extraction/verify.py     verification checks, confidence, omission pass
    safety/metrics.py        CKD-EPI 2021 eGFR
    safety/engine.py         rule engine, contradiction engine, explain traces
    routes/patients.py       list, chart, timeline, trends, search, gap checklist
    routes/ingest.py         upload, job status, document pages, recordings
    routes/review.py         confirm/reject facts, alert actions, sign-off
    routes/export.py         FHIR bundle, templated patient summary
    routes/admin.py          audit log, chain verification, model status
  tests/                     43 tests (units, database rules, scenarios through the API)
apps/web/src/
  lib/api.ts                 API client, role storage, formatting, reason labels
  app/page.tsx               role sign-in
  app/patients/page.tsx      patient list and overdue follow-ups
  app/patients/[id]/page.tsx chart: review, note, sign-off, timeline, search
  app/admin/page.tsx         audit log and chain check
  components/SourceViewer.tsx  PDF box / transcript span / computed-value viewer
  components/AlertDrawer.tsx   explain trace and alert actions
  components/Trends.tsx        lab trend charts
data/synthetic/              generated sample files for live upload (gitignored)
```

---

## 4. Setup and running

### 4.1 Prerequisites

- Python 3.12 (`py -3.12`). The default Python 3.14 on the dev machine is untested.
- Node.js 20 or later and npm.
- A Groq API key.
- Either a Supabase project or nothing (the embedded local database needs no install beyond `pip`).

Not needed: Docker, the Supabase CLI, Tesseract, poppler, ffmpeg.

### 4.2 Environment (`.env` in the repo root)

| Variable | Meaning |
|---|---|
| `SUPABASE_DB_URL` | Supabase **session pooler** connection string (port 5432). Leave empty to use the embedded local database |
| `LLM_MODE` | `external` (Groq) or `onprem` (Ollama) |
| `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL` | OpenAI-compatible endpoint, key and model for extraction |
| `OLLAMA_URL`, `OLLAMA_MODEL` | Used when `LLM_MODE=onprem` |
| `STT_MODEL` | Whisper model name on the same endpoint |
| `WEB_ORIGIN` | Origin allowed by CORS (comma-separated for several) |

The frontend reads `NEXT_PUBLIC_API_URL` (default `http://localhost:8000`).

### 4.3 First-time setup

```
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install -e "services/api[dev]"
```

Choose a database:

- **Supabase.** Create a project, enable the `vector`, `pgcrypto` and `pg_trgm` extensions, and put the session pooler string in `.env`. Percent-encode special characters in the password.
- **Embedded local.** Leave `SUPABASE_DB_URL` empty and run `python scripts/local_db.py` in its own terminal. Data lives in `.localdb/`.

Then create everything:

```
python scripts/setup_db.py
```

### 4.4 `setup_db.py`

| Command | Effect |
|---|---|
| `python scripts/setup_db.py` | Apply missing migrations, re-apply the reference seed, build demo scenarios if absent. Safe to re-run |
| `--reseed-demo` | Delete and rebuild the six demo patients' clinical data |
| `--s1-labs-preloaded` | Seed scenario S1 with its lab report already uploaded |
| `--no-demo` | Skip the demo scenarios |
| `--reset` | **Drop the whole `public` schema first.** Asks you to type `reset`. Destroys all ACESO data in that database |

Applied migrations are recorded in `supabase_migrations.schema_migrations`, the same table the Supabase CLI uses. If the database already has ACESO tables that this script did not create, it stops and asks for `--reset`.

On a shared Supabase project, `--reseed-demo` and `--reset` affect every teammate.

### 4.5 Running

```
cd services/api
uvicorn aceso.main:app --port 8000
```

```
cd apps/web
npm install
npm run build
npm run start
```

`npm run dev` also works but uses far more memory. Do not run `npm run build` while a dev server is running in the same folder; it breaks the dev server.

Open http://localhost:3000. Health check: http://localhost:8000/health.

### 4.6 Network note

Some campus and venue networks block outbound database ports (5432 and 6543). On such a network the Supabase database is unreachable unless a VPN such as Cloudflare WARP or a phone hotspot is used; the API then answers every data request with a 500 after a 30-second wait. The model API uses HTTPS and is not affected. For a demo on an unknown network, use the embedded local database.

With Supabase in Tokyo reached through WARP, the patient list takes about 2.5 s and a chart about 5 s, because a chart makes roughly 25 round trips.

---

## 5. Database

### 5.1 Migrations

| File | Contents |
|---|---|
| `0001_base` | Extensions and enums (`fact_type`, `fact_assertion`, `fact_state`, `source_kind`, `job_status`, `alert_status`, `note_status`, `user_role`) |
| `0002_core` | `profiles`, `patients`, `encounters` |
| `0003_inputs` | `audio_recordings`, `transcript_segments`, `source_documents`, `ocr_blocks` |
| `0004_facts` | `facts` (with the provenance constraint), `fact_chunks` |
| `0005_knowledge` | `concepts`, `drug_brands`, `allergy_groups`, `reference_ranges`, `drug_interactions`, `dose_limits`, `safety_rules`, `safety_alerts` |
| `0006_workflow` | `soap_notes`, `note_edits`, `patient_exports`, `open_loops` (+ `open_loops_v`), `jobs`, `eval_runs`, `eval_results` |
| `0007_audit_lifecycle` | `audit_log`, hash chain, append-only triggers, `app_role()`, `facts_guard`, `facts_audit`, `verify_audit_chain()` |
| `0008_rls` | Row Level Security policies |
| `0009_timeline_views` | Superseded by the view in `0010` |
| `0010_prototype` | `file_blobs`, job progress columns, alert `dedupe_key` and unique index, `lock_signed_note` trigger, `patient_timeline_v` |

### 5.2 The fact row

A fact is one clinical statement: type, assertion (`present`, `denied`, `uncertain`), a coded identity, a value, a lifecycle state and its provenance.

How the columns are used in this build:

| Column | Use |
|---|---|
| `display` | Normalised name. For a medication this is the generic, capitalised ("Metformin") |
| `raw_text` | The exact quote from the source ("Glycomet 500 twice daily") |
| `value_text` | The generic substance key for medications and allergies (`metformin`, `penicillin`); `*` for a blanket "no allergies" |
| `code_system`, `code` | RxNorm, LOINC or ICD-10 code when mapped |
| `dose` | Medications: `{generic, brand, amount, unit, freq, times_per_day, daily_mg}`. Allergies: `{group}`. Computed eGFR: `{formula, input_fact, inputs}` |
| `value_num`, `unit` | Lab or vital result, or the medication strength |
| `state` | `extracted` → `verified` → `clinician_confirmed`; or `rejected`; or `superseded` |
| `needs_attention`, `attention_reasons` | Why the fact was held back (list in §6.5) |
| `confidence`, `confidence_parts`, `verification` | Scores and per-check results |
| Document provenance | `document_id`, `block_ids`, `page_no`, `bbox` (normalised 0..1) |
| Audio provenance | `recording_id`, `segment_ids`, `audio_start_ms`, `audio_end_ms` |

### 5.3 Lifecycle and audit, enforced in the database

- **Allowed transitions** (`facts_guard`): `extracted → verified | rejected | superseded`; `verified → clinician_confirmed | rejected | superseded`; `clinician_confirmed → superseded`. Anything else raises an error.
- **Only a doctor can confirm.** The trigger reads the acting user from `auth.uid()`.
- **Every insert and state change on `facts` writes an audit row** (`facts_audit`).
- **`audit_log` is append-only.** Update, delete and truncate raise errors, even for the database owner.
- **Hash chain.** Each row stores the SHA-256 of the previous row's hash plus its own content. `verify_audit_chain()` recomputes the chain and reports the first broken row.
- **A signed note cannot be edited** (`lock_signed_note`).

How the backend sets the acting user: `db.tx(user)` runs `set_config('request.jwt.claim.sub', <profile id>, true)` at the start of the transaction, so `auth.uid()` resolves to that profile exactly as it would for a Supabase JWT. Without a user, the transaction acts as `system:pipeline`.

### 5.4 Row Level Security

Policies exist and RLS is enabled on every table. They are not what protects data in this build: the backend connects as the database owner, which bypasses RLS, and the browser has no database access. Role enforcement happens in the API (§8.1) and in the lifecycle triggers.

### 5.5 Audit actions written

`fact.created`, `fact.state_change`, `source.upload`, `llm.call`, `stt.call`, `alert.acknowledged`, `alert.overridden`, `alert.resolved`, `note.sign`, `search.query`, `export.fhir`, `export.patient_summary`.

`llm.call` records the model id, prompt version, number of evidence units, number of redactions and number of rejected model outputs. It never records the text.

---

## 6. The pipeline (`pipeline.py`)

`POST /api/ingest` stores the file, creates the source row and a `jobs` row in one transaction, then starts `run_job` in the background. Stages shown in the UI: *Reading document layout* or *Transcribing audio*, *Extracting facts*, *Verifying N facts*, *Running safety checks*, *Done*. A failure at any stage marks the job and the source as failed with the error message; each stage commits separately.

### 6.1 Perception

**PDF (`perception/pdf.py`).** PyMuPDF reads the text layer. Words on the same baseline (within 3 pt) are merged into one row, so a lab table row such as `Creatinine, serum 2.1 mg/dL 0.6 - 1.1` is a single evidence unit. Each row is stored in `ocr_blocks` with a normalised box, and its individual words with their boxes are kept in `table_ref.words`. A PDF with no text layer is rejected with "This PDF has no text layer (it looks like a scan)". The document date is the first plausible date near the top that is not on a line mentioning birth; the document kind is guessed from header words.

**Audio (`perception/stt.py`).** The file goes to Groq Whisper with word and segment timestamps, auto-detected language, and a spelling hint built from our drug brand list (without it, "Telma" was heard as "till my"). Whisper's own segments can span the whole clip, so we cut our own sentence-sized segments from the word timestamps: a segment ends at `.`, `?` or `!`, or after 15 seconds. Confidence per segment is `exp(avg_logprob)` of the Whisper segment it falls in. Speakers are not labelled.

**Typed transcript (`.txt`).** One utterance per line, optionally `[mm:ss-mm:ss] Speaker: text`. Missing times are estimated at 2.5 words per second. Confidence is 1.0.

### 6.2 Extraction (`extraction/extract.py`)

The model receives numbered evidence units and nothing else:

```text
[B6] (page 1) "Creatinine, serum 2.1 mg/dL 0.6 - 1.1"
[S4] (doctor) "Continue Glycomet 500 twice daily."
```

Each unit's text is redacted first (patient name and name parts, email, MRN, ABHA, Aadhaar, Indian mobile numbers). Units are sent in chunks of 60. The model must return JSON `{"facts": [...]}`, each fact with `fact_type`, `assertion`, `name`, `raw_text` (an exact quote), `value_num`, `unit`, `dose` and `evidence_ids`. The prompt (`extract-v1`) forbids inference, requires explicit denials to be returned as `denied`, treats a blanket "no allergies" as one allergy fact, splits blood pressure into two vitals, and returns follow-up instructions as `plan_item`.

Server-side validation rejects, and never repairs, any output that:

- fails the schema or uses an unknown fact type or assertion;
- cites an evidence id that was not in the packet;
- has a `raw_text` that is not found in the cited evidence (fuzzy partial match below 85).

If the model is unreachable or returns invalid JSON twice, the job still completes: the dictionary detector's hits (§6.5) are queued as facts needing review, and the job result carries a warning.

### 6.3 Normalisation (deterministic)

| Fact type | Procedure |
|---|---|
| medication | Find a brand or generic from `drug_brands` (exact token or two-token match, then fuzzy ratio ≥ 88 for tokens of 5+ letters). Sets generic, RxNorm code and brand. Dose is parsed from the text after the drug name: first number is the strength (milligrams if no unit), frequency from shorthand (`OD`, `BD`, `TDS`, `QID`, `HS`, `SOS`) or phrases ("twice daily"). `daily_mg = amount × times_per_day`. Unmatched → `unmapped_drug` |
| allergy | Blanket statements become `value_text = '*'`. Otherwise the substance is mapped to a generic and to its cross-reactivity group from `allergy_groups`. Unmatched → `unmapped_allergen` |
| lab_result, vital | Longest synonym match in `concepts` (LOINC). Creatinine in µmol/L is converted to mg/dL (÷ 88.4). No match → `unmapped_test`; no value → `missing_value` |
| diagnosis | Longest synonym match in `concepts` (ICD-10). No match → `unmapped_diagnosis` |
| symptom, history, plan_item | Stored as written |

### 6.4 Negation cross-check (`extraction/negation.py`)

A rule-based detector reads the same evidence. A cue (`no`, `not`, `denies`, `without`, `never`, `none`, `nil`, `stopped`, and a few Tamil and Hindi words) negates a term that appears within the next six tokens, stopping at a comma, full stop, semicolon or `but`/`however`/`except`. If the model says `present` and the rule says negated, or the model says `denied` and there is no cue at all, the fact becomes `uncertain` with reason `negation_conflict` and goes to review.

### 6.5 Verification (`extraction/verify.py`)

| Check | Passes when |
|---|---|
| Source match (`ocr_match` for documents, `transcript_support` for audio) | The quote is literally in the cited evidence, and the stated value and dose amount appear there as numbers |
| Plausibility | A lab or vital value is inside `plausible_min..plausible_max` from `reference_ranges`. Outside → 0 (`out_of_plausible_range`); no range on file → 0.5 (`no_reference_range`); non-numeric facts → 1 |
| Omission | A separate high-recall pass: every drug name (4+ letters), concept synonym (5+ letters) and the word "allergy/allergic" found in the source must be covered by some fact. Uncovered hits become `Possible omission: …` facts in state `extracted` |

```text
confidence = 0.30 × perception  (0.99 for a PDF text layer; Whisper confidence for audio, 0.9 if unknown)
           + 0.20 × plausibility
           + 0.50 × share of checks passed
```

A fact becomes `verified` only if it has no attention reasons, its assertion is not `uncertain`, and confidence is at least 0.90. Everything else stays `extracted`.

All attention reasons: `possible_omission`, `unmapped_drug`, `unmapped_allergen`, `unmapped_test`, `unmapped_diagnosis`, `negation_conflict`, `out_of_plausible_range`, `ocr_mismatch`, `not_supported_by_transcript`, `no_reference_range`, `low_confidence`, `missing_value`.

### 6.6 Provenance, computed by our code

- **Document facts:** if one row is cited, the box is the union of the words that spell the printed value (or the quote); the result is a tight box around `2.1`, not the whole row. Several rows → the union of the rows.
- **Audio facts:** the span is the earliest start to the latest end of the cited segments.
- **Effective date:** the document's printed date for PDFs; the time of processing for audio.

### 6.7 After the facts are stored

The safety engine runs for the patient, then the SOAP draft for the encounter is rebuilt. Both also run after every confirm, reject and contradiction resolution.

---

## 7. Safety engine (`safety/engine.py`)

### 7.1 What it reads

Only `verified` and `clinician_confirmed` facts. From them it builds:

- **Current medications:** the latest fact per (generic, brand). A newer `denied` medication fact for the same generic removes it. The same product mentioned in an old prescription and in today's consult counts once.
- **Allergies on record:** every `present` allergy fact. An allergy stays active even if later denied, until a doctor resolves the contradiction.

### 7.2 Rules (rows in `safety_rules`)

| Rule id | Fires when | Severity |
|---|---|---|
| `KDIGO-METFORMIN-EGFR30` | Metformin is current **and** computed eGFR < 30. Generic: any rule of type `lab_contraindication` with a `fact` condition and an `egfr` metric condition is evaluated from its JSON | critical |
| `INT-PAIR` | Two current generics form a row in `drug_interactions` of at least moderate severity | from the table (major → high) |
| `DUP-THERAPY` | One generic is current under two different products | moderate |
| `DOSE-MAX-DAILY` | The summed `daily_mg` of all current products of a generic exceeds `dose_limits.max_daily_mg` | high |
| `ALLERGY-CONFLICT` | A current medication is the allergen itself or in the same `allergy_groups` group | critical |
| `RECORD-CONTRADICTION` | An allergy (same substance, same group, or a blanket denial) or a diagnosis (same code) is `present` and later `denied`. "Not mentioned" never contradicts anything | high |

Knowledge currently loaded is minimal: one interaction (aspirin + warfarin), two dose limits (paracetamol 4000 mg/day, metformin 2550 mg/day), two allergy groups.

### 7.3 eGFR

`safety/metrics.py` implements CKD-EPI 2021 (race-free). The engine uses the latest trusted creatinine (LOINC 2160-0) no older than 90 days, with the patient's age on the measurement date and sex. If there is none, the rule does not fire and the chart shows "eGFR cannot be computed …" with the rule marked not evaluated. The computed value is stored as a derived fact (LOINC 62238-1, `created_by = system:metric`, `source = manual`) so it appears on trends; it is superseded automatically if its input creatinine stops being current.

### 7.4 Explain trace

Every alert stores the rule (id, title, version, source), an ordered list of steps and a conclusion. A step can carry a result (true/false), a computed value with unit and formula, its inputs (each with a fact id and source), an evidence line (quote, source, date, and the dictionary mapping used), and a fact id that the UI links to the source viewer.

### 7.5 Idempotency and self-closing

Each alert has a `dedupe_key` of rule id plus sorted trigger fact ids, with a unique index over alerts that are not resolved; re-running the engine never duplicates an alert. An open alert whose condition no longer holds (for example the drug fact was rejected) is resolved automatically with a note.

### 7.6 Unverified facts

The chart response includes `unverified_count`, and the UI shows "N facts are not yet verified and were not evaluated by the safety engine. No alert does not mean safe."

---

## 8. Review, sign-off and exports

### 8.1 Roles (demo authentication)

The web app sends the chosen role in the `X-Demo-Role` header (or `?as=` for images, audio and new tabs). The API acts as the first seeded profile with that role. There are no passwords. Role checks and the database triggers apply to that profile.

| Capability | Doctor | Nurse | Admin |
|---|:--:|:--:|:--:|
| Patient list | ✅ | ✅ | ✅ demographics only |
| Chart, timeline, trends, search, sources | ✅ | ✅ | ❌ |
| Upload | ✅ | ✅ | ❌ |
| Reject a fact | ✅ | ✅ | ❌ |
| Confirm a fact, act on alerts, sign off | ✅ | ❌ | ❌ |
| Exports | ✅ | ✅ | ❌ |
| Audit log, chain verification | ❌ | ❌ | ✅ |

### 8.2 SOAP note (`soap.py`)

One sentence per trusted fact of the encounter, generator id `template:soap-v1`:

| Section | Facts | Example |
|---|---|---|
| Subjective | symptoms, history, allergies, denied medications | "Denies any known allergies." |
| Objective | labs and vitals | "Creatinine, serum: 2.1 mg/dL." |
| Assessment | diagnoses | "Type 2 diabetes mellitus." |
| Plan | medications, plan items | "Metformin (Glycomet) 500 mg BD." |

Guards run on every sentence: no number that is not in the fact, and a denied fact must read as a denial. A sentence that fails falls back to the bare fact rather than being dropped. The draft is rebuilt whenever facts change; a signed note is never touched.

### 8.3 Sign-off (`POST /encounters/{id}/sign`)

Blocked (HTTP 409 with the list) until all of these hold:

1. No fact of the encounter is still `extracted`.
2. No possible omission is unresolved.
3. Every allergy and medication fact of the encounter has been explicitly confirmed (none merely `verified`).
4. The patient has no open critical or high alert.

Then, in one transaction as the doctor: remaining verified facts are confirmed (each audited), the note is rebuilt and marked signed with a SHA-256 of its content, the encounter is marked signed, follow-up plan items matching `(repeat|recheck|review|follow-up|test) … in N day/week/month` become `open_loops` with a due date, and a `note.sign` audit row is written.

### 8.4 Alerts

- **Acknowledge** and **Override** require a reason of at least 10 characters, stored on the alert and in the audit log.
- **Resolve** (contradictions only): the doctor picks which of the two facts is true; it is confirmed, the other is superseded, the alert is resolved and the engine re-runs.

### 8.5 Exports (signed encounters only, `clinician_confirmed` facts only)

- **FHIR R4 document bundle** (`GET /encounters/{id}/fhir`): Composition (first entry, with S/O/A/P sections and the note hash), Patient, Encounter, Practitioner, and one resource per fact: Observation, Condition, MedicationStatement, AllergyIntolerance. Codes are included where mapped; provenance travels in `meta.tag`. Not validated against ABDM profiles.
- **Patient summary** (`GET /encounters/{id}/patient-summary?lang=en|ta|hi`): HTML for browser printing. Medicines table (name, dose, when), allergies on record, follow-ups with dates. Frequencies come from a fixed lookup table per language. A round-trip check refuses to produce the page if any dose or follow-up date from the payload is missing from the output. The payload and HTML are stored in `patient_exports`.

---

## 9. API reference

All routes are under `/api` and need a demo role.

| Method and path | Role | Purpose |
|---|---|---|
| `GET /patients` | any | List with open-alert, unverified and overdue counts; overdue follow-ups |
| `POST /patients/{id}/encounters` | clinical | Open (or return) the current visit |
| `GET /patients/{id}/chart` | clinical | Everything the chart screen needs in one call |
| `GET /patients/{id}/timeline` | clinical | Visits, documents, facts, alerts in date order |
| `GET /patients/{id}/trends` | clinical | Series per lab with range, points, summary sentence |
| `POST /patients/{id}/search` `{q}` | clinical | Answer and evidence from the fact store; audited |
| `POST /ingest` (multipart `patient_id`, `file`) | clinical | Upload a PDF, audio or `.txt`; returns `job_id`. Max 25 MB |
| `GET /jobs/{id}` | clinical | Stage, status, error, result counts |
| `GET /documents/{id}` | clinical | Metadata and text rows with boxes |
| `GET /documents/{id}/pages/{n}.png` | clinical | Rendered page image |
| `GET /recordings/{id}` | clinical | Segments; `has_audio` |
| `GET /recordings/{id}/audio` | clinical | The audio file |
| `POST /facts/{id}/confirm` | doctor | `extracted`/`verified` → `clinician_confirmed` |
| `POST /facts/{id}/reject` | clinical | → `rejected` |
| `POST /alerts/{id}/acknowledge` `{reason}` | doctor | |
| `POST /alerts/{id}/override` `{reason}` | doctor | |
| `POST /alerts/{id}/resolve` `{keep_fact_id, reason}` | doctor | Contradictions only |
| `GET /encounters/{id}/sign-check` | clinical | Current blockers |
| `POST /encounters/{id}/sign` | doctor | Sign-off |
| `GET /encounters/{id}/fhir` | clinical | FHIR bundle |
| `GET /encounters/{id}/patient-summary` | clinical | Templated HTML |
| `GET /admin/audit` | admin | Latest audit rows |
| `POST /admin/audit/verify` | admin | Chain check |
| `GET /status` | any | Which model layer is configured |

`GET /health` (no role) returns `{"status":"ok"}`.

**Search** is structured and lexical. The question is tokenised, expanded through our dictionaries (synonym → code, brand → generic, substance → allergy group), and scored against trusted and unverified facts. The answer is assembled from the top three facts with numbered citations. With no match it returns exactly "No supporting record found in this patient's chart."

**Trends** covers HbA1c, creatinine, eGFR, fasting glucose and blood pressure. The summary sentence is computed: "HbA1c fell from 8.9 to 7.6 % over 6 months; latest value is outside the reference range".

**Gap checklist** (inside the chart response): chief complaint, allergies asked, medications reviewed, vitals recorded, follow-up plan stated, plus one "pending from last visit" item per open follow-up.

---

## 10. Frontend

| Route | Screen |
|---|---|
| `/` | Role sign-in (Dr. Rao, Nurse Priya, Admin Kumar) |
| `/patients` | Patient table with attention counts; overdue follow-ups panel |
| `/patients/[id]` | The chart |
| `/admin` | Audit table with filter, model-layer notice, "Verify hash chain" |

**Chart layout.** A header with identity and visit status. A safety banner that is always visible: one row per open alert with severity icon and label and an "Explain & act" button; the unverified-facts notice; "cannot compute" notices; handled alerts collapsed. Four tabs:

- **Review & note** (three columns).
  - *Left:* upload button and job progress; "Needs your attention" (unverified facts plus every allergy and medication of this visit) with Confirm and Reject; collapsed groups for verified items, doctor-confirmed facts and rejected facts; the consult checklist.
  - *Middle:* the SOAP note, each sentence clickable, sentences involved in an open alert marked; the sign-off panel listing blockers, or after signing the lock, hash and export links.
  - *Right:* the source viewer. Document facts show the page image with a pulsing red box; audio facts show the transcript with the cited segment highlighted and, for real audio, a player that jumps to the span; computed facts show the formula, inputs and a link to the input fact.
- **Timeline:** events grouped by month with filter chips.
- **Trends:** one SVG chart per lab with reference band, hover tooltip, hollow markers for out-of-range points, a table view and the summary sentence. Clicking a point opens its source.
- **Search:** a question box, the cited answer and the evidence list.

**Explain drawer.** Rule and source, the step tree with values, formula, inputs and "view source" links, the conclusion, and the action form (reason plus Acknowledge/Override, or a choice between the two contradicting facts).

While any job is queued or running, the chart is re-fetched every 1.5 seconds. Every state has an icon and a text label, never colour alone. The chart is wrapped in `Suspense` because this Next.js version requires it for client-side route parameters.

---

## 11. Demo data (`demo.py`)

Seeding generates each scenario's PDFs and transcripts and pushes them through the **real pipeline** with a scripted stand-in for the model (`ScriptedLLM`), so it is deterministic and needs no API key. Alerts come from the safety engine. Past visits are confirmed and signed through the same code path as the UI. Dates are relative to the day of seeding.

| Patient | What is planted | Result after seeding |
|---|---|---|
| **S1** Meena Rajan, 50 F, `ACE-0001` | 400 days ago: prescription with T2DM, Glycomet 500 BD, Telma 40 OD (signed). Today: consult with "no allergies", "Continue Glycomet 500 twice daily", and an ibuprofen mention the script does not extract | No alert; one possible omission (ibuprofen); "eGFR cannot be computed". Uploading the lab sample fires `KDIGO-METFORMIN-EGFR30` with eGFR 28.2 |
| **S2** Arjun Menon, 45 M, `ACE-0002` | 700 days ago: discharge summary with penicillin allergy (signed). Today: "No allergies", Mox 500 three times daily | `RECORD-CONTRADICTION` + `ALLERGY-CONFLICT` |
| **S3** Lakshmi Narayanan, 58 F, `ACE-0003` | Today: "no diabetes, not allergic to sulfa, no chest pain"; Septran prescribed | Three denied facts, zero alerts |
| **S4** Suresh Babu, 72 M, `ACE-0004` | 200 days ago: Ecosprin 75 OD (signed). Today: outside prescription with Warf 5 OD, Dolo 650 QID, Crocin 650 TDS | `INT-PAIR`, `DUP-THERAPY`, `DOSE-MAX-DAILY` (4550 mg/day) |
| **S5** Fatima Begum, 55 F, `ACE-0005` | HbA1c 8.9, 8.2, 7.6 over three signed visits; "Repeat HbA1c in 3 months" at the last one | Trend chart; one overdue follow-up; zero alerts |
| **S6** Karthik S, 34 M, `ACE-0006` | Today: fever, viral URI, paracetamol 500 TDS, no allergies | Zero alerts (false-positive control) |

Files written to `data/synthetic/` for live upload:

- `S1_meena_labs_today.pdf` — creatinine 2.1, HbA1c 7.9, potassium 4.8.
- `S1_meena_labs_misprint.pdf` — creatinine 21; held back as `out_of_plausible_range`.
- `S6_karthik_followup.txt` — a typed follow-up consult.

Demo users (seeded into `auth.users` and `profiles`): `dr.rao@aceso.demo`, `nurse.priya@aceso.demo`, `admin.kumar@aceso.demo`.

---

## 12. Tests

`cd services/api && pytest` — 43 tests. They start a throwaway embedded Postgres, apply the real migrations and seed, and build the scenarios; nothing mocks the database. Set `TEST_DATABASE_URL` to use another empty database.

| File | Covers |
|---|---|
| `test_units.py` | eGFR oracles (28.2, 28.7, 58.2, 45.5, 94.6), brand mapping and dose, denied allergy group, rejection of missing evidence and invented quotes, negation scope, misread value held back, value not in source, omission detection, redaction, SOAP guards |
| `test_database.py` | Provenance constraints, illegal transition, doctor-only confirmation with audit row, append-only audit log, intact chain, immutable signed note |
| `test_scenarios.py` | Exact alerts for all six scenarios, S1 trace contents and tight box, S3 denials, S4 summed dose, S5 trend and overdue loop, engine idempotency, search, role matrix, the full review → resolve → reject → sign → export flow, and the misprint upload |

Also checked by hand: live PDF, typed-transcript and audio uploads with the real Groq models; the same on Supabase including doctor-only confirmation and chain verification; the main screens in a headless browser.

Not exercised in a browser: sign-off, exports and the nurse view (covered through the API tests only). `eslint` reports `any` types throughout the frontend; `next build` passes.

---

## 13. Demo script (about 8 minutes)

Run `python scripts/setup_db.py --reseed-demo` first and keep `data/synthetic/` open.

1. **Framing (30 s).** The model does one job; everything that makes it safe is our code.
2. **Meena Rajan (3 min).** Open as Dr. Rao: no alert, the eGFR notice, the ibuprofen omission. Upload `S1_meena_labs_today.pdf`. Open "Explain & act": Glycomet → metformin, eGFR 28.2 from creatinine 2.1. "View source" on creatinine shows the box on the PDF. Click the metformin sentence in the note to show the spoken sentence at 00:41. Do not sign her off (see §14, stopping a medication).
3. **Bad scan (30 s).** Upload `S1_meena_labs_misprint.pdf` to Karthik S: 21 is held back and no alert fires.
4. **Arjun Menon (1 min).** Contradiction between the 2024 discharge and today's "no allergies"; resolve it by choosing the true statement.
5. **Lakshmi and Suresh (1 min).** Three denials and no false alarm; three alerts including a dose summed across two brands.
6. **Fatima Begum (30 s).** HbA1c trend and the overdue follow-up.
7. **Sign-off and exports (1 min).** On a clean patient: confirm the allergy and medication facts, sign, open the Tamil patient summary and the FHIR bundle. Rehearse this step.
8. **Governance (30 s).** Nurse has no confirm or sign buttons. Admin sees every step in the audit log; verify the chain.

Fallback if the model or network fails on stage: seed with `--s1-labs-preloaded`, and keep a screen recording.

---

## 14. Known limitations

- **No way to stop or edit a medication.** The review screen has only Confirm and Reject. After the metformin alert the doctor cannot record "stop metformin", and a signed S1 visit would export a patient summary that still lists it.
- **No OCR.** Scanned or handwritten documents are rejected.
- **Demo authentication only.** No passwords, no JWT verification.
- **Audio.** Tested with a synthetic voice only. No speaker labels. Audio is sent to the transcription API unredacted.
- **On-prem mode.** The Ollama adapter is written but untested; there is no on-prem speech-to-text.
- **Search** is keyword and dictionary matching; embeddings are not used.
- **SOAP wording** is a fixed template.
- **FHIR** is not validated against ABDM/NRCeS profiles.
- **Translations and all clinical content** are unreviewed.
- **Knowledge tables are tiny** (one interaction, two dose limits, two allergy groups, about 27 drug names).
- **Files in the database** rather than object storage.
- **Chart loading is slow on a distant database** (§4.6).
- **No evaluation harness.** The earlier one tested only mocks and was removed.
- **Unused leftovers:** `fact_chunks`, `note_edits`, `eval_runs`, `eval_results` tables; `services/api/aceso/templates/fonts/` (from the earlier PDF export).

---

## 15. What we plan to build next

In priority order for the hackathon:

1. **"Stop medication" action.** A button that records a `denied` medication fact as the doctor. The engine already treats a newer denial as removing the drug, so the alert closes itself; the patient summary then says "Stop taking Metformin" in the patient's language. Closes the loop: detect, explain, act, tell the patient.
2. **Faster charts on Supabase.** Cache the reference tables and demo profiles, and batch the chart queries, to bring a chart from about 5 s to 1–2 s.
3. **Live model swap.** Install Ollama, test the on-prem adapter, and add a visible switch so the Swap Test can be shown on stage.
4. **Evaluation page.** Run the six scenarios through the live model and report extraction precision and recall, alert recall, false alarms on the control patient, and the cases that fail.
5. **Tamper demonstration.** Show what the chain check reports when an audit row is altered.
6. **A recorded real consult** for the audio path, read by two people from the S1 script.

After the hackathon:

- Fact editing that creates a new fact superseding the old one.
- OCR for scans (Tesseract or Azure Document Intelligence) behind the same `parse_pdf` interface.
- Real login with Supabase Auth and JWT verification; let RLS do the enforcement.
- A licensed open interaction dataset and a larger Indian brand dictionary.
- Semantic search using the existing `fact_chunks` table and multilingual embeddings.
- Speaker diarization and code-mixed Tamil/Hindi-English speech.
- Model-written note wording under the existing number and negation guards.
- FHIR validation against ABDM profiles.
- Edit-diff learning from doctor corrections.
- Supabase Storage for files; a proper job worker with retries.
- Clinician review of every rule, limit and template, recorded per rule in `safety_rules.clinician_reviewed_by`.

---

## 16. Troubleshooting

| Symptom | Cause and fix |
|---|---|
| Every data request returns 500 after 30 s | The database is unreachable. On a network that blocks port 5432, turn on WARP or a hotspot, then restart the API |
| "No database configured" | `SUPABASE_DB_URL` is empty and the local database is not running. Set one or run `python scripts/local_db.py` |
| `setup_db.py` says the database already has ACESO tables | They were created by something else. Re-run with `--reset` (destroys data) |
| Web page shows "Jest worker encountered … child process exceptions" | A build ran while the dev server was up. Stop the server on port 3000, `npm run build`, `npm run start` |
| `EADDRINUSE :::3000` | An old Node process still holds the port. Find it with `netstat -ano \| findstr :3000` and end it |
| Upload fails with "no text layer" | The PDF is a scan; only text PDFs are supported |
| Job result shows a warning about the language model | Groq was unreachable or returned invalid JSON; dictionary detections were queued for review instead |
| 401 "Pick a demo role" | The role is not set in the browser; sign in again from `/` |
| S1 shows no alert | Expected until `S1_meena_labs_today.pdf` is uploaded, or seed with `--s1-labs-preloaded` |
