"""Privacy gateway: redact PHI from text before it leaves the machine.

Known limitation: audio sent for transcription cannot be text-redacted. Use
LLM_MODE=onprem (or typed transcripts) when that matters.
"""
import re
from typing import Iterable

PATTERNS = [
    ("EMAIL", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")),
    ("MRN", re.compile(r"\bACE-\d{4}\b", re.I)),
    ("ABHA", re.compile(r"\b\d{2}-?\d{4}-?\d{4}-?\d{4}\b")),
    ("AADHAAR", re.compile(r"\b\d{4}\s?\d{4}\s?\d{4}\b")),
    ("PHONE", re.compile(r"(?<!\d)(?:\+91[\- ]?)?[6-9]\d{9}(?!\d)")),
]


class Redactor:
    """Replaces known patient names and identifier patterns with placeholders."""

    def __init__(self, names: Iterable[str] = ()):
        parts = set()
        for name in names:
            if not name:
                continue
            parts.add(name.strip())
            parts.update(p for p in re.split(r"\s+", name.strip()) if len(p) >= 3)
        # longest first so "Meena Rajan" is replaced before "Meena"
        self._names = sorted(parts, key=len, reverse=True)
        self.count = 0

    def redact(self, text: str) -> str:
        for name in self._names:
            text, n = re.subn(rf"\b{re.escape(name)}\b", "<PERSON>", text, flags=re.I)
            self.count += n
        for label, pattern in PATTERNS:
            text, n = pattern.subn(f"<{label}>", text)
            self.count += n
        return text
