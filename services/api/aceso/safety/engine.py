import logging
import uuid
import json
from typing import List, Dict, Any, Optional
from datetime import date
from aceso.db import pool

logger = logging.getLogger(__name__)

def calculate_egfr(creatinine: float, age: int, sex: str) -> float:
    kappa = 0.7 if sex == 'F' else 0.9
    alpha = -0.241 if sex == 'F' else -0.302
    
    scr_over_kappa = creatinine / kappa
    min_val = min(scr_over_kappa, 1.0)
    max_val = max(scr_over_kappa, 1.0)
    
    egfr = 142.0 * (min_val ** alpha) * (max_val ** -1.200) * (0.9938 ** age)
    if sex == 'F':
        egfr *= 1.012
        
    return round(egfr, 1)

class PatientHealthData:
    def __init__(self, age: int, sex: str, facts: List[Dict]):
        self.age = age
        self.sex = sex
        self.facts = facts

def evaluate_safety_rules(patient_data: PatientHealthData, encounter_id: Optional[str]) -> List[Dict]:
    alerts = []
    facts = patient_data.facts
    
    # Pre-filter facts
    meds = [f for f in facts if f['fact_type'] == 'medication' and f['assertion'] == 'present']
    creatinines = [f for f in facts if f['fact_type'] == 'lab_result' and ('creatinine' in f['display'].lower() or f['code'] == '2160-0' or f['display'].lower() == 'scr')]
    allergies = [f for f in facts if f['fact_type'] == 'allergy' and f['assertion'] == 'present']
    denied_allergies = [f for f in facts if f['fact_type'] == 'allergy' and f['assertion'] == 'denied']
    
    # 1. eGFR / Metformin Check
    if creatinines:
        latest_scr_fact = creatinines[0]
        scr = float(latest_scr_fact['value_num']) if latest_scr_fact['value_num'] else 1.0
        egfr = calculate_egfr(scr, patient_data.age, patient_data.sex)
        
        metformin_meds = [m for m in meds if m['code'] == 'metformin' or 'metformin' in m['display'].lower() or m['code'] == '6809']
        
        if egfr < 30 and metformin_meds:
            metformin_fact = metformin_meds[0]
            trace = {
                "logic": "IF eGFR < 30 AND Medication = Metformin THEN Contraindicated",
                "variables": {"eGFR": egfr, "creatinine_value": scr, "age": patient_data.age, "sex": patient_data.sex},
                "steps": [
                    f"Identified verified serum creatinine: {scr} mg/dL",
                    f"Computed eGFR using CKD-EPI 2021: {egfr} mL/min/1.73m²",
                    "Detected active Metformin prescription",
                    "Triggered KDIGO rule due to eGFR < 30"
                ]
            }
            alerts.append({
                "rule_id": "KDIGO-METFORMIN-EGFR30",
                "severity": "critical",
                "message": f"Critical: Metformin is contraindicated with eGFR < 30 (Current eGFR: {egfr} mL/min/1.73m²)",
                "trigger_fact_ids": [str(latest_scr_fact['id']), str(metformin_fact['id'])],
                "trace": trace
            })

    # 2. Contradiction check: patient denies an allergy they historically have
    for da in denied_allergies:
        da_code = da.get('code')
        da_display = da.get('display', '').lower()
        # Find if this allergy exists in historical facts as 'present'
        # For simplicity, match by code or a simple text match
        for a in allergies:
            a_code = a.get('code')
            a_display = a.get('display', '').lower()
            if (da_code and a_code and da_code == a_code) or (da_display in a_display or a_display in da_display) or (da_code == 'allergies' and allergies):
                trace = {
                    "logic": "IF patient denies allergy AND allergy exists in history THEN Contradiction",
                    "variables": {"denied_text": da['raw_text'], "historical_allergy": a['display']},
                    "steps": ["Detected denied allergy in current encounter", "Found conflicting allergy in historical record"]
                }
                alerts.append({
                    "rule_id": "CONTRADICTION-ALLERGY",
                    "severity": "moderate",
                    "message": f"Contradiction: Patient claims {da['raw_text']}, but history shows allergy to {a['display']}.",
                    "trigger_fact_ids": [str(da['id']), str(a['id'])],
                    "trace": trace
                })
                break
                
    # 3. Allergy conflict check: prescribed drug belongs to allergy group
    # A simple cross check (using DB is better but let's do an in-memory mock check if DB is not reachable or fetch from DB in evaluate logic)
    # The prompt says S2 has Mox (amoxicillin) and allergy is Penicillin.
    # Group: penicillins -> amoxicillin. Let's just do a manual rule for the demo or fetch from DB.
    # Actually, the repo should fetch `allergy_groups`. I will implement the fetch in the repo.

    # 4. Duplicate therapy (paracetamol x2)
    # 5. Dose-range alert
    # 6. Interaction alert

    return alerts

class SafetyEngineRepository:
    def get_patient_health_data(self, patient_id: str) -> Optional[PatientHealthData]:
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT dob, sex FROM patients WHERE id = %s", (patient_id,))
                patient = cur.fetchone()
                if not patient:
                    return None
                
                dob, sex = patient
                today = date.today()
                age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
                
                cur.execute("""
                    SELECT id, fact_type, display, value_num, unit, code, code_system, state, created_at, assertion, raw_text, dose, encounter_id
                    FROM facts
                    WHERE patient_id = %s AND state IN ('verified', 'clinician_confirmed')
                    ORDER BY created_at DESC
                """, (patient_id,))
                facts = cur.fetchall()
                
                fact_dicts = []
                for f in facts:
                    fact_dicts.append({
                        'id': f[0], 'fact_type': f[1], 'display': f[2], 'value_num': f[3],
                        'unit': f[4], 'code': f[5], 'system': f[6], 'state': f[7],
                        'created_at': f[8], 'assertion': f[9], 'raw_text': f[10], 'dose': f[11], 'encounter_id': f[12]
                    })
                        
                return PatientHealthData(age, sex, fact_dicts)

    def get_allergy_conflicts(self, patient_id: str) -> List[Dict]:
        with pool.connection() as conn:
            with conn.cursor() as cur:
                # Find if any active medication generic code is in an allergy group where the patient has a historical allergy
                cur.execute("""
                    SELECT f_med.id, f_alg.id, f_med.display, f_alg.display
                    FROM facts f_med
                    JOIN allergy_groups ag ON f_med.code = ag.member_generic
                    JOIN allergy_groups ag2 ON ag.group_name = ag2.group_name
                    JOIN facts f_alg ON f_alg.code = ag2.member_generic OR f_alg.code = ag2.group_name OR f_alg.display ilike '%' || ag2.member_generic || '%'
                    WHERE f_med.patient_id = %s 
                      AND f_alg.patient_id = %s
                      AND f_med.fact_type = 'medication' AND f_med.assertion = 'present'
                      AND f_alg.fact_type = 'allergy' AND f_alg.assertion = 'present'
                      AND f_med.state IN ('verified', 'clinician_confirmed')
                      AND f_alg.state IN ('verified', 'clinician_confirmed')
                """, (patient_id, patient_id))
                return [{"med_id": r[0], "alg_id": r[1], "med_display": r[2], "alg_display": r[3]} for r in cur.fetchall()]

    def get_interactions(self, patient_id: str) -> List[Dict]:
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT f1.id, f2.id, f1.display, f2.display, di.severity, di.description
                    FROM facts f1
                    JOIN facts f2 ON f1.patient_id = f2.patient_id AND f1.id < f2.id
                    JOIN drug_interactions di ON 
                        (f1.code = di.drug_a AND f2.code = di.drug_b) OR 
                        (f1.code = di.drug_b AND f2.code = di.drug_a)
                    WHERE f1.patient_id = %s 
                      AND f1.fact_type = 'medication' AND f1.assertion = 'present'
                      AND f2.fact_type = 'medication' AND f2.assertion = 'present'
                      AND f1.state IN ('verified', 'clinician_confirmed')
                      AND f2.state IN ('verified', 'clinician_confirmed')
                """, (patient_id,))
                return [{"med1_id": r[0], "med2_id": r[1], "med1": r[2], "med2": r[3], "severity": r[4], "desc": r[5]} for r in cur.fetchall()]

    def get_duplicate_therapies(self, patient_id: str) -> List[Dict]:
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT f1.id, f2.id, f1.display, f2.display, f1.code
                    FROM facts f1
                    JOIN facts f2 ON f1.patient_id = f2.patient_id AND f1.id < f2.id AND f1.code = f2.code
                    WHERE f1.patient_id = %s 
                      AND f1.fact_type = 'medication' AND f1.assertion = 'present'
                      AND f2.fact_type = 'medication' AND f2.assertion = 'present'
                      AND f1.state IN ('verified', 'clinician_confirmed')
                      AND f2.state IN ('verified', 'clinician_confirmed')
                """, (patient_id,))
                return [{"med1_id": r[0], "med2_id": r[1], "med1": r[2], "med2": r[3], "code": r[4]} for r in cur.fetchall()]
                
    def get_dose_warnings(self, patient_id: str) -> List[Dict]:
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT f.id, f.display, f.code, (f.dose->>'daily_mg')::numeric, dl.max_daily_mg
                    FROM facts f
                    JOIN dose_limits dl ON f.code = dl.generic
                    WHERE f.patient_id = %s 
                      AND f.fact_type = 'medication' AND f.assertion = 'present'
                      AND f.state IN ('verified', 'clinician_confirmed')
                      AND f.dose->>'daily_mg' IS NOT NULL
                      AND (f.dose->>'daily_mg')::numeric > dl.max_daily_mg
                """, (patient_id,))
                return [{"med_id": r[0], "display": r[1], "code": r[2], "daily_mg": float(r[3]), "max_mg": float(r[4])} for r in cur.fetchall()]

    def save_alerts(self, patient_id: str, encounter_id: Optional[str], alerts: List[Dict]):
        if not alerts:
            return
            
        with pool.connection() as conn:
            with conn.cursor() as cur:
                for alert in alerts:
                    cur.execute("""
                        SELECT id FROM safety_alerts 
                        WHERE patient_id = %s AND rule_id = %s AND status = 'open'
                    """, (patient_id, alert['rule_id']))
                    existing = cur.fetchone()
                    
                    if not existing:
                        cur.execute("""
                            INSERT INTO safety_alerts (id, patient_id, encounter_id, rule_id, severity, message, status, trigger_fact_ids, trace)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """, (
                            str(uuid.uuid4()), patient_id, encounter_id, alert['rule_id'], alert['severity'], 
                            alert['message'], 'open', alert['trigger_fact_ids'], json.dumps(alert['trace'])
                        ))
                conn.commit()


def evaluate_patient_safety(patient_id: str, encounter_id: Optional[str] = None):
    logger.info(f"Evaluating safety rules for patient {patient_id}")
    repo = SafetyEngineRepository()
    patient_data = repo.get_patient_health_data(patient_id)
    
    if not patient_data:
        logger.warning(f"Could not load data for patient {patient_id}")
        return
        
    alerts = evaluate_safety_rules(patient_data, encounter_id)
    
    # DB-based rules
    # 3. Allergy Conflicts
    conflicts = repo.get_allergy_conflicts(patient_id)
    for c in conflicts:
        alerts.append({
            "rule_id": "ALLERGY-CONFLICT",
            "severity": "critical",
            "message": f"Critical: Prescribed {c['med_display']} conflicts with documented allergy to {c['alg_display']}.",
            "trigger_fact_ids": [str(c['med_id']), str(c['alg_id'])],
            "trace": {"logic": "Allergy cross-reactivity check", "variables": {}, "steps": []}
        })
        
    # 4. Interactions
    interactions = repo.get_interactions(patient_id)
    for i in interactions:
        alerts.append({
            "rule_id": "DRUG-INTERACTION",
            "severity": i["severity"],
            "message": f"Interaction ({i['severity']}): {i['med1']} and {i['med2']} - {i['desc']}",
            "trigger_fact_ids": [str(i['med1_id']), str(i['med2_id'])],
            "trace": {"logic": "Drug interaction check", "variables": {}, "steps": []}
        })
        
    # 5. Duplicate Therapy
    duplicates = repo.get_duplicate_therapies(patient_id)
    for d in duplicates:
        alerts.append({
            "rule_id": "DUPLICATE-THERAPY",
            "severity": "moderate",
            "message": f"Duplicate Therapy: Both {d['med1']} and {d['med2']} contain {d['code']}.",
            "trigger_fact_ids": [str(d['med1_id']), str(d['med2_id'])],
            "trace": {"logic": "Duplicate generic check", "variables": {}, "steps": []}
        })
        
    # 6. Dose Warnings
    doses = repo.get_dose_warnings(patient_id)
    for d in doses:
        alerts.append({
            "rule_id": "DOSE-EXCEEDED",
            "severity": "high",
            "message": f"Dose Exceeded: {d['display']} daily dose {d['daily_mg']}mg exceeds max limit {d['max_mg']}mg.",
            "trigger_fact_ids": [str(d['med_id'])],
            "trace": {"logic": "Max dose check", "variables": {}, "steps": []}
        })
    
    repo.save_alerts(patient_id, encounter_id, alerts)
    if alerts:
        logger.warning(f"Fired {len(alerts)} alerts for patient {patient_id}")
