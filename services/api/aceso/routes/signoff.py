from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from aceso.db import pool
import hashlib
import json

router = APIRouter()

class SignOffRequest(BaseModel):
    user_id: str

@router.post("/{encounter_id}/signoff")
def sign_off_encounter(encounter_id: str, req: SignOffRequest):
    with pool.connection() as conn:
        with conn.cursor() as cur:
            # 1. Gating logic: check for open alerts
            cur.execute("""
                SELECT id FROM safety_alerts
                WHERE encounter_id = %s AND status = 'open'
            """, (encounter_id,))
            open_alerts = cur.fetchall()
            
            if open_alerts:
                raise HTTPException(status_code=400, detail="Cannot sign off. There are unacknowledged safety alerts.")
                
            # 2. Transaction for sign-off
            with conn.transaction():
                # Setting auth user ID so the audit trigger writes the correct actor
                cur.execute("SELECT set_config('request.jwt.claim.sub', %s, true)", (req.user_id,))

                # Set 'verified' facts to 'clinician_confirmed'
                # Triggers on facts table will automatically write audit_log row for each transition
                cur.execute("""
                    UPDATE facts
                    SET state = 'clinician_confirmed'
                    WHERE encounter_id = %s AND state = 'verified'
                """, (encounter_id,))
                
                # Update soap notes
                cur.execute("""
                    SELECT subjective, objective, assessment, plan
                    FROM soap_notes
                    WHERE encounter_id = %s
                    ORDER BY version DESC LIMIT 1
                """, (encounter_id,))
                note_row = cur.fetchone()
                
                if note_row:
                    note_dict = {
                        "subjective": note_row[0],
                        "objective": note_row[1],
                        "assessment": note_row[2],
                        "plan": note_row[3],
                    }
                    canonical = json.dumps(note_dict, sort_keys=True)
                    content_hash = hashlib.sha256(canonical.encode('utf-8')).hexdigest()
                    
                    cur.execute("""
                        UPDATE soap_notes
                        SET status = 'signed', signed_by = %s, signed_at = now(), content_hash = %s
                        WHERE encounter_id = %s
                    """, (req.user_id, content_hash, encounter_id))
                
                # Update encounter
                cur.execute("""
                    UPDATE encounters
                    SET status = 'signed'
                    WHERE id = %s
                """, (encounter_id,))
                
                # Write an explicit audit row for note.sign
                cur.execute("""
                    INSERT INTO audit_log (actor_id, action, entity_type, entity_id, payload)
                    VALUES (%s, 'note.sign', 'encounter', %s, %s)
                """, (req.user_id, encounter_id, json.dumps({"action": "sign_off"})))
                
                return {"status": "success", "message": "Encounter signed off successfully."}
