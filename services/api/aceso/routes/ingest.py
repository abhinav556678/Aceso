"""Uploads, job progress and the source viewers (PDF page images, audio, transcript)."""
import hashlib
import os
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Response, UploadFile

from aceso.auth import any_role, clinical
from aceso.db import audit, tx
from aceso.extraction.verify import OCR_REVIEW_BELOW
from aceso.perception import ocr, pdf, stt
from aceso.pipeline import create_job, ensure_encounter, run_job

router = APIRouter()
MAX_UPLOAD_BYTES = 25 * 1024 * 1024


@router.post("/ingest")
async def ingest(background: BackgroundTasks, patient_id: str = Form(...), file: UploadFile = File(...),
                 user: dict = Depends(clinical)):
    """Accept a PDF, an audio recording or a typed transcript and start the pipeline."""
    extension = os.path.splitext(file.filename or "")[1].lower()
    if extension == ".pdf" or extension in ocr.IMAGE_EXTENSIONS:
        kind = "document"
    elif extension in stt.AUDIO_EXTENSIONS | stt.TRANSCRIPT_EXTENSIONS:
        kind = "audio"
    else:
        raise HTTPException(400, "Unsupported file type. Upload a PDF, a scan or photo (jpg/png), "
                                 "an audio file (wav/mp3/m4a/webm) or a typed transcript (.txt).")
    content = await file.read()
    if not content:
        raise HTTPException(400, "The file is empty.")
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "File is larger than 25 MB.")
    if extension in ocr.IMAGE_EXTENSIONS:
        try:
            ocr.open_image(content)
        except ocr.NoReadableText as exc:
            raise HTTPException(400, str(exc))
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


@router.get("/jobs/{job_id}/privacy")
def job_privacy(job_id: str, user: dict = Depends(any_role)):
    """What this upload sent to the language model, next to what was removed first.

    Clinical roles see the original text with the removed parts marked. An admin
    audits the outbound side only and never sees the original.
    """
    with tx() as cur:
        cur.execute("select id, kind, payload from jobs where id = %s", (job_id,))
        job = cur.fetchone()
        if not job:
            raise HTTPException(404, "Job not found")
        cur.execute("select seq, model, prompt_version, system_prompt, user_message, sha256, units, redacted, error, "
                    "created_at from llm_calls where job_id = %s order by seq", (job_id,))
        calls = cur.fetchall()
        cur.execute("select id, payload from audit_log where action = 'llm.call' and entity_id = %s "
                    "order by id desc limit 1", (job_id,))
        audit_row = cur.fetchone()
        cur.execute("select payload from audit_log where action = 'stt.call' and entity_id = %s limit 1",
                    (job["payload"]["source_id"],))
        stt_row = cur.fetchone()
        originals = {}
        if user["role"] != "admin":
            refs = [u["ref"] for call in calls for u in call["units"]]
            cur.execute("select id::text as id, text from ocr_blocks where id = any(%s::uuid[]) union all "
                        "select id::text, text from transcript_segments where id = any(%s::uuid[])", (refs, refs))
            originals = {row["id"]: row["text"] for row in cur.fetchall()}
    logged = set((audit_row or {}).get("payload", {}).get("sent_sha256") or [])
    for call in calls:
        stored = hashlib.sha256(f"{call['system_prompt']}\n\n{call['user_message']}".encode()).hexdigest()
        call["intact"] = stored == call["sha256"] and stored in logged
        for unit in call["units"]:
            unit["original"] = originals.get(unit.pop("ref"))
            if unit["original"] is None:
                unit.pop("spans")
    return {"filename": job["payload"].get("filename"), "calls": calls, "shows_original": user["role"] != "admin",
            "audit_id": audit_row["id"] if audit_row else None,
            "audio_sent_unredacted": bool(stt_row), "stt_model": stt_row["payload"].get("model") if stt_row else None}


def _blob(cur, owner_id: str) -> Optional[dict]:
    cur.execute("select mime, content from file_blobs where owner_id = %s", (owner_id,))
    return cur.fetchone()


@router.get("/documents/{document_id}")
def document(document_id: str, user: dict = Depends(clinical)):
    with tx() as cur:
        cur.execute("select id, patient_id, original_name, kind, doc_date, page_count, status, ocr_engine from source_documents "
                    "where id = %s", (document_id,))
        doc = cur.fetchone()
        if not doc:
            raise HTTPException(404, "Document not found")
        cur.execute("select id, page_no, text, confidence, x, y, w, h from ocr_blocks where document_id = %s "
                    "order by page_no, block_idx", (document_id,))
        doc["blocks"] = cur.fetchall()
    doc["thresholds"] = {"unreadable_below": ocr.UNREADABLE_BELOW, "review_below": OCR_REVIEW_BELOW}
    return doc


@router.get("/documents/{document_id}/pages/{page_no}.png")
def document_page(document_id: str, page_no: int, user: dict = Depends(clinical)):
    with tx() as cur:
        blob = _blob(cur, document_id)
    if not blob:
        raise HTTPException(404, "Document file not found")
    content = bytes(blob["content"])
    try:
        if pdf.is_pdf(content):
            png = pdf.render_page_png(content, page_no)
        elif page_no == 1:
            png = ocr.page_png(content)  # an uploaded photo is its own single page
        else:
            raise IndexError(page_no)
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
