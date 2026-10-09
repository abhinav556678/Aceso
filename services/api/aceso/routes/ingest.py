"""Uploads, job progress and the source viewers (PDF page images, audio, transcript)."""
import os
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Response, UploadFile

from aceso.auth import clinical
from aceso.db import audit, tx
from aceso.perception import pdf, stt
from aceso.pipeline import create_job, ensure_encounter, run_job

router = APIRouter()
MAX_UPLOAD_BYTES = 25 * 1024 * 1024


@router.post("/ingest")
async def ingest(background: BackgroundTasks, patient_id: str = Form(...), file: UploadFile = File(...),
                 user: dict = Depends(clinical)):
    """Accept a PDF, an audio recording or a typed transcript and start the pipeline."""
    extension = os.path.splitext(file.filename or "")[1].lower()
    if extension == ".pdf":
        kind = "document"
    elif extension in stt.AUDIO_EXTENSIONS | stt.TRANSCRIPT_EXTENSIONS:
        kind = "audio"
    else:
        raise HTTPException(400, "Unsupported file type. Upload a PDF, an audio file (wav/mp3/m4a/webm) "
                                 "or a typed transcript (.txt).")
    content = await file.read()
    if not content:
        raise HTTPException(400, "The file is empty.")
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "File is larger than 25 MB.")
    with tx(user) as cur:
        cur.execute("select 1 from patients where id = %s", (patient_id,))
        if not cur.fetchone():
            raise HTTPException(404, "Patient not found")
        encounter_id = ensure_encounter(cur, patient_id, user)
        job_id, source_id = create_job(cur, kind, patient_id, encounter_id, file.filename, content, file.content_type)
        audit(cur, "source.upload", kind, source_id, patient_id, {"filename": file.filename, "bytes": len(content)}, user)
    background.add_task(run_job, job_id)
    return {"job_id": job_id, "encounter_id": encounter_id, "kind": kind}


@router.get("/jobs/{job_id}")
def job_status(job_id: str, user: dict = Depends(clinical)):
    with tx() as cur:
        cur.execute("select id, kind, status::text as status, stage, error, result, payload->>'filename' as filename "
                    "from jobs where id = %s", (job_id,))
        job = cur.fetchone()
    if not job:
        raise HTTPException(404, "Job not found")
    return job


def _blob(cur, owner_id: str) -> Optional[dict]:
    cur.execute("select mime, content from file_blobs where owner_id = %s", (owner_id,))
    return cur.fetchone()


@router.get("/documents/{document_id}")
def document(document_id: str, user: dict = Depends(clinical)):
    with tx() as cur:
        cur.execute("select id, patient_id, original_name, kind, doc_date, page_count, status from source_documents "
                    "where id = %s", (document_id,))
        doc = cur.fetchone()
        if not doc:
            raise HTTPException(404, "Document not found")
        cur.execute("select id, page_no, text, confidence, x, y, w, h from ocr_blocks where document_id = %s "
                    "order by page_no, block_idx", (document_id,))
        doc["blocks"] = cur.fetchall()
    return doc


@router.get("/documents/{document_id}/pages/{page_no}.png")
def document_page(document_id: str, page_no: int, user: dict = Depends(clinical)):
    with tx() as cur:
        blob = _blob(cur, document_id)
    if not blob:
        raise HTTPException(404, "Document file not found")
    try:
        png = pdf.render_page_png(bytes(blob["content"]), page_no)
    except IndexError:
        raise HTTPException(404, "No such page")
    return Response(png, media_type="image/png", headers={"Cache-Control": "private, max-age=3600"})


@router.get("/recordings/{recording_id}")
def recording(recording_id: str, user: dict = Depends(clinical)):
    with tx() as cur:
        cur.execute("select id, original_name, duration_ms, language, status from audio_recordings where id = %s",
                    (recording_id,))
        rec = cur.fetchone()
        if not rec:
            raise HTTPException(404, "Recording not found")
        cur.execute("select id, seq, speaker, start_ms, end_ms, text, confidence from transcript_segments "
                    "where recording_id = %s order by seq", (recording_id,))
        rec["segments"] = cur.fetchall()
        blob = _blob(cur, recording_id)
    extension = os.path.splitext(rec["original_name"] or "")[1].lower()
    rec["has_audio"] = bool(blob) and extension in stt.AUDIO_EXTENSIONS
    return rec


@router.get("/recordings/{recording_id}/audio")
def recording_audio(recording_id: str, user: dict = Depends(clinical)):
    with tx() as cur:
        blob = _blob(cur, recording_id)
    if not blob:
        raise HTTPException(404, "Audio not found")
    return Response(bytes(blob["content"]), media_type=blob["mime"] or "audio/wav",
                    headers={"Accept-Ranges": "none"})
