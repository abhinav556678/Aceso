# 06 — Fact-Driven SOAP Generation

**What to build:** The system drafts a complete clinical SOAP note using only verified facts. The doctor can click any sentence in the note to see exactly which fact and source document/audio it came from.

**Blocked by:** 04 — Three-Way Verification Engine

**Status:** ready-for-agent

- [ ] SOAP generation worker reads `verified` facts and drafts a note.
- [ ] Strict guards enforce that all numbers and negations in the note precisely match the verified facts.
- [ ] UI displays the SOAP draft with interactive, clickable citations for every sentence.
