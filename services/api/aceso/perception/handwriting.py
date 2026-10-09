"""A second reader for handwritten pages, which the print OCR misreads with confidence.

TrOCR (a transformer trained on handwritten lines) runs on this machine, on the
GPU when there is one. It needs `pip install torch transformers`; without them,
or with HANDWRITING_OCR=off, scans are read by the print engine alone.

The model always produces some plausible text, even from a scribble, so nothing
it reads is auto-verified: every fact from it is held for the doctor.
"""
import math
import threading

from PIL import Image

from aceso.config import settings

ENGINE = "trocr-handwritten"
BATCH_LINES = 8
MAX_TOKENS = 64

_model = _processor = None
_lock = threading.Lock()


def enabled() -> bool:
    """auto: only with a GPU (a page takes most of a minute on CPU). on: always. off: never."""
    mode = settings.handwriting_ocr.lower()
    if mode == "off":
        return False
    try:
        import torch
        import transformers  # noqa: F401
    except ImportError:
        return False
    return mode == "on" or torch.cuda.is_available()


def read_lines(images: list[Image.Image]) -> list[tuple[str, float]]:
    """(text, confidence) per single-line image. Confidence is the mean per-token probability."""
    global _model, _processor
    import torch
    with _lock:  # one model, one GPU: uploads run in background threads
        if _model is None:
            from transformers import TrOCRProcessor, VisionEncoderDecoderModel
            _processor = TrOCRProcessor.from_pretrained(settings.handwriting_model)
            _model = VisionEncoderDecoderModel.from_pretrained(settings.handwriting_model).eval()
            if torch.cuda.is_available():
                _model = _model.half().cuda()
        pad = _processor.tokenizer.pad_token_id
        results = []
        for start in range(0, len(images), BATCH_LINES):
            pixels = _processor(images=images[start:start + BATCH_LINES], return_tensors="pt").pixel_values
            pixels = pixels.to(_model.device, _model.dtype)
            with torch.inference_mode():
                out = _model.generate(pixels, max_new_tokens=MAX_TOKENS, num_beams=1, do_sample=False,
                                      output_scores=True, return_dict_in_generate=True)
            log_probs = _model.compute_transition_scores(out.sequences, out.scores, normalize_logits=True).float()
            written = out.sequences[:, -log_probs.shape[1]:] != pad
            for text, row, mask in zip(_processor.batch_decode(out.sequences, skip_special_tokens=True), log_probs, written):
                confidence = math.exp(row[mask].mean().item()) if mask.any() else 0.0
                results.append((" ".join(text.split()), round(confidence, 3)))
        return results
