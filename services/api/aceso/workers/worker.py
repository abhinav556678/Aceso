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

def process_job(conn, job: dict):
    logger.info(f"Processing job {job['id']} of type {job['type']}")
    try:
        if job['type'] == 'audio_ingestion':
            result = process_audio(job['payload'])
        elif job['type'] == 'document_ingestion':
            result = process_document(job['payload'])
        else:
            raise ValueError(f"Unknown job type: {job['type']}")
        
        complete_job(conn, job['id'], result)
        logger.info(f"Completed job {job['id']}")
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
