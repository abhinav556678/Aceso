"""Fact extraction: the LLM's only job, fenced in by deterministic checks.

The model sees numbered evidence units and must cite their IDs. Spans and
bounding boxes are then computed by our code from those IDs, never by the model.
"""
import logging
import re
from typing import Optional

from pydantic import BaseModel, ValidationError
from rapidfuzz import fuzz

from aceso.extraction.negation import has_cue, is_negated
from aceso.extraction.terminology import BLANKET_ALLERGY, UNIT_CONVERSIONS, Terminology, parse_dose
from aceso.llm.client import LLMClient

logger = logging.getLogger(__name__)

PROMPT_VERSION = "extract-v1"
FACT_TYPES = {"allergy", "medication", "lab_result", "diagnosis", "vital", "symptom", "history", "plan_item"}
CHUNK_UNITS = 60

SYSTEM_PROMPT = """You extract clinical facts from numbered evidence units of a medical record.
Return a JSON object: {"facts": [ ... ]}. Each fact:
{
  "fact_type": one of allergy | medication | lab_result | diagnosis | vital | symptom | history | plan_item,
  "assertion": "present" | "denied" | "uncertain",
  "name": the drug / test / condition / substance exactly as written (for plan_item: the instruction),
  "raw_text": an exact quote copied from the cited evidence that states this fact,
  "value_num": number or null (lab and vital results only),
  "unit": string or null,
  "dose": {"amount": number, "unit": string, "freq": string} or null (medications only),
  "evidence_ids": ["B3"] the IDs of the unit(s) that state it
}
Rules:
- Extract only what is explicitly stated. Never infer a diagnosis, a drug or a value.
- An explicit denial ("no diabetes", "not allergic to sulfa", "no allergies") is a fact with assertion "denied".
  A blanket "no allergies" is one allergy fact with name "allergies".
- If something is not mentioned, output nothing for it.
- Blood pressure "130/80" is two vital facts: systolic blood pressure 130 and diastolic blood pressure 80.
- Follow-up instructions ("repeat HbA1c in 3 months") are plan_item facts.
- Ignore reference ranges, lab names of the clinic, addresses and patient identifiers.
- Every fact needs at least one evidence id that appears in the input."""


class LLMFact(BaseModel):
    fact_type: str
    assertion: str = "present"
    name: str
    raw_text: str
    value_num: Optional[float] = None
    unit: Optional[str] = None
    dose: Optional[dict] = None
    evidence_ids: list[str]


def format_unit(unit: dict) -> str:
    """One line of the packet. Only `sent`, the redacted text, ever reaches the model."""
    text = unit["sent"]
    if unit["kind"] == "segment":
        return f'[{unit["id"]}] ({unit.get("speaker") or "unknown"}) "{text}"'
    return f'[{unit["id"]}] (page {unit["page_no"]}) "{text}"'


def extract(llm: LLMClient, units: list[dict], term: Terminology) -> tuple[list[dict], list[str]]:
    """Run the model over the units and return (accepted draft facts, rejection reasons)."""
    by_id = {u["id"]: u for u in units}
    drafts, rejected = [], []
    for start in range(0, len(units), CHUNK_UNITS):
        chunk = units[start:start + CHUNK_UNITS]
        packet = "\n".join(format_unit(u) for u in chunk)
        raw = llm.extract_json(SYSTEM_PROMPT, f"Evidence units:\n{packet}")
        for item in raw.get("facts") or []:
            draft, reason = _validate(item, by_id)
            if draft:
                drafts.append(normalise(draft, term))
            else:
                rejected.append(reason)
    if rejected:
        logger.info("Rejected %d model outputs: %s", len(rejected), rejected[:5])
    return drafts, rejected


def _validate(item: dict, by_id: dict) -> tuple[Optional[dict], str]:
    """Reject, don't repair: unknown evidence, unknown types and unquoted text are dropped."""
    try:
        fact = LLMFact.model_validate(item)
    except ValidationError as exc:
        return None, f"schema: {exc.errors()[0]['msg']}"
    if fact.fact_type not in FACT_TYPES:
        return None, f"unknown fact_type {fact.fact_type!r}"
    if fact.assertion not in ("present", "denied", "uncertain"):
        return None, f"unknown assertion {fact.assertion!r}"
    cited = [by_id[e] for e in fact.evidence_ids if e in by_id]
    if not cited or len(cited) != len(fact.evidence_ids):
        return None, f"cites evidence that does not exist: {fact.evidence_ids}"
    evidence_text = " ".join(u["text"] for u in cited)
    if fuzz.partial_ratio(fact.raw_text.lower(), evidence_text.lower()) < 85:
        return None, f"raw_text not found in cited evidence: {fact.raw_text!r}"
    return {**fact.model_dump(), "units": cited, "evidence_text": evidence_text,
            "attention_reasons": []}, ""


def normalise(draft: dict, term: Terminology) -> dict:
    """Map the fact onto our terminology. Unmapped terms are flagged, never guessed."""
    kind, name, raw = draft["fact_type"], draft["name"].strip(), draft["raw_text"]
    draft.update(code_system=None, code=None, display=name, value_text=None,
                 stated_value=draft.get("value_num"))
    reasons = draft["attention_reasons"]

    if kind == "medication":
        drug = term.match_drug(name) or term.match_drug(raw)
        # read the strength from the text that follows the drug name ("1. Tab Glycomet 500 BD" -> 500)
        dose_text = raw if re.search(r"\d", raw) else draft["evidence_text"]
        at = dose_text.lower().find((drug["brand"] if drug else name).lower())
        dose = parse_dose(dose_text[at:] if at >= 0 else dose_text, draft.get("dose"))
        if drug:
            draft.update(code_system="RxNorm", code=drug["rxnorm"], display=drug["generic"].capitalize(),
                         value_text=drug["generic"])
            dose.update(generic=drug["generic"], brand=drug["brand"])
        else:
            reasons.append("unmapped_drug")
        draft["dose"] = dose or None
        draft["value_num"], draft["unit"] = dose.get("amount"), dose.get("unit")

    elif kind == "allergy":
        draft["dose"] = None
        if BLANKET_ALLERGY.match(name) or BLANKET_ALLERGY.match(re.sub(r"[^a-z ]", "", raw.lower()).strip()):
            draft.update(display="Allergies (any)", value_text="*")
        else:
            drug = term.match_drug(name)
            substance = drug["generic"] if drug else re.sub(r"\ballerg\w*\b", "", name.lower()).strip(" :-")
            group = term.allergy_group(substance)
            draft.update(display=substance.capitalize(), value_text=substance,
                         code_system="RxNorm" if drug and drug["rxnorm"] else None,
                         code=drug["rxnorm"] if drug else None,
                         dose={"group": group} if group else None)
            if not drug and not group:
                reasons.append("unmapped_allergen")

    elif kind in ("lab_result", "vital"):
        draft["dose"] = None
        concept = term.match_concept(name, ("LOINC",)) or term.match_concept(raw, ("LOINC",))
        if concept:
            draft.update(code_system="LOINC", code=concept["code"], display=concept["display"])
            conversion = UNIT_CONVERSIONS.get((concept["code"], (draft.get("unit") or "").lower()))
            if conversion and draft.get("value_num") is not None:
                draft["value_num"] = round(draft["value_num"] * conversion[0], 2)
                draft["unit"] = conversion[1]
        else:
            reasons.append("unmapped_test")
        if draft.get("value_num") is None and draft["assertion"] == "present":
            reasons.append("missing_value")

    elif kind == "diagnosis":
        draft["dose"] = None
        concept = term.match_concept(name, ("ICD10",))
        if concept:
            draft.update(code_system="ICD10", code=concept["code"], display=concept["display"])
        else:
            reasons.append("unmapped_diagnosis")
    else:
        draft["dose"] = None

    _cross_check_negation(draft)
    return draft


def _cross_check_negation(draft: dict) -> None:
    """The model's assertion must agree with a rule-based reading of the same span."""
    term_text = draft["name"] if draft["value_text"] != "*" else "allergies"
    negated = is_negated(draft["evidence_text"], term_text)
    if draft["assertion"] == "present" and negated:
        draft["assertion"] = "uncertain"
        draft["attention_reasons"].append("negation_conflict")
    elif draft["assertion"] == "denied" and not negated and not has_cue(draft["evidence_text"]):
        draft["assertion"] = "uncertain"
        draft["attention_reasons"].append("negation_conflict")
