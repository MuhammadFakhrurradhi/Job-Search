import csv

from linkedin_apply.filters import JobInfo
from linkedin_apply.tracker import APPLIED, DRY_RUN, NEEDS_ANSWERS, SKIPPED, Tracker


def test_tracker_persists_and_dedupes(tmp_path):
    path, unanswered = tmp_path / "apps.csv", tmp_path / "q.csv"
    t = Tracker(path, unanswered)
    t.record(JobInfo("1", title="A", company="X"), APPLIED)
    t.record(JobInfo("2", title="B"), SKIPPED, "title excluded")
    t.record(JobInfo("3", title="C"), DRY_RUN)
    t.record(JobInfo("4", title="D"), NEEDS_ANSWERS)

    reloaded = Tracker(path, unanswered)
    assert reloaded.already_handled("1")
    assert reloaded.already_handled("2")
    assert not reloaded.already_handled("3")  # dry runs are retried for real later
    assert not reloaded.already_handled("4")  # retried once answers are added
    assert not reloaded.already_handled("5")
    assert reloaded.summary() == {APPLIED: 1, SKIPPED: 1, DRY_RUN: 1, NEEDS_ANSWERS: 1}

    rows = list(csv.DictReader(path.open()))
    assert [r["job_id"] for r in rows] == ["1", "2", "3", "4"]
    assert rows[1]["reason"] == "title excluded"


def test_unanswered_log(tmp_path):
    t = Tracker(tmp_path / "a.csv", tmp_path / "q.csv")
    t.record_unanswered("9", "Shift preference", "select", ["Day", "Night"])
    rows = list(csv.DictReader((tmp_path / "q.csv").open()))
    assert rows[0]["question"] == "Shift preference"
    assert rows[0]["options"] == "Day | Night"
