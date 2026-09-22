"""Label masking, so a screenshot of the graph does not leak personal data.

Applied on output only. Plug in another validator by passing any object with
a `mask(text) -> str` method wherever a Masker is accepted.
"""

from __future__ import annotations

import re

DEFAULT_PATTERNS = [
    r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+",                       # email
    r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){3,7}(?: ?[A-Z0-9]{1,4})?\b",  # IBAN
    r"\b\d{3}-\d{2}-\d{4}\b",                            # US social security number
    r"(?<!\w)\+?\d[\d .\-/]{6,}\d(?!\w)",                  # phone or card number, 8+ characters
]

REPLACEMENT = "███"

# ISO dates and timestamps are runs of digits and separators too, so the phone
# pattern would eat them. They are set aside before masking and put back after.
ISO_DATETIME = re.compile(
    r"\b\d{4}-\d{2}-\d{2}"
    r"(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?")

# Private-use characters: they cannot occur in a phone number or an email, so a
# placeholder never merges with the text around it.
_OPEN, _CLOSE = "", ""
_PLACEHOLDER = re.compile(f"{_OPEN}(\\d+){_CLOSE}")


class Masker:
    def __init__(self, patterns: list[str] | None = None) -> None:
        source = DEFAULT_PATTERNS if patterns is None else patterns
        self._patterns = [re.compile(p) for p in source]

    def mask(self, text: str) -> str:
        kept: list[str] = []

        def set_aside(match: re.Match) -> str:
            kept.append(match.group(0))
            return f"{_OPEN}{len(kept) - 1}{_CLOSE}"

        text = ISO_DATETIME.sub(set_aside, text)
        for pattern in self._patterns:
            text = pattern.sub(REPLACEMENT, text)
        return _PLACEHOLDER.sub(lambda m: kept[int(m.group(1))], text)
