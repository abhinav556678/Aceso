"""Exports of a signed encounter: FHIR R4 bundle and the templated patient-facing summary.

Only `clinician_confirmed` facts leave the system. The patient summary is built
from structured data through fixed per-language templates; no model translates it.
Translations below need review by a native speaker and a clinician before real use.
"""
import html
import uuid
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse

from aceso.auth import clinical
from aceso.db import audit, tx

router = APIRouter()
TEMPLATE_VERSION = "patient-summary-v1"

CODE_SYSTEMS = {"LOINC": "http://loinc.org", "RxNorm": "http://www.nlm.nih.gov/research/umls/rxnorm",
                "ICD10": "http://hl7.org/fhir/sid/icd-10"}

LABELS = {
    "en": {"title": "Your Visit Summary", "patient": "Patient", "date": "Visit date", "doctor": "Doctor",
           "medicines": "Your medicines", "name": "Medicine", "dose": "Dose", "when": "When to take",
           "allergies": "Allergies on record", "followups": "Follow-up", "due": "due", "none": "None",
           "footer": "Prepared from your doctor's verified record on {date}. Ask your doctor if anything is unclear."},
    "ta": {"title": "உங்கள் வருகை சுருக்கம்", "patient": "நோயாளி", "date": "வருகை தேதி", "doctor": "மருத்துவர்",
           "medicines": "உங்கள் மருந்துகள்", "name": "மருந்து", "dose": "அளவு", "when": "எப்போது எடுக்க வேண்டும்",
           "allergies": "பதிவில் உள்ள ஒவ்வாமைகள்", "followups": "பின்தொடர்தல்", "due": "தேதி", "none": "இல்லை",
           "footer": "உங்கள் மருத்துவர் சரிபார்த்த பதிவிலிருந்து {date} அன்று தயாரிக்கப்பட்டது. ஏதேனும் புரியவில்லை என்றால் உங்கள் மருத்துவரிடம் கேளுங்கள்."},
    "hi": {"title": "आपकी विज़िट का सारांश", "patient": "मरीज़", "date": "विज़िट की तारीख", "doctor": "डॉक्टर",
           "medicines": "आपकी दवाएं", "name": "दवा", "dose": "खुराक", "when": "कब लेनी है",
           "allergies": "दर्ज एलर्जी", "followups": "अगली जांच", "due": "तारीख", "none": "कोई नहीं",
           "footer": "आपके डॉक्टर के सत्यापित रिकॉर्ड से {date} को तैयार किया गया। कुछ समझ न आए तो अपने डॉक्टर से पूछें।"},
}
# Frequencies come from this lookup table, never from free text.
FREQUENCY = {
    "OD": {"en": "Once a day", "ta": "தினமும் ஒரு முறை", "hi": "दिन में एक बार"},
    "BD": {"en": "Twice a day", "ta": "தினமும் இரண்டு முறை", "hi": "दिन में दो बार"},
    "TDS": {"en": "Three times a day", "ta": "தினமும் மூன்று முறை", "hi": "दिन में तीन बार"},
    "QID": {"en": "Four times a day", "ta": "தினமும் நான்கு முறை", "hi": "दिन में चार बार"},
    "HS": {"en": "At bedtime", "ta": "இரவு படுக்கும் முன்", "hi": "रात को सोते समय"},
    "SOS": {"en": "Only when needed", "ta": "தேவைப்படும் போது மட்டும்", "hi": "केवल ज़रूरत पड़ने पर"},
}
FREQUENCY_ALIASES = {"BID": "BD", "TID": "TDS", "QDS": "QID", "QD": "OD"}


def _signed_encounter(cur, encounter_id: str) -> dict:
    cur.execute(
        """select e.id, e.started_at, e.status, p.id as patient_id, p.full_name, p.dob, p.sex, p.mrn,
                  p.preferred_lang, d.full_name as doctor_name, d.registration_no, d.id as doctor_id
           from encounters e join patients p on p.id = e.patient_id left join profiles d on d.id = e.doctor_id
           where e.id = %s""", (encounter_id,))
    encounter = cur.fetchone()
    if not encounter:
        raise HTTPException(404, "Encounter not found")
    if encounter["status"] != "signed":
        raise HTTPException(409, "Only a signed encounter can be exported. Sign off first.")
    cur.execute("select * from facts where encounter_id = %s and state = 'clinician_confirmed' "
                "order by fact_type, created_at", (encounter_id,))
    encounter["facts"] = cur.fetchall()
    return encounter


# ------------------------------------------------------------ patient summary

def build_payload(cur, encounter: dict) -> dict:
    meds = []
    for fact in encounter["facts"]:
        if fact["fact_type"] != "medication" or fact["assertion"] != "present":
            continue
        dose = fact["dose"] or {}
        freq = (dose.get("freq") or "").upper()
        meds.append({"generic": fact["value_text"] or fact["display"], "display_name": dose.get("brand"),
                     "dose_amount": dose.get("amount"), "dose_unit": dose.get("unit"),
                     "freq": FREQUENCY_ALIASES.get(freq, freq) or None})
    allergies = [f["display"] for f in encounter["facts"]
                 if f["fact_type"] == "allergy" and f["assertion"] == "present" and f["value_text"] != "*"]
    cur.execute("select description, due_date from open_loops where encounter_id = %s and status = 'open' "
                "order by due_date", (encounter["id"],))
    followups = [{"task": r["description"], "due": r["due_date"].isoformat()} for r in cur.fetchall()]
    return {"patient": {"name": encounter["full_name"], "mrn": encounter["mrn"]},
            "visit_date": encounter["started_at"].date().isoformat(), "doctor": encounter["doctor_name"],
            "medications": meds, "allergies": allergies, "followups": followups}


def render_summary(payload: dict, lang: str) -> str:
    t, e = LABELS[lang], html.escape
    rows = []
    for med in payload["medications"]:
        name = e(med["generic"].capitalize()) + (f" ({e(med['display_name'].capitalize())})"
                                                 if med["display_name"] and med["display_name"] != med["generic"] else "")
        dose = f"{med['dose_amount']:g} {e(med['dose_unit'] or '')}" if med["dose_amount"] is not None else "—"
        when = FREQUENCY[med["freq"]][lang] if med["freq"] in FREQUENCY else "—"
        rows.append(f"<tr><td>{name}</td><td class='dose'>{dose}</td><td>{when}</td></tr>")
    med_table = (f"<table><tr><th>{t['name']}</th><th>{t['dose']}</th><th>{t['when']}</th></tr>{''.join(rows)}</table>"
                 if rows else f"<p>{t['none']}</p>")
    allergies = "".join(f"<li>{e(a)}</li>" for a in payload["allergies"]) or f"<li>{t['none']}</li>"
    followups = "".join(f"<li>{e(f['task'])} — {t['due']}: {f['due']}</li>" for f in payload["followups"]) \
        or f"<li>{t['none']}</li>"
    return f"""<!DOCTYPE html>
<html lang="{lang}"><head><meta charset="utf-8"><title>{t['title']}</title>
<style>
  body {{ font-family: 'Noto Sans', 'Noto Sans Tamil', 'Noto Sans Devanagari', 'Nirmala UI', sans-serif;
         font-size: 18px; line-height: 1.5; max-width: 720px; margin: 32px auto; color: #0f172a; }}
  h1 {{ font-size: 28px; }} h2 {{ font-size: 20px; border-bottom: 1px solid #cbd5e1; padding-bottom: 4px; margin-top: 28px; }}
  table {{ border-collapse: collapse; width: 100%; }} th, td {{ border: 1px solid #cbd5e1; padding: 8px 10px; text-align: left; }}
  footer {{ margin-top: 36px; font-size: 14px; color: #475569; }}
  @media print {{ button {{ display: none; }} }}
</style></head><body>
<h1>{t['title']}</h1>
<p><b>{t['patient']}:</b> {e(payload['patient']['name'])} ({e(payload['patient']['mrn'])})<br>
<b>{t['date']}:</b> {payload['visit_date']}<br><b>{t['doctor']}:</b> {e(payload['doctor'] or '—')}</p>
<h2>{t['medicines']}</h2>{med_table}
<h2>{t['allergies']}</h2><ul>{allergies}</ul>
<h2>{t['followups']}</h2><ul>{followups}</ul>
<footer>{t['footer'].format(date=date.today().isoformat())}</footer>
<p><button onclick="window.print()">Print</button></p>
</body></html>"""


def round_trip_ok(payload: dict, rendered: str) -> bool:
    """Every dose, frequency and follow-up date in the payload must be present in the output."""
    for med in payload["medications"]:
        if med["dose_amount"] is not None and f"{med['dose_amount']:g}" not in rendered:
            return False
    return all(f["due"] in rendered for f in payload["followups"])


@router.get("/encounters/{encounter_id}/patient-summary", response_class=HTMLResponse)
def patient_summary(encounter_id: str, lang: str = "", user: dict = Depends(clinical)):
    with tx(user) as cur:
        encounter = _signed_encounter(cur, encounter_id)
        lang = lang if lang in LABELS else (encounter["preferred_lang"] if encounter["preferred_lang"] in LABELS else "en")
        payload = build_payload(cur, encounter)
        rendered = render_summary(payload, lang)
        if not round_trip_ok(payload, rendered):
            raise HTTPException(500, "Patient summary failed its round-trip check and was not produced.")
        cur.execute("insert into patient_exports(encounter_id, lang, template_version, payload, rendered_html) "
                    "values (%s, %s, %s, %s, %s)", (encounter_id, lang, TEMPLATE_VERSION, payload, rendered))
        audit(cur, "export.patient_summary", "encounter", encounter_id, encounter["patient_id"], {"lang": lang}, user)
    return rendered


# ------------------------------------------------------------ FHIR

def _codeable(fact: dict) -> dict:
    concept = {"text": fact["display"]}
    if fact["code"] and fact["code_system"] in CODE_SYSTEMS:
        concept["coding"] = [{"system": CODE_SYSTEMS[fact["code_system"]], "code": fact["code"],
                              "display": fact["display"]}]
    return concept


def _resource(fact: dict, patient_ref: dict, encounter_ref: dict) -> dict | None:
    kind, base = fact["fact_type"], {"id": str(fact["id"])}
    denied = fact["assertion"] == "denied"
    if kind in ("lab_result", "vital"):
        if denied or fact["value_num"] is None:
            return None
        resource = {"resourceType": "Observation", "status": "final", "code": _codeable(fact),
                    "subject": patient_ref, "encounter": encounter_ref,
                    "valueQuantity": {"value": float(fact["value_num"]), "unit": fact["unit"] or ""}}
        if fact["effective_at"]:
            resource["effectiveDateTime"] = fact["effective_at"].isoformat()
    elif kind == "diagnosis":
        resource = {"resourceType": "Condition", "code": _codeable(fact), "subject": patient_ref,
                    "encounter": encounter_ref,
                    "verificationStatus": {"coding": [{
                        "system": "http://terminology.hl7.org/CodeSystem/condition-ver-status",
                        "code": "refuted" if denied else "confirmed"}]}}
        if not denied:
            resource["clinicalStatus"] = {"coding": [{
                "system": "http://terminology.hl7.org/CodeSystem/condition-clinical", "code": "active"}]}
    elif kind == "medication":
        dose = fact["dose"] or {}
        resource = {"resourceType": "MedicationStatement", "status": "not-taken" if denied else "active",
                    "medicationCodeableConcept": _codeable(fact), "subject": patient_ref, "context": encounter_ref}
        if dose.get("amount") is not None and not denied:
            text = f"{dose['amount']:g} {dose.get('unit', 'mg')} {dose.get('freq', '')}".strip()
            resource["dosage"] = [{"text": text}]
    elif kind == "allergy":
        if fact["value_text"] == "*":
            if not denied:
                return None
            code = {"coding": [{"system": "http://snomed.info/sct", "code": "716186003",
                                "display": "No known allergy"}], "text": "No known allergy"}
        else:
            code = _codeable(fact)
        resource = {"resourceType": "AllergyIntolerance", "code": code, "patient": patient_ref,
                    "encounter": encounter_ref,
                    "verificationStatus": {"coding": [{
                        "system": "http://terminology.hl7.org/CodeSystem/allergyintolerance-verification",
                        "code": "refuted" if denied and fact["value_text"] != "*" else "confirmed"}]}}
        if not denied or fact["value_text"] == "*":
            resource["clinicalStatus"] = {"coding": [{
                "system": "http://terminology.hl7.org/CodeSystem/allergyintolerance-clinical", "code": "active"}]}
    else:
        return None
    # provenance travels with the record
    provenance = {k: fact[k] for k in ("source", "page_no", "bbox", "audio_start_ms", "audio_end_ms") if fact[k] is not None}
    resource["meta"] = {"tag": [{"system": "https://aceso.demo/provenance", "code": str(provenance.get("source")),
                                 "display": str(provenance)}]}
    return {**base, **resource}


@router.get("/encounters/{encounter_id}/fhir")
def fhir_bundle(encounter_id: str, user: dict = Depends(clinical)):
    """FHIR R4 document bundle of the signed encounter. Not yet validated against ABDM profiles."""
    with tx(user) as cur:
        encounter = _signed_encounter(cur, encounter_id)
        cur.execute("select subjective, objective, assessment, plan, signed_at, content_hash from soap_notes "
                    "where encounter_id = %s and status = 'signed' order by version desc limit 1", (encounter_id,))
        note = cur.fetchone() or {}
        audit(cur, "export.fhir", "encounter", encounter_id, encounter["patient_id"], {}, user)

    now = datetime.now(timezone.utc).isoformat()
    patient_ref = {"reference": f"urn:uuid:{encounter['patient_id']}"}
    encounter_ref = {"reference": f"urn:uuid:{encounter_id}"}
    entries = [
        {"resourceType": "Patient", "id": str(encounter["patient_id"]),
         "identifier": [{"system": "https://aceso.demo/mrn", "value": encounter["mrn"]}],
         "name": [{"text": encounter["full_name"]}],
         "gender": {"M": "male", "F": "female"}.get(encounter["sex"], "other"),
         "birthDate": encounter["dob"].isoformat()},
        {"resourceType": "Encounter", "id": str(encounter_id), "status": "finished",
         "class": {"system": "http://terminology.hl7.org/CodeSystem/v3-ActCode", "code": "AMB"},
         "subject": patient_ref, "period": {"start": encounter["started_at"].isoformat()}},
    ]
    author = {"display": encounter["doctor_name"] or "Unknown"}
    if encounter["doctor_id"]:
        entries.append({"resourceType": "Practitioner", "id": str(encounter["doctor_id"]),
                        "name": [{"text": encounter["doctor_name"]}],
                        "identifier": [{"system": "https://aceso.demo/registration", "value": encounter["registration_no"]}]})
        author = {"reference": f"urn:uuid:{encounter['doctor_id']}"}
    clinical_entries = [r for r in (_resource(f, patient_ref, encounter_ref) for f in encounter["facts"]) if r]
    sections = [{"title": title, "text": {"status": "generated", "div": "<div xmlns=\"http://www.w3.org/1999/xhtml\">"
                 + "".join(f"<p>{html.escape(s['text'])}</p>" for s in (note.get(key) or [])) + "</div>"},
                 "entry": [{"reference": f"urn:uuid:{fid}"} for s in (note.get(key) or []) for fid in s["fact_ids"]
                           if any(r["id"] == fid for r in clinical_entries)]}
                for title, key in (("Subjective", "subjective"), ("Objective", "objective"),
                                   ("Assessment", "assessment"), ("Plan", "plan"))]
    composition = {"resourceType": "Composition", "id": str(uuid.uuid4()), "status": "final",
                   "type": {"coding": [{"system": "http://loinc.org", "code": "34108-1", "display": "Outpatient Note"}]},
                   "subject": patient_ref, "encounter": encounter_ref, "date": now, "author": [author],
                   "title": "OP Consultation Record", "section": sections,
                   "extension": [{"url": "https://aceso.demo/content-hash", "valueString": note.get("content_hash")}]}
    return {"resourceType": "Bundle", "id": str(uuid.uuid4()), "type": "document", "timestamp": now,
            "entry": [{"fullUrl": f"urn:uuid:{r['id']}", "resource": r}
                      for r in [composition, *entries, *clinical_entries]]}
