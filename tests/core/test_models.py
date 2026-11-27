from __future__ import annotations

import json

import pytest

from getmeajob.errors import StoreError
from getmeajob.models import (
    FORWARD_ORDER,
    SIDE_STATES,
    ApplyMode,
    ApplyStatus,
    AppStatus,
    Board,
    Flag,
    Job,
    LedgerEntry,
    Option,
    Plan,
    PlannedAnswer,
    PlanStatus,
    Question,
    QuestionType,
    QueueItem,
    QueueKind,
    RankResult,
    StatusEvent,
    UnknownQuestion,
)

TS = "2026-11-27T10:00:00Z"
KEY = "greenhouse:examplecorp:1001"


def _samples() -> list[object]:
    flag = Flag(code="too_senior", reason="asks for 8+ years", hard=True)
    option = Option(label="Yes", value="1")
    return [
        Board(company="Example Corp", ats="greenhouse", slug="examplecorp", region="us"),
        Job(
            key=KEY,
            ats="greenhouse",
            board="examplecorp",
            job_id="1001",
            company="Example Corp",
            title="Senior Backend Engineer",
            url="https://boards.example.com/1001",
            location="Remote - Worldwide",
            remote=True,
            description="Python and Postgres.",
            first_seen=TS,
            last_seen=TS,
        ),
        flag,
        RankResult(
            key=KEY,
            score=88,
            eligible=True,
            tier="remote_worldwide",
            track="backend",
            yoe_min=3,
            yoe_max=5,
            reasons=["3-5 years fits"],
            flags=[flag],
            skills_hit=["python"],
            skills_missing=["go"],
            ranked_at=TS,
        ),
        option,
        Question(
            id="question_2002",
            label="Are you legally authorized to work in Canada?",
            type=QuestionType.select,
            required=True,
            options=[option, Option(label="No", value="0")],
            max_length=None,
        ),
        PlannedAnswer(
            question_id="question_2006[]",
            label="Which of these have you used in production?",
            type=QuestionType.multiselect,
            value=["Python", "Kubernetes"],
            source="rule:skills",
        ),
        UnknownQuestion(
            question_id="question_2005",
            label="Why do you want to join Example Corp?",
            type=QuestionType.textarea,
            required=True,
            options=[],
            reason="free text",
            dedupe_key="why do you want to join example corp|0",
        ),
        Plan(
            job_key=KEY,
            ats="greenhouse",
            company="Example Corp",
            title="Senior Backend Engineer",
            url="https://boards.example.com/1001",
            form_url="https://boards.example.com/1001/apply",
            status=PlanStatus.needs_answers,
            answers=[
                PlannedAnswer(
                    question_id="first_name",
                    label="First Name",
                    type=QuestionType.text,
                    value="Alex",
                    source="rule:first_name",
                )
            ],
            unknowns=[],
            created_at=TS,
        ),
        LedgerEntry(
            ts=TS,
            run_id="run-1",
            job_key=KEY,
            company="Example Corp",
            title="Senior Backend Engineer",
            mode=ApplyMode.dry,
            status=ApplyStatus.dry_ok,
            problems=["none"],
        ),
        QueueItem(
            id="1",
            job_key=KEY,
            kind=QueueKind.needs_answers,
            detail="1 question",
            url=None,
            created_at=TS,
        ),
        StatusEvent(ts=TS, job_key=KEY, status=AppStatus.shortlisted, source="rank"),
    ]


def test_roundtrip_all_models() -> None:
    samples = _samples()
    assert len({type(s) for s in samples}) == 12
    for sample in samples:
        data = sample.to_dict()  # type: ignore[attr-defined]
        json.dumps(data)  # JSON-safe
        again = type(sample).from_dict(json.loads(json.dumps(data)))  # type: ignore[attr-defined]
        assert again == sample, type(sample).__name__


def test_enums_serialise_as_values() -> None:
    event = StatusEvent(ts=TS, job_key=KEY, status=AppStatus.applied, source="manual")
    assert event.to_dict()["status"] == "applied"
    assert isinstance(StatusEvent.from_dict(event.to_dict()).status, AppStatus)


def test_from_dict_ignores_unknown_keys() -> None:
    job = Job.from_dict(
        {
            "key": KEY,
            "ats": "greenhouse",
            "board": "examplecorp",
            "job_id": 1001,
            "company": "Example Corp",
            "title": "Senior Backend Engineer",
            "url": "https://boards.example.com/1001",
            "something_new": {"nested": True},
        }
    )
    assert job.job_id == "1001"
    assert job.location == ""
    assert job.status == "open"
    assert job.remote is None


def test_from_dict_fills_list_and_optional_defaults() -> None:
    item = QueueItem.from_dict(
        {"id": 3, "job_key": KEY, "kind": "captcha", "detail": "x", "created_at": TS}
    )
    assert item.id == "3" and item.url is None and item.resolved_at is None
    assert item.kind is QueueKind.captcha
    question = Question.from_dict({"id": "q", "label": "Q", "type": "text", "options": None})
    assert question.options == []


def test_from_dict_missing_required_raises_store_error() -> None:
    with pytest.raises(StoreError) as info:
        Job.from_dict({"key": KEY})
    assert "missing" in info.value.message
    with pytest.raises(StoreError):
        StatusEvent.from_dict({"ts": TS, "job_key": KEY, "status": "nope", "source": "x"})


def test_make_key() -> None:
    assert Job.make_key("ashby", "samplesystems", "abc") == "ashby:samplesystems:abc"
    assert Job.make_key("greenhouse", "examplecorp", "1001") == KEY


def test_status_constants() -> None:
    assert FORWARD_ORDER[0] == AppStatus.discovered
    assert FORWARD_ORDER[-1] == AppStatus.accepted
    assert AppStatus.closed in SIDE_STATES
    assert not set(FORWARD_ORDER) & SIDE_STATES
