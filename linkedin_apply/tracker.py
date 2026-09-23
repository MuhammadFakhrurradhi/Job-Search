"""CSV logs of processed jobs and of questions the answer bank could not handle."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path

from .filters import JobInfo

FIELDS = ["timestamp", "job_id", "status", "title", "company", "location", "url", "reason"]
UNANSWERED_FIELDS = ["timestamp", "job_id", "question", "kind", "options"]

APPLIED = "applied"
DRY_RUN = "dry_run"
SKIPPED = "skipped"
FAILED = "failed"
# stopped on a question the answer bank could not handle; retried on later runs
NEEDS_ANSWERS = "needs_answers"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _append(path: Path, fields: list[str], row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists() or path.stat().st_size == 0
    with path.open("a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        if new:
            writer.writeheader()
        writer.writerow(row)


class Tracker:
    def __init__(self, path: str | Path, unanswered_path: str | Path):
        self.path = Path(path)
        self.unanswered_path = Path(unanswered_path)
        self.seen: dict[str, str] = {}
        if self.path.exists():
            with self.path.open(newline="", encoding="utf-8") as fh:
                for row in csv.DictReader(fh):
                    self.seen[row["job_id"]] = row["status"]

    def already_handled(self, job_id: str) -> bool:
        """Applied or filtered-out jobs are not revisited; dry runs, failures and needs_answers are."""
        return self.seen.get(job_id) in (APPLIED, SKIPPED)

    def record(self, job: JobInfo, status: str, reason: str = "") -> None:
        self.seen[job.job_id] = status
        _append(
            self.path,
            FIELDS,
            {
                "timestamp": _now(),
                "job_id": job.job_id,
                "status": status,
                "title": job.title,
                "company": job.company,
                "location": job.location,
                "url": job.url,
                "reason": reason,
            },
        )

    def record_unanswered(self, job_id: str, question: str, kind: str, options: list[str]) -> None:
        _append(
            self.unanswered_path,
            UNANSWERED_FIELDS,
            {
                "timestamp": _now(),
                "job_id": job_id,
                "question": question,
                "kind": kind,
                "options": " | ".join(options),
            },
        )

    def summary(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for status in self.seen.values():
            counts[status] = counts.get(status, 0) + 1
        return counts
