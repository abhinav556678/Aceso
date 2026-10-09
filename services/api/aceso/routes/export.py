from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel
from aceso.db import pool
from typing import Optional
import json
import uuid
import datetime

router = APIRouter()

# Simple hardcoded dictionaries for translations to avoid LLM translation
TRANSLATIONS = {
    'en': {
        'title': 'Patient Visit Summary',
        'patient': 'Patient',
        'age': 'Age',
        'gender': 'Gender',
        'date': 'Date',
        'conditions': 'Active Conditions',
        'medications': 'Medications',
        'allergies': 'Allergies',
        'plan': 'Care Plan & Follow-ups'
    },
    'ta': {
        'title': 'நோயாளி வருகை சுருக்கம் (Patient Visit Summary)',
        'patient': 'நோயாளி',
        'age': 'வயது',
        'gender': 'பாலினம்',
        'date': 'தேதி',
        'conditions': 'தற்போதைய நிலைமைகள் (Active Conditions)',
        'medications': 'மருந்துகள் (Medications)',
        'allergies': 'ஒவ்வாமை (Allergies)',
        'plan': 'கவனிப்பு திட்டம் & பின்தொடர்தல் (Care Plan & Follow-ups)'
    },
    'hi': {
        'title': 'मरीज़ की विज़िट का सारांश (Patient Visit Summary)',
        'patient': 'मरीज़',
        'age': 'आयु',
        'gender': 'लिंग',
        'date': 'दिनांक',
        'conditions': 'वर्तमान स्थिति (Active Conditions)',
        'medications': 'दवाएं (Medications)',
        'allergies': 'एलर्जी (Allergies)',
        'plan': 'देखभाल योजना और अनुवर्ती (Care Plan & Follow-ups)'
    }
}

try:
    from jinja2 import Template
    from xhtml2pdf import pisa
    from io import BytesIO
    CAN_GENERATE_PDF = True
except ImportError:
    CAN_GENERATE_PDF = False

def _get_encounter_data(encounter_id: str, cur):
    # Get encounter & patient details
    cur.execute("""
        SELECT p.id, p.full_name, p.dob, p.sex, e.created_at, e.status
        FROM encounters e
        JOIN patients p ON p.id = e.patient_id
        WHERE e.id = %s
    """, (encounter_id,))
    row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Encounter not found")
        
    patient_id, name, dob, sex, date, status = row
    if status != 'signed':
        raise HTTPException(status_code=400, detail="Encounter is not signed off")
        
    # Get facts
    cur.execute("""
        SELECT id, fact_type, display, value_num, unit, assertion, effective_at 
        FROM facts 
        WHERE encounter_id = %s AND state IN ('verified', 'clinician_confirmed')
    """, (encounter_id,))
    facts = cur.fetchall()
    
    return {
        "patient_id": patient_id, "name": name, "dob": dob, "sex": sex, "date": date, "facts": facts
    }

@router.get("/{encounter_id}/export/pdf")
def export_pdf(encounter_id: str, lang: str = 'en'):
    if not CAN_GENERATE_PDF:
        raise HTTPException(status_code=500, detail="PDF generation library missing")
        
    t = TRANSLATIONS.get(lang, TRANSLATIONS['en'])
    
    with pool.connection() as conn:
        with conn.cursor() as cur:
            data = _get_encounter_data(encounter_id, cur)
            
            dob = data["dob"]
            age = datetime.date.today().year - dob.year if dob else 'Unknown'
            
            facts = data["facts"]
            conditions = [f[2] for f in facts if f[1] in ('condition', 'diagnosis')]
            medications = [f[2] for f in facts if f[1] == 'medication']
            allergies = [f[2] for f in facts if f[1] == 'allergy']
            
            # Get plan from signed soap notes
            cur.execute("""
                SELECT plan FROM soap_notes WHERE encounter_id = %s AND status = 'signed' ORDER BY version DESC LIMIT 1
            """, (encounter_id,))
            plan_row = cur.fetchone()
            plan_items = []
            if plan_row and plan_row[0]:
                for item in plan_row[0]:
                    plan_items.append(item.get('text', ''))
            
            import os
            template_path = os.path.join(os.path.dirname(__file__), '..', 'templates', 'summary.html')
            font_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'templates', 'fonts')).replace('\\', '/')
            with open(template_path, 'r', encoding='utf-8') as f:
                html_template = f.read()
            
            template = Template(html_template)
            rendered_html = template.render(
                t=t, name=data["name"], age=age, sex=data["sex"], date=data["date"], 
                conditions=conditions, medications=medications, allergies=allergies, plan_items=plan_items, font_dir=font_dir
            )
            
            # Generate PDF
            pdf_out = BytesIO()
            pisa.CreatePDF(BytesIO(rendered_html.encode('utf-8')), pdf_out)
            pdf_value = pdf_out.getvalue()
            pdf_out.close()
            
            return Response(content=pdf_value, media_type="application/pdf")

def _make_observation(fact, patient_id, encounter_id):
    fid, ftype, display, vnum, unit, assertion, eff_at = fact
    obs = {
        "fullUrl": f"urn:uuid:{fid}",
        "resource": {
            "resourceType": "Observation",
            "id": str(fid),
            "status": "final",
            "code": {"text": display},
            "subject": {"reference": f"urn:uuid:{patient_id}"},
            "encounter": {"reference": f"urn:uuid:{encounter_id}"}
        }
    }
    if eff_at:
        obs["resource"]["effectiveDateTime"] = eff_at.isoformat()
    if vnum is not None:
        obs["resource"]["valueQuantity"] = {"value": float(vnum), "unit": unit or ""}
    return obs

def _make_condition(fact, patient_id, encounter_id):
    fid, ftype, display, vnum, unit, assertion, eff_at = fact
    return {
        "fullUrl": f"urn:uuid:{fid}",
        "resource": {
            "resourceType": "Condition",
            "id": str(fid),
            "clinicalStatus": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/condition-clinical", "code": "active"}]},
            "verificationStatus": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/condition-ver-status", "code": "confirmed"}]},
            "code": {"text": display},
            "subject": {"reference": f"urn:uuid:{patient_id}"},
            "encounter": {"reference": f"urn:uuid:{encounter_id}"}
        }
    }

def _make_medication(fact, patient_id, encounter_id):
    fid, ftype, display, vnum, unit, assertion, eff_at = fact
    return {
        "fullUrl": f"urn:uuid:{fid}",
        "resource": {
            "resourceType": "MedicationStatement",
            "id": str(fid),
            "status": "active",
            "medicationCodeableConcept": {"text": display},
            "subject": {"reference": f"urn:uuid:{patient_id}"},
            "context": {"reference": f"urn:uuid:{encounter_id}"}
        }
    }

def _make_allergy(fact, patient_id, encounter_id):
    fid, ftype, display, vnum, unit, assertion, eff_at = fact
    return {
        "fullUrl": f"urn:uuid:{fid}",
        "resource": {
            "resourceType": "AllergyIntolerance",
            "id": str(fid),
            "clinicalStatus": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/allergyintolerance-clinical", "code": "active"}]},
            "verificationStatus": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/allergyintolerance-verification", "code": "confirmed"}]},
            "code": {"text": display},
            "patient": {"reference": f"urn:uuid:{patient_id}"},
            "encounter": {"reference": f"urn:uuid:{encounter_id}"}
        }
    }

RESOURCE_FACTORIES = {
    'lab_result': _make_observation,
    'vital': _make_observation,
    'condition': _make_condition,
    'diagnosis': _make_condition,
    'medication': _make_medication,
    'allergy': _make_allergy
}

@router.get("/{encounter_id}/export/fhir")
def export_fhir(encounter_id: str):
    """Generate a valid FHIR R4 ABDM bundle for the signed encounter."""
    with pool.connection() as conn:
        with conn.cursor() as cur:
            data = _get_encounter_data(encounter_id, cur)
            patient_id, name, dob, sex, date, facts = (
                data["patient_id"], data["name"], data["dob"], data["sex"], data["date"], data["facts"]
            )
            
            # Build FHIR Bundle
            bundle = {
                "resourceType": "Bundle",
                "id": str(uuid.uuid4()),
                "type": "document",
                "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
                "entry": []
            }
            
            # Composition Resource (required as first entry for document bundles)
            composition_id = str(uuid.uuid4())
            composition_resource = {
                "fullUrl": f"urn:uuid:{composition_id}",
                "resource": {
                    "resourceType": "Composition",
                    "id": composition_id,
                    "status": "final",
                    "type": {"coding": [{"system": "http://loinc.org", "code": "11503-0", "display": "Medical records"}]},
                    "subject": {"reference": f"urn:uuid:{patient_id}"},
                    "encounter": {"reference": f"urn:uuid:{encounter_id}"},
                    "date": datetime.datetime.utcnow().isoformat() + "Z",
                    "author": [{"display": "Aceso System"}],
                    "title": "Patient Visit Summary",
                    "section": [{"title": "Facts", "entry": []}]
                }
            }
            bundle["entry"].append(composition_resource)
            
            # Patient Resource
            fhir_sex = "male" if sex.upper() == 'M' else "female" if sex.upper() == 'F' else "unknown"
            patient_resource = {
                "fullUrl": f"urn:uuid:{patient_id}",
                "resource": {
                    "resourceType": "Patient",
                    "id": str(patient_id),
                    "name": [{"text": name}],
                    "gender": fhir_sex,
                    "birthDate": dob.isoformat() if dob else None
                }
            }
            bundle["entry"].append(patient_resource)
            
            # Encounter Resource
            encounter_resource = {
                "fullUrl": f"urn:uuid:{encounter_id}",
                "resource": {
                    "resourceType": "Encounter",
                    "id": str(encounter_id),
                    "status": "finished",
                    "class": {"system": "http://terminology.hl7.org/CodeSystem/v3-ActCode", "code": "AMB", "display": "ambulatory"},
                    "subject": {"reference": f"urn:uuid:{patient_id}"},
                    "period": {"start": date.isoformat()}
                }
            }
            bundle["entry"].append(encounter_resource)
            
            # Map facts to Resources
            for fact in facts:
                ftype = fact[1]
                factory = RESOURCE_FACTORIES.get(ftype)
                if factory:
                    res = factory(fact, patient_id, encounter_id)
                    bundle["entry"].append(res)
                    composition_resource["resource"]["section"][0]["entry"].append({"reference": res["fullUrl"]})
            
            return bundle
