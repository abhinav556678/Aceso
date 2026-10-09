"""Deterministic safety engine + contradiction engine.

Reads only `verified` / `clinician_confirmed` facts. Rules are rows in
`safety_rules`; every alert carries an explainability trace of the exact
inputs, comparisons and source facts. No language model is involved.
"""
import logging
from datetime import datetime, timedelta, timezone
from itertools import combinations
from typing import Optional

from aceso.safety.metrics import egfr_ckdepi_2021

logger = logging.getLogger(__name__)

CREATININE_LOINC = "2160-0"
EGFR_LOINC = "62238-1"
EGFR_UNIT = "mL/min/1.73m2"
CREATININE_MAX_AGE_DAYS = 90
INTERACTION_SEVERITY = {"contraindicated": "critical", "major": "high", "moderate": "moderate", "minor": "info"}
SEVERITY_ORDER = ["minor", "moderate", "major", "contraindicated"]
OPS = {"<": lambda a, b: a < b, "<=": lambda a, b: a <= b, ">": lambda a, b: a > b, ">=": lambda a, b: a >= b}


def _when(fact: dict) -> datetime:
    return fact["effective_at"] or fact["created_at"]


def _generic(fact: dict) -> str:
    return (fact["value_text"] or fact["display"] or "").lower()


def _source(fact: dict) -> str:
    if fact["source"] == "document":
        return f"{fact.get('document_name') or 'document'} p{fact['page_no']}"
    if fact["source"] == "audio":
        return f"consult audio {fact['audio_start_ms'] // 1000}s–{fact['audio_end_ms'] // 1000}s"
    return fact["created_by"] or "manual entry"


def _evidence(fact: dict) -> str:
    quote = f"\"{fact['raw_text']}\"" if fact["raw_text"] else fact["display"]
    return f"{quote} · {_source(fact)} · {_when(fact):%d %b %Y}"


class PatientState:
    """The trusted view of one patient that the rules run against."""

    def __init__(self, patient: dict, facts: list[dict]):
        self.patient = patient
        self.facts = facts
        meds = [f for f in facts if f["fact_type"] == "medication" and f["assertion"] in ("present", "denied")]
        latest: dict = {}
        for fact in sorted(meds, key=_when):
            brand = (fact["dose"] or {}).get("brand") or _generic(fact)
            latest[(_generic(fact), brand)] = fact
        stopped = {g: _when(f) for (g, _), f in latest.items() if f["assertion"] == "denied"}
        # one entry per product; a newer "not taking X" removes X from the current list
        self.current_meds = [f for (g, _), f in latest.items()
                             if f["assertion"] == "present" and not (g in stopped and stopped[g] > _when(f))]
        self.allergies_present = [f for f in facts if f["fact_type"] == "allergy" and f["assertion"] == "present"]
        self.allergies_denied = [f for f in facts if f["fact_type"] == "allergy" and f["assertion"] == "denied"]

    def meds_of(self, generic: str) -> list[dict]:
        return [f for f in self.current_meds if _generic(f) == generic]


# ---------------------------------------------------------------- metrics

def compute_egfr(state: PatientState) -> dict:
    """Latest trusted creatinine -> eGFR. Missing or stale input is reported, never guessed."""
    creatinines = [f for f in state.facts if f["code"] == CREATININE_LOINC
                   and f["assertion"] == "present" and f["value_num"] is not None]
    if not creatinines:
        return {"available": False, "reason": "eGFR cannot be computed: no verified creatinine on file"}
    latest = max(creatinines, key=_when)
    measured = _when(latest)
    if datetime.now(timezone.utc) - measured > timedelta(days=CREATININE_MAX_AGE_DAYS):
        return {"available": False,
                "reason": f"eGFR cannot be computed: latest creatinine is older than {CREATININE_MAX_AGE_DAYS} days"}
    dob, sex = state.patient["dob"], state.patient["sex"]
    age = measured.year - dob.year - ((measured.month, measured.day) < (dob.month, dob.day))
    value = egfr_ckdepi_2021(float(latest["value_num"]), age, sex)
    return {"available": True, "value": value, "age": age, "sex": sex, "creatinine": latest}


def _persist_egfr(cur, state: PatientState, egfr: dict) -> None:
    """Store the computed value as a derived fact so it shows on trends with its inputs."""
    cur.execute("select id, dose->>'input_fact' as input_fact from facts where patient_id = %s and code = %s "
                "and created_by = 'system:metric' and state not in ('superseded','rejected')",
                (state.patient["id"], EGFR_LOINC))
    existing = cur.fetchall()
    current_input = str(egfr["creatinine"]["id"]) if egfr["available"] else None
    for row in existing:
        if row["input_fact"] != current_input:
            cur.execute("update facts set state = 'superseded' where id = %s", (row["id"],))
    if not egfr["available"] or any(r["input_fact"] == current_input for r in existing):
        return
    creatinine = egfr["creatinine"]
    cur.execute(
        """insert into facts(patient_id, encounter_id, fact_type, assertion, code_system, code, display,
                             raw_text, value_num, unit, dose, effective_at, state, confidence, source, created_by)
           values (%s, %s, 'lab_result', 'present', 'LOINC', %s, 'eGFR (CKD-EPI 2021)', %s, %s, %s, %s, %s,
                   'verified', 1, 'manual', 'system:metric')""",
        (state.patient["id"], creatinine["encounter_id"], EGFR_LOINC,
         f"computed from creatinine {float(creatinine['value_num']):g} mg/dL",
         egfr["value"], EGFR_UNIT,
         {"formula": "CKD-EPI 2021", "input_fact": str(creatinine["id"]),
          "inputs": {"creatinine_mg_dl": float(creatinine["value_num"]), "age": egfr["age"], "sex": egfr["sex"]}},
         _when(creatinine)))


# ---------------------------------------------------------------- rules

def _alert(rule: dict, severity: str, message: str, facts: list[dict], steps: list[dict], conclusion: str) -> dict:
    return {
        "rule_id": rule["id"], "severity": severity, "message": message,
        "trigger_fact_ids": [f["id"] for f in facts],
        "trace": {"rule": {"id": rule["id"], "title": rule["title"], "version": rule["version"],
                           "source": rule["guideline_source"]},
                  "steps": steps, "conclusion": conclusion},
    }


def rule_lab_contraindication(rule: dict, state: PatientState, ctx: dict) -> list[dict]:
    spec, steps, facts = rule["rule"], [], []
    for condition in spec.get("all", []):
        if "fact" in condition:
            wanted = condition["fact"]
            meds = state.meds_of(wanted["generic"])
            if not meds:
                return []
            med = meds[0]
            brand = (med["dose"] or {}).get("brand")
            mapping = f" (dictionary: {brand} → {wanted['generic']})" if brand and brand != wanted["generic"] else ""
            steps.append({"label": "Medication on list", "result": True, "fact_id": med["id"],
                          "evidence": _evidence(med) + mapping})
            facts.append(med)
        elif condition.get("metric") == "egfr":
            egfr = ctx["egfr"]
            if not egfr["available"]:
                ctx["notes"].append({"rule_id": rule["id"], "kind": "metric_unavailable", "message": egfr["reason"]})
                return []
            creatinine = egfr["creatinine"]
            steps.append({"label": "Computed eGFR", "value": egfr["value"], "unit": "mL/min/1.73 m²",
                          "formula": "CKD-EPI 2021",
                          "inputs": [{"name": "creatinine", "value": float(creatinine["value_num"]), "unit": "mg/dL",
                                      "fact_id": creatinine["id"], "source": _source(creatinine)},
                                     {"name": "age", "value": egfr["age"]}, {"name": "sex", "value": egfr["sex"]}]})
            passed = OPS[condition["op"]](egfr["value"], condition["value"])
            steps.append({"label": f"eGFR {condition['op']} {condition['value']}", "result": passed})
            if not passed:
                return []
            facts.append(creatinine)
    if not facts:
        return []
    message = spec.get("message") or rule["title"]
    return [_alert(rule, rule["severity"], message, facts, steps, message)]


def rule_interaction(rule: dict, state: PatientState, ctx: dict) -> list[dict]:
    floor = SEVERITY_ORDER.index(rule["rule"].get("min_severity", "moderate"))
    by_generic = {_generic(f): f for f in state.current_meds}
    alerts = []
    for a, b in combinations(sorted(by_generic), 2):
        row = ctx["interactions"].get((a, b))
        if not row or SEVERITY_ORDER.index(row["severity"]) < floor:
            continue
        pair = [by_generic[a], by_generic[b]]
        message = f"{row['severity'].capitalize()} interaction: {a} + {b} — {row['description']}"
        steps = [{"label": f"On current list: {g}", "result": True, "fact_id": f["id"], "evidence": _evidence(f)}
                 for g, f in zip((a, b), pair)]
        steps.append({"label": "Interaction table lookup", "result": True,
                      "evidence": f"{a} + {b}: {row['severity']} ({row['source']} {row['source_ref'] or ''})".strip()})
        alerts.append(_alert(rule, INTERACTION_SEVERITY[row["severity"]], message, pair, steps, message))
    return alerts


def rule_duplicate(rule: dict, state: PatientState, ctx: dict) -> list[dict]:
    alerts = []
    for generic in sorted({_generic(f) for f in state.current_meds}):
        products = state.meds_of(generic)
        if len(products) < 2:
            continue
        names = " + ".join(((f["dose"] or {}).get("brand") or generic).capitalize() for f in products)
        message = f"Duplicate therapy: {names} both contain {generic}"
        steps = [{"label": f"Contains {generic}", "result": True, "fact_id": f["id"], "evidence": _evidence(f)}
                 for f in products]
        alerts.append(_alert(rule, rule["severity"], message, products, steps, message))
    return alerts


def rule_dose(rule: dict, state: PatientState, ctx: dict) -> list[dict]:
    alerts = []
    for generic, limit in ctx["dose_limits"].items():
        products = state.meds_of(generic)
        dosed = [f for f in products if (f["dose"] or {}).get("daily_mg")]
        if not dosed:
            continue
        total = sum(f["dose"]["daily_mg"] for f in dosed)
        steps = [{"label": f"{(f['dose'].get('brand') or generic)}: {f['dose']['amount']:g} mg × {f['dose']['times_per_day']}/day",
                  "value": f["dose"]["daily_mg"], "unit": "mg/day", "fact_id": f["id"], "evidence": _evidence(f)}
                 for f in dosed]
        steps.append({"label": f"Total {generic} per day", "value": total, "unit": "mg/day"})
        exceeded = total > float(limit["max_daily_mg"])
        steps.append({"label": f"Total > {float(limit['max_daily_mg']):g} mg/day ({limit['source']})", "result": exceeded})
        if exceeded:
            message = (f"Daily dose exceeded: {generic} {total:g} mg/day is above the "
                       f"{float(limit['max_daily_mg']):g} mg/day limit")
            alerts.append(_alert(rule, rule["severity"], message, dosed, steps, message))
    return alerts


def rule_allergy(rule: dict, state: PatientState, ctx: dict) -> list[dict]:
    alerts, groups = [], ctx["allergy_groups"]
    for med in state.current_meds:
        generic = _generic(med)
        for allergy in state.allergies_present:
            substance = _generic(allergy)
            if substance == "*":
                continue
            shared = groups.get(generic) if groups.get(generic) and groups.get(generic) == groups.get(substance) else None
            if generic != substance and not shared:
                continue
            why = f"both belong to the {shared} group" if shared and generic != substance else "same substance"
            message = f"Allergy conflict: {generic} prescribed, but an allergy to {substance} is on record ({why})"
            steps = [{"label": "Allergy on record", "result": True, "fact_id": allergy["id"], "evidence": _evidence(allergy)},
                     {"label": "Medication on list", "result": True, "fact_id": med["id"], "evidence": _evidence(med)},
                     {"label": f"Cross-reactivity: {why}", "result": True}]
            alerts.append(_alert(rule, rule["severity"], message, [allergy, med], steps, message))
    return alerts


def rule_contradiction(rule: dict, state: PatientState, ctx: dict) -> list[dict]:
    """Only an explicit denial can contradict the record; "not mentioned" never does."""
    alerts, groups = [], ctx["allergy_groups"]

    def clash(present: dict, denied: dict, what: str) -> None:
        message = (f"Record contradiction: {what} is on record ({_when(present):%b %Y}) "
                   f"but was denied on {_when(denied):%d %b %Y}")
        steps = [{"label": "On record", "result": True, "fact_id": present["id"], "evidence": _evidence(present)},
                 {"label": "Later denied", "result": True, "fact_id": denied["id"], "evidence": _evidence(denied)},
                 {"label": "Both cannot be true — doctor must choose", "result": True}]
        alerts.append(_alert(rule, rule["severity"], message, [present, denied], steps, message))

    for present in state.allergies_present:
        substance = _generic(present)
        for denied in state.allergies_denied:
            if _when(denied) <= _when(present):
                continue
            other = _generic(denied)
            same_group = groups.get(substance) and groups.get(substance) == groups.get(other)
            if other == "*" or other == substance or same_group:
                clash(present, denied, f"{substance} allergy")
                break
    by_code = lambda kind, assertion: [f for f in state.facts if f["fact_type"] == kind
                                       and f["assertion"] == assertion and f["code"]]
    for present in by_code("diagnosis", "present"):
        for denied in by_code("diagnosis", "denied"):
            if denied["code"] == present["code"] and _when(denied) > _when(present):
                clash(present, denied, present["display"])
                break
    return alerts


RULE_TYPES = {
    "lab_contraindication": rule_lab_contraindication,
    "interaction": rule_interaction,
    "duplicate": rule_duplicate,
    "dose": rule_dose,
    "allergy": rule_allergy,
    "contradiction": rule_contradiction,
}


# ---------------------------------------------------------------- entry point

def load_state(cur, patient_id) -> Optional[PatientState]:
    cur.execute("select id, dob, sex, full_name from patients where id = %s", (patient_id,))
    patient = cur.fetchone()
    if not patient:
        return None
    cur.execute(
        """select f.*, d.original_name as document_name from facts f
           left join source_documents d on d.id = f.document_id
           where f.patient_id = %s and f.state in ('verified','clinician_confirmed')""", (patient_id,))
    return PatientState(patient, cur.fetchall())


def evaluate(cur, patient_id, encounter_id=None, dry_run: bool = False) -> dict:
    """Run every active rule for one patient. Idempotent: re-running never duplicates alerts.

    Returns {"fired": [...], "notes": [...]}; notes explain rules that could not be
    evaluated (e.g. eGFR unavailable) so "no alert" is never mistaken for "safe".
    """
    state = load_state(cur, patient_id)
    if state is None:
        return {"fired": [], "notes": []}
    egfr = compute_egfr(state)
    if not dry_run:
        _persist_egfr(cur, state, egfr)

    cur.execute("select drug_a, drug_b, severity, description, source, source_ref from drug_interactions")
    interactions = {(r["drug_a"], r["drug_b"]): r for r in cur.fetchall()}
    cur.execute("select generic, max_daily_mg, source from dose_limits where route = 'PO' and population = 'adult'")
    dose_limits = {r["generic"]: r for r in cur.fetchall()}
    cur.execute("select member_generic, group_name from allergy_groups")
    allergy_groups = {r["member_generic"]: r["group_name"] for r in cur.fetchall()}
    ctx = {"egfr": egfr, "interactions": interactions, "dose_limits": dose_limits,
           "allergy_groups": allergy_groups, "notes": []}

    cur.execute("select * from safety_rules where active order by id")
    fired = []
    for rule in cur.fetchall():
        handler = RULE_TYPES.get(rule["rule_type"])
        if handler:
            fired.extend(handler(rule, state, ctx))
    for alert in fired:
        alert["dedupe_key"] = alert["rule_id"] + ":" + ",".join(sorted(str(i) for i in alert["trigger_fact_ids"]))
    if dry_run:
        return {"fired": fired, "notes": ctx["notes"]}

    for alert in fired:
        cur.execute(
            """insert into safety_alerts(patient_id, encounter_id, rule_id, severity, message, status,
                                         trigger_fact_ids, trace, dedupe_key)
               values (%s, %s, %s, %s, %s, 'open', %s::uuid[], %s, %s)
               on conflict (patient_id, dedupe_key) where status <> 'resolved' do nothing""",
            (patient_id, encounter_id, alert["rule_id"], alert["severity"], alert["message"],
             [str(i) for i in alert["trigger_fact_ids"]], alert["trace"], alert["dedupe_key"]))
    # an open alert whose condition no longer holds (e.g. a fact was rejected) closes itself
    live_keys = [a["dedupe_key"] for a in fired]
    cur.execute(
        """update safety_alerts set status = 'resolved', resolved_at = now(),
                  override_reason = 'auto-resolved: the triggering condition no longer holds'
           where patient_id = %s and status = 'open' and not (dedupe_key = any(%s::text[]))""",
        (patient_id, live_keys))
    if fired:
        logger.info("Patient %s: %d alert(s) active", patient_id, len(fired))
    return {"fired": fired, "notes": ctx["notes"]}
