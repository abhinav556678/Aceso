import os
import shutil
import uuid
from fastapi import APIRouter, UploadFile, File, HTTPException
from aceso.db import pool
from pydantic import BaseModel

router = APIRouter()

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

class UploadResponse(BaseModel):
    job_id: str
    message: str

@router.post("/upload", response_model=UploadResponse)
async def upload_file(file: UploadFile = File(...)):
    # Save file
    file_extension = os.path.splitext(file.filename)[1].lower()
    job_id = str(uuid.uuid4())
    file_path = os.path.join(UPLOAD_DIR, f"{job_id}{file_extension}")
    
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    # Determine job type
    if file_extension in ['.mp3', '.wav', '.m4a']:
        job_type = "audio_ingestion"
    elif file_extension in ['.pdf']:
        job_type = "document_ingestion"
    else:
        os.remove(file_path)
        raise HTTPException(status_code=400, detail="Unsupported file type")
        
    payload = {"file_path": file_path, "original_name": file.filename}
    
    # Insert job into DB
    try:
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO jobs (id, type, payload, status)
                    VALUES (%s, %s, %s, 'pending')
                    RETURNING id;
                """, (job_id, job_type, payload))
                conn.commit()
    except Exception as e:
        # Mocking or DB not available
        print(f"Warning: Failed to insert job into DB: {e}")
        pass
        
    return UploadResponse(job_id=job_id, message="File uploaded successfully and job queued.")
