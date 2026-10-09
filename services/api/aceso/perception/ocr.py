"""OCR for scanned PDF pages and photographed documents.

Runs on this machine (RapidOCR: PaddleOCR models on ONNX Runtime), so a page
image never leaves it. Output has the same shape as the PDF text layer: one
block per visual row with normalised boxes, plus the engine's confidence.

Limits: printed text only. Handwriting mostly comes back with low confidence,
which holds the facts for review instead of guessing. Text the detector does
not see at all (very faint or badly out of focus) cannot be flagged.
"""
import io
import math
import threading
from statistics import median
from typing import Optional

from PIL import Image, ImageOps, UnidentifiedImageError

ENGINE = "rapidocr-onnx"
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
UNREADABLE_BELOW = 0.50   # rows under this are flagged for the doctor and never sent for extraction
MAX_SIDE_PX = 2200
INK_CONTRAST = 14         # grey levels darker than its surroundings for a pixel to count as ink

_engine = None
_lock = threading.Lock()


class OCRUnavailable(RuntimeError):
    pass


class NoReadableText(ValueError):
    pass


def _run(image: Image.Image) -> list:
    """[(four corner points, text, score)] for every text region the engine detects,
    plus ("", 0.0) regions for ink it did not read."""
    global _engine
    import numpy as np
    pixels = np.asarray(image)
    with _lock:  # one inference at a time: uploads run in background threads
        if _engine is None:
            try:
                from rapidocr_onnxruntime import RapidOCR
            except ImportError as exc:
                raise OCRUnavailable("Scanned documents need the OCR engine: pip install rapidocr-onnxruntime") from exc
            _engine = RapidOCR()
        result, _ = _engine(pixels, text_score=0.0)  # keep low scores: we flag them ourselves
    detections = [(box, text, float(score)) for box, text, score in result or []]
    return detections + _unread_ink(pixels, detections)


def _unread_ink(pixels, detections: list) -> list:
    """Text-sized marks on the page that no detection covers: a smudged or faded word.

    The engine silently skips what it cannot make out, which would leave a gap
    nobody knows about. Anything here is reported as an unreadable region.
    """
    import cv2
    import numpy as np
    heights = [math.dist(box[0], box[3]) for box, _, _ in detections]
    if not heights:
        return []
    line = median(heights)
    gray = cv2.cvtColor(pixels, cv2.COLOR_RGB2GRAY)
    ink = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV,
                                int(line) * 2 + 1, INK_CONTRAST)
    pad = line * 0.3
    for box, _, _ in detections:  # ignore everything the engine did read
        centre = np.mean(box, axis=0)
        grown = [[x + math.copysign(pad, x - centre[0]), y + math.copysign(pad, y - centre[1])] for x, y in box]
        cv2.fillPoly(ink, [np.array(grown, dtype=np.int32)], 0)
    ink = cv2.morphologyEx(ink, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))  # drop paper grain
    ink = cv2.dilate(ink, np.ones((max(int(line * 0.3), 1), max(int(line), 1)), np.uint8))  # letters -> words
    regions = []
    count, _, stats, _ = cv2.connectedComponentsWithStats(ink)
    for x, y, w, h, _ in stats[1:count]:
        if 0.5 * line <= h <= 2.5 * line and w >= 1.2 * line:  # the size of printed words, not rules or logos
            regions.append(([[x, y], [x + w, y], [x + w, y + h], [x, y + h]], "", 0.0))
    return regions


def open_image(content: bytes) -> Image.Image:
    """The upload as an upright RGB image (phone photos carry their rotation in EXIF)."""
    try:
        image = ImageOps.exif_transpose(Image.open(io.BytesIO(content)))
    except (UnidentifiedImageError, OSError) as exc:
        raise NoReadableText("This file could not be opened as an image.") from exc
    image = image.convert("RGB")
    image.thumbnail((MAX_SIDE_PX, MAX_SIDE_PX))
    return image


def page_png(content: bytes) -> bytes:
    """The page exactly as the OCR saw it, so stored boxes line up in the viewer."""
    out = io.BytesIO()
    open_image(content).save(out, format="PNG")
    return out.getvalue()


def group_rows(detections: list, width: float, height: float) -> list[dict]:
    """Merge detected text regions into visual rows: {block_idx, text, confidence, x, y, w, h, words[]}.

    A lab table comes back as separate cells; cells on one line are joined so
    "Creatinine 2.1 mg/dL" stays a single evidence unit. Lines are found after
    undoing the page tilt, which keeps rows apart on a photo taken at an angle.
    """
    cells = []
    for box, text, score in detections:
        text = " ".join(text.split())
        xs, ys = [p[0] for p in box], [p[1] for p in box]
        cells.append({"text": text, "score": score, "x0": min(xs), "x1": max(xs), "y0": min(ys), "y1": max(ys),
                      "cx": sum(xs) / 4, "cy": sum(ys) / 4,
                      "height": math.dist(box[0], box[3]), "length": math.dist(box[0], box[1]),
                      "angle": math.atan2(box[1][1] - box[0][1], box[1][0] - box[0][0])})
    if not cells:
        return []
    long_cells = [c["angle"] for c in cells if c["text"] and c["length"] > 3 * c["height"]]
    tilt = median(long_cells) if long_cells else 0.0
    for cell in cells:
        cell["along"] = cell["cx"] * math.cos(tilt) + cell["cy"] * math.sin(tilt)
        cell["down"] = cell["cy"] * math.cos(tilt) - cell["cx"] * math.sin(tilt)

    rows: list[list[dict]] = []
    for cell in sorted(cells, key=lambda c: c["down"]):
        last = rows[-1] if rows else None
        if last and abs(cell["down"] - sum(c["down"] for c in last) / len(last)) <= 0.5 * min(cell["height"], last[0]["height"]):
            last.append(cell)
        else:
            rows.append([cell])

    blocks = []
    for idx, row in enumerate(rows):
        row.sort(key=lambda c: c["along"])
        x0, y0 = min(c["x0"] for c in row) / width, min(c["y0"] for c in row) / height
        x1, y1 = max(c["x1"] for c in row) / width, max(c["y1"] for c in row) / height
        # one unread mark makes the whole row unreadable: half a result is not a result
        blocks.append({"block_idx": idx, "text": " ".join(c["text"] for c in row if c["text"]),
                       "confidence": round(min(c["score"] for c in row), 3), "engine": ENGINE,
                       "x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0,
                       "words": [word for cell in row if cell["text"] for word in _words(cell, width, height)]})
    return blocks


def _words(cell: dict, width: float, height: float) -> list[dict]:
    """The engine boxes whole regions; a word's share of the region is estimated from its characters."""
    span, length, words, at = cell["x1"] - cell["x0"], len(cell["text"]), [], 0
    for token in cell["text"].split(" "):
        words.append({"t": token, "x": (cell["x0"] + span * at / length) / width, "y": cell["y0"] / height,
                      "w": span * len(token) / length / width, "h": (cell["y1"] - cell["y0"]) / height})
        at += len(token) + 1
    return words


def read_rows(image: Image.Image, page_no: int = 1) -> list[dict]:
    blocks = group_rows(_run(image), image.width, image.height)
    for block in blocks:
        block["page_no"] = page_no
    return blocks


def parse_image(content: bytes) -> list[dict]:
    """A photographed or scanned single page."""
    blocks = read_rows(open_image(content))
    if not any(b["text"] for b in blocks):
        raise NoReadableText("No text could be found in this image.")
    return blocks


def summary(blocks: list[dict], review_below: float) -> Optional[dict]:
    """Counts for the upload result; None when nothing was read by OCR."""
    rows = [b for b in blocks if b["engine"] == ENGINE]
    if not rows:
        return None
    return {"engine": ENGINE, "rows": len(rows),
            "unreadable": sum(1 for b in rows if b["confidence"] < UNREADABLE_BELOW),
            "low_confidence": sum(1 for b in rows if UNREADABLE_BELOW <= b["confidence"] < review_below)}
