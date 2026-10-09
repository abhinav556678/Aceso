import logging
from rapidfuzz import process, fuzz

logger = logging.getLogger(__name__)

# Mock terminology database
RXNORM_DB = {
    "Metformin": "860975",
    "Metformin 500 mg": "860975",
    "Glycomet": "860975", 
    "Lisinopril": "29046",
    "Amoxicillin": "733",
    "Penicillin": "70618",
}

LOINC_DB = {
    "HbA1c": "4548-4",
    "Hemoglobin A1c": "4548-4",
    "Glucose": "2345-7",
    "Cholesterol": "2093-3"
}

import json
import os

SNOMED_DB = {
    "Hypertension": "38341003",
    "Diabetes Type 2": "44054006",
    "Pain": "22253000",
    "Fever": "386661006",
    "Cough": "49727002",
}

# Dynamically load colloquial terms
VOCAB_PATH = os.path.join(os.path.dirname(__file__), "vocabulary.json")
try:
    with open(VOCAB_PATH, "r", encoding="utf-8") as f:
        vocab_config = json.load(f)
        for term, code in vocab_config.get("tamil_snomed_map", {}).items():
            SNOMED_DB[term] = code
except Exception as e:
    logger.warning(f"Could not load dynamic vocabulary config: {e}")

def normalize_term(term: str, fact_type: str) -> dict:
    """
    Normalizes a clinical term using fuzzy matching against mock terminology DBs.
    """
    db = {}
    system = "Unknown"
    
    if fact_type == "medication" or fact_type == "allergy":
        db = RXNORM_DB
        system = "RxNorm"
    elif fact_type == "lab_result":
        db = LOINC_DB
        system = "LOINC"
    elif fact_type == "condition" or fact_type == "symptom":
        db = SNOMED_DB
        system = "SNOMED-CT"
        
    if not db:
        return {"code": None, "system": None, "confidence": 0.0}
        
    choices = list(db.keys())
    # Find best match
    match = process.extractOne(term, choices, scorer=fuzz.WRatio)
    
    if match:
        best_term, score, index = match
        if score > 80: # 80% confidence threshold
            return {
                "code": db[best_term],
                "system": system,
                "confidence": round(score / 100.0, 2),
                "standard_name": best_term
            }
            
    return {"code": None, "system": None, "confidence": 0.0}
