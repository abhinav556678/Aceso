import pytest
from aceso.ai.verifier import verify_facts

def test_ocr_match_check():
    structured_facts = [{
        "display": "Metformin",
        "evidence_text": "metformin 500mg"
    }]
    result_data = {
        "pages": [{
            "blocks": [{"text": "Patient is taking Metformin 500mg daily"}],
            "text": "Patient is taking Metformin 500mg daily"
        }]
    }
    verified = verify_facts(structured_facts, "document", result_data)
    assert len(verified) == 1
    assert verified[0]["confidence"] > 0.8
    assert verified[0]["state"] == "verified"

def test_ocr_match_fail():
    structured_facts = [{
        "display": "Metformin",
        "evidence_text": "glycomet"
    }]
    result_data = {
        "pages": [{
            "blocks": [{"text": "Patient is taking Metformin 500mg daily"}],
            "text": "Patient is taking Metformin 500mg daily"
        }]
    }
    verified = verify_facts(structured_facts, "document", result_data)
    assert len(verified) == 1
    assert verified[0]["confidence"] < 0.8
    assert verified[0]["state"] == "needs_attention"

def test_omission_check():
    structured_facts = [{
        "display": "Hypertension",
        "evidence_text": "high blood pressure"
    }]
    result_data = {
        "transcript": "Patient has high blood pressure and a severe allergy to penicillin.",
        "segments": []
    }
    verified = verify_facts(structured_facts, "audio", result_data)
    assert len(verified) == 3
    omissions = [f for f in verified if f.get("fact_type") == "omission_warning"]
    assert any("allergy" in o["display"].lower() for o in omissions)
    assert any("severe" in o["display"].lower() for o in omissions)
    assert omissions[0]["state"] == "needs_attention"
