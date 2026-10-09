"""The ingestion pipeline: perception -> extraction -> verification -> fact store -> safety -> SOAP.

Runs in a background thread per upload; progress is written to the `jobs` row
so the UI can poll it. Each stage commits on its own, so a late failure never
leaves facts without provenance.
"""
import hashlib
import logging
import os
import re
from collections import Counter
from datetime import datetime, time, timezone
from typing import Optional

from psycopg.types.json import Jsonb

from aceso import soap
from aceso.db import audit, tx
from aceso.extraction.extract import CHUNK_UNITS, PROMPT_VERSION, extract
from aceso.extraction.terminology import Terminology
from aceso.extraction.verify import OCR_REVIEW_BELOW, find_omissions, verify
from aceso.llm.client import LLMError, RecordingLLM, get_llm
from aceso.perception import ocr, pdf, stt
from aceso.privacy import Redactor
from aceso.safety import engine

logger = logging.getLogger(__name__)


def ensure_encounter(cur, patient_id, user: Optional[dict] = None):
    """The patient's open visit, creating one if every visit is already signed."""
    cur.execute("select id from encounters where patient_id = %s and status <> 'signed' "
                "order by started_at desc limit 1", (patient_id,))
    row = cur.fetchone()
    if row:
        return row["id"]
    doctor_id = user["id"] if user and user["role"] == "doctor" else None
    cur.execute("insert into encounters(patient_id, doctor_id, chief_complaint) values (%s, %s, 'Visit') returning id",
                (patient_id, doctor_id))
    return cur.fetchone()["id"]


def create_job(cur, kind: str, patient_id, encounter_id, filename: str, content: bytes, mime: Optional[str]):
    """Register the upload (source row + file + queued job) in one transaction."""
    if kind == "document":
        cur.execute("insert into source_documents(patient_id, encounter_id, storage_path, kind, original_name, status) "
                    "values (%s, %s, %s, 'other', %s, 'uploaded') returning id",
                    (patient_id, encounter_id, f"db:file_blobs/{filename}", filename))
    else:
        cur.execute("insert into audio_recordings(encounter_id, storage_path, original_name, status) "
                    "values (%s, %s, %s, 'uploaded') returning id",
                    (encounter_id, f"db:file_blobs/{filename}", filename))
    source_id = cur.fetchone()["id"]
    cur.execute("insert into file_blobs(owner_id, owner_kind, mime, content) values (%s, %s, %s, %s)",
                (source_id, "document" if kind == "document" else "audio", mime, content))
    cur.execute("insert into jobs(kind, payload, status, stage, patient_id, encounter_id) "
                "values (%s, %s, 'queued', 'Queued', %s, %s) returning id",
                (f"perceive_{kind}", {"source_id": str(source_id), "filename": filename}, patient_id, encounter_id))
    return cur.fetchone()["id"], source_id


def _stage(job_id, stage: str, status: str = "running", error: Optional[str] = None, result: Optional[dict] = None):
    with tx() as cur:
        cur.execute("update jobs set stage = %s, status = %s::job_status, error = %s, "
                    "result = coalesce(%s, result), locked_at = now() where id = %s",
                    (stage, status, error, result, job_id))


def run_job(job_id, llm=None) -> None:
    """Entry point for the background task. Never raises: failures land on the job row.

    `llm` overrides the configured model (the demo seeder passes a scripted one).
    """
    with tx() as cur:
        cur.execute("select * from jobs where id = %s", (job_id,))
        job = cur.fetchone()
    source_id, table = job["payload"]["source_id"], None
    try:
        if job["kind"] == "perceive_document":
            table = "source_documents"
            result = _run_document(job, source_id, llm)
        else:
            table = "audio_recordings"
            result = _run_audio(job, source_id, llm)
        _stage(job_id, "Done", "done", result=result)
    except Exception as exc:  # noqa: BLE001 - the job row is the error channel
        logger.exception("Job %s failed", job_id)
        message = str(exc) or exc.__class__.__name__
        with tx() as cur:
            cur.execute(f"update {table} set status = 'failed', error = %s where id = %s", (message, source_id))
        _stage(job_id, "Failed", "failed", error=message)


def _load_blob(source_id) -> bytes:
    with tx() as cur:
        cur.execute("select content from file_blobs where owner_id = %s", (source_id,))
        return bytes(cur.fetchone()["content"])


def _run_document(job: dict, source_id, llm=None) -> dict:
    _stage(job["id"], "Reading document layout")
    content = _load_blob(source_id)
    scanning = lambda: _stage(job["id"], "Reading the scan with OCR on this machine")
    if pdf.is_pdf(content):
        blocks = pdf.parse_pdf(content, on_scan=scanning)
    else:
        scanning()
        blocks = ocr.parse_image(content)
    doc_date = pdf.find_document_date(blocks)
    with tx() as cur:
        cur.execute("update source_documents set status = 'ocr_running', kind = %s, doc_date = %s, page_count = %s, "
                    "ocr_engine = %s where id = %s",
                    (pdf.guess_kind(blocks), doc_date, max(b["page_no"] for b in blocks),
                     "+".join(sorted({b["engine"] for b in blocks})), source_id))
        for block in blocks:
            cur.execute(
                "insert into ocr_blocks(document_id, page_no, block_idx, kind, text, confidence, x, y, w, h, table_ref) "
                "values (%s, %s, %s, 'line', %s, %s, %s, %s, %s, %s, %s) returning id",
                (source_id, block["page_no"], block["block_idx"], block["text"], block["confidence"],
                 block["x"], block["y"], block["w"], block["h"], {"words": block["words"]}))
            block["id"] = cur.fetchone()["id"]
    # a row the OCR could not read is shown to the doctor as unreadable; it is not evidence
    readable = [b for b in blocks if b["confidence"] >= ocr.UNREADABLE_BELOW]
    units = [{"id": f"B{i}", "kind": "block", "db_id": b["id"], "text": b["text"], "page_no": b["page_no"],
              "confidence": b["confidence"], "ocr": b["engine"] == ocr.ENGINE, "block": b}
             for i, b in enumerate(readable, start=1)]
    effective = datetime.combine(doc_date, time(12), tzinfo=timezone.utc) if doc_date else datetime.now(timezone.utc)
    result = _extract_and_store(job, units, "document", source_id, effective, llm)
    result.update(document_id=str(source_id), ocr=ocr.summary(blocks, OCR_REVIEW_BELOW))
    with tx() as cur:
        cur.execute("update source_documents set status = 'done' where id = %s", (source_id,))
    return result


def _run_audio(job: dict, source_id, llm=None) -> dict:
    filename = job["payload"]["filename"]
    content = _load_blob(source_id)
    if os.path.splitext(filename)[1].lower() in stt.TRANSCRIPT_EXTENSIONS:
        _stage(job["id"], "Reading transcript")
        transcript = stt.parse_transcript(content.decode("utf-8", errors="replace"))
    else:
        _stage(job["id"], "Transcribing audio")
        with tx() as cur:
            cur.execute("update audio_recordings set status = 'transcribing' where id = %s", (source_id,))
            audit(cur, "stt.call", "audio_recording", source_id, job["patient_id"],
                  {"model": stt.settings.stt_model, "bytes_out": len(content), "redacted": False})
        with tx() as cur:
            brands = tuple(sorted(b.capitalize() for b in Terminology.load(cur).brands))
        transcript = stt.transcribe_audio(content, filename, brands)
    with tx() as cur:
        cur.execute("update audio_recordings set status = 'done', duration_ms = %s, language = %s where id = %s",
                    (transcript["duration_ms"], transcript["language"], source_id))
        for seq, segment in enumerate(transcript["segments"], start=1):
            cur.execute(
                "insert into transcript_segments(recording_id, seq, speaker, start_ms, end_ms, text, lang, confidence) "
                "values (%s, %s, %s, %s, %s, %s, %s, %s) returning id",
                (source_id, seq, segment["speaker"], segment["start_ms"], segment["end_ms"], segment["text"],
                 transcript["language"], segment["confidence"]))
            segment["id"] = cur.fetchone()["id"]
    units = [{"id": f"S{i}", "kind": "segment", "db_id": s["id"], "text": s["text"], "speaker": s["speaker"],
              "start_ms": s["start_ms"], "end_ms": s["end_ms"], "confidence": s["confidence"]}
             for i, s in enumerate(transcript["segments"], start=1)]
    return _extract_and_store(job, units, "audio", source_id, datetime.now(timezone.utc), llm)


def _extract_and_store(job: dict, units: list[dict], source: str, source_id, effective_at: datetime,
                       llm=None) -> dict:
    patient_id, encounter_id = job["patient_id"], job["encounter_id"]
    with tx() as cur:
        term = Terminology.load(cur)
        cur.execute("select full_name, sex from patients where id = %s", (patient_id,))
        patient = cur.fetchone()

    redactor = Redactor([patient["full_name"]])
    for unit in units:
        unit["sent"], unit["redactions"] = redactor.apply(unit["text"])
    _stage(job["id"], f"Redacted {redactor.count} identifier{'' if redactor.count == 1 else 's'} · extracting facts")
    warning, drafts, rejected, recorder = None, [], [], None
    try:
        recorder = RecordingLLM(llm or get_llm())
        drafts, rejected = extract(recorder, units, term)
    except LLMError as exc:
        # the note is never blocked by the model: dictionary detections go to the review queue instead
        warning = f"Language model unavailable ({exc}). Dictionary detections were queued for manual review."
        logger.warning(warning)
    if recorder and recorder.sent:
        with tx() as cur:
            hashes = _store_llm_calls(cur, job, recorder, units, failed=warning)
            audit(cur, "llm.call", "job", job["id"], patient_id,
                  {"model": recorder.id, "prompt": PROMPT_VERSION, "units": len(units),
                   "entities_redacted": redactor.count, "redacted": dict(redactor.counts),
                   "sent_sha256": hashes, "facts_rejected": len(rejected), "failed": bool(warning)})

    _stage(job["id"], f"Verifying {len(drafts)} facts")
    facts = [verify(d, term, patient["sex"]) for d in drafts]
    omissions = find_omissions(units, facts, term)
    with tx() as cur:
        for fact in facts + omissions:
            _insert_fact(cur, fact, patient_id, encounter_id, source, source_id, effective_at)

    _stage(job["id"], "Running safety checks")
    with tx() as cur:
        engine.evaluate(cur, patient_id, encounter_id)
    with tx() as cur:
        soap.regenerate(cur, encounter_id)
    return {"facts": len(facts), "verified": sum(1 for f in facts if f["state"] == "verified"),
            "needs_attention": sum(1 for f in facts if f["state"] != "verified"),
            "possible_omissions": len(omissions), "rejected_model_outputs": len(rejected), "warning": warning,
            "redacted": redactor.count, "llm_calls": len(recorder.sent) if recorder else 0}


def _store_llm_calls(cur, job: dict, recorder: RecordingLLM, units: list[dict], failed: Optional[str]) -> list[str]:
    """Keep exactly what was handed to the model, one row per call. Returns each call's SHA-256.

    The hashes go into the audit chain, so a stored payload that is edited later no longer matches.
    Originals are not copied here: each unit points at its source row.
    """
    hashes = []
    for seq, call in enumerate(recorder.sent):
        chunk = units[seq * CHUNK_UNITS:(seq + 1) * CHUNK_UNITS]
        digest = hashlib.sha256(f"{call['system']}\n\n{call['user']}".encode()).hexdigest()
        hashes.append(digest)
        last = seq == len(recorder.sent) - 1
        cur.execute(
            "insert into llm_calls(job_id, patient_id, seq, model, prompt_version, system_prompt, user_message, "
            "sha256, units, redacted, error) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (job["id"], job["patient_id"], seq, recorder.id, PROMPT_VERSION, call["system"], call["user"], digest,
             Jsonb([{"unit": u["id"], "kind": u["kind"], "ref": str(u["db_id"]), "sent": u["sent"],
                     "spans": u["redactions"]} for u in chunk]),
             dict(Counter(label for u in chunk for _, _, label in u["redactions"])),
             failed if failed and last else None))
    return hashes


def _needle(fact: dict) -> str:
    """The words to box inside a cited row: the printed value for results, the quote otherwise."""
    if fact.get("stated_value") is not None:
        value = re.escape(format(fact["stated_value"], "g"))
        printed = re.search(rf"(?<![\d.]){value}0*(?![\d.])", fact["evidence_text"])
        if printed:
            return printed.group(0)
    return fact["raw_text"]


def _insert_fact(cur, fact: dict, patient_id, encounter_id, source: str, source_id, effective_at: datetime):
    units = fact["units"]
    provenance = dict(recording_id=None, segment_ids=None, audio_start_ms=None, audio_end_ms=None,
                      document_id=None, block_ids=None, page_no=None, bbox=None)
    if source == "document":
        bbox = (pdf.locate(units[0]["block"], _needle(fact)) if len(units) == 1
                else pdf.union_bbox([u["block"] for u in units if u["page_no"] == units[0]["page_no"]]))
        provenance.update(document_id=source_id, block_ids=[str(u["db_id"]) for u in units],
                          page_no=units[0]["page_no"], bbox=bbox)
    else:
        provenance.update(recording_id=source_id, segment_ids=[str(u["db_id"]) for u in units],
                          audio_start_ms=min(u["start_ms"] for u in units),
                          audio_end_ms=max(u["end_ms"] for u in units))
    cur.execute(
        """insert into facts(patient_id, encounter_id, fact_type, assertion, code_system, code, display, raw_text,
                             value_num, value_text, unit, dose, effective_at, state, confidence, confidence_parts,
                             needs_attention, attention_reasons, source, recording_id, segment_ids, audio_start_ms,
                             audio_end_ms, document_id, block_ids, page_no, bbox, verification)
           values (%s, %s, %s::fact_type, %s::fact_assertion, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::fact_state,
                   %s, %s, %s, %s, %s::source_kind, %s, %s::uuid[], %s, %s, %s, %s::uuid[], %s, %s, %s)
           returning id""",
        (patient_id, encounter_id, fact["fact_type"], fact["assertion"], fact["code_system"], fact["code"],
         fact["display"], fact["raw_text"], fact["value_num"], fact["value_text"], fact["unit"], fact["dose"],
         effective_at, fact["state"], fact["confidence"], fact["confidence_parts"], fact["needs_attention"],
         fact["attention_reasons"] or None, source, provenance["recording_id"], provenance["segment_ids"],
         provenance["audio_start_ms"], provenance["audio_end_ms"], provenance["document_id"],
         provenance["block_ids"], provenance["page_no"], provenance["bbox"], fact["verification"]))
    return cur.fetchone()["id"]
