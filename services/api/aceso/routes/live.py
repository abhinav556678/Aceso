from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from aceso.db import pool
import asyncio
import json

router = APIRouter()

@router.websocket("/{encounter_id}/gaps")
async def websocket_gap_prompts(websocket: WebSocket, encounter_id: str):
    await websocket.accept()
    try:
        while True:
            gaps = []
            with pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT patient_id FROM encounters WHERE id = %s", (encounter_id,))
                    row = cur.fetchone()
                    if row:
                        patient_id = row[0]
                        
                        # Overdue loops
                        cur.execute("""
                            SELECT description, due_date
                            FROM open_loops_v
                            WHERE patient_id = %s AND overdue = true
                        """, (patient_id,))
                        for open_loop in cur.fetchall():
                            gaps.append({
                                "type": "overdue_loop",
                                "message": f"Follow-up overdue: {open_loop[0]} (Due {open_loop[1]})"
                            })
                        
                        # Check missing essential steps (e.g. vitals, allergies)
                        cur.execute("""
                            SELECT count(*) FROM facts 
                            WHERE encounter_id = %s AND fact_type = 'allergy'
                        """, (encounter_id,))
                        if cur.fetchone()[0] == 0:
                            gaps.append({
                                "type": "missing_essential",
                                "message": "Missing essential step: Confirm allergies"
                            })
                            
            await websocket.send_text(json.dumps({"gaps": gaps}))
            await asyncio.sleep(5)
            
    except WebSocketDisconnect:
        pass
