"""Fixtures for the ranking tests: the demo preferences and a job builder."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from getmeajob.models import Job
from getmeajob.rank.prefs import Preferences, parse_preferences
from getmeajob.yamlio import load_yaml

DEMO_PREFS = Path(__file__).resolve().parents[2] / "examples" / "demo" / "preferences.yaml"


@pytest.fixture
def prefs() -> Preferences:
    return parse_preferences(load_yaml(DEMO_PREFS))


@pytest.fixture
def make_job() -> Callable[..., Job]:
    def build(
        title: str = "Backend Engineer",
        location: str = "Remote - Worldwide",
        *,
        key: str = "greenhouse:examplecorp:1",
        company: str = "Example Corp",
        workplace: str | None = None,
        remote: bool | None = None,
        description: str = "",
    ) -> Job:
        ats, board, job_id = key.split(":", 2)
        return Job(
            key=key,
            ats=ats,
            board=board,
            job_id=job_id,
            company=company,
            title=title,
            url=f"https://jobs.example.com/{job_id}",
            location=location,
            workplace=workplace,
            remote=remote,
            description=description,
        )

    return build
