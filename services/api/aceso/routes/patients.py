"""Patient list, chart, timeline, trends, search and gap prompts (all deterministic reads)."""
import re
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from aceso.auth import any_role, clinical
from aceso.db import audit, tx
from aceso.extraction.terminology import Terminology
from aceso.pipeline import ensure_encounter
from aceso.safety import engine

router = APIRouter()

NEVER_COLLAPSE = ("allergy", "medication")
COLLAPSE_CONFIDENCE = 0.90
TREND_LOINCS = ["4548-4", "2160-0", "62238-1", "1558-6", "8480-6", "8462-4"]
STOPWORDS = set("a an and any are about did do does for from had has have he her his in is it last latest me of on "
                "or she show tell the their there this to was what when which with patient".split())
FACT_COLUMNS = """f.id, f.patient_id, f.encounter_id, f.fact_type::text as fact_type, f.assertion::text as assertion,
    f.code_system, f.code, f.display, f.raw_text, f.value_num, f.value_text, f.unit, f.dose, f.effective_at,
    f.state::text as state, f.confidence, f.confidence_parts, f.needs_attention, f.attention_reasons,
    f.source::text as source, f.recording_id, f.segment_ids, f.audio_start_ms, f.audio_end_ms, f.document_id,
    f.block_ids, f.page_no, f.bbox, f.verification, f.created_by, f.created_at,
    d.original_name as document_name"""


def age_on(dob: date, when: date | None = None) -> int:
    when = when or date.today()
    return when.year - dob.year - ((when.month, when.day) < (dob.month, dob.day))


def collapsible(fact: dict) -> bool:
    """Only high-confidence verified facts may be hidden; allergies and medications never are."""
    return (fact["state"] == "verified" and (fact["confidence"] or 0) >= COLLAPSE_CONFIDENCE
            and not fact["needs_attention"] and fact["fact_type"] not in NEVER_COLLAPSE)


@router.get("/patients")
def list_patients(user: dict = Depends(any_role)):
    with tx() as cur:
        cur.execute(
            """select p.id, p.mrn, p.full_name, p.dob, p.sex, p.preferred_lang,
                      (select count(*) from safety_alerts a where a.patient_id = p.id and a.status = 'open') as open_alerts,
                      (select count(*) from facts f where f.patient_id = p.id and f.state = 'extracted') as unverified,
                      (select count(*) from open_loops_v o where o.patient_id = p.id and o.overdue) as overdue_loops
               from patients p order by p.mrn""")
        patients = cur.fetchall()
        cur.execute(
            """select o.id, o.description, o.due_date, p.id as patient_id, p.full_name as patient_name
               from open_loops_v o join patients p on p.id = o.patient_id where o.overdue order by o.due_date""")
        overdue = cur.fetchall()
    for p in patients:
        p["age"] = age_on(p["dob"])
        if user["role"] == "admin":  # admins see demographics only
            p.update(open_alerts=None, unverified=None, overdue_loops=None)
    return {"patients": patients, "overdue_loops": [] if user["role"] == "admin" else overdue}


@router.post("/patients/{patient_id}/encounters")
def start_encounter(patient_id: str, user: dict = Depends(clinical)):
    with tx(user) as cur:
        encounter_id = ensure_encounter(cur, patient_id, user)
    return {"encounter_id": encounter_id}


@router.get("/patients/{patient_id}/chart")
def chart(patient_id: str, user: dict = Depends(clinical)):
    with tx() as cur:
        cur.execute("select * from patients where id = %s", (patient_id,))
        patient = cur.fetchone()
        if not patient:
            raise HTTPException(404, "Patient not found")
        patient["age"] = age_on(patient["dob"])

        cur.execute("select * from encounters where patient_id = %s order by started_at desc", (patient_id,))
        encounters = cur.fetchall()
        encounter = encounters[0] if encounters else None

        cur.execute(f"""select {FACT_COLUMNS} from facts f left join source_documents d on d.id = f.document_id
                        where f.patient_id = %s and f.state <> 'superseded'
                        order by f.effective_at desc nulls last, f.created_at desc""", (patient_id,))
        facts = cur.fetchall()
        for fact in facts:
            fact["collapsible"] = collapsible(fact)
            fact["current_encounter"] = bool(encounter and fact["encounter_id"] == encounter["id"])

        cur.execute("""select a.*, r.title as rule_title from safety_alerts a left join safety_rules r on r.id = a.rule_id
                       where a.patient_id = %s
                       order by case a.severity when 'critical' then 0 when 'high' then 1 when 'moderate' then 2 else 3 end,
                                a.created_at desc""", (patient_id,))
        alerts = cur.fetchall()

        note = None
        if encounter:
            cur.execute("select * from soap_notes where encounter_id = %s order by version desc limit 1",
                        (encounter["id"],))
            note = cur.fetchone()

        cur.execute("select id, original_name, kind, doc_date, page_count, status, error, encounter_id, created_at "
                    "from source_documents where patient_id = %s order by created_at desc", (patient_id,))
        documents = cur.fetchall()
        cur.execute("""select r.id, r.original_name, r.duration_ms, r.language, r.status, r.error, r.encounter_id
                       from audio_recordings r join encounters e on e.id = r.encounter_id
                       where e.patient_id = %s order by r.created_at desc""", (patient_id,))
        recordings = cur.fetchall()
        cur.execute("select * from open_loops_v where patient_id = %s order by due_date", (patient_id,))
        loops = cur.fetchall()
        cur.execute("select id, kind, status::text as status, stage, error, result, payload->>'filename' as filename "
                    "from jobs where patient_id = %s and created_at > now() - interval '15 minutes' "
                    "order by created_at desc limit 5", (patient_id,))
        jobs = cur.fetchall()
        notes = engine.evaluate(cur, patient_id, dry_run=True)["notes"]

    trusted = [f for f in facts if f["state"] in ("verified", "clinician_confirmed")]
    summary = {
        "problems": [f for f in trusted if f["fact_type"] == "diagnosis" and f["assertion"] == "present"],
        "medications": [f for f in trusted if f["fact_type"] == "medication" and f["assertion"] == "present"],
        "allergies": [f for f in trusted if f["fact_type"] == "allergy"],
        "unverified_not_shown": sum(1 for f in facts if f["state"] == "extracted"),
    }
    return {
        "patient": patient, "encounters": encounters, "encounter": encounter, "facts": facts,
        "alerts": alerts, "note": note, "documents": documents, "recordings": recordings,
        "open_loops": loops, "jobs": jobs, "summary": summary, "safety_notes": notes,
        "gaps": gaps_for(encounter, facts, loops) if encounter else [],
        # never imply "no alerts = safe" while unverified facts exist
        "unverified_count": sum(1 for f in facts if f["state"] == "extracted"),
        "viewer": {"role": user["role"], "name": user["full_name"]},
    }


def gaps_for(encounter: dict, facts: list[dict], loops: list[dict]) -> list[dict]:
    """Live gap prompts: what this consult has not captured yet. Deterministic checklist."""
    here = [f for f in facts if f["encounter_id"] == encounter["id"] and f["state"] != "rejected"]
    has = lambda *kinds: any(f["fact_type"] in kinds for f in here)
    items = [
        ("chief_complaint", "Chief complaint", has("symptom", "history") or encounter["chief_complaint"] not in (None, "", "Visit")),
        ("allergies", "Allergies asked", has("allergy")),
        ("medications", "Current medications reviewed", has("medication")),
        ("vitals", "Vitals recorded", has("vital")),
        ("plan", "Follow-up plan stated", has("plan_item")),
    ]
    gaps = [{"key": key, "label": label, "status": "captured" if done else "missing", "detail": None}
            for key, label, done in items]
    for loop in loops:
        if loop["status"] == "open":
            gaps.append({"key": f"loop:{loop['id']}", "label": "Pending from last visit",
                         "status": "pending_from_history",
                         "detail": f"{loop['description']} (due {loop['due_date']:%d %b %Y})"})
    return gaps


@router.get("/patients/{patient_id}/timeline")
def timeline(patient_id: str, user: dict = Depends(clinical)):
    with tx() as cur:
        cur.execute("select at, kind, ref_id, title, state from patient_timeline_v where patient_id = %s "
                    "order by at desc nulls last", (patient_id,))
        return {"events": cur.fetchall()}


@router.get("/patients/{patient_id}/trends")
def trends(patient_id: str, user: dict = Depends(clinical)):
    """One series per lab with points, reference band, medication markers and a deterministic summary."""
    with tx() as cur:
        term = Terminology.load(cur)
        cur.execute("select sex from patients where id = %s", (patient_id,))
        patient = cur.fetchone()
        if not patient:
            raise HTTPException(404, "Patient not found")
        cur.execute(
            """select id, code, display, value_num, unit, effective_at, state::text as state from facts
               where patient_id = %s and code = any(%s) and value_num is not null and assertion = 'present'
                 and state in ('verified','clinician_confirmed') order by effective_at""", (patient_id, TREND_LOINCS))
        points = cur.fetchall()
        cur.execute(
            """select display, effective_at, assertion::text as assertion from facts
               where patient_id = %s and fact_type = 'medication' and state in ('verified','clinician_confirmed')
               order by effective_at""", (patient_id,))
        meds = cur.fetchall()
    series = []
    for loinc in TREND_LOINCS:
        rows = [p for p in points if p["code"] == loinc]
        if not rows:
            continue
        limits = term.reference_range(loinc, patient["sex"])
        low = float(limits["low"]) if limits and limits["low"] is not None else None
        high = float(limits["high"]) if limits and limits["high"] is not None else None
        first, last = rows[0], rows[-1]
        name, unit = last["display"], last["unit"] or ""
        if len(rows) == 1:
            text = f"{name} {float(last['value_num']):g} {unit} (single measurement)"
        else:
            delta = float(last["value_num"]) - float(first["value_num"])
            months = max(1, round((last["effective_at"] - first["effective_at"]).days / 30))
            verb = "was stable at" if abs(delta) < 1e-9 else ("fell from" if delta < 0 else "rose from")
            text = (f"{name} was stable at {float(last['value_num']):g} {unit} over {months} months" if verb == "was stable at"
                    else f"{name} {verb} {float(first['value_num']):g} to {float(last['value_num']):g} {unit} over {months} months")
        value = float(last["value_num"])
        out_of_range = (low is not None and value < low) or (high is not None and value > high)
        if out_of_range:
            text += "; latest value is outside the reference range"
        series.append({"loinc": loinc, "name": name, "unit": unit, "range": {"low": low, "high": high},
                       "points": [{"at": p["effective_at"], "value": float(p["value_num"]), "fact_id": p["id"],
                                   "state": p["state"]} for p in rows],
                       "summary": text.strip(), "latest_out_of_range": out_of_range})
    events = [{"at": m["effective_at"], "type": "med_stop" if m["assertion"] == "denied" else "med_start",
               "label": m["display"]} for m in meds if m["effective_at"]]
    return {"series": series, "events": events}


class SearchRequest(BaseModel):
    q: str


@router.post("/patients/{patient_id}/search")
def search(patient_id: str, req: SearchRequest, user: dict = Depends(clinical)):
    """Citation-only search over the fact store. Structured and lexical; never a generated guess."""
    with tx(user) as cur:
        term = Terminology.load(cur)
        cur.execute(f"""select {FACT_COLUMNS} from facts f left join source_documents d on d.id = f.document_id
                        where f.patient_id = %s and f.state in ('verified','clinician_confirmed','extracted')""",
                    (patient_id,))
        facts = cur.fetchall()
        audit(cur, "search.query", "patient", patient_id, patient_id, {"q": req.q}, user)

    query = req.q.lower()
    tokens = [t for t in re.findall(r"[a-z0-9]+", query) if t not in STOPWORDS and len(t) > 1]
    # expand through our dictionaries: "sugar" -> E11, "glycomet" -> metformin, "sulfa" -> its allergy group
    codes = {c["code"] for c in term.concepts
             if any(re.search(rf"\b{re.escape(s.lower())}\b", query) for s in [c["display"], *c["synonyms"]])}
    drug = term.match_drug(query)
    generics = {drug["generic"]} if drug else set()
    groups = {term.allergy_group(t) for t in tokens} - {None}
    wants = {kind for kind, words in {"allergy": ("allergy", "allergic", "allergies"),
                                      "medication": ("medication", "medications", "medicine", "drug", "drugs", "taking"),
                                      "lab_result": ("lab", "labs", "result", "results"),
                                      "diagnosis": ("diagnosis", "diagnoses", "condition", "problem")}.items()
             if any(w in tokens for w in words)}

    scored = []
    for fact in facts:
        haystack = f"{fact['display']} {fact['raw_text'] or ''} {fact['value_text'] or ''}".lower()
        score = sum(1 for t in tokens if re.search(rf"\b{re.escape(t)}", haystack))
        score += 3 if fact["code"] in codes else 0
        score += 3 if (fact["value_text"] or "").lower() in generics else 0
        score += 3 if (fact["dose"] or {}).get("group") in groups and groups else 0
        if fact["fact_type"] in wants:
            score += 2 if score or len(tokens) <= 2 else 0
            # a blanket "no allergies" answers any allergy question
            score += 2 if fact["value_text"] == "*" else 0
        if score:
            scored.append((score + (0.5 if fact["state"] != "extracted" else 0), fact))
    scored.sort(key=lambda pair: (pair[0], pair[1]["effective_at"] or pair[1]["created_at"]), reverse=True)
    evidence = [fact for _, fact in scored[:8]]
    if not evidence:
        return {"answer": "No supporting record found in this patient's chart.", "evidence": []}
    return {"answer": " ".join(f"{describe(f)} [{i}]" for i, f in enumerate(evidence[:3], start=1)),
            "evidence": evidence}


def describe(fact: dict) -> str:
    when = f"{fact['effective_at']:%d %b %Y}" if fact["effective_at"] else "undated"
    status = "unverified" if fact["state"] == "extracted" else fact["state"].replace("_", " ")
    if fact["assertion"] == "denied":
        what = "Any allergy" if fact["value_text"] == "*" else fact["display"]
        body = f"{what}: explicitly denied"
    elif fact["value_num"] is not None and fact["fact_type"] in ("lab_result", "vital"):
        body = f"{fact['display']} {float(fact['value_num']):g} {fact['unit'] or ''}".strip()
    else:
        body = f"{fact['fact_type'].replace('_', ' ').capitalize()}: {fact['display']}"
    return f"{body} ({when}, {status})."
