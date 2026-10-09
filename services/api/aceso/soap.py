"""SOAP note generation from verified facts.

Every sentence is rendered from exactly one trusted fact and cites it, so the
note cannot contain a claim the fact store does not hold. Wording is a
deterministic template; an LLM may only ever rephrase under the same guards.
"""
import re
from typing import Optional

from psycopg.types.json import Jsonb

GENERATOR_ID = "template:soap-v1"
NEGATION_WORDS = ("no ", "not ", "denies", "denied", "without")


def fmt_num(value) -> str:
    return f"{float(value):g}"


def sentence_for(fact: dict) -> tuple[Optional[str], str]:
    """(section, text) for one fact."""
    kind, display, denied = fact["fact_type"], fact["display"], fact["assertion"] == "denied"
    dose = fact["dose"] or {}
    if kind in ("symptom", "history"):
        return "subjective", f"Denies {display}." if denied else f"Reports {display}."
    if kind == "allergy":
        if fact["value_text"] == "*":
            return "subjective", "Denies any known allergies." if denied else "Reports allergies (unspecified)."
        return "subjective", f"Denies allergy to {display}." if denied else f"Allergy: {display}."
    if kind in ("lab_result", "vital"):
        if fact["value_num"] is None:
            return "objective", f"{display}: not done." if denied else f"{display} noted."
        computed = " (computed)" if fact["created_by"] == "system:metric" else ""
        return "objective", f"{display}: {fmt_num(fact['value_num'])} {fact['unit'] or ''}".rstrip() + f"{computed}."
    if kind == "diagnosis":
        return "assessment", f"No history of {display}." if denied else f"{display}."
    if kind == "medication":
        if denied:
            return "subjective", f"Not taking {display}."
        brand = dose.get("brand")
        name = f"{display} ({brand.capitalize()})" if brand and brand != (fact["value_text"] or "").lower() else display
        strength = f" {fmt_num(dose['amount'])} {dose.get('unit', 'mg')}" if dose.get("amount") is not None else ""
        freq = f" {dose['freq']}" if dose.get("freq") else ""
        return "plan", f"{name}{strength}{freq}."
    if kind == "plan_item":
        text = display.rstrip(".")
        return "plan", f"{text[0].upper()}{text[1:]}."
    return None, ""


def check_sentence(text: str, fact: dict) -> list[str]:
    """Hard gates: no number that is not in the fact, and denials must read as denials."""
    problems = []
    dose = fact["dose"] or {}
    allowed = set(re.findall(r"\d+(?:\.\d+)?", f"{fact['display']} {fact['raw_text'] or ''} {fact['unit'] or ''}"))
    for value in (fact["value_num"], dose.get("amount")):
        if value is not None:
            allowed.add(fmt_num(value))
    for number in re.findall(r"\d+(?:\.\d+)?", text):
        if number not in allowed and fmt_num(number) not in allowed:
            problems.append(f"number {number} is not in the cited fact")
    if fact["assertion"] == "denied" and not any(w in text.lower() for w in NEGATION_WORDS):
        problems.append("denied fact rendered without a negation")
    return problems


def build_note(facts: list[dict]) -> dict:
    note = {"subjective": [], "objective": [], "assessment": [], "plan": []}
    order = {"allergy": 0, "symptom": 1, "history": 2, "medication": 3, "vital": 0, "lab_result": 1,
             "diagnosis": 0, "plan_item": 4}
    for fact in sorted(facts, key=lambda f: (order.get(f["fact_type"], 9), f["created_at"])):
        section, text = sentence_for(fact)
        if not section or check_sentence(text, fact):
            # fall back to the bare fact rather than drop it: never-collapse facts must appear
            section, text = section or "objective", f"{fact['fact_type'].replace('_', ' ').capitalize()}: {fact['display']}."
        note[section].append({"text": text, "fact_ids": [str(fact["id"])]})
    return note


def regenerate(cur, encounter_id) -> Optional[dict]:
    """Rebuild the draft for an encounter from its trusted facts. Signed notes are never touched."""
    cur.execute("select id, status::text as status from soap_notes where encounter_id = %s "
                "order by version desc limit 1", (encounter_id,))
    existing = cur.fetchone()
    if existing and existing["status"] == "signed":
        return None
    cur.execute("select * from facts where encounter_id = %s and state in ('verified','clinician_confirmed')",
                (encounter_id,))
    note = build_note(cur.fetchall())
    sections = [Jsonb(note[s]) for s in ("subjective", "objective", "assessment", "plan")]
    if existing:
        cur.execute("update soap_notes set subjective=%s, objective=%s, assessment=%s, plan=%s, generated_by=%s "
                    "where id = %s", (*sections, GENERATOR_ID, existing["id"]))
    else:
        cur.execute("insert into soap_notes(encounter_id, version, subjective, objective, assessment, plan, "
                    "status, generated_by) values (%s, 1, %s, %s, %s, %s, 'draft', %s)",
                    (encounter_id, *sections, GENERATOR_ID))
    return note
