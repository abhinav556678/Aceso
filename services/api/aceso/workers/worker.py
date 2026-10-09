import time
import logging
from typing import Optional
from aceso.db import pool
from aceso.perception.stt import process_audio
from aceso.perception.ocr import process_document

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def claim_job(conn) -> Optional[dict]:
    # Try to claim a pending job using FOR UPDATE SKIP LOCKED
    with conn.cursor() as cur:
        cur.execute("""
            UPDATE jobs
            SET status = 'running', updated_at = NOW()
            WHERE id = (
                SELECT id
                FROM jobs
                WHERE status = 'pending'
                ORDER BY created_at ASC
                FOR UPDATE SKIP LOCKED
                LIMIT 1
            )
            RETURNING id, type, payload, status;
        """)
        job = cur.fetchone()
        if job:
            return {
                "id": job[0],
                "type": job[1],
                "payload": job[2],
                "status": job[3]
            }
    return None

def complete_job(conn, job_id: str, result: dict):
    with conn.cursor() as cur:
        cur.execute("""
            UPDATE jobs
            SET status = 'done', result = %s, updated_at = NOW()
            WHERE id = %s
        """, (result, job_id))
        conn.commit()

def fail_job(conn, job_id: str, error: str):
    with conn.cursor() as cur:
        cur.execute("""
            UPDATE jobs
            SET status = 'failed', result = %s, updated_at = NOW()
            WHERE id = %s
        """, ({"error": error}, job_id))
        conn.commit()

from aceso.ai.extractor import extract_facts
from aceso.ai.normalizer import normalize_term
import uuid

def process_job(conn, job: dict):
    logger.info(f"Processing job {job['id']} of type {job['type']}")
    try:
        text_content = ""
        source_type = ""
        
        if job['type'] == 'audio_ingestion':
            result = process_audio(job['payload'])
            text_content = result.get('transcript', '')
            source_type = "audio"
        elif job['type'] == 'document_ingestion':
            result = process_document(job['payload'])
            text_content = result.get('text', '')
            source_type = "document"
        else:
            raise ValueError(f"Unknown job type: {job['type']}")
            
        # Fact Extraction
        from aceso.ai.verifier import verify_facts
        extracted_facts = extract_facts(text_content, source_type)
        
        # Fact Normalization & Conversion to dict
        structured_facts = []
        for fact in extracted_facts:
            norm = normalize_term(fact.display, fact.fact_type)
            fact_dict = fact.model_dump()
            fact_dict['id'] = str(uuid.uuid4())
            fact_dict['patient_id'] = job['payload'].get('patient_id', 'unknown')
            fact_dict['job_id'] = job['id']
            fact_dict['source_type'] = source_type
            fact_dict['normalized_code'] = norm.get('code')
            fact_dict['normalized_system'] = norm.get('system')
            structured_facts.append(fact_dict)
            
        # 3-Way Verification Engine
        verified_facts = verify_facts(structured_facts, source_type, result)
        
        # DB Saving
        with conn.cursor() as cur:
            for fact_dict in verified_facts:
                # Omissions won't have patient_id and job_id from the verifier
                if 'patient_id' not in fact_dict:
                    fact_dict['id'] = str(uuid.uuid4())
                    fact_dict['patient_id'] = job['payload'].get('patient_id', 'unknown')
                    fact_dict['job_id'] = job['id']
                
                # Insert into DB (mock or real)
                try:
                    cur.execute("""
                        INSERT INTO facts (id, patient_id, job_id, fact_type, display, value_num, unit, evidence_text, source_type, normalized_code, normalized_system, state, confidence)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (
                        fact_dict.get('id'), fact_dict.get('patient_id'), fact_dict.get('job_id'), fact_dict.get('fact_type'), fact_dict.get('display'),
                        fact_dict.get('value_num'), fact_dict.get('unit'), fact_dict.get('evidence_text'), fact_dict.get('source_type'),
                        fact_dict.get('normalized_code'), fact_dict.get('normalized_system'), fact_dict.get('state', 'needs_attention'), fact_dict.get('confidence', 0.0)
                    ))
                except Exception as db_err:
                    logger.warning(f"Could not insert fact into DB (table might not exist): {db_err}")
                    conn.rollback()
        
        result['extracted_facts'] = verified_facts
        
        # Trigger safety evaluation if we extracted and saved facts
        if verified_facts:
            try:
                from aceso.safety.engine import evaluate_patient_safety
                patient_id = job['payload'].get('patient_id')
                encounter_id = job['payload'].get('encounter_id')
                if patient_id:
                    evaluate_patient_safety(patient_id, encounter_id)
            except Exception as safety_err:
                logger.error(f"Safety evaluation failed: {safety_err}")
                
        complete_job(conn, job['id'], result)
        logger.info(f"Completed job {job['id']} with {len(verified_facts)} facts extracted/verified.")
    except Exception as e:
        logger.error(f"Failed job {job['id']}: {str(e)}")
        fail_job(conn, job['id'], str(e))

def run_worker_loop(once=False):
    # This loop should run continuously in the background
    logger.info("Worker loop started")
    with pool.connection() as conn:
        while True:
            try:
                job = claim_job(conn)
                if job:
                    conn.commit() # commit the claim
                    process_job(conn, job)
                else:
                    if once:
                        break
                    time.sleep(2)
            except Exception as e:
                logger.error(f"Worker loop error: {str(e)}")
                conn.rollback()
                if once:
                    break
                time.sleep(5)
