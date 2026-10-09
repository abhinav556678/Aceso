# 11 — Open-Loop Tracker & Live Gap Prompts

**What to build:** The system keeps track of promised follow-ups (e.g., "recheck HbA1c in 3 months") and actively nudges the doctor during a live consult if essential steps (like asking about allergies or vitals) are missing.

**Blocked by:** 07 — Review-by-Exception & Sign-Off Flow

**Status:** ready-for-agent

- [ ] Backend parses signed plans to detect follow-up tasks and logs them as `open_loops`.
- [ ] Live WebSocket/Realtime updates push gap prompts to the UI during an active consult.
- [ ] Dashboard displays overdue loops.
