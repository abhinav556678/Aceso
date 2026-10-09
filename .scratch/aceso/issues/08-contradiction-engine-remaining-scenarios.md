# 08 — Contradiction Engine & Remaining Scenarios

**What to build:** The system now supports the full suite of test patients (S2, S3, S4, S6) and actively detects contradictions (e.g., patient says "no allergies" but an old record shows a Penicillin allergy) and complex interactions.

**Blocked by:** 07 — Review-by-Exception & Sign-Off Flow

**Status:** ready-for-agent

- [ ] Seed scripts inject synthetic patients S2, S3, S4, and S6.
- [ ] Contradiction engine detects conflicts between new and historical facts.
- [ ] Rule engine implements duplicate therapy and max-dose checks.
- [ ] UI provides a resolution modal for doctors to resolve detected contradictions.
