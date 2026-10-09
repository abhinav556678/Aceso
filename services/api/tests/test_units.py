"""Pure-function tests: no database, no network."""
import pytest

from aceso.extraction.extract import _validate, normalise
from aceso.extraction.negation import is_negated
from aceso.extraction.terminology import Terminology, parse_dose
from aceso.extraction.verify import find_omissions, verify
from aceso.privacy import Redactor
from aceso.safety.metrics import egfr_ckdepi_2021
from aceso.soap import check_sentence, sentence_for

TERM = Terminology(
    brands={"glycomet": {"generic": "metformin", "rxnorm": "6809"}, "dolo": {"generic": "paracetamol", "rxnorm": "161"},
            "ibuprofen": {"generic": "ibuprofen", "rxnorm": "5640"}},
    concepts=[{"system": "LOINC", "code": "2160-0", "display": "Creatinine, serum", "synonyms": ["creatinine"]},
              {"system": "ICD10", "code": "E11", "display": "Type 2 diabetes mellitus", "synonyms": ["diabetes"]}],
    allergy_groups={"sulfa": "sulfonamide_antibiotics", "co-trimoxazole": "sulfonamide_antibiotics"},
    ranges=[{"loinc": "2160-0", "sex": "F", "low": 0.6, "high": 1.1, "plausible_min": 0.1, "plausible_max": 20}],
)


def unit(uid: str, text: str, kind: str = "segment") -> dict:
    return {"id": uid, "kind": kind, "text": text, "page_no": 1, "confidence": 0.99, "start_ms": 0, "end_ms": 1000}


def draft(units: list[dict], **fact) -> dict:
    by_id = {u["id"]: u for u in units}
    validated, reason = _validate({"assertion": "present", "evidence_ids": [units[0]["id"]], **fact}, by_id)
    assert validated, reason
    return normalise(validated, TERM)


# CKD-EPI 2021 oracles from the build guide (§6.1)
@pytest.mark.parametrize("scr, age, sex, expected", [
    (2.1, 50, "F", 28.2), (2.4, 68, "M", 28.7), (1.1, 58, "F", 58.2), (1.6, 72, "M", 45.5), (1.0, 45, "M", 94.6)])
def test_egfr_oracles(scr, age, sex, expected):
    assert egfr_ckdepi_2021(scr, age, sex) == pytest.approx(expected, abs=0.1)


def test_brand_maps_to_generic_with_dose():
    fact = draft([unit("S1", "Continue Glycomet 500 BD.")], fact_type="medication", name="Glycomet",
                 raw_text="Glycomet 500 BD")
    assert (fact["value_text"], fact["code"], fact["dose"]["times_per_day"]) == ("metformin", "6809", 2)
    assert fact["dose"]["daily_mg"] == 1000


def test_denied_allergy_keeps_its_group():
    fact = draft([unit("S1", "I'm not allergic to sulfa.")], fact_type="allergy", assertion="denied",
                 name="sulfa", raw_text="not allergic to sulfa")
    assert (fact["assertion"], fact["dose"]) == ("denied", {"group": "sulfonamide_antibiotics"})
    assert fact["attention_reasons"] == []


def test_fact_citing_missing_evidence_is_rejected():
    validated, reason = _validate({"fact_type": "medication", "name": "Glycomet", "raw_text": "Glycomet",
                                   "evidence_ids": ["S99"]}, {"S1": unit("S1", "Glycomet")})
    assert validated is None and "does not exist" in reason


def test_invented_quote_is_rejected():
    validated, reason = _validate({"fact_type": "medication", "name": "Warfarin", "raw_text": "Warfarin 5 mg",
                                   "evidence_ids": ["S1"]}, {"S1": unit("S1", "Continue Glycomet 500.")})
    assert validated is None and "raw_text" in reason


def test_model_saying_present_for_a_negated_term_is_flagged():
    fact = draft([unit("S1", "Patient has no diabetes.")], fact_type="diagnosis", name="diabetes", raw_text="no diabetes")
    assert fact["assertion"] == "uncertain" and "negation_conflict" in fact["attention_reasons"]


@pytest.mark.parametrize("text, term, expected", [
    ("no diabetes, not allergic to sulfa, no chest pain", "sulfa", True),
    ("no diabetes, takes Glycomet daily", "glycomet", False),
    ("no chest pain but has a cough", "cough", False),
    ("Allergies: none", "allergies", True)])
def test_negation_scope(text, term, expected):
    assert is_negated(text, term) is expected


@pytest.mark.parametrize("text, amount, freq, daily", [
    ("Dolo 650 QID", 650, "QID", 2600), ("Glycomet 500 twice daily", 500, "BD", 1000), ("Septran twice daily", None, "BD", None)])
def test_dose_parsing(text, amount, freq, daily):
    dose = parse_dose(text)
    assert (dose.get("amount"), dose.get("freq"), dose.get("daily_mg")) == (amount, freq, daily)


def test_plausible_value_verifies_and_misread_does_not():
    good = verify(draft([unit("B1", "Creatinine, serum 2.1 mg/dL 0.6 - 1.1", "block")], fact_type="lab_result",
                        name="Creatinine, serum", raw_text="Creatinine, serum 2.1 mg/dL", value_num=2.1, unit="mg/dL"), TERM, "F")
    assert good["state"] == "verified" and good["confidence"] >= 0.9
    bad = verify(draft([unit("B1", "Creatinine, serum 21 mg/dL 0.6 - 1.1", "block")], fact_type="lab_result",
                       name="Creatinine, serum", raw_text="Creatinine, serum 21 mg/dL", value_num=21, unit="mg/dL"), TERM, "F")
    assert bad["state"] == "extracted" and "out_of_plausible_range" in bad["attention_reasons"]


def test_value_not_in_source_is_held_back():
    fact = verify(draft([unit("B1", "Creatinine, serum 2.1 mg/dL", "block")], fact_type="lab_result",
                        name="Creatinine, serum", raw_text="Creatinine, serum", value_num=1.2, unit="mg/dL"), TERM, "F")
    assert fact["state"] == "extracted" and "ocr_mismatch" in fact["attention_reasons"]


def test_omission_check_catches_a_drug_mentioned_in_passing():
    units = [unit("S1", "Continue Glycomet 500 BD."), unit("S2", "Sometimes I take an ibuprofen.")]
    facts = [draft(units[:1], fact_type="medication", name="Glycomet", raw_text="Glycomet 500 BD")]
    omissions = find_omissions(units, facts, TERM)
    assert [o["name"] for o in omissions] == ["ibuprofen"]
    assert omissions[0]["attention_reasons"] == ["possible_omission"]


def test_redactor_removes_name_phone_and_mrn():
    redactor = Redactor(["Meena Rajan"])
    out = redactor.redact("Patient: Meena Rajan MRN: ACE-0001 phone 9876543210. Serum Creatinine 2.1. Continue Glycomet.")
    assert "Meena" not in out and "Rajan" not in out and "ACE-0001" not in out and "9876543210" not in out
    assert "Serum Creatinine 2.1" in out and "Continue Glycomet" in out  # clinical text is untouched


def test_redactor_reports_what_it_removed_and_where():
    redactor = Redactor(["Meena Rajan"])
    text = "Patient:MeenaRajan DOB: 12/03/1976. Seen by Dr. Rao. Continue Glycomet 500 BD"
    sent, spans = redactor.apply(text)
    assert sent == "Patient:<PERSON> DOB: <DOB>. Seen by Dr. <PERSON>. Continue Glycomet 500 BD"
    assert [(text[a:b], label) for a, b, label in spans] == [("MeenaRajan", "PERSON"), ("12/03/1976", "DOB"), ("Rao", "PERSON")]
    assert redactor.counts == {"PERSON": 2, "DOB": 1}


def test_redactor_catches_an_unregistered_name_but_not_a_denial():
    redactor = Redactor(["Karthik S"])
    assert redactor.redact("Name: Suresh Kumar Age: 50 Sex: M") == "Name: <PERSON> Age: 50 Sex: M"
    assert redactor.redact("Patient: Meena Rajan MRN: ACE-0001") == "Patient: <PERSON> MRN: <MRN>"
    assert redactor.redact("Patient: No allergies. Ramipril 5 mg OD") == "Patient: No allergies. Ramipril 5 mg OD"


def test_redactor_removes_a_spoken_introduction_and_later_mentions():
    redactor = Redactor(["Karthik S"])
    lines = ["Hello doctor, my name is sasmit and I have a fever.", "I am Sasmit Rao. I am diabetic and I'm not allergic.",
             "Okay Sasmit, continue Glycomet 500."]
    redactor.learn(lines)
    assert [redactor.redact(line) for line in lines] == [
        "Hello doctor, my name is <PERSON> and I have a fever.", "I am <PERSON>. I am diabetic and I'm not allergic.",
        "Okay <PERSON>, continue Glycomet 500."]


def test_ocr_rows_survive_a_tilted_photo_and_flag_unread_ink():
    from aceso.perception import ocr, pdf
    tilt = lambda x, y: [x + 0.06 * y, y - 0.06 * x]   # a page photographed about 3.5 degrees off
    cell = lambda x, y, w, text, score: ([tilt(x, y), tilt(x + w, y), tilt(x + w, y + 30), tilt(x, y + 30)], text, score)
    rows = ocr.group_rows([cell(700, 500, 50, "2.1", 0.99), cell(100, 500, 220, "Creatinine, serum", 0.97),
                           cell(900, 500, 80, "mg/dL", 0.98),
                           cell(100, 560, 90, "HbA1c", 0.99), cell(700, 560, 50, "7.9", 0.99),
                           cell(700, 620, 50, "4.8", 0.95), cell(100, 620, 130, "", 0.0)], 1600, 2200)
    assert [(r["text"], r["confidence"]) for r in rows] == [
        ("Creatinine, serum 2.1 mg/dL", 0.97), ("HbA1c 7.9", 0.99), ("4.8", 0.0)]
    box = pdf.locate(rows[0], "2.1")
    assert box["w"] < 0.05 and abs(box["x"] - tilt(700, 500)[0] / 1600) < 0.01  # the value, not the row


def test_fact_from_a_low_confidence_scan_row_is_held():
    scanned = lambda confidence: verify(
        {"fact_type": "symptom", "assertion": "present", "raw_text": "fever", "evidence_text": "fever for two days",
         "units": [{"kind": "block", "confidence": confidence, "ocr": True}], "attention_reasons": []},
        Terminology(), None)
    assert scanned(0.95)["state"] == "verified"
    held = scanned(0.70)
    assert held["state"] == "extracted" and held["attention_reasons"] == ["low_ocr_confidence"]


def test_fact_read_by_the_handwriting_model_is_never_auto_verified():
    from aceso.perception import handwriting, ocr
    box = lambda x, w: [[x, 100], [x + w, 100], [x + w, 130], [x, 130]]
    row = ocr.group_rows([(box(100, 60), "Tab", 0.97), (box(180, 200), "Glycomet 500 BD", 0.96, "hand"),
                           (box(60, 30), "", 0.0, "loose")], 1000, 1000)[0]
    assert row["engine"] == handwriting.ENGINE and row["text"] == "Tab Glycomet 500 BD"
    fact = verify({"fact_type": "symptom", "assertion": "present", "raw_text": "fever", "evidence_text": "fever",
                   "units": [{"kind": "block", "confidence": 0.99, "ocr": True, "handwriting": True}],
                   "attention_reasons": []}, Terminology(), None)
    assert fact["state"] == "extracted" and fact["attention_reasons"] == ["read_by_handwriting_model"]


def test_soap_guards():
    fact = {"fact_type": "lab_result", "assertion": "present", "display": "Creatinine, serum", "raw_text": "2.1",
            "value_num": 2.1, "unit": "mg/dL", "dose": None, "value_text": None, "created_by": "system:pipeline"}
    section, text = sentence_for(fact)
    assert (section, text) == ("objective", "Creatinine, serum: 2.1 mg/dL.")
    assert check_sentence(text, fact) == []
    assert check_sentence("Creatinine, serum: 1.2 mg/dL.", fact) == ["number 1.2 is not in the cited fact"]
    denied = {**fact, "fact_type": "symptom", "assertion": "denied", "display": "chest pain", "value_num": None}
    assert sentence_for(denied)[1] == "Denies chest pain."
    assert check_sentence("Reports chest pain.", denied) == ["denied fact rendered without a negation"]
