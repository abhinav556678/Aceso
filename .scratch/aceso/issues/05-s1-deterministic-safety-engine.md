# 05 — S1 Deterministic Safety Engine (eGFR Alert)

**What to build:** The system protects patient safety by automatically computing health metrics (like eGFR) from verified facts, evaluating safety rules, and loudly warning the doctor of contraindications (like Metformin usage with low eGFR).

**Blocked by:** 04 — Three-Way Verification Engine

**Status:** ready-for-agent

- [ ] Safety engine computes eGFR deterministically from verified creatinine facts.
- [ ] Rule engine evaluates the `KDIGO-METFORMIN-EGFR30` rule and fires a critical alert.
- [ ] UI displays the critical alert banner prominently on the chart.
- [ ] Alert explainability drawer shows the step-by-step logic and links to the source creatinine fact.
