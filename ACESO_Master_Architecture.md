# ACESO: Master Architecture
*The Deep-Tech Clinical EMR*

## 1. Core Philosophy: The "Swap Test"
The guiding principle of this architecture is the **Swap Test**: *If a judge swaps out our underlying LLM for a completely different one, does the product still have unique value?* 

Yes. The LLM is relegated to a single extraction step within a much larger, proprietary pipeline. The true IP of ACESO lives in the layers *around* the model: Claim-level provenance, the longitudinal fact store, deterministic clinical safety rules, and fully explainable decision traces.

---

## 2. The Master Pipeline: Fact-First Generation

**Crucial Architecture Decision:** We do not ask the LLM to write a prose SOAP note and try to attribute citations afterward. We extract facts first (which carry their spans and bounding boxes), verify those facts, and then generate the SOAP note *from* the verified facts. This makes provenance tracing mathematically sound.

```text
  Raw Input (Audio / PDFs)
         │
         ▼
  1. STT / OCR Perception (Keeping Audio Spans & Bounding Boxes)
         │
         ▼
  2. Fact Extraction ──► Terminology Normalization (RxNorm/LOINC) & Negation Handling
         │
         ▼
  3. Three-Way Verification Pass (OCR Bbox match, Transcript Support, Omission Check)
         │
         ▼
  4. Longitudinal Fact Store (Fact State: extracted ─► verified ─► clinician_confirmed)
         │
         ▼
  5. Deterministic Safety Engine ──► The Explainability Trace
         │
         ▼
  6. SOAP Generation & Review-by-Exception UI
         │
         ▼
  7. Doctor Sign-off ──► Official Record (FHIR/ABDM)
         │
         ▼
  8. Safe Patient-Facing Export (Structured Templating, NOT LLM translation)
```

---

## 3. Deep-Dive: Core Differentiators

### Differentiator 1: Claim-Level Provenance & The 3-Way Verification Pass
*Standard RAG links to a whole PDF. We link to the exact coordinate.*
* **Audio & Visual Provenance:** Every fact carries hidden metadata linking to the `[start:end]` audio timestamp or OCR `[x, y, w, h]` bounding box. 
* **The 3-Way Verification Pass:** Before a fact enters the store, three distinct checks occur:
  1. **OCR Match:** Does the text inside the bounding box actually equal the extracted value?
  2. **Transcript Support:** Is the extracted medical claim supported by the transcript span?
  3. **Omission Check:** A diff check for things the patient said that are missing from the extracted facts.

### Differentiator 2: The Longitudinal Fact Store
*We do not just chunk text into pgvector. We extract facts into a time-aware database.*
* **Fact Lifecycle:** Every fact has a state field (`extracted` ➔ `verified` ➔ `clinician_confirmed`). The safety engine's behavior depends strictly on verified/confirmed facts.
* **Negation Handling:** Extraction explicitly stores "explicitly denied" separately from "not mentioned". Without this, allergy contradiction checks will throw false alarms.
* **Contradiction Detection:** If a 2024 PDF states `Allergy: Penicillin`, and today's audio transcript yields `Allergy: None`, the Contradiction Engine flags it. 

### Differentiator 3: True Clinical Knowledge & Deterministic Safety
*We never ask an LLM "Is this drug safe?".*
* **Terminology Normalization:** Drugs (RxNorm/ATC), Labs (LOINC), Diagnoses (ICD-10/SNOMED). Proprietary dictionaries map Indian brand names (e.g., *"Glycomet"*) to generics (*"Metformin"*).
* **Computed Safety Metrics:** Deterministic code calculates the **eGFR** from age, sex, and raw creatinine. Rules are written against eGFR, not raw creatinine.
* **Open Dataset Checks:** We run interaction, duplicate-therapy, and dose-range checks against an actual open dataset deterministically.

### Differentiator 4: The Explainability Trace
*Doctors hate black boxes. We show them the math.*
When the safety engine blocks a medication, it provides an **"Explain"** trace button showing the exact execution graph and the source guideline.
* *Example UI:* `Rule: KDIGO Guideline (Metformin in CKD) triggered ➔ Because Computed eGFR = 28 mL/min/1.73m² (from raw Creatinine 2.1) ➔ AND Metformin is contraindicated when eGFR < 30.`

### Differentiator 5: Safe Patient-Facing Summary (Templated)
*We translate data, not hallucinations, for the patient.*
Generating patient-facing instructions via LLM translation is dangerous (it might omit crucial dosage info). Instead, ACESO uses **Structured Data Translation**. We take the perfectly normalized, verified Fact Store data and pass *only* the structured plan through rigid regional-language templates, guaranteeing zero clinical data is hallucinated.

---

## 4. UI/UX: Review-by-Exception
*We respect the doctor's time. We don't make them re-read everything.*
* **Defensible Confidence Scoring:** Scored based on OCR confidence, reference-range plausibility, and the Verification Pass.
* **Auto-Collapsing:** High-agreement, verified fields are visually collapsed.
* **The "Never-Collapse" Rule:** The UI **never** auto-collapses allergies, dosages, or new medications. These always require explicit manual review.

---

## 5. Required Arena Features (Graded Modules)
This architecture natively powers the required grading rubric features:
1. **RBAC & Audit Logs:** Strict roles; every fact state transition (`verified` ➔ `clinician_confirmed`) is appended to an immutable audit log.
2. **Timeline & Trend Analysis:** Powered directly by the Longitudinal Fact Store, graphing changes in normalized LOINC lab values over time.
3. **Natural-Language Search:** The Fact Store and PGVector chunk database enable querying exact clinical events across the patient's history.

---

## 6. The Evaluation Harness
We ship an evaluation harness running against a small synthetic patient set with ground truth.
* **Metrics Tracked:** Extraction F1 Score, Unsupported-Claim Rate (Hallucination rate), Citation Precision, Interaction Recall, Doctor Edit Rate on notes.
* **The Pitch:** A wrapper demo says "it works." We say "it works this well, and here is where it fails."

---

## 7. High-Impact Secondary Features
* **Open-Loop Tracker:** Plan items ("repeat HbA1c in 3 months") become tracked commitments on the dashboard, flagged when overdue.
* **Live Gap Prompts:** A side panel during the consult showing what hasn't been captured yet (allergies not asked, pending lab from last visit).
* **Edit-Diff Learning:** We store doctor edits to AI drafts to adapt formatting templates per doctor.
* **Privacy-First Model Gateway:** PHI redaction happens *before* any external API call, combined with an on-premise fallback switch.

---

## 8. Stretch Goals / Future Scope
* **Code-Mixed, Multilingual Scribe:** Accurately transcribing heavily code-mixed Indian speech (Tamil-English, Hinglish) is a hard research problem. As a stretch goal, we will experiment with speaker diarization, language-aware transcription, and dynamic vocabulary normalization steps.
