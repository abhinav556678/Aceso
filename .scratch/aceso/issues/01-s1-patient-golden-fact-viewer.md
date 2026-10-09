# 01 — S1 Patient Golden Fact Viewer (Foundation)

**What to build:** A functional foundation allowing the doctor to log in, view a list of patients, and open the chart for Scenario 1 (Meena Rajan). The chart displays pre-populated "golden" clinical facts and allows clicking them to view the original source document bounding boxes or audio spans.

**Blocked by:** None — can start immediately

**Status:** ready-for-agent

- [ ] Supabase schema is created with auth, patients, and facts tables.
- [ ] Seed script injects S1 golden facts with simulated provenance (audio spans/bounding boxes).
- [ ] Next.js app shell allows role-based login.
- [ ] Patient chart UI displays facts correctly and clicking a fact opens the source viewer to the correct region.
