# 02 — Audio & PDF Ingestion Pipeline

**What to build:** The system can accept raw PDF or Audio uploads from the UI, process them in the background to extract raw text (STT for audio, OCR with bounding boxes for documents), and update the UI in real-time as the processing finishes.

**Blocked by:** 01 — S1 Patient Golden Fact Viewer

**Status:** ready-for-agent

- [x] FastAPI job worker skeleton is running and claiming jobs.
- [x] Document perception worker processes PDFs via Azure/Tesseract to create `ocr_blocks` with bounding boxes.
- [x] Audio perception worker processes audio via Whisper to create `transcript_segments` with word-level timestamps.
- [x] UI reflects the upload and ingestion status via Supabase Realtime.
