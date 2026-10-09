"""Deterministic terminology: brand -> generic, lab/diagnosis synonyms -> codes, dose parsing."""
import re
from dataclasses import dataclass, field
from typing import Optional

from rapidfuzz import fuzz, process

FREQUENCIES = {  # shorthand -> times per day (None = as needed)
    "od": 1, "qd": 1, "hs": 1, "bd": 2, "bid": 2, "tds": 3, "tid": 3, "qid": 4, "qds": 4, "sos": None,
}
FREQUENCY_PHRASES = [
    (re.compile(r"\b(twice|two times|2 times)\s+(a|per)?\s*(day|daily)\b"), "BD"),
    (re.compile(r"\b(thrice|three times|3 times)\s+(a|per)?\s*(day|daily)\b"), "TDS"),
    (re.compile(r"\b(four times|4 times)\s+(a|per)?\s*(day|daily)\b"), "QID"),
    (re.compile(r"\b(as needed|when needed|if needed|prn)\b"), "SOS"),
    (re.compile(r"\b(once|one time)\s+(a|per)?\s*(day|daily)\b|\bdaily\b"), "OD"),  # last: "twice daily" is not OD
]
_DOSE = re.compile(r"(\d+(?:\.\d+)?)\s*(mg|mcg|g|ml|units?|iu)?\b", re.I)
_FORM_WORDS = {"tab", "tablet", "tablets", "cap", "capsule", "capsules", "syrup", "inj", "injection", "mg", "mcg", "ml"}
BLANKET_ALLERGY = re.compile(r"^(no\s+)?(any\s+)?(known\s+)?(drug\s+)?(allerg(y|ies)|nka|nkda)$", re.I)
# creatinine µmol/L -> mg/dL
UNIT_CONVERSIONS = {("2160-0", "umol/l"): (1 / 88.4, "mg/dL"), ("2160-0", "µmol/l"): (1 / 88.4, "mg/dL")}


@dataclass
class Terminology:
    brands: dict = field(default_factory=dict)         # brand key -> {generic, rxnorm}
    concepts: list = field(default_factory=list)       # {system, code, display, synonyms[]}
    allergy_groups: dict = field(default_factory=dict)  # member generic -> group
    ranges: list = field(default_factory=list)

    @classmethod
    def load(cls, cur) -> "Terminology":
        cur.execute("select brand, generic, rxnorm from drug_brands")
        brands = {r["brand"].lower(): {"generic": r["generic"], "rxnorm": r["rxnorm"]} for r in cur.fetchall()}
        cur.execute("select system, code, display, synonyms from concepts")
        concepts = cur.fetchall()
        cur.execute("select group_name, member_generic from allergy_groups")
        groups = {r["member_generic"].lower(): r["group_name"] for r in cur.fetchall()}
        cur.execute("select * from reference_ranges")
        return cls(brands, concepts, groups, cur.fetchall())

    # ---- drugs ----
    def match_drug(self, text: str) -> Optional[dict]:
        """{generic, brand, rxnorm} for the first drug name in `text`, exact first then fuzzy."""
        tokens = [t for t in re.findall(r"[a-z][a-z+\-]*", text.lower()) if t not in _FORM_WORDS]
        candidates = tokens + [" ".join(pair) for pair in zip(tokens, tokens[1:])]
        for cand in candidates:
            if cand in self.brands:
                return {"brand": cand, **self.brands[cand]}
        for cand in tokens:
            if len(cand) < 5:
                continue
            hit = process.extractOne(cand, list(self.brands), scorer=fuzz.ratio, score_cutoff=88)
            if hit:
                return {"brand": hit[0], **self.brands[hit[0]]}
        return None

    def allergy_group(self, substance: str) -> Optional[str]:
        return self.allergy_groups.get((substance or "").lower())

    # ---- labs / vitals / diagnoses ----
    def match_concept(self, text: str, systems: tuple) -> Optional[dict]:
        """Longest synonym (whole words) found in `text`, so 'ckd stage 4' beats 'ckd'."""
        lowered = text.lower()
        best, best_len = None, 0
        for concept in self.concepts:
            if concept["system"] not in systems:
                continue
            for term in [concept["display"].lower(), *[s.lower() for s in concept["synonyms"]]]:
                if len(term) > best_len and re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", lowered):
                    best, best_len = concept, len(term)
        return best

    def reference_range(self, loinc: str, sex: Optional[str] = None) -> Optional[dict]:
        rows = [r for r in self.ranges if r["loinc"] == loinc]
        for row in rows:
            if row["sex"] == sex:
                return row
        return next((r for r in rows if r["sex"] == "any"), rows[0] if rows else None)

    # ---- high-recall detector used by the omission check ----
    def detect(self, text: str) -> list[dict]:
        """Every dictionary term visible in `text`: [{kind, key, term}]."""
        lowered = text.lower()
        found = []
        for brand, info in self.brands.items():
            if len(brand) >= 4 and re.search(rf"(?<![a-z]){re.escape(brand)}(?![a-z])", lowered):
                found.append({"kind": "medication", "key": info["generic"], "term": brand})
        for concept in self.concepts:
            for term in [s.lower() for s in concept["synonyms"]]:
                if len(term) >= 5 and re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", lowered):
                    kind = "diagnosis" if concept["system"] == "ICD10" else "lab_result"
                    found.append({"kind": kind, "key": concept["code"], "term": term})
                    break
        if re.search(r"\ballerg(y|ic|ies)\b", lowered):
            found.append({"kind": "allergy", "key": "allergy", "term": "allergy"})
        return found


def parse_frequency(text: str) -> Optional[str]:
    lowered = text.lower()
    for token in re.findall(r"[a-z]+", lowered):
        if token in FREQUENCIES:
            return token.upper()
    for pattern, code in FREQUENCY_PHRASES:
        if pattern.search(lowered):
            return code
    return None


def parse_dose(text: str, hint: Optional[dict] = None) -> dict:
    """{amount, unit, freq, times_per_day, daily_mg} from text like 'Dolo 650 QID'.

    A bare number after a drug name is read as milligrams (Indian Rx convention).
    """
    hint = hint or {}
    amount, unit = hint.get("amount"), hint.get("unit")
    if amount is None:
        for match in _DOSE.finditer(text):
            amount, unit = float(match.group(1)), match.group(2)
            break
    freq = (hint.get("freq") or "").upper() or parse_frequency(text)
    if freq and freq.lower() not in FREQUENCIES:
        freq = parse_frequency(freq) or freq
    dose = {}
    if amount is not None:
        dose["amount"] = float(amount)
        dose["unit"] = (unit or "mg").lower()
    if freq:
        dose["freq"] = freq
        per_day = FREQUENCIES.get(freq.lower())
        if per_day:
            dose["times_per_day"] = per_day
            if dose.get("unit") == "mg":
                dose["daily_mg"] = dose["amount"] * per_day
    return dose
