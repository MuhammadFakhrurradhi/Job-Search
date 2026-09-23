"""Decide whether a job is worth applying to."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .config import FilterConfig


@dataclass
class JobInfo:
    job_id: str
    title: str = ""
    company: str = ""
    location: str = ""
    description: str = ""
    url: str = ""


def _compile(patterns: list[str]) -> list[re.Pattern]:
    return [re.compile(p, re.IGNORECASE) for p in patterns]


class JobFilter:
    def __init__(self, cfg: FilterConfig):
        self.title_include = _compile(cfg.title_include)
        self.title_exclude = _compile(cfg.title_exclude)
        self.description_exclude = _compile(cfg.description_exclude)
        self.company_exclude = {c.strip().lower() for c in cfg.company_exclude}

    def check_listing(self, job: JobInfo) -> str | None:
        """Checks that need only title and company. Returns a skip reason or None."""
        if self.title_include and not any(p.search(job.title) for p in self.title_include):
            return "title does not match title_include"
        for pattern in self.title_exclude:
            if pattern.search(job.title):
                return f"title matches exclude '{pattern.pattern}'"
        if job.company.strip().lower() in self.company_exclude:
            return f"company '{job.company}' is excluded"
        return None

    def check(self, job: JobInfo) -> str | None:
        """Full check including the description. Returns a skip reason or None."""
        reason = self.check_listing(job)
        if reason:
            return reason
        for pattern in self.description_exclude:
            if pattern.search(job.description):
                return f"description matches exclude '{pattern.pattern}'"
        return None
