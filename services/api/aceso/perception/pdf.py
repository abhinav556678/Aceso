"""PDF perception: text lines with normalised bounding boxes.

Reads the PDF's text layer (exact boxes, no OCR engine to install). Scanned
PDFs without a text layer are rejected with a clear message; plugging Tesseract
or Azure Document Intelligence in here is the upgrade path.
"""
import re
from datetime import date, datetime
from typing import Optional

import pymupdf as fitz

TEXT_LAYER_CONFIDENCE = 0.99
ROW_TOLERANCE_PT = 3.0


class NoTextLayer(ValueError):
    pass


def parse_pdf(content: bytes) -> list[dict]:
    """One block per visual text row: {page_no, block_idx, text, x, y, w, h, words[]}.

    Coordinates are 0..1 relative to the page so they survive zoom. Words on the
    same baseline are merged into one row, which keeps a lab table row
    ("Creatinine 2.1 mg/dL 0.6-1.1") together as a single evidence unit.
    """
    blocks: list[dict] = []
    with fitz.open(stream=content, filetype="pdf") as doc:
        for page_no, page in enumerate(doc, start=1):
            pw, ph = page.rect.width, page.rect.height
            words = sorted(page.get_text("words"), key=lambda w: (round(w[1]), w[0]))
            rows: list[list] = []
            for word in words:
                if rows and abs(rows[-1][0][1] - word[1]) <= ROW_TOLERANCE_PT:
                    rows[-1].append(word)
                else:
                    rows.append([word])
            for idx, row in enumerate(rows):
                row.sort(key=lambda w: w[0])
                x0, y0 = min(w[0] for w in row), min(w[1] for w in row)
                x1, y1 = max(w[2] for w in row), max(w[3] for w in row)
                blocks.append({
                    "page_no": page_no, "block_idx": idx,
                    "text": " ".join(w[4] for w in row),
                    "x": x0 / pw, "y": y0 / ph, "w": (x1 - x0) / pw, "h": (y1 - y0) / ph,
                    "words": [{"t": w[4], "x": w[0] / pw, "y": w[1] / ph,
                               "w": (w[2] - w[0]) / pw, "h": (w[3] - w[1]) / ph} for w in row],
                })
    if not blocks:
        raise NoTextLayer("This PDF has no text layer (it looks like a scan). "
                          "Scanned-document OCR is not enabled in this prototype.")
    return blocks


def page_count(content: bytes) -> int:
    with fitz.open(stream=content, filetype="pdf") as doc:
        return doc.page_count


def render_page_png(content: bytes, page_no: int, zoom: float = 1.6) -> bytes:
    with fitz.open(stream=content, filetype="pdf") as doc:
        if not 1 <= page_no <= doc.page_count:
            raise IndexError(page_no)
        return doc[page_no - 1].get_pixmap(matrix=fitz.Matrix(zoom, zoom)).tobytes("png")


def union_bbox(boxes: list[dict]) -> dict:
    x0 = min(b["x"] for b in boxes)
    y0 = min(b["y"] for b in boxes)
    x1 = max(b["x"] + b["w"] for b in boxes)
    y1 = max(b["y"] + b["h"] for b in boxes)
    return {"x": round(x0, 4), "y": round(y0, 4), "w": round(x1 - x0, 4), "h": round(y1 - y0, 4)}


def locate(block: dict, needle: str) -> dict:
    """Box of the words inside `block` that spell `needle`; the whole row if not found."""
    tokens = needle.lower().split()
    words = block.get("words") or []
    texts = [w["t"].lower().strip(",;:()") for w in words]
    for i in range(len(texts) - len(tokens) + 1):
        if tokens and texts[i:i + len(tokens)] == [t.strip(",;:()") for t in tokens]:
            return union_bbox(words[i:i + len(tokens)])
    return union_bbox([block])


_MONTHS = "jan feb mar apr may jun jul aug sep oct nov dec".split()
_DATE_PATTERNS = [
    (re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"), lambda m: (int(m[1]), int(m[2]), int(m[3]))),
    (re.compile(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b"), lambda m: (int(m[3]), int(m[2]), int(m[1]))),
    (re.compile(r"\b(\d{1,2})\s+([A-Za-z]{3})[a-z]*\.?,?\s+(\d{4})\b"),
     lambda m: (int(m[3]), _MONTHS.index(m[2].lower()) + 1 if m[2].lower() in _MONTHS else 0, int(m[1]))),
]


def find_document_date(blocks: list[dict]) -> Optional[date]:
    """First plausible date printed near the top of the document, never a birth date."""
    for block in blocks[:25]:
        text = block["text"]
        if re.search(r"\b(dob|birth)\b", text, re.I):
            continue
        for pattern, to_ymd in _DATE_PATTERNS:
            match = pattern.search(text)
            if not match:
                continue
            try:
                found = datetime(*to_ymd(match)).date()
            except ValueError:
                continue
            if date(1990, 1, 1) <= found <= date.today():
                return found
    return None


def guess_kind(blocks: list[dict]) -> str:
    head = " ".join(b["text"] for b in blocks[:12]).lower()
    if "discharge" in head:
        return "discharge"
    if "prescription" in head or re.search(r"\brx\b", head):
        return "prescription"
    if "laboratory" in head or "lab report" in head or "test" in head:
        return "lab_pdf"
    return "other"
