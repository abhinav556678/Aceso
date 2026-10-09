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
