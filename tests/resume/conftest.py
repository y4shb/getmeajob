"""Fixtures for the resume tests: the demo bank and a job builder."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from getmeajob.models import Job
from getmeajob.resume.bank import Bank, parse_bank
from getmeajob.yamlio import load_yaml

DEMO_BANK = Path(__file__).resolve().parents[2] / "examples" / "demo" / "resume" / "bank.yaml"

JD_BACKEND = """\
We are looking for 3-5 years of professional experience building APIs.
You will work in Python with PostgreSQL and run services on Kubernetes.
Nice to have: Terraform, gRPC and Rust. Experience with CI/CD pipelines helps.
"""


@pytest.fixture
def bank() -> Bank:
    return parse_bank(load_yaml(DEMO_BANK))


@pytest.fixture
def make_job() -> Callable[..., Job]:
    def build(
        title: str = "Senior Backend Engineer",
        *,
        key: str = "greenhouse:examplecorp:1001",
        company: str = "Example Corp",
        location: str = "Remote - Worldwide",
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
        )

    return build
