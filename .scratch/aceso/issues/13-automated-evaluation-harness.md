# 13 — Automated Evaluation Harness

**What to build:** A rigorous testing suite that runs all scenarios, proving the system's accuracy and safety by measuring extraction F1 scores, hallucination rates, and interaction catch rates.

**Blocked by:** 08 — Contradiction Engine & Remaining Scenarios

**Status:** ready-for-agent

- [ ] `eval/run.py` runs all 6 synthetic scenarios end-to-end against `truth.json`.
- [ ] Calculates key metrics including Extraction F1, hallucination rate, and interaction recall.
- [ ] Auto-generates `REPORT.md` and `FAILURES.md` detailing the system's performance.
