"""Build LinkedIn job-search URLs from the search config."""

from __future__ import annotations

import re
from urllib.parse import urlencode

from .config import SearchConfig

BASE_URL = "https://www.linkedin.com/jobs/search/"
PAGE_SIZE = 25

DATE_POSTED = {"any": None, "past_24h": "r86400", "past_week": "r604800", "past_month": "r2592000"}
EXPERIENCE = {
    "internship": "1",
    "entry": "2",
    "associate": "3",
    "mid_senior": "4",
    "director": "5",
    "executive": "6",
}
JOB_TYPES = {
    "full_time": "F",
    "part_time": "P",
    "contract": "C",
    "temporary": "T",
    "internship": "I",
    "volunteer": "V",
    "other": "O",
}
WORKPLACE = {"onsite": "1", "remote": "2", "hybrid": "3"}

_JOB_ID_RE = re.compile(r"/jobs/view/(\d+)|currentJobId=(\d+)")


def _codes(values: list[str], table: dict[str, str], name: str) -> str:
    codes = []
    for value in values:
        key = value.strip().lower()
        if key not in table:
            raise ValueError(f"unknown {name} '{value}', expected one of {sorted(table)}")
        codes.append(table[key])
    return ",".join(codes)


def build_search_url(cfg: SearchConfig, keyword: str, page: int = 0) -> str:
    params: dict[str, str] = {"keywords": keyword}
    if cfg.location:
        params["location"] = cfg.location
    if cfg.easy_apply_only:
        params["f_AL"] = "true"
    if cfg.date_posted not in DATE_POSTED:
        raise ValueError(f"unknown date_posted '{cfg.date_posted}', expected one of {sorted(DATE_POSTED)}")
    if DATE_POSTED[cfg.date_posted]:
        params["f_TPR"] = DATE_POSTED[cfg.date_posted]
    if cfg.experience:
        params["f_E"] = _codes(cfg.experience, EXPERIENCE, "experience")
    if cfg.job_types:
        params["f_JT"] = _codes(cfg.job_types, JOB_TYPES, "job type")
    if cfg.workplace:
        params["f_WT"] = _codes(cfg.workplace, WORKPLACE, "workplace")
    if cfg.sort_by_recent:
        params["sortBy"] = "DD"
    if page:
        params["start"] = str(page * PAGE_SIZE)
    return f"{BASE_URL}?{urlencode(params)}"


def job_url(job_id: str) -> str:
    return f"https://www.linkedin.com/jobs/view/{job_id}/"


def extract_job_id(href: str) -> str | None:
    match = _JOB_ID_RE.search(href or "")
    if not match:
        return None
    return match.group(1) or match.group(2)
