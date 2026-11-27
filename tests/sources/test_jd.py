from __future__ import annotations

import pytest

from getmeajob.errors import ConfigError
from getmeajob.models import Job
from getmeajob.sources.jd import jd_digest, jd_grep, mentions

JOB = Job(
    key="greenhouse:examplecorp:1003",
    ats="greenhouse",
    board="examplecorp",
    job_id="1003",
    company="Example Corp",
    title="Backend Engineer, Payments",
    url="https://job-boards.greenhouse.io/examplecorp/jobs/1003",
    location="Remote - US",
    workplace="remote",
    posted="2026-11-07",
    department="Payments",
    comp="USD 120,000-150,000",
)
TEXT = "\n".join(
    [
        "Build payment services in Python on Postgres.",
        "3+ years of experience building backend services.",
        "Bonus: 2 years with Go, Rust or Scala.",
        "Candidates must be authorized to work in the United States.",
        "We are unable to sponsor visas for this role.",
        "Security clearance is not needed.",
        *[f"Filler line {n} about kubernetes, aws, docker and fastapi." for n in range(40)],
    ]
)
PREFS = {
    "skills": {
        "have": {"python": 3, "postgres": 2, "kubernetes": 2, "aws": 2, "fastapi": 1, "docker": 1},
        "lack": ["go", "rust", "scala"],
    }
}


def test_digest_max_12_lines() -> None:
    digest = jd_digest(JOB, TEXT, PREFS)
    assert 1 < len(digest) <= 12
    assert all(len(line) < 200 for line in digest)
    joined = "\n".join(digest)
    assert digest[0] == "Backend Engineer, Payments at Example Corp"
    assert "where: Remote - US" in joined and "pay: USD 120,000-150,000" in joined
    assert '"3+ years of experience building backend services"' in joined
    assert "skills you have: python, postgres, kubernetes, aws, fastapi, docker" in joined
    assert "skills you lack: go, rust, scala" in joined
    assert "authorized to work in the United States" in joined and "unable to sponsor" in joined
    assert len(jd_digest(JOB, "", PREFS)) <= 12


def test_go_needs_a_real_mention() -> None:
    assert not mentions("We go to market fast and google things.", "go")
    assert mentions("Services in Go and gRPC.", "go") and mentions("golang", "go")
    assert not mentions("A scalable system.", "scala")


def test_grep_numbers_lines_with_context() -> None:
    lines = jd_grep(TEXT, r"sponsor|clearance", context=0)
    assert lines == [
        "5: We are unable to sponsor visas for this role.",
        "6: Security clearance is not needed.",
    ]
    around = jd_grep(TEXT, "authorized", context=1)
    assert around == [
        "3: Bonus: 2 years with Go, Rust or Scala.",
        "4: Candidates must be authorized to work in the United States.",
        "5: We are unable to sponsor visas for this role.",
    ]
    split = jd_grep(TEXT, r"^Build|Filler line 0 ", context=0)
    assert split[1] == "--"
    with pytest.raises(ConfigError):
        jd_grep(TEXT, "(unclosed")
