"""Load and validate the YAML configuration."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


class ConfigError(ValueError):
    pass


@dataclass
class SearchConfig:
    keywords: list[str]
    location: str = ""
    workplace: list[str] = field(default_factory=list)
    experience: list[str] = field(default_factory=list)
    job_types: list[str] = field(default_factory=list)
    date_posted: str = "any"
    easy_apply_only: bool = True
    sort_by_recent: bool = True


@dataclass
class FilterConfig:
    title_include: list[str] = field(default_factory=list)
    title_exclude: list[str] = field(default_factory=list)
    company_exclude: list[str] = field(default_factory=list)
    description_exclude: list[str] = field(default_factory=list)


@dataclass
class Limits:
    max_applications_per_run: int = 15
    max_pages_per_search: int = 3
    delay_seconds: tuple[float, float] = (2, 6)
    between_applications_seconds: tuple[float, float] = (20, 60)


@dataclass
class Behavior:
    dry_run: bool = True
    review_before_submit: bool = True
    on_unknown_question: str = "ask"
    unfollow_company: bool = True


@dataclass
class Files:
    tracker: str = "applications.csv"
    unanswered: str = "unanswered_questions.csv"
    screenshots_dir: str = "screenshots"


@dataclass
class Applicant:
    first_name: str = ""
    last_name: str = ""
    email: str = ""
    phone: str = ""
    phone_country: str = ""
    city: str = ""
    resume_path: str = ""
    default_years_experience: int = 2
    default_yes_no: str = ""


@dataclass
class AnswerRule:
    match: str
    answer: str


@dataclass
class Config:
    search: SearchConfig
    filters: FilterConfig
    limits: Limits
    behavior: Behavior
    files: Files
    applicant: Applicant
    answers: list[AnswerRule]
    profile_dir: str = ".browser-profile"
    headless: bool = False


def _pair(value: Any, name: str) -> tuple[float, float]:
    if isinstance(value, (int, float)):
        return (float(value), float(value))
    if isinstance(value, (list, tuple)) and len(value) == 2:
        lo, hi = float(value[0]), float(value[1])
        if lo > hi:
            raise ConfigError(f"{name}: min {lo} is greater than max {hi}")
        return (lo, hi)
    raise ConfigError(f"{name} must be a number or a [min, max] pair")


def _section(raw: dict, key: str) -> dict:
    value = raw.get(key) or {}
    if not isinstance(value, dict):
        raise ConfigError(f"'{key}' must be a mapping")
    return value


def _build(cls, values: dict, name: str):
    try:
        return cls(**values)
    except TypeError as exc:  # unknown or misspelled key
        valid = ", ".join(cls.__dataclass_fields__)
        raise ConfigError(f"'{name}' has an unknown key ({exc}); valid keys: {valid}") from exc


def parse_config(raw: dict) -> Config:
    if not isinstance(raw, dict):
        raise ConfigError("config root must be a mapping")

    search_raw = _section(raw, "search")
    keywords = search_raw.get("keywords") or []
    if isinstance(keywords, str):
        keywords = [keywords]
    if not keywords:
        raise ConfigError("search.keywords must list at least one keyword")
    search = _build(SearchConfig, {**search_raw, "keywords": list(keywords)}, "search")

    limits_raw = _section(raw, "limits")
    limits = Limits(
        max_applications_per_run=int(limits_raw.get("max_applications_per_run", 15)),
        max_pages_per_search=int(limits_raw.get("max_pages_per_search", 3)),
        delay_seconds=_pair(limits_raw.get("delay_seconds", (2, 6)), "limits.delay_seconds"),
        between_applications_seconds=_pair(
            limits_raw.get("between_applications_seconds", (20, 60)),
            "limits.between_applications_seconds",
        ),
    )

    behavior = _build(Behavior, _section(raw, "behavior"), "behavior")
    if behavior.on_unknown_question not in ("ask", "skip"):
        raise ConfigError("behavior.on_unknown_question must be 'ask' or 'skip'")

    answers = []
    for i, rule in enumerate(raw.get("answers") or []):
        if not isinstance(rule, dict) or "match" not in rule or "answer" not in rule:
            raise ConfigError(f"answers[{i}] needs 'match' and 'answer'")
        answers.append(AnswerRule(match=str(rule["match"]), answer=str(rule["answer"])))

    return Config(
        search=search,
        filters=_build(FilterConfig, _section(raw, "filters"), "filters"),
        limits=limits,
        behavior=behavior,
        files=_build(Files, _section(raw, "files"), "files"),
        applicant=_build(Applicant, _section(raw, "applicant"), "applicant"),
        answers=answers,
        profile_dir=str(raw.get("profile_dir", ".browser-profile")),
        headless=bool(raw.get("headless", False)),
    )


def load_config(path: str | Path) -> Config:
    path = Path(path)
    if not path.exists():
        raise ConfigError(f"{path} not found — copy config.example.yaml to {path} first")
    with path.open(encoding="utf-8") as fh:
        return parse_config(yaml.safe_load(fh) or {})
