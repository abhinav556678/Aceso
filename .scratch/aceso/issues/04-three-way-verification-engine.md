# 04 — Three-Way Verification Engine

**What to build:** A deterministic safety layer that cross-checks the AI's work by ensuring extracted facts perfectly match the OCR text/audio transcript. Facts that pass become "verified" automatically, while discrepancies are flagged for the doctor.

**Blocked by:** 03 — AI Fact Extraction & Normalization

**Status:** ready-for-agent

- [ ] OCR match check verifies bounding box text against the extracted value.
- [ ] Transcript support check verifies audio facts.
- [ ] Omission check runs a high-recall pass to flag potentially missed items.
- [ ] Confidence score is calculated; passing facts move to `verified` state, failing ones get `needs_attention`.
