"""Fixtures for the plan tests: the demo profile, question and job factories,
the two demo form jobs, and fixture-backed HTTP clients (no network)."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from getmeajob.demo import examples_dir
from getmeajob.http import FixtureTransport, HttpClient
from getmeajob.models import Job, Option, Question, QuestionType
from getmeajob.plan.profile import Profile
from getmeajob.plan.rules import Rule, load_rules
from getmeajob.store import JobStore
from getmeajob.workspace import Workspace
from getmeajob.yamlio import load_yaml

GH_KEY = "greenhouse:examplecorp:1001"
ASHBY_KEY = "ashby:samplesystems:5a1e0000-0000-4000-8000-000000000001"


@pytest.fixture
def demo_profile() -> Profile:
    return Profile(data=load_yaml(examples_dir() / "demo" / "profile.yaml"))


@pytest.fixture
def default_rules() -> list[Rule]:
    return load_rules(None)


@pytest.fixture
def make_q() -> Callable[..., Question]:
    def make(
        label: str,
        qtype: QuestionType = QuestionType.text,
        options: list[str] | None = None,
        *,
        required: bool = True,
        qid: str = "q1",
        description: str = "",
        section: str | None = None,
    ) -> Question:
        return Question(
            id=qid,
            label=label,
            type=qtype,
            required=required,
            options=[Option(o, o) for o in options or []],
            description=description,
            section=section,
        )

    return make


def _job(key: str, company: str, title: str, location: str, **extra: Any) -> Job:
    ats, board, job_id = key.split(":")
    return Job(
        key=key,
        ats=ats,
        board=board,
        job_id=job_id,
        company=company,
        title=title,
        url=f"https://jobs.example.com/{board}/{job_id}",
        location=location,
        **extra,
    )


@pytest.fixture
def make_job() -> Callable[..., Job]:
    return _job


@pytest.fixture
def demo_jobs() -> list[Job]:
    return [
        _job(GH_KEY, "Example Corp", "Senior Backend Engineer", "Remote - Worldwide", remote=True),
        _job(ASHBY_KEY, "Sample Systems", "Platform Engineer", "Springfield, Ontario, Canada"),
        _job(
            "lever:demowidgets:7c0de000-0000-4000-8000-000000000001",
            "Demo Widgets",
            "Software Engineer II",
            "Toronto, Ontario, Canada",
        ),
    ]


@pytest.fixture
def planned_ws(demo_ws: Workspace, demo_jobs: list[Job]) -> Workspace:
    """The demo workspace with the demo form jobs in data/jobs.jsonl."""
    JobStore(demo_ws).upsert(demo_jobs, "2026-11-27T00:00:00Z")
    return demo_ws


@pytest.fixture
def fixture_client() -> Iterator[Callable[[Path], HttpClient]]:
    """Build HTTP clients that replay files from a folder (closed after the test)."""
    clients: list[HttpClient] = []

    def build(root: Path) -> HttpClient:
        client = HttpClient(transport=FixtureTransport(root), min_interval=0, retries=0)
        clients.append(client)
        return client

    yield build
    for client in clients:
        client.close()
