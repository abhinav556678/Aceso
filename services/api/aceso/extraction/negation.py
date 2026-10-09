"""NegEx-style negation detector used to cross-check the LLM's assertion."""
import re

CUES = {"no", "not", "denies", "denied", "deny", "without", "never", "negative", "none", "nil",
        "nka", "nkda", "n/o", "stopped", "illa", "illai", "kedaiyathu", "nahi", "nahin"}
TERMINATORS = {"but", "however", "except", "although"}
SCOPE_TOKENS = 6


def is_negated(text: str, term: str) -> bool:
    """True when a negation cue's scope covers `term` inside `text`.

    Scope runs forward from the cue for a few tokens and stops at a clause break,
    so "no diabetes, takes metformin" does not negate metformin.
    """
    tokens = re.findall(r"[a-z0-9/+\-]+|[.,;:]", text.lower())
    term_tokens = re.findall(r"[a-z0-9/+\-]+", term.lower())
    if not term_tokens:
        return False
    for i, token in enumerate(tokens):
        if token != term_tokens[0]:
            continue
        for back in range(1, SCOPE_TOKENS + 1):
            if i - back < 0:
                break
            previous = tokens[i - back]
            if previous in TERMINATORS or previous in ".;,":
                break
            if previous in CUES:
                return True
    # "Allergies: none", "Penicillin - nil": cue directly after the term
    return bool(re.search(rf"{re.escape(term_tokens[-1])}\s*[:\-]?\s*(none|nil|no|negative|nka|nkda)\b", text.lower()))


def has_cue(text: str) -> bool:
    return any(token in CUES for token in re.findall(r"[a-z/]+", text.lower()))
