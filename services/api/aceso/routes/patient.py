from fastapi import APIRouter, HTTPException
from typing import List, Dict, Any
from datetime import timedelta
from aceso.db import pool

router = APIRouter()

def get_verified_facts(cur, patient_id: str, fact_type: str):
    cur.execute("""
        SELECT display FROM facts
        WHERE patient_id = %s AND fact_type = %s AND state = 'verified'
    """, (patient_id, fact_type))
    return [r[0] for r in cur.fetchall()]

@router.get("/{patient_id}/timeline")
def get_timeline(patient_id: str):
    """Unified chronological timeline of all events."""
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT event_id, event_time, event_type, subtype, title, description, value_num, unit, state
                FROM patient_timeline_events
                WHERE patient_id = %s
                ORDER BY event_time DESC NULLS LAST
            """, (patient_id,))
            rows = cur.fetchall()
            
            events = []
            for r in rows:
                events.append({
                    "id": r[0],
                    "time": r[1].isoformat() if r[1] else None,
                    "type": r[2],
                    "subtype": r[3],
                    "title": r[4],
                    "description": r[5],
                    "value_num": float(r[6]) if r[6] is not None else None,
                    "unit": r[7],
                    "state": r[8]
                })
            return {"events": events}

@router.get("/{patient_id}/trends")
def get_trends(patient_id: str, concept: str = "HbA1c"):
    """Trends UI charts lab results against reference range bands, marking medication start/stop points."""
    with pool.connection() as conn:
        with conn.cursor() as cur:
            # Fetch lab results for the concept
            cur.execute("""
                SELECT effective_at, value_num, unit
                FROM facts
                WHERE patient_id = %s AND fact_type = 'lab_result' AND display ILIKE %s AND state = 'verified'
                ORDER BY effective_at ASC
            """, (patient_id, f"%{concept}%"))
            lab_rows = cur.fetchall()
            
            labs = [{"date": r[0].isoformat() if r[0] else None, "value": float(r[1]) if r[1] is not None else None, "unit": r[2]} for r in lab_rows]
            
            # Fetch medications
            cur.execute("""
                SELECT effective_at, display, state, dose
                FROM facts
                WHERE patient_id = %s AND fact_type = 'medication' AND state = 'verified'
                ORDER BY effective_at ASC
            """, (patient_id,))
            meds_rows = cur.fetchall()
            
            meds = []
            for r in meds_rows:
                start_date = r[0]
                dose = r[3] or {}
                end_date = None
                if start_date and "duration_days" in dose:
                    end_date = start_date + timedelta(days=int(dose["duration_days"]))
                meds.append({
                    "start_date": start_date.isoformat() if start_date else None,
                    "end_date": end_date.isoformat() if end_date else None,
                    "name": r[1],
                    "state": r[2]
                })
            
            # Mock reference ranges for the concept
            ranges = {}
            if concept.lower() == "hba1c":
                ranges = {"normal_min": 4.0, "normal_max": 5.7, "prediabetes_max": 6.4}
            elif concept.lower() == "creatinine":
                ranges = {"normal_min": 0.6, "normal_max": 1.2}
            
            return {"labs": labs, "meds": meds, "ranges": ranges}

@router.get("/{patient_id}/summary")
def get_summary(patient_id: str):
    """Deterministic patient summary card."""
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT full_name, dob, sex FROM patients WHERE id = %s", (patient_id,))
            patient = cur.fetchone()
            if not patient:
                raise HTTPException(status_code=404, detail="Patient not found")
                
            return {
                "name": patient[0],
                "dob": patient[1].isoformat() if patient[1] else None,
                "sex": patient[2],
                "active_conditions": get_verified_facts(cur, patient_id, 'condition'),
                "active_medications": get_verified_facts(cur, patient_id, 'medication'),
                "allergies": get_verified_facts(cur, patient_id, 'allergy')
            }
