# 12 — Privacy Gateway & Safe Export (FHIR + PDF)

**What to build:** Patient privacy is guaranteed via a gateway that redacts PHI before sending it to the LLM. Verified records can be cleanly exported as a multilingual summary for the patient, or as a standard FHIR bundle for other systems.

**Blocked by:** 07 — Review-by-Exception & Sign-Off Flow

**Status:** ready-for-agent

- [ ] Privacy gateway redacts PHI (names, numbers) from outbound LLM payloads.
- [ ] Jinja2 templates generate a patient-facing PDF summary in English, Tamil, and Hindi without LLM translation.
- [ ] Backend generates a valid FHIR R4 ABDM bundle for the signed encounter.
