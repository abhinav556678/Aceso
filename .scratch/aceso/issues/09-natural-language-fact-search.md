# 09 — Natural-Language Fact Search

**What to build:** The doctor can type a natural language question (e.g., "Does he have a sulfa allergy?") into a search bar and instantly receive a sourced answer citing the exact audio span or document box.

**Blocked by:** 08 — Contradiction Engine & Remaining Scenarios

**Status:** ready-for-agent

- [ ] Facts and transcripts are embedded using `pgvector` during the verification stage.
- [ ] Hybrid search endpoint (SQL + semantic vector search) is implemented.
- [ ] Search UI tab allows querying and displays the composed answer with citation chips.
