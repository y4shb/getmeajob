from __future__ import annotations

from collections.abc import Callable

from getmeajob.files import read_jsonl
from getmeajob.models import AppStatus, Job
from getmeajob.rank.score import job_text, rank_all
from getmeajob.store import JobStore, StatusLog
from getmeajob.workspace import Workspace

MakeJob = Callable[..., Job]

GOOD = (
    "We want 3-5 years of professional experience. You will work in Python with PostgreSQL "
    "and Kubernetes. " * 4
)
BAD = "8+ years of experience leading platform work. " * 6


def _store(ws: Workspace, jobs: list[Job]) -> None:
    JobStore(ws).upsert(jobs, "2026-11-27T09:00:00+00:00")


def test_rank_all_writes_every_job_and_shortlists_the_good_ones(
    demo_ws: Workspace, make_job: MakeJob
) -> None:
    good = make_job("Senior Backend Engineer", key="greenhouse:examplecorp:1001")
    bad = make_job("Staff Platform Engineer", key="greenhouse:examplecorp:1002")
    _store(demo_ws, [good, bad])
    demo_ws.jd_path(good.key).write_text(GOOD, encoding="utf-8")
    demo_ws.jd_path(bad.key).write_text(BAD, encoding="utf-8")
    results = rank_all(demo_ws)
    assert [r.key for r in results] == [good.key, bad.key]
    rows = read_jsonl(demo_ws.ranked_path)
    assert [r["key"] for r in rows] == [good.key, bad.key]
    assert rows[0]["eligible"] is True and rows[1]["eligible"] is False
    status = StatusLog(demo_ws)
    assert status.current(good.key) == AppStatus.shortlisted
    assert status.current(bad.key) is None


def test_min_score_only_trims_the_returned_list(demo_ws: Workspace, make_job: MakeJob) -> None:
    _store(demo_ws, [make_job(key="greenhouse:examplecorp:1")])
    assert rank_all(demo_ws, min_score=101) == []
    assert len(read_jsonl(demo_ws.ranked_path)) == 1


def test_rank_twice_changes_nothing(demo_ws: Workspace, make_job: MakeJob) -> None:
    job = make_job("Senior Backend Engineer", key="greenhouse:examplecorp:1001")
    _store(demo_ws, [job])
    demo_ws.jd_path(job.key).write_text(GOOD, encoding="utf-8")
    rank_all(demo_ws)
    first = demo_ws.ranked_path.read_text(encoding="utf-8")
    rank_all(demo_ws)
    assert demo_ws.ranked_path.read_text(encoding="utf-8") == first
    assert len(read_jsonl(demo_ws.root / "data" / "events.jsonl")) == 1


def test_closed_jobs_are_not_ranked(demo_ws: Workspace, make_job: MakeJob) -> None:
    job = make_job(key="greenhouse:examplecorp:1")
    _store(demo_ws, [job])
    JobStore(demo_ws).mark_closed([job.key], "2026-11-27T11:00:00+00:00")
    assert rank_all(demo_ws) == []


def test_job_text_falls_back_to_the_stored_description(
    demo_ws: Workspace, make_job: MakeJob
) -> None:
    job = make_job(description="<p>3+ years of experience</p><ul><li>Python</li></ul>")
    text = job_text(demo_ws, job)
    assert "3+ years of experience" in text
    assert "<p>" not in text
    demo_ws.jd_path(job.key).write_text("From the file", encoding="utf-8")
    assert job_text(demo_ws, job) == "From the file"
