# 07 — Review-by-Exception & Sign-Off Flow

**What to build:** The doctor completes their visit by reviewing only the risky or unverified items (safe items are collapsed). They acknowledge alerts, sign off on the record, and the system permanently locks the encounter in an immutable audit log.

**Blocked by:** 05 — S1 Deterministic Safety Engine, 06 — Fact-Driven SOAP Generation

**Status:** ready-for-agent

- [ ] Review UI collapses trusted facts and explicitly forces review of allergies, doses, new meds, and unverified facts.
- [ ] Backend sign-off endpoint enforces gating logic (all alerts must be acknowledged/overridden with reason).
- [ ] Immutable, hash-chained `audit_log` records the signature and state changes.
- [ ] Encounter and SOAP note are locked against further direct edits.
