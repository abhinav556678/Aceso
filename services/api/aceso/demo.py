"""Synthetic demo data: the six planted scenarios from the build guide.

Each scenario's PDFs and transcripts are generated here and pushed through the
real pipeline (perception, normalisation, verification, safety, SOAP) with a
scripted stand-in for the language model, so seeding is deterministic and needs
no API key. Alerts are produced by the safety engine, never hand-written.

All patients are fictional.
"""
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import pymupdf as fitz

from aceso.config import REPO_ROOT
from aceso.db import tx
from aceso.pipeline import create_job, run_job
from aceso.routes import review

SAMPLES_DIR = REPO_ROOT / "data" / "synthetic"
PATIENT = "00000000-0000-4000-8000-00000000000{}"
COLUMNS = (60, 300, 380, 450)


def make_pdf(title: str, patient: dict, when: date, rows: list) -> bytes:
    """A one-page clinic document. `rows` are strings or tuples of table cells."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((60, 70), "ACESO Demo Clinic (synthetic data)", fontsize=10, color=(0.4, 0.4, 0.4))
    page.insert_text((60, 100), title, fontsize=17)
    page.insert_text((60, 130), f"Patient: {patient['full_name']}", fontsize=11)
    page.insert_text((330, 130), f"MRN: {patient['mrn']}", fontsize=11)
    page.insert_text((60, 150), f"Date: {when:%d %b %Y}", fontsize=11)
    y = 195
    for row in rows:
        cells = (row,) if isinstance(row, str) else row
        for x, cell in zip(COLUMNS, cells):
            page.insert_text((x, y), cell, fontsize=11)
        y += 24
    return doc.tobytes()


def lab_report(patient: dict, when: date, results: list[tuple]) -> bytes:
    return make_pdf("Laboratory Report", patient, when, [("Test", "Result", "Unit", "Reference range"), *results])


class ScriptedLLM:
    """Stands in for the model during seeding: returns the scenario's known facts.

    Each scripted fact names the text it comes from (`find`); the evidence id is
    resolved from the packet exactly as a real model would cite it.
    """
    id = "scripted:demo-seed"

    def __init__(self, facts: list[dict]):
        self.facts = facts

    def extract_json(self, system: str, user: str) -> dict:
        units = re.findall(r'^\[([BS]\d+)\] \([^)]*\) "(.*)"$', user, flags=re.M)
        out = []
        for fact in self.facts:
            unit_id = next((uid for uid, text in units if fact["find"].lower() in text.lower()), None)
            if unit_id:
                out.append({"assertion": "present", **{k: v for k, v in fact.items() if k != "find"},
                            "evidence_ids": [unit_id]})
        return {"facts": out}


def med(find: str, name: str, raw: str, **extra) -> dict:
    return {"find": find, "fact_type": "medication", "name": name, "raw_text": raw, **extra}


def lab(name: str, value: float, unit: str) -> dict:
    return {"find": name, "fact_type": "lab_result", "name": name, "raw_text": f"{name} {value:g} {unit}",
            "value_num": value, "unit": unit}


def scenarios(today: date, s1_labs_preloaded: bool) -> list[dict]:
    """visits are oldest first; each has sources (pdf or transcript) and whether it is already signed."""
    s1_labs = {"pdf": "labs_today.pdf", "title": "Laboratory Report", "days_ago": 3,
               "rows": [("Test", "Result", "Unit", "Reference range"),
                        ("Creatinine, serum", "2.1", "mg/dL", "0.6 - 1.1"),
                        ("HbA1c", "7.9", "%", "4.0 - 5.6"),
                        ("Potassium", "4.8", "mmol/L", "3.5 - 5.1")],
               "facts": [lab("Creatinine, serum", 2.1, "mg/dL"), lab("HbA1c", 7.9, "%"), lab("Potassium", 4.8, "mmol/L")]}
    return [
        {"key": "S1_metformin_ckd", "patient": 1, "visits": [
            {"days_ago": 400, "complaint": "Diabetes review", "signed": True, "sources": [
                {"pdf": "rx_old.pdf", "title": "Prescription", "rows": [
                    "Diagnosis: Type 2 diabetes mellitus", "1. Tab Glycomet 500 BD", "2. Tab Telma 40 OD"],
                 "facts": [{"find": "Diagnosis", "fact_type": "diagnosis", "name": "Type 2 diabetes mellitus",
                            "raw_text": "Type 2 diabetes mellitus"},
                           med("Glycomet", "Glycomet", "Glycomet 500 BD"), med("Telma", "Telma", "Telma 40 OD")]}]},
            {"days_ago": 0, "complaint": "Routine follow-up", "signed": False, "sources": [
                {"transcript": "visit.txt", "lines": [
                    "[00:05-00:09] Doctor: Do you have any allergies to medicines?",
                    "[00:10-00:12] Patient: No, no allergies.",
                    "[00:20-00:26] Patient: Sometimes I take an ibuprofen for my knee pain.",
                    "[00:41-00:45] Doctor: Continue Glycomet 500 twice daily."],
                 "facts": [{"find": "no allergies", "fact_type": "allergy", "assertion": "denied",
                            "name": "allergies", "raw_text": "no allergies"},
                           med("Continue Glycomet", "Glycomet", "Glycomet 500 twice daily")]},
                *([s1_labs] if s1_labs_preloaded else [])]}]},

        {"key": "S2_allergy_contradiction", "patient": 2, "visits": [
            {"days_ago": 700, "complaint": "Hospital discharge", "signed": True, "sources": [
                {"pdf": "discharge_old.pdf", "title": "Discharge Summary", "rows": [
                    "Diagnosis: Essential hypertension", "Allergy: Penicillin (rash)", "1. Tab Telma 40 OD"],
                 "facts": [{"find": "Diagnosis", "fact_type": "diagnosis", "name": "Essential hypertension",
                            "raw_text": "Essential hypertension"},
                           {"find": "Allergy:", "fact_type": "allergy", "name": "Penicillin",
                            "raw_text": "Allergy: Penicillin (rash)"},
                           med("Telma", "Telma", "Telma 40 OD")]}]},
            {"days_ago": 0, "complaint": "Sore throat", "signed": False, "sources": [
                {"transcript": "visit.txt", "lines": [
                    "[00:08-00:11] Doctor: Do you have any allergies?",
                    "[00:12-00:14] Patient: No allergies.",
                    "[00:30-00:37] Doctor: I will prescribe Mox 500 three times daily for five days."],
                 "facts": [{"find": "No allergies", "fact_type": "allergy", "assertion": "denied",
                            "name": "allergies", "raw_text": "No allergies"},
                           med("prescribe Mox", "Mox", "Mox 500 three times daily")]}]}]},

        {"key": "S3_negation", "patient": 3, "visits": [
            {"days_ago": 0, "complaint": "Burning urination", "signed": False, "sources": [
                {"transcript": "visit.txt", "lines": [
                    "[00:06-00:14] Patient: I have no diabetes, I am not allergic to sulfa, and no chest pain.",
                    "[00:25-00:31] Doctor: I will prescribe Septran twice daily for the urinary infection."],
                 "facts": [{"find": "no diabetes", "fact_type": "diagnosis", "assertion": "denied",
                            "name": "diabetes", "raw_text": "no diabetes"},
                           {"find": "not allergic", "fact_type": "allergy", "assertion": "denied",
                            "name": "sulfa", "raw_text": "not allergic to sulfa"},
                           {"find": "no chest pain", "fact_type": "symptom", "assertion": "denied",
                            "name": "chest pain", "raw_text": "no chest pain"},
                           med("prescribe Septran", "Septran", "Septran twice daily")]}]}]},

        {"key": "S4_duplicate_dose_interaction", "patient": 4, "visits": [
            {"days_ago": 200, "complaint": "Cardiology review", "signed": True, "sources": [
                {"pdf": "rx_cardiology.pdf", "title": "Prescription", "rows": [
                    "Diagnosis: Atrial fibrillation", "1. Tab Ecosprin 75 OD"],
                 "facts": [{"find": "Diagnosis", "fact_type": "diagnosis", "name": "Atrial fibrillation",
                            "raw_text": "Atrial fibrillation"},
                           med("Ecosprin", "Ecosprin", "Ecosprin 75 OD")]}]},
            {"days_ago": 0, "complaint": "Knee pain", "signed": False, "sources": [
                {"pdf": "rx_outside_clinic.pdf", "title": "Prescription", "rows": [
                    "Diagnosis: Osteoarthritis", "1. Tab Warf 5 OD", "2. Tab Dolo 650 QID", "3. Tab Crocin 650 TDS"],
                 "facts": [{"find": "Diagnosis", "fact_type": "diagnosis", "name": "Osteoarthritis",
                            "raw_text": "Osteoarthritis"},
                           med("Warf", "Warf", "Warf 5 OD"),
                           med("Dolo", "Dolo", "Dolo 650 QID"), med("Crocin", "Crocin", "Crocin 650 TDS")]}]}]},

        {"key": "S5_trend_open_loop", "patient": 5, "visits": [
            {"days_ago": 280, "complaint": "Diabetes review", "signed": True, "sources": [
                {"pdf": "rx_start.pdf", "title": "Prescription", "rows": [
                    "Diagnosis: Type 2 diabetes mellitus", "1. Tab Glycomet 500 BD"],
                 "facts": [{"find": "Diagnosis", "fact_type": "diagnosis", "name": "Type 2 diabetes mellitus",
                            "raw_text": "Type 2 diabetes mellitus"},
                           med("Glycomet", "Glycomet", "Glycomet 500 BD")]},
                {"pdf": "hba1c_1.pdf", "title": "Laboratory Report",
                 "rows": [("Test", "Result", "Unit", "Reference range"), ("HbA1c", "8.9", "%", "4.0 - 5.6")],
                 "facts": [lab("HbA1c", 8.9, "%")]}]},
            {"days_ago": 190, "complaint": "Diabetes review", "signed": True, "sources": [
                {"pdf": "hba1c_2.pdf", "title": "Laboratory Report",
                 "rows": [("Test", "Result", "Unit", "Reference range"), ("HbA1c", "8.2", "%", "4.0 - 5.6")],
                 "facts": [lab("HbA1c", 8.2, "%")]}]},
            {"days_ago": 100, "complaint": "Diabetes review", "signed": True, "sources": [
                {"pdf": "hba1c_3.pdf", "title": "Laboratory Report",
                 "rows": [("Test", "Result", "Unit", "Reference range"), ("HbA1c", "7.6", "%", "4.0 - 5.6")],
                 "facts": [lab("HbA1c", 7.6, "%")]},
                {"transcript": "visit.txt", "lines": [
                    "[00:50-00:55] Doctor: Sugar control is improving. Repeat HbA1c in 3 months."],
                 "facts": [{"find": "Repeat HbA1c", "fact_type": "plan_item", "name": "Repeat HbA1c in 3 months",
                            "raw_text": "Repeat HbA1c in 3 months"}]}]},
            {"days_ago": 0, "complaint": "Routine follow-up", "signed": False, "sources": []}]},

        {"key": "S6_control", "patient": 6, "visits": [
            {"days_ago": 0, "complaint": "Cold and fever", "signed": False, "sources": [
                {"transcript": "visit.txt", "lines": [
                    "[00:04-00:09] Patient: I have had a fever and a runny nose for two days.",
                    "[00:12-00:14] Doctor: Any allergies?",
                    "[00:15-00:16] Patient: No allergies.",
                    "[00:30-00:38] Doctor: This looks like a viral URI. Take paracetamol 500 three times daily for three days."],
                 "facts": [{"find": "fever", "fact_type": "symptom", "name": "fever", "raw_text": "fever"},
                           {"find": "No allergies", "fact_type": "allergy", "assertion": "denied",
                            "name": "allergies", "raw_text": "No allergies"},
                           {"find": "viral URI", "fact_type": "diagnosis", "name": "viral URI", "raw_text": "viral URI"},
                           med("paracetamol", "paracetamol", "paracetamol 500 three times daily")]}]}]},
    ]


def _doctor(cur) -> dict:
    cur.execute("select id, full_name, role::text as role from profiles where role = 'doctor' order by created_at limit 1")
    doctor = cur.fetchone()
    if not doctor:
        raise RuntimeError("No doctor profile found. Apply supabase/seed.sql first.")
    return doctor


def wipe_demo(cur) -> None:
    """Remove all clinical data of the six demo patients (the audit log is append-only and stays)."""
    ids = [PATIENT.format(n) for n in range(1, 7)]
    cur.execute("select id from encounters where patient_id = any(%s::uuid[])", (ids,))
    encounters = [r["id"] for r in cur.fetchall()]
    cur.execute("delete from safety_alerts where patient_id = any(%s::uuid[])", (ids,))
    cur.execute("delete from open_loops where patient_id = any(%s::uuid[])", (ids,))
    cur.execute("delete from note_edits where note_id in (select id from soap_notes where encounter_id = any(%s))", (encounters,))
    cur.execute("delete from patient_exports where encounter_id = any(%s)", (encounters,))
    cur.execute("delete from soap_notes where encounter_id = any(%s)", (encounters,))
    cur.execute("delete from fact_chunks where patient_id = any(%s::uuid[])", (ids,))
    cur.execute("update facts set superseded_by = null where patient_id = any(%s::uuid[])", (ids,))
    cur.execute("delete from facts where patient_id = any(%s::uuid[])", (ids,))
    cur.execute("delete from file_blobs where owner_id in (select id from source_documents where patient_id = any(%s::uuid[]))", (ids,))
    cur.execute("delete from file_blobs where owner_id in (select id from audio_recordings where encounter_id = any(%s))", (encounters,))
    cur.execute("delete from source_documents where patient_id = any(%s::uuid[])", (ids,))
    cur.execute("delete from audio_recordings where encounter_id = any(%s)", (encounters,))
    cur.execute("delete from jobs where patient_id = any(%s::uuid[])", (ids,))
    cur.execute("delete from encounters where patient_id = any(%s::uuid[])", (ids,))


def write_samples(today: date) -> list[Path]:
    """Files to upload live during a demo."""
    SAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    meena = {"full_name": "Meena Rajan", "mrn": "ACE-0001"}
    labs = SAMPLES_DIR / "S1_meena_labs_today.pdf"
    labs.write_bytes(lab_report(meena, today - timedelta(days=3), [
        ("Creatinine, serum", "2.1", "mg/dL", "0.6 - 1.1"), ("HbA1c", "7.9", "%", "4.0 - 5.6"),
        ("Potassium", "4.8", "mmol/L", "3.5 - 5.1")]))
    typo = SAMPLES_DIR / "S1_meena_labs_misprint.pdf"
    typo.write_bytes(lab_report(meena, today - timedelta(days=3), [("Creatinine, serum", "21", "mg/dL", "0.6 - 1.1")]))
    transcript = SAMPLES_DIR / "S6_karthik_followup.txt"
    transcript.write_text(
        "[00:03-00:08] Doctor: How is the fever now?\n"
        "[00:09-00:15] Patient: The fever is gone but I still have a cough.\n"
        "[00:20-00:27] Doctor: Blood pressure is 124 over 80. Continue paracetamol 500 twice daily for two more days.\n"
        "[00:28-00:33] Doctor: Review in 1 week if the cough continues.\n", encoding="utf-8")
    return [labs, typo, transcript]


def seed_demo(reseed: bool = False, s1_labs_preloaded: bool = False, log=print) -> None:
    today = date.today()
    with tx() as cur:
        doctor = _doctor(cur)
        cur.execute("select count(*) as n from encounters where patient_id = any(%s::uuid[])",
                    ([PATIENT.format(n) for n in range(1, 7)],))
        existing = cur.fetchone()["n"]
        if existing and not reseed:
            log(f"Demo data already present ({existing} encounters) - skipping. Use --reseed-demo to rebuild it.")
            return
        if existing:
            wipe_demo(cur)
            log("Removed previous demo clinical data.")

    for scenario in scenarios(today, s1_labs_preloaded):
        patient_id = PATIENT.format(scenario["patient"])
        with tx() as cur:
            cur.execute("select full_name, mrn from patients where id = %s", (patient_id,))
            patient = cur.fetchone()
        for visit in scenario["visits"]:
            started = datetime.now(timezone.utc) - timedelta(days=visit["days_ago"])
            with tx(doctor) as cur:
                cur.execute("insert into encounters(patient_id, doctor_id, started_at, chief_complaint) "
                            "values (%s, %s, %s, %s) returning id",
                            (patient_id, doctor["id"], started, visit["complaint"]))
                encounter_id = cur.fetchone()["id"]
            for source in visit["sources"]:
                if "pdf" in source:
                    when = today - timedelta(days=source.get("days_ago", visit["days_ago"]))
                    kind, name = "document", source["pdf"]
                    content, mime = make_pdf(source["title"], patient, when, source["rows"]), "application/pdf"
                else:
                    kind, name = "audio", source["transcript"]
                    content, mime = "\n".join(source["lines"]).encode(), "text/plain"
                with tx() as cur:
                    job_id, _ = create_job(cur, kind, patient_id, encounter_id, name, content, mime)
                run_job(job_id, llm=ScriptedLLM(source["facts"]))
                with tx() as cur:
                    cur.execute("select status::text as status, error from jobs where id = %s", (job_id,))
                    job = cur.fetchone()
                    if job["status"] != "done":
                        raise RuntimeError(f"{scenario['key']}: {name} failed: {job['error']}")
                    # spoken facts date from the visit, not from the moment of seeding
                    cur.execute("update facts set effective_at = %s where encounter_id = %s and source = 'audio'",
                                (started, encounter_id))
            if visit["signed"]:
                _sign_historic_visit(encounter_id, doctor)
        with tx() as cur:
            from aceso.safety import engine
            fired = engine.evaluate(cur, patient_id)["fired"]
        log(f"  {scenario['key']}: {len(fired)} alert(s) " + ", ".join(sorted({a['rule_id'] for a in fired})))
    for path in write_samples(today):
        log(f"  sample for live upload: {path}")


def _sign_historic_visit(encounter_id, doctor: dict) -> None:
    """Past visits were reviewed and signed by the doctor: same code path as the UI."""
    with tx(doctor) as cur:
        cur.execute("select id, state::text as state, attention_reasons from facts where encounter_id = %s "
                    "and state in ('extracted','verified')", (encounter_id,))
        for fact in cur.fetchall():
            if "possible_omission" in (fact["attention_reasons"] or []):
                cur.execute("update facts set state = 'rejected', needs_attention = false where id = %s", (fact["id"],))
            else:
                review.confirm_fact(cur, fact)
    review.sign(str(encounter_id), user=doctor)
