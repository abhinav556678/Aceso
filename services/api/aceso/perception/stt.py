import os
import logging

try:
    from faster_whisper import WhisperModel
except ImportError:
    WhisperModel = None

logger = logging.getLogger(__name__)

# Initialize model once
# Using "tiny" or "base" for faster local processing, assuming CPU
_model = None

def get_model():
    global _model
    if _model is None and WhisperModel is not None:
        logger.info("Loading Whisper model...")
        _model = WhisperModel("tiny", device="cpu", compute_type="int8")
    return _model

def process_audio(payload: dict) -> dict:
    file_path = payload.get("file_path")
    if not file_path or not os.path.exists(file_path):
        raise FileNotFoundError(f"Audio file not found: {file_path}")
    
    model = get_model()
    if model is None:
        # Fallback if whisper isn't installed
        logger.warning("WhisperModel not available. Returning mock data.")
        return {
            "transcript": "Mock transcript because faster_whisper is missing.",
            "segments": [{"start": 0, "end": 2, "text": "Mock transcript"}]
        }

    segments, info = model.transcribe(file_path, beam_size=5, word_timestamps=True)
    
    transcript_segments = []
    full_text = []
    
    for segment in segments:
        full_text.append(segment.text)
        words = []
        if segment.words:
            for word in segment.words:
                words.append({
                    "start": word.start,
                    "end": word.end,
                    "word": word.word
                })
        
        transcript_segments.append({
            "start": segment.start,
            "end": segment.end,
            "text": segment.text,
            "words": words
        })
        
    return {
        "transcript": " ".join(full_text),
        "language": info.language,
        "language_probability": info.language_probability,
        "segments": transcript_segments
    }
