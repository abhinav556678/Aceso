# 03 — AI Fact Extraction & Normalization

**What to build:** The system automatically reads transcribed audio and OCR text, extracting structured clinical facts (e.g., Medications, Labs) linked precisely to their source evidence, and displays them on the UI in an "extracted" state.

**Blocked by:** 02 — Audio & PDF Ingestion Pipeline

**Status:** ready-for-agent

- [x] LLM adapter extracts facts strictly from the provided text segments, citing evidence IDs.
- [x] Terminology normalizer maps extracted terms to standard codes (RxNorm, LOINC).
- [x] Extracted facts are saved to the database with computed provenance spans/boxes.
- [x] UI displays newly extracted facts with their provenance links.
