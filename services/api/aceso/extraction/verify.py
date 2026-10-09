"""Three-way verification and confidence scoring.

A fact becomes `verified` only when every applicable check passes and the
confidence clears the threshold. Anything else stays `extracted` with the
reasons the doctor will see. Checks may only hold a fact back, never promote it.
"""
import re
from typing import Optional

from aceso.extraction.terminology import Terminology

VERIFY_THRESHOLD = 0.90
OCR_REVIEW_BELOW = 0.80  # a row the OCR engine was less sure of than this is never auto-verified
DEFAULT_SEGMENT_CONFIDENCE = 0.9
_NUMBER = re.compile(r"\d+(?:\.\d+)?")


def _numbers(text: str) -> set:
    return {float(n) for n in _NUMBER.findall(text or "")}


def _claimed_numbers(draft: dict) -> set:
    """Numbers the fact asserts, as printed/spoken (before any unit conversion)."""
    claimed = set()
    if draft.get("stated_value") is not None:
        claimed.add(float(draft["stated_value"]))
    dose = draft.get("dose") or {}
    if dose.get("amount") is not None:
        claimed.add(float(dose["amount"]))
    return claimed


def _source_match(draft: dict) -> dict:
    """Is the quote really in the cited evidence, and do the claimed numbers appear there?"""
    squash = lambda text: re.sub(r"\s+", " ", text.lower()).strip()
    evidence = draft["evidence_text"]
    if squash(draft["raw_text"]) not in squash(evidence):
        return {"ok": False, "detail": "the quoted text differs from the cited source"}
    missing = sorted(_claimed_numbers(draft) - _numbers(evidence))
    if missing:
        return {"ok": False, "detail": f"value {missing[0]:g} is not in the cited source"}
    return {"ok": True, "detail": "quote and values found in the cited source"}


def _plausibility(draft: dict, term: Terminology, sex: Optional[str]) -> tuple[float, Optional[str]]:
    """1 inside the physiologically possible range, 0 outside (likely a misread such as 21 for 2.1)."""
    if draft["fact_type"] not in ("lab_result", "vital") or draft.get("value_num") is None:
        return 1.0, None
    limits = term.reference_range(draft.get("code") or "", sex)
    if not limits or limits["plausible_min"] is None:
        return 0.5, "no_reference_range"
    if float(limits["plausible_min"]) <= draft["value_num"] <= float(limits["plausible_max"]):
        return 1.0, None
    return 0.0, "out_of_plausible_range"


def verify(draft: dict, term: Terminology, sex: Optional[str]) -> dict:
    """Fill in verification, confidence, state and attention reasons on a draft fact."""
    is_document = draft["units"][0]["kind"] == "block"
    match = _source_match(draft)
    plausibility, plausibility_reason = _plausibility(draft, term, sex)
    reasons = draft["attention_reasons"]
    if not match["ok"]:
        reasons.append("ocr_mismatch" if is_document else "not_supported_by_transcript")
    if plausibility_reason:
        reasons.append(plausibility_reason)

    perception = [u.get("confidence") or DEFAULT_SEGMENT_CONFIDENCE for u in draft["units"]]
    if any(u.get("ocr") for u in draft["units"]):
        if any(u.get("handwriting") for u in draft["units"]):
            # the handwriting model writes something plausible even when it is wrong: never auto-verify
            reasons.append("read_by_handwriting_model")
        elif min(perception) < OCR_REVIEW_BELOW:
            reasons.append("low_ocr_confidence")
        # a misread brand can fuzzy-match the wrong drug, so only a literal dictionary hit is trusted
        brand = (draft.get("dose") or {}).get("brand")
        if draft["fact_type"] == "medication" and brand and brand not in draft["evidence_text"].lower():
            reasons.append("ocr_inexact_drug")
    perception_score = sum(perception) / len(perception)
    checks = [match["ok"], plausibility > 0]
    verification_score = sum(1 for ok in checks if ok) / len(checks)
    confidence = round(0.30 * perception_score + 0.20 * plausibility + 0.50 * verification_score, 3)
    if confidence < VERIFY_THRESHOLD and not reasons:
        reasons.append("low_confidence")

    draft["verification"] = {
        "ocr_match": match if is_document else {"ok": None},
        "transcript_support": {"ok": None} if is_document else match,
        "plausibility": {"ok": plausibility > 0, "score": plausibility},
        "omission": {"ok": True},
    }
    draft["confidence"] = confidence
    draft["confidence_parts"] = {"perception": round(perception_score, 3), "plausibility": plausibility,
                                 "verification": verification_score}
    draft["needs_attention"] = bool(reasons)
    draft["state"] = "extracted" if reasons or draft["assertion"] == "uncertain" else "verified"
    return draft


def find_omissions(units: list[dict], drafts: list[dict], term: Terminology) -> list[dict]:
    """A separate high-recall pass: dictionary terms present in the source that no fact covers."""
    covered, quoted = set(), {}
    for draft in drafts:
        for unit in draft["units"]:
            quoted[unit["id"]] = quoted.get(unit["id"], "") + " " + draft["raw_text"].lower()
        covered.add((draft["fact_type"], draft.get("value_text")))
        covered.add((draft["fact_type"], draft.get("code")))
        if draft["fact_type"] == "allergy":
            covered.add(("allergy", "allergy"))
    omissions, seen = [], set()
    for unit in units:
        for hit in term.detect(unit["text"]):
            key = (hit["kind"], hit["key"])
            if key in covered or key in seen or hit["term"] in quoted.get(unit["id"], ""):
                continue
            # a drug named as an allergen ("allergic to penicillin") is covered by the allergy fact
            if hit["kind"] == "medication" and ("allergy", hit["key"]) in covered:
                continue
            seen.add(key)
            omissions.append({
                "fact_type": hit["kind"], "assertion": "uncertain", "name": hit["term"],
                "display": f"Possible omission: {hit['term']}", "raw_text": unit["text"],
                "code_system": None, "code": None, "value_num": None, "value_text": None,
                "unit": None, "dose": None, "units": [unit], "evidence_text": unit["text"],
                "state": "extracted", "needs_attention": True,
                "attention_reasons": ["possible_omission"],
                "confidence": 0.0, "confidence_parts": None,
                "verification": {"omission": {"ok": False, "detail": f"'{hit['term']}' appears in the source but no fact covers it"}},
            })
    return omissions
