"""Small deterministic text helpers used by mock services."""

import re

STOP_WORDS = {
    "a",
    "an",
    "and",
    "at",
    "by",
    "for",
    "from",
    "in",
    "is",
    "of",
    "on",
    "the",
    "to",
    "with",
}


def tokens(text: str) -> list[str]:
    normalized = re.sub(r"[^a-z0-9 ]+", " ", text.lower())
    words = normalized.split()
    return sorted({word.rstrip("s") for word in words if len(word) > 1 and word not in STOP_WORDS})

