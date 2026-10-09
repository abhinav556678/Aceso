"""The six planted scenarios, end to end through the API against a real database."""
from pathlib import Path

import pytest

from aceso import pipeline
from aceso.demo import ScriptedLLM, lab
from tests.conftest import PATIENTS, as_role

DOCTOR, NURSE, ADMIN = as_role("doctor"), as_role("nurse"), as_role("admin")
SAMPLES = Path(__file__).resolve().parents[3] / "data" / "synthetic"

EXPECTED_ALERTS = {
    1: {"KDIGO-METFORMIN-EGFR30"},
    2: {"RECORD-CONTRADICTION", "ALLERGY-CONFLICT"},
    3: set(),                                              # negation: no false allergy alarm
    4: {"INT-PAIR", "DUP-THERAPY", "DOSE-MAX-DAILY"},
    5: set(),
    6: set(),                                              # healthy control: false-positive check
    # background charts: one alert each on two of them, nothing on the rest
    7: set(), 8: set(), 9: {"ALLERGY-CONFLICT"}, 10: set(), 11: {"DOSE-MAX-DAILY"},
    12: set(), 13: set(), 14: set(), 15: set(),
}


def chart(client, n: int) -> dict:
    response = client.get(f"/api/patients/{PATIENTS[n]}/chart", headers=DOCTOR)
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize("n, expected", EXPECTED_ALERTS.items())
def test_scenario_fires_exactly_the_expected_alerts(client, n, expected):
    open_alerts = {a["rule_id"] for a in chart(client, n)["alerts"] if a["status"] == "open"}
    assert open_alerts == expected


def test_s1_trace_shows_the_math_and_the_sources(client):
    data = chart(client, 1)
    alert = next(a for a in data["alerts"] if a["rule_id"] == "KDIGO-METFORMIN-EGFR30")
    steps = alert["trace"]["steps"]
    egfr = next(s for s in steps if s["label"] == "Computed eGFR")
    assert egfr["value"] == pytest.approx(28.2, abs=0.1) and egfr["formula"] == "CKD-EPI 2021"
    assert egfr["inputs"][0]["value"] == 2.1 and "labs_today.pdf" in egfr["inputs"][0]["source"]
    assert "glycomet → metformin" in steps[0]["evidence"]
    creatinine = next(f for f in data["facts"] if f["code"] == "2160-0")
    assert creatinine["source"] == "document" and creatinine["bbox"]["w"] < 0.1  # box is the value, not the row
    assert any(f["code"] == "62238-1" and f["created_by"] == "system:metric" for f in data["facts"])


def test_s3_stores_three_denied_facts(client):
    denied = {f["display"] for f in chart(client, 3)["facts"] if f["assertion"] == "denied"}
    assert denied == {"Type 2 diabetes mellitus", "Sulfa", "chest pain"}


def test_s4_dose_is_summed_across_products(client):
    alert = next(a for a in chart(client, 4)["alerts"] if a["rule_id"] == "DOSE-MAX-DAILY")
    assert "4550 mg/day" in alert["message"]


def test_s5_trend_and_overdue_loop(client):
    series = client.get(f"/api/patients/{PATIENTS[5]}/trends", headers=DOCTOR).json()["series"]
    hba1c = next(s for s in series if s["loinc"] == "4548-4")
    assert [p["value"] for p in hba1c["points"]] == [8.9, 8.2, 7.6]
    assert hba1c["summary"].startswith("HbA1c fell from 8.9 to 7.6 %")
    data = chart(client, 5)
    assert [loop["overdue"] for loop in data["open_loops"]] == [True]
    assert any(g["status"] == "pending_from_history" for g in data["gaps"])


def test_engine_is_idempotent(client, database):
    from aceso.db import tx
    from aceso.safety import engine
    before = len(chart(client, 4)["alerts"])
    with tx() as cur:
        engine.evaluate(cur, PATIENTS[4])
        engine.evaluate(cur, PATIENTS[4])
    assert len(chart(client, 4)["alerts"]) == before


def test_search_answers_only_from_the_record(client):
    search = lambda n, q: client.post(f"/api/patients/{PATIENTS[n]}/search", json={"q": q}, headers=DOCTOR).json()
    assert "explicitly denied" in search(3, "Does she have a sulfa allergy?")["answer"]
    assert "Creatinine, serum 2.1 mg/dL" in search(1, "What was her creatinine?")["answer"]
    assert search(6, "any history of stroke?") == {
        "answer": "No supporting record found in this patient's chart.", "evidence": []}


def test_role_matrix(client):
    assert client.get("/api/patients").status_code == 401
    assert client.get("/api/patients", headers=ADMIN).status_code == 200
    assert client.get(f"/api/patients/{PATIENTS[1]}/chart", headers=ADMIN).status_code == 403
    assert client.get("/api/admin/audit", headers=DOCTOR).status_code == 403
    assert client.get("/api/admin/audit", headers=ADMIN).status_code == 200
    assert client.post("/api/admin/audit/verify", headers=ADMIN).json()["ok"] is True
    fact = next(f for f in chart(client, 6)["facts"] if f["state"] == "verified")
    assert client.post(f"/api/facts/{fact['id']}/confirm", headers=NURSE).status_code == 403


def test_review_sign_and_export_flow(client):
    """S2: blocked until every fact is reviewed and each alert handled; then signed, locked and exportable."""
    data = chart(client, 2)
    encounter_id = data["encounter"]["id"]
    blocked = client.post(f"/api/encounters/{encounter_id}/sign", headers=DOCTOR)
    assert blocked.status_code == 409 and len(blocked.json()["detail"]["blockers"]) == 2
    assert client.get(f"/api/encounters/{encounter_id}/fhir", headers=DOCTOR).status_code == 409

    contradiction = next(a for a in data["alerts"] if a["rule_id"] == "RECORD-CONTRADICTION")
    penicillin = next(f for f in data["facts"] if f["display"] == "Penicillin")
    resolved = client.post(f"/api/alerts/{contradiction['id']}/resolve", headers=DOCTOR,
                           json={"keep_fact_id": penicillin["id"], "reason": "Patient confirms the rash in 2024."})
    assert resolved.status_code == 200, resolved.text

    data = chart(client, 2)
    assert not any(f["value_text"] == "*" for f in data["facts"])  # the denial was superseded
    conflict = next(a for a in data["alerts"] if a["rule_id"] == "ALLERGY-CONFLICT" and a["status"] == "open")
    assert client.post(f"/api/alerts/{conflict['id']}/override", headers=DOCTOR, json={"reason": "short"}).status_code == 422
    mox = next(f for f in data["facts"] if f["display"] == "Amoxicillin")
    assert client.post(f"/api/facts/{mox['id']}/reject", headers=DOCTOR).status_code == 200
    # rejecting the drug removes the cause, so the alert closes itself
    assert not [a for a in chart(client, 2)["alerts"] if a["status"] == "open"]

    signed = client.post(f"/api/encounters/{encounter_id}/sign", headers=DOCTOR)
    assert signed.status_code == 200, signed.text
    assert client.post(f"/api/encounters/{encounter_id}/sign", headers=DOCTOR).status_code == 409

    bundle = client.get(f"/api/encounters/{encounter_id}/fhir", headers=DOCTOR).json()
    kinds = [e["resource"]["resourceType"] for e in bundle["entry"]]
    assert kinds[0] == "Composition" and "Patient" in kinds and "Amoxicillin" not in str(bundle)
    for lang in ("en", "ta", "hi"):
        page = client.get(f"/api/encounters/{encounter_id}/patient-summary?lang={lang}", headers=DOCTOR)
        assert page.status_code == 200 and "Arjun Menon" in page.text


def test_misprinted_lab_value_is_held_for_review(client, monkeypatch):
    """Upload path with a scripted model: creatinine 21 mg/dL is outside the plausible range."""
    monkeypatch.setattr(pipeline, "get_llm", lambda: ScriptedLLM([lab("Creatinine, serum", 21, "mg/dL")]))
    with open(SAMPLES / "S1_meena_labs_misprint.pdf", "rb") as handle:
        response = client.post("/api/ingest", headers=NURSE, data={"patient_id": PATIENTS[6]},
                               files={"file": ("misprint.pdf", handle, "application/pdf")})
    assert response.status_code == 200, response.text
    job = client.get(f"/api/jobs/{response.json()['job_id']}", headers=NURSE).json()
    assert job["status"] == "done", job
    fact = next(f for f in chart(client, 6)["facts"] if f["code"] == "2160-0")
    assert fact["state"] == "extracted" and fact["attention_reasons"] == ["out_of_plausible_range"]
    assert not [a for a in chart(client, 6)["alerts"] if a["status"] == "open"]  # unverified facts never reach the engine
    page = client.get(f"/api/documents/{fact['document_id']}/pages/1.png", headers=NURSE)
    assert page.status_code == 200 and page.content[:4] == b"\x89PNG"


def test_privacy_receipt_shows_exactly_what_was_sent(client, monkeypatch):
    """The stored payload has no identifiers, matches the audit chain, and hides originals from the admin."""
    monkeypatch.setattr(pipeline, "get_llm", lambda: ScriptedLLM([]))
    transcript = b"[00:01-00:05] Doctor: Karthik, your phone is still 9876543210?\n[00:06-00:08] Patient: Yes.\n"
    response = client.post("/api/ingest", headers=NURSE, data={"patient_id": PATIENTS[6]},
                           files={"file": ("call.txt", transcript, "text/plain")})
    job_id = response.json()["job_id"]
    result = client.get(f"/api/jobs/{job_id}", headers=NURSE).json()["result"]
    assert result["redacted"] == 2 and result["llm_calls"] == 1

    receipt = client.get(f"/api/jobs/{job_id}/privacy", headers=DOCTOR).json()
    call = receipt["calls"][0]
    assert "Karthik" not in call["user_message"] and "9876543210" not in call["user_message"]
    assert call["redacted"] == {"PERSON": 1, "PHONE": 1} and call["intact"] is True
    first = call["units"][0]
    assert first["sent"] == "<PERSON>, your phone is still <PHONE>?"
    assert [first["original"][a:b] for a, b, _ in first["spans"]] == ["Karthik", "9876543210"]

    audited = client.get(f"/api/jobs/{job_id}/privacy", headers=ADMIN).json()
    assert audited["shows_original"] is False and "Karthik" not in str(audited)
    assert audited["calls"][0]["intact"] is True
    assert client.post("/api/admin/audit/verify", headers=ADMIN).json()["ok"] is True

    preview = client.post("/api/privacy/preview", headers=ADMIN, json={"text": "Dr. Iyer saw ACE-0003"}).json()
    assert preview["sent"] == "Dr. <PERSON> saw <MRN>"


def test_photographed_report_is_read_by_ocr_and_a_smudged_row_is_not_guessed(client, monkeypatch):
    pytest.importorskip("rapidocr_onnxruntime")
    monkeypatch.setattr(pipeline, "get_llm", lambda: ScriptedLLM([
        {**lab("Creatinine", 2.1, "mg/dL"), "raw_text": "2.1 mg/dL"}, {**lab("Potassium", 4.8, "mmol/L"), "raw_text": "4.8"}]))
    with open(SAMPLES / "S1_meena_labs_photo_smudged.jpg", "rb") as handle:
        response = client.post("/api/ingest", headers=NURSE, data={"patient_id": PATIENTS[3]},
                               files={"file": ("photo.jpg", handle, "image/jpeg")})
    assert response.status_code == 200, response.text
    job = client.get(f"/api/jobs/{response.json()['job_id']}", headers=NURSE).json()
    assert job["status"] == "done", job
    assert job["result"]["ocr"]["unreadable"] == 1 and job["result"]["facts"] == 1  # potassium row: no fact, flagged

    creatinine = next(f for f in chart(client, 3)["facts"] if f["code"] == "2160-0")
    assert creatinine["state"] == "verified" and creatinine["value_num"] == 2.1 and creatinine["bbox"]["w"] < 0.1
    document = client.get(f"/api/documents/{creatinine['document_id']}", headers=NURSE).json()
    assert document["ocr_engine"].startswith("rapidocr-onnx")  # "+trocr-handwritten" where that reader is installed
    assert sum(1 for b in document["blocks"] if b["confidence"] < document["thresholds"]["unreadable_below"]) == 1
    page = client.get(f"/api/documents/{creatinine['document_id']}/pages/1.png", headers=NURSE)
    assert page.status_code == 200 and page.content[:4] == b"\x89PNG"

    # the name printed on the photo is not this patient's registered name, and still does not leave
    sent = client.get(f"/api/jobs/{job['id']}/privacy", headers=DOCTOR).json()["calls"][0]["user_message"]
    assert "Meena" not in sent and "Rajan" not in sent and "ACE-0001" not in sent and "Creatinine" in sent


def test_sign_in_sets_a_session_and_wrong_passwords_are_refused(client, monkeypatch):
    from aceso.config import settings
    monkeypatch.setattr(settings, "nurse_password", "only-for-this-test")
    monkeypatch.setattr(settings, "demo_role_header", False)  # as in the real app: the session is the only way in
    assert client.get("/api/patients", headers=NURSE).status_code == 401
    assert client.post("/api/login", json={"username": "nurse", "password": "wrong"}).status_code == 401
    assert client.post("/api/login", json={"username": "doctor", "password": ""}).status_code == 401  # no password set
    try:
        signed_in = client.post("/api/login", json={"username": "Nurse", "password": "only-for-this-test"})
        assert signed_in.status_code == 200 and signed_in.json()["role"] == "nurse"
        assert client.get("/api/session").json()["role"] == "nurse"
        assert client.get("/api/patients").status_code == 200
        assert client.get("/api/admin/audit").status_code == 403
        client.cookies.set("aceso_session", signed_in.cookies["aceso_session"].replace("nurse", "admin"))
        assert client.get("/api/admin/audit").status_code == 401  # a cookie edited to another role is rejected
    finally:
        client.cookies.clear()
    assert client.get("/api/patients").status_code == 401


@pytest.mark.parametrize("n", range(7, 16))
def test_background_charts_start_with_nothing_unverified(client, n):
    data = chart(client, n)
    assert data["encounter"] and data["encounter"]["status"] != "signed"  # an open visit to work in
    assert [f["display"] for f in data["facts"] if f["state"] == "extracted"] == []
