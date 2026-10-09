import pytest
from aceso.ai.soap import generate_soap_note, verify_numbers_and_negations, SoapGuardError

def test_generate_soap_note():
    facts = [
        {"id": "1", "fact_type": "symptom", "display": "headache", "assertion": "present"},
        {"id": "2", "fact_type": "symptom", "display": "fever", "assertion": "denied"},
        {"id": "3", "fact_type": "lab_result", "display": "HbA1c", "value_num": 7.2, "unit": "%"},
        {"id": "4", "fact_type": "medication", "display": "Metformin 500 mg"}
    ]
    note = generate_soap_note(facts)
    
    assert len(note['subjective']) == 2
    assert "Patient reports headache." in note['subjective'][0]['text']
    assert "Patient denies fever." in note['subjective'][1]['text']
    assert note['subjective'][1]['fact_ids'] == ["2"]
    
    assert len(note['objective']) == 1
    assert "HbA1c is 7.2 %" in note['objective'][0]['text']
    
    assert len(note['plan']) == 1
    assert "Prescribed Metformin 500 mg." in note['plan'][0]['text']

def test_soap_guard_numbers():
    # Should pass
    verify_numbers_and_negations("Prescribed Metformin 500 mg", [{"display": "Metformin 500 mg"}])
    verify_numbers_and_negations("HbA1c is 7.2", [{"display": "HbA1c", "value_num": 7.2}])
    
    # Should fail due to wrong number
    with pytest.raises(SoapGuardError):
        verify_numbers_and_negations("Prescribed Metformin 1000 mg", [{"display": "Metformin 500 mg"}])

def test_soap_guard_negation():
    # Should fail due to negation when fact is present
    with pytest.raises(SoapGuardError):
        verify_numbers_and_negations("Patient denies headache", [{"display": "headache", "assertion": "present"}])
