from __future__ import annotations

import dataclasses

import pytest

from getmeajob.errors import StoreError
from getmeajob.models import (
    ApplyMode,
    ApplyStatus,
    AppStatus,
    Job,
    LedgerEntry,
    QueueKind,
)
from getmeajob.store import (
    JobStore,
    Ledger,
    QueueLog,
    StatusLog,
    append_jsonl,
    now_iso,
    read_json,
    read_jsonl,
    write_json_atomic,
)
from getmeajob.workspace import Workspace

T1 = "2026-11-01T00:00:00Z"
T2 = "2026-11-02T00:00:00Z"
KEY = "greenhouse:examplecorp:1001"


def _job(job_id: str, title: str = "Backend Engineer", **extra: object) -> Job:
    return Job(
        key=Job.make_key("greenhouse", "examplecorp", job_id),
        ats="greenhouse",
        board="examplecorp",
        job_id=job_id,
        company="Example Corp",
        title=title,
        url=f"https://boards.example.com/{job_id}",
        description="Python and Postgres.",
        **extra,  # type: ignore[arg-type]
    )


def test_now_iso_format() -> None:
    value = now_iso()
    assert len(value) == 20 and value.endswith("Z") and value[10] == "T"


def test_upsert_new_changed_unchanged(tmp_ws: Workspace) -> None:
    store = JobStore(tmp_ws)
    first = store.upsert([_job("1"), _job("2"), _job("3")], T1)
    assert first.new == [f"greenhouse:examplecorp:{n}" for n in "123"]
    assert first.changed == [] and first.unchanged == []

    second = store.upsert(
        [_job("1"), _job("2", title="Senior Backend Engineer"), _job("3"), _job("4")], T2
    )
    assert second.new == ["greenhouse:examplecorp:4"]
    assert second.changed == ["greenhouse:examplecorp:2"]
    assert second.unchanged == ["greenhouse:examplecorp:1", "greenhouse:examplecorp:3"]

    third = store.upsert([dataclasses.replace(_job("1"), description="")], T2)
    assert third.unchanged == ["greenhouse:examplecorp:1"]  # an empty description keeps the old
    kept = store.get("greenhouse:examplecorp:1")
    assert kept is not None and kept.description == "Python and Postgres."
    assert len(store.all()) == 4


def test_upsert_keeps_first_seen(tmp_ws: Workspace) -> None:
    store = JobStore(tmp_ws)
    store.upsert([_job("1")], T1)
    store.upsert([_job("1", location="Remote - Worldwide")], T2)
    job = store.get("greenhouse:examplecorp:1")
    assert job is not None
    assert job.first_seen == T1 and job.last_seen == T2
    assert job.location == "Remote - Worldwide"


def test_mark_closed_and_reopen_counts_as_changed(tmp_ws: Workspace) -> None:
    store = JobStore(tmp_ws)
    store.upsert([_job("1"), _job("2")], T1)
    assert store.mark_closed(["greenhouse:examplecorp:1", "missing:key:x"], T2) == [
        "greenhouse:examplecorp:1"
    ]
    assert store.mark_closed(["greenhouse:examplecorp:1"], T2) == []
    assert store.upsert([_job("1")], T2).changed == ["greenhouse:examplecorp:1"]


def test_status_forward_only_for_automatic(tmp_ws: Workspace) -> None:
    log = StatusLog(tmp_ws)
    assert log.record(KEY, AppStatus.discovered, "source")
    assert log.record(KEY, AppStatus.planned, "plan")
    assert not log.record(KEY, AppStatus.shortlisted, "rank")  # backwards
    assert not log.record(KEY, AppStatus.planned, "plan")  # same status again: no-op
    assert log.current(KEY) == AppStatus.planned
    assert not log.record(KEY, AppStatus.rejected, "apply")  # automatic side state
    assert log.record(KEY, AppStatus.applied, "apply")
    assert log.record(KEY, AppStatus.ghosted, "liveness")
    assert not log.record(KEY, AppStatus.interviewing, "apply")  # never out of a side state
    assert [e.status for e in log.history(KEY)] == [
        AppStatus.discovered,
        AppStatus.planned,
        AppStatus.applied,
        AppStatus.ghosted,
    ]


def test_status_manual_can_go_back(tmp_ws: Workspace) -> None:
    log = StatusLog(tmp_ws)
    log.record(KEY, AppStatus.interviewing, "manual")
    assert log.record(KEY, AppStatus.applied, "manual", note="moved back by hand")
    assert log.record(KEY, AppStatus.rejected, "xlsx")
    assert log.record(KEY, AppStatus.screening, "manual")  # out of a side state by hand
    assert log.current(KEY) == AppStatus.screening
    assert StatusLog(tmp_ws).current_all() == {KEY: AppStatus.screening}  # read back from disk


def test_closed_not_after_applied(tmp_ws: Workspace) -> None:
    log = StatusLog(tmp_ws)
    other = "lever:demowidgets:x"
    log.record(other, AppStatus.shortlisted, "rank")
    assert log.record(other, AppStatus.closed, "liveness")
    log.record(KEY, AppStatus.applied, "apply")
    assert not log.record(KEY, AppStatus.closed, "liveness")
    assert not log.record("ashby:x:y", AppStatus.ghosted, "liveness")  # ghosted needs applied
    assert log.record(KEY, AppStatus.closed, "manual")


def test_queue_add_dedupes_open_item(tmp_ws: Workspace) -> None:
    queue = QueueLog(tmp_ws)
    first = queue.add(KEY, QueueKind.needs_answers, "1 question")
    again = queue.add(KEY, QueueKind.needs_answers, "1 question")
    updated = queue.add(KEY, QueueKind.needs_answers, "2 questions", url="https://example.com/a")
    assert first.id == again.id == updated.id == "1"
    assert updated.created_at == first.created_at
    other = queue.add(KEY, QueueKind.captcha, "bot check")
    assert other.id == "2"
    reread = QueueLog(tmp_ws).open_items()
    assert [(i.id, i.detail) for i in reread] == [("1", "2 questions"), ("2", "bot check")]
    assert len(read_jsonl(tmp_ws.queue_path)) == 3  # the repeat add wrote nothing


def test_queue_resolve_by_kind(tmp_ws: Workspace) -> None:
    queue = QueueLog(tmp_ws)
    queue.add(KEY, QueueKind.needs_answers, "x")
    queue.add(KEY, QueueKind.captcha, "y")
    queue.add("ashby:samplesystems:1", QueueKind.needs_answers, "z")
    assert queue.resolve(KEY, QueueKind.needs_answers, "answered") == 1
    assert {i.kind for i in queue.open_items() if i.job_key == KEY} == {QueueKind.captcha}
    assert queue.resolve(KEY, None, "done") == 1
    assert queue.resolve(KEY, None, "done") == 0
    assert queue.resolve_id("3", "fixed")
    assert not queue.resolve_id("3", "fixed")
    assert QueueLog(tmp_ws).open_items() == []
    resolved = QueueLog(tmp_ws).all_items()
    assert all(i.resolved_at for i in resolved) and resolved[0].resolution == "answered"
    fresh = queue.add(KEY, QueueKind.needs_answers, "new one")
    assert fresh.id == "4"


def test_ledger_last_status(tmp_ws: Workspace) -> None:
    ledger = Ledger(tmp_ws)
    assert ledger.last_status(KEY) is None
    for status in (ApplyStatus.fill_problem, ApplyStatus.dry_ok):
        ledger.append(
            LedgerEntry(
                ts=now_iso(),
                run_id="r1",
                job_key=KEY,
                company="Example Corp",
                title="Senior Backend Engineer",
                mode=ApplyMode.dry,
                status=status,
            )
        )
    assert ledger.last_status(KEY) == ApplyStatus.dry_ok
    assert len(ledger.entries()) == 2 and ledger.entries("other:x:y") == []


def test_read_jsonl_bad_line_names_line(tmp_ws: Workspace) -> None:
    path = tmp_ws.events_path
    append_jsonl(path, {"a": 1})
    with path.open("a", encoding="utf-8") as fh:
        fh.write("{not json\n")
    with pytest.raises(StoreError) as info:
        read_jsonl(path)
    assert "line 2" in info.value.message and str(path) in info.value.message
    assert read_jsonl(tmp_ws.data_dir / "missing.jsonl") == []


def test_json_atomic_roundtrip(tmp_ws: Workspace) -> None:
    path = tmp_ws.plans_dir / "x.json"
    write_json_atomic(path, {"k": ["v", 1]})
    assert read_json(path) == {"k": ["v", 1]}
    assert read_json(tmp_ws.plans_dir / "nope.json", default={}) == {}
    path.write_text("{", encoding="utf-8")
    with pytest.raises(StoreError):
        read_json(path)


def test_source_reopens_closed_posting(tmp_ws: Workspace) -> None:
    log = StatusLog(tmp_ws)
    assert log.record("greenhouse:examplecorp:1", AppStatus.discovered, "source")
    assert log.record("greenhouse:examplecorp:1", AppStatus.closed, "source")
    assert not log.record("greenhouse:examplecorp:1", AppStatus.discovered, "rank")
    assert log.record("greenhouse:examplecorp:1", AppStatus.discovered, "source")
    assert log.current("greenhouse:examplecorp:1") == AppStatus.discovered
