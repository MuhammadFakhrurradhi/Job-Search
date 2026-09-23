"""Answer application questions from the configured answer bank."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .config import Applicant, AnswerRule

_YES_NO = {"yes", "no"}
_PLACEHOLDERS = {"", "select an option", "select", "choose", "please select", "--"}


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip().lower()


def real_options(options: list[str]) -> list[str]:
    """Drop placeholder entries such as 'Select an option'."""
    return [o for o in options if normalize(o) not in _PLACEHOLDERS]


def pick_option(answer: str, options: list[str]) -> str | None:
    """Return the option best matching ``answer``: exact, then prefix, then substring."""
    target = normalize(answer)
    candidates = real_options(options)
    if not target or not candidates:
        return None
    for option in candidates:
        if normalize(option) == target:
            return option
    for option in candidates:
        if normalize(option).startswith(target):
            return option
    for option in candidates:
        norm = normalize(option)
        if target in norm or norm in target:
            return option
    return None


@dataclass
class Question:
    label: str
    kind: str  # text, number, textarea, select, radio, checkbox
    options: list[str]


class AnswerBank:
    def __init__(self, rules: list[AnswerRule], applicant: Applicant):
        self.rules = [(re.compile(r.match, re.IGNORECASE), r.answer) for r in rules]
        self.applicant = applicant
        self.learned: dict[str, str] = {}

    def remember(self, label: str, answer: str) -> None:
        """Keep an answer typed in the terminal for the rest of this run."""
        self.learned[normalize(label)] = answer

    def _profile_answer(self, label: str) -> str | None:
        a = self.applicant
        lab = normalize(label)
        table = [
            (r"first name", a.first_name),
            (r"last name|surname|family name", a.last_name),
            (r"e-?mail", a.email),
            (r"country code|phone country", a.phone_country),
            (r"mobile|phone", a.phone),
            (r"city|location", a.city),
        ]
        for pattern, value in table:
            if value and re.search(pattern, lab):
                return value
        return None

    def answer(self, q: Question) -> str | None:
        """Return the answer to put in the field (an option text for choices), or None."""
        raw = self.learned.get(normalize(q.label))
        if raw is None:
            raw = next((ans for pat, ans in self.rules if pat.search(q.label)), None)
        if raw is None:
            raw = self._profile_answer(q.label)
        if raw is None and q.kind in ("number", "text") and re.search(r"how many|years", q.label, re.I):
            raw = str(self.applicant.default_years_experience)

        options = real_options(q.options)
        if q.kind in ("select", "radio"):
            if raw is None and self.applicant.default_yes_no and {normalize(o) for o in options} <= _YES_NO:
                raw = self.applicant.default_yes_no
            return pick_option(raw, options) if raw is not None else None

        if raw is not None and q.kind == "number":
            number = re.search(r"-?\d+(?:\.\d+)?", raw.replace(",", ""))
            return number.group(0) if number else None
        return raw
