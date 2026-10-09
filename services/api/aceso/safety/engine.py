import logging
import uuid
import json
from typing import List, Dict, Any, Optional
from datetime import date
from aceso.db import pool

logger = logging.getLogger(__name__)

def calculate_egfr(creatinine: float, age: int, sex: str) -> float:
    """
    Computes eGFR deterministically using CKD-EPI 2021 formula.
    creatinine: Serum creatinine in mg/dL
    age: Age in years
    sex: 'M' or 'F'
    """
    kappa = 0.7 if sex == 'F' else 0.9
    alpha = -0.241 if sex == 'F' else -0.302
    
    scr_over_kappa = creatinine / kappa
    min_val = min(scr_over_kappa, 1.0)
    max_val = max(scr_over_kappa, 1.0)
    
    egfr = 142.0 * (min_val ** alpha) * (max_val ** -1.200) * (0.9938 ** age)
    if sex == 'F':
        egfr *= 1.012
        
    return round(egfr, 1)

def evaluate_patient_safety(patient_id: str, encounter_id: Optional[str] = None):
    """
    Evaluates safety rules for a patient.
    Computes health metrics and fires alerts if rules are violated.
    """
    logger.info(f"Evaluating safety rules for patient {patient_id}")
    
    with pool.connection() as conn:
        with conn.cursor() as cur:
            # 1. Fetch patient demographic data (for age/sex)
            cur.execute("SELECT dob, sex FROM patients WHERE id = %s", (patient_id,))
            patient = cur.fetchone()
            if not patient:
                logger.warning(f"Patient {patient_id} not found")
                return
            
            dob, sex = patient
            # Compute age (rough estimate)
            today = date.today()
            age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
            
            # 2. Fetch verified facts (Medications and Labs)
            cur.execute("""
                SELECT id, fact_type, display, value_num, unit, normalized_code, normalized_system, state, created_at
                FROM facts
                WHERE patient_id = %s AND state IN ('verified', 'clinician_confirmed')
                ORDER BY created_at DESC
            """, (patient_id,))
            facts = cur.fetchall()
            
            medications = []
            creatinine_facts = []
            
            for f in facts:
                fact_dict = {
                    'id': f[0], 'fact_type': f[1], 'display': f[2], 'value_num': f[3],
                    'unit': f[4], 'code': f[5], 'system': f[6]
                }
                if fact_dict['fact_type'] == 'medication':
                    medications.append(fact_dict)
                elif fact_dict['fact_type'] == 'lab_result' and ('creatinine' in fact_dict['display'].lower() or fact_dict['code'] == '2160-0' or fact_dict['display'].lower() == 'scr'):
                    creatinine_facts.append(fact_dict)
            
            # 3. Compute eGFR if creatinine is present
            if creatinine_facts:
                latest_scr_fact = creatinine_facts[0]
                scr = float(latest_scr_fact['value_num']) if latest_scr_fact['value_num'] else 1.0
                
                egfr = calculate_egfr(scr, age, sex)
                logger.info(f"Computed eGFR: {egfr} for patient {patient_id}")
                
                # 4. Evaluate KDIGO-METFORMIN-EGFR30 rule
                # Condition: eGFR < 30 AND patient is on Metformin
                is_on_metformin = any('metformin' in m['display'].lower() or m['code'] == '860975' for m in medications)
                
                if egfr < 30 and is_on_metformin:
                    # Fire critical alert
                    metformin_fact = next(m for m in medications if 'metformin' in m['display'].lower() or m['code'] == '860975')
                    
                    rule_id = "KDIGO-METFORMIN-EGFR30"
                    message = f"Critical: Metformin is contraindicated with eGFR < 30 (Current eGFR: {egfr} mL/min/1.73m²)"
                    trace = {
                        "logic": "IF eGFR < 30 AND Medication = Metformin THEN Contraindicated",
                        "variables": {
                            "eGFR": egfr,
                            "creatinine_value": scr,
                            "age": age,
                            "sex": sex
                        },
                        "steps": [
                            f"Identified verified serum creatinine: {scr} mg/dL",
                            f"Computed eGFR using CKD-EPI 2021: {egfr} mL/min/1.73m²",
                            "Detected active Metformin prescription",
                            "Triggered KDIGO rule due to eGFR < 30"
                        ]
                    }
                    
                    trigger_fact_ids = [str(latest_scr_fact['id']), str(metformin_fact['id'])]
                    
                    # Check if alert already exists for this rule and patient to avoid duplicates
                    cur.execute("""
                        SELECT id FROM safety_alerts 
                        WHERE patient_id = %s AND rule_id = %s AND status = 'open'
                    """, (patient_id, rule_id))
                    existing = cur.fetchone()
                    
                    if not existing:
                        cur.execute("""
                            INSERT INTO safety_alerts (id, patient_id, encounter_id, rule_id, severity, message, status, trigger_fact_ids, trace)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """, (
                            str(uuid.uuid4()), patient_id, encounter_id, rule_id, 'critical', message, 'open', trigger_fact_ids,
                            json.dumps(trace)
                        ))
                        conn.commit()
                        logger.warning(f"Fired KDIGO-METFORMIN-EGFR30 alert for patient {patient_id}")
