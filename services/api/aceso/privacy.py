"""Privacy gateway: redact PHI from text before it leaves the machine.

Every replacement is reported as a span on the original text, so the UI can
show exactly what was removed next to exactly what was sent.

Known limitations: audio sent for transcription cannot be text-redacted (use
LLM_MODE=onprem or typed transcripts when that matters), and a name that is
neither the registered patient name nor introduced by a title or a label
("Dr.", "Name:") is not recognised.
"""
import re
from collections import Counter
from typing import Iterable

# A pattern with a capture group redacts only the group (the label before it stays readable).
# Up to three capitalised words or initials. It stops at punctuation and at the next
# "Label:", so "Dr. Rao. Continue Glycomet" and "Name: Meena Rajan Age: 50" lose only the name.
_WORD = r"(?:[A-Z]\.|[A-Z][A-Za-z'-]*\b)(?!\s*:)"
_NAME = rf"{_WORD}(?:[ \t]*{_WORD}){{0,2}}"
PATTERNS = [
    ("EMAIL", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")),
    ("MRN", re.compile(r"\bACE-\d{4}\b", re.I)),
    ("ABHA", re.compile(r"\b\d{2}-?\d{4}-?\d{4}-?\d{4}\b")),
    ("AADHAAR", re.compile(r"\b\d{4}\s?\d{4}\s?\d{4}\b")),
    ("PHONE", re.compile(r"(?<!\d)(?:\+91[\- ]?)?[6-9]\d{9}(?!\d)")),
    ("DOB", re.compile(r"\b(?:d\.?o\.?b\.?|date of birth|born on)\s*[:\-]?\s*"
                       r"(\d{4}-\d{2}-\d{2}|\d{1,2}[/\-. ]\s?\w{1,9}[/\-. ]\s?\d{2,4})", re.I)),
    ("PERSON", re.compile(rf"\b(?:Dr|Mr|Mrs|Ms|Shri|Smt)\b\.?\s*({_NAME})")),
    # "Patient: Meena Rajan" on a report, but not "Patient: No allergies" in a note
    ("PERSON", re.compile(rf"(?i:\b(?:patient(?:'s)?(?: name)?|name|s/o|d/o|w/o|c/o|attendant|referred by|ref\.? by))"
                          rf"\s*[:\-]\s*(?!(?:No|Not|Nil|None|Yes|Denies|Has|Had|Is|Was|Complains|Reports|Known|Stable)\b)"
                          rf"({_NAME})")),
    ("ADDRESS", re.compile(r"\b(?:address|addr|residence)\s*[:\-]\s*([^\n]{4,120})", re.I)),
]
# Someone saying who they are. "My name is ..." is taken in any spelling; "I am ..." only when
# the next word is capitalised, because "I am diabetic" must stay readable.
INTRODUCTIONS = [
    re.compile(rf"(?i:\bmy name is|\bmy name's)\s+({_NAME}|[A-Za-z][A-Za-z'-]+)"),
    re.compile(rf"(?:\b[Ii] am|\b[Ii]['’]m|\b[Mm]yself|\b[Cc]all me)\s+"
               rf"(?!(?:Not|No|Fine|Okay|OK|Sorry|Here|Diabetic|Allergic|Pregnant|Taking|Having|Feeling|Type|On)\b)"
               rf"({_NAME})"),
]
PATTERNS += [("PERSON", pattern) for pattern in INTRODUCTIONS]


class Redactor:
    """Replaces known patient names and identifier patterns with placeholders."""

    def __init__(self, names: Iterable[str] = ()):
        self._names: list[re.Pattern] = []
        self.counts: Counter = Counter()
        for name in names:
            self.add_name(name)

    def add_name(self, name: str) -> None:
        tokens = re.split(r"\s+", (name or "").strip())
        if not tokens[0]:
            return
        # OCR sometimes drops the space inside a name ("MeenaRajan"), so whitespace is optional
        parts = {r"\s*".join(re.escape(t) for t in tokens), *(re.escape(t) for t in tokens if len(t) >= 3)}
        self._names += [re.compile(rf"(?<![A-Za-z]){p}(?![A-Za-z])", re.I) for p in parts]

    def learn(self, texts: Iterable[str]) -> None:
        """Pick up names people introduce themselves with, so later mentions are removed too."""
        for text in texts:
            for pattern in INTRODUCTIONS:
                for match in pattern.finditer(text):
                    self.add_name(match.group(1))

    @property
    def count(self) -> int:
        return sum(self.counts.values())

    def scan(self, text: str) -> list[tuple[int, int, str]]:
        """Non-overlapping (start, end, label) spans of everything that would be removed."""
        found = [(*m.span(), "PERSON") for pattern in self._names for m in pattern.finditer(text)]
        for label, pattern in PATTERNS:
            for m in pattern.finditer(text):
                start, end = m.span(1) if pattern.groups else m.span()
                end = start + len(text[start:end].rstrip())
                if end > start:
                    found.append((start, end, label))
        spans, cursor = [], 0
        for start, end, label in sorted(found, key=lambda s: (s[0], s[0] - s[1])):  # earliest, then longest
            if start >= cursor:
                spans.append((start, end, label))
                cursor = end
        return spans

    def apply(self, text: str) -> tuple[str, list[tuple[int, int, str]]]:
        """(redacted text, spans on the original). Counts accumulate on the redactor."""
        spans = self.scan(text)
        out, cursor = [], 0
        for start, end, label in spans:
            out += [text[cursor:start], f"<{label}>"]
            cursor = end
            self.counts[label] += 1
        return "".join(out) + text[cursor:], spans

    def redact(self, text: str) -> str:
        return self.apply(text)[0]
