"""Speech perception: audio (or a typed transcript) -> timed segments."""
import math
import re

import httpx

from aceso.config import settings

AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a", ".webm", ".ogg", ".flac"}
TRANSCRIPT_EXTENSIONS = {".txt"}
WORDS_PER_SECOND = 2.5
MAX_SEGMENT_SECONDS = 15


class STTError(RuntimeError):
    pass


def transcribe_audio(content: bytes, filename: str, vocabulary: tuple = ()) -> dict:
    """Whisper via the OpenAI-compatible transcription API (Groq by default).

    Language is auto-detected so code-mixed speech is not forced into one language.
    `vocabulary` (our brand names) is passed as a spelling hint so "Telma" is not heard as "till my".
    """
    if settings.llm_mode == "onprem":
        raise STTError("LLM_MODE=onprem: audio transcription needs an on-prem Whisper, which this "
                       "prototype does not bundle. Upload a typed transcript (.txt) instead.")
    if not settings.llm_api_key:
        raise STTError("LLM_API_KEY is not set in .env")
    try:
        response = httpx.post(
            f"{settings.llm_base_url.rstrip('/')}/audio/transcriptions",
            headers={"Authorization": f"Bearer {settings.llm_api_key}"},
            files={"file": (filename, content)},
            data={"model": settings.stt_model, "response_format": "verbose_json", "temperature": "0",
                  "prompt": ("Doctor-patient consultation in India. Medicines: " + ", ".join(vocabulary))[:800],
                  "timestamp_granularities[]": ["word", "segment"]},
            timeout=180,
        )
    except httpx.HTTPError as exc:
        raise STTError(f"Transcription service unreachable: {exc}") from exc
    if response.status_code != 200:
        raise STTError(f"Transcription HTTP {response.status_code}: {response.text[:300]}")
    body = response.json()
    segments = _sentences(body.get("words") or [], body.get("segments") or [])
    if not segments:
        raise STTError("No speech was recognised in this recording.")
    return {"language": body.get("language"),
            "duration_ms": int(float(body.get("duration") or 0) * 1000) or segments[-1]["end_ms"],
            "segments": segments}


def _sentences(words: list[dict], whisper_segments: list[dict]) -> list[dict]:
    """Cut the transcript into sentence-sized segments from word timestamps.

    Whisper's own segments can span a whole consult; a fact should point at the
    sentence that states it, so we split on sentence ends (or every ~15 s).
    """
    def confidence_at(second: float):
        for seg in whisper_segments:
            if seg["start"] <= second <= seg["end"] and seg.get("avg_logprob") is not None:
                return round(math.exp(seg["avg_logprob"]), 3)
        return None

    if not words:  # no word timing: fall back to Whisper's segments as they are
        return [{"speaker": "unknown", "start_ms": int(seg["start"] * 1000), "end_ms": int(seg["end"] * 1000),
                 "text": seg["text"].strip(), "confidence": confidence_at(seg["start"])}
                for seg in whisper_segments if (seg.get("text") or "").strip()]
    segments, current = [], []
    for word in words:
        current.append(word)
        if word["word"].rstrip().endswith((".", "?", "!")) or word["end"] - current[0]["start"] >= MAX_SEGMENT_SECONDS:
            segments.append(current)
            current = []
    if current:
        segments.append(current)
    return [{"speaker": "unknown", "start_ms": int(group[0]["start"] * 1000), "end_ms": int(group[-1]["end"] * 1000),
             "text": " ".join(w["word"].strip() for w in group), "confidence": confidence_at(group[0]["start"])}
            for group in segments]


_LINE = re.compile(
    r"^\s*(?:\[(\d+):(\d{2})(?:\s*-\s*(\d+):(\d{2}))?\]\s*)?(?:(doctor|dr|patient|pt|nurse)\s*:\s*)?(.+?)\s*$",
    re.I)


def parse_transcript(text: str) -> dict:
    """Typed transcript, one utterance per line: `[00:41-00:45] Doctor: Continue Glycomet 500.`

    Timestamps and speaker are optional; missing times are estimated from word count.
    """
    segments, clock = [], 0
    for line in text.splitlines():
        if not line.strip():
            continue
        m = _LINE.match(line)
        start_min, start_sec, end_min, end_sec, speaker, utterance = m.groups()
        start = (int(start_min) * 60 + int(start_sec)) * 1000 if start_min else clock
        estimated = int(max(1.5, len(utterance.split()) / WORDS_PER_SECOND) * 1000)
        end = (int(end_min) * 60 + int(end_sec)) * 1000 if end_min else start + estimated
        role = (speaker or "unknown").lower()
        role = {"dr": "doctor", "pt": "patient"}.get(role, role)
        segments.append({"speaker": role, "start_ms": start, "end_ms": max(end, start + 500),
                         "text": utterance, "confidence": 1.0})
        clock = segments[-1]["end_ms"] + 300
    if not segments:
        raise STTError("The transcript file is empty.")
    return {"language": "typed", "duration_ms": segments[-1]["end_ms"], "segments": segments}
