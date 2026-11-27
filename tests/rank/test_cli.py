from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from getmeajob.cli import main
from getmeajob.models import Job
from getmeajob.store import JobStore
from getmeajob.workspace import Workspace

MakeJob = Callable[..., Job]

GOOD = (
    "We want 3-5 years of professional experience. You will work in Python with PostgreSQL "
    "and Kubernetes. " * 4
)
BAD = "8+ years of experience leading platform work. " * 6


@pytest.fixture
def ranked_ws(demo_ws: Workspace, make_job: MakeJob) -> Workspace:
    good = make_job("Senior Backend Engineer", key="greenhouse:examplecorp:1001")
    bad = make_job("Staff Platform Engineer", key="greenhouse:examplecorp:1002")
    JobStore(demo_ws).upsert([good, bad], "2026-11-27T09:00:00+00:00")
    demo_ws.jd_path(good.key).write_text(GOOD, encoding="utf-8")
    demo_ws.jd_path(bad.key).write_text(BAD, encoding="utf-8")
    return demo_ws


@pytest.mark.parametrize("command", [["rank"], ["explain", "x"]])
def test_missing_workspace_friendly(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], command: list[str]
) -> None:
    code = main([*command, "--home", str(tmp_path / "nothing")])
    captured = capsys.readouterr()
    assert code == 2
    assert "getmeajob init" in captured.err
    assert "Traceback" not in captured.err + captured.out


def test_rank_prints_a_short_table(
    ranked_ws: Workspace, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["rank", "--home", str(ranked_ws.root)]) == 0
    out = capsys.readouterr().out
    header = out.splitlines()[0].split()
    assert header == ["score", "eligible", "tier", "company", "title", "key"]
    assert "Senior Backend Engineer" in out
    assert "Staff Platform Engineer" not in out
    assert "--all" in out
    assert len(out.splitlines()) < 10


def test_rank_all_shows_ineligible_too(
    ranked_ws: Workspace, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["rank", "--all", "--home", str(ranked_ws.root)]) == 0
    out = capsys.readouterr().out
    assert "Staff Platform Engineer" in out
    assert " no " in out


def test_rank_limit_and_min_score(ranked_ws: Workspace, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["rank", "--all", "--limit", "1", "--home", str(ranked_ws.root)]) == 0
    out = capsys.readouterr().out
    assert "Staff Platform Engineer" not in out
    assert "more not shown" in out
    assert main(["rank", "--min-score", "101", "--home", str(ranked_ws.root), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["shown"] == 0


def test_rank_json(ranked_ws: Workspace, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--json", "rank", "--all", "--home", str(ranked_ws.root)]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["total"] == 2 and data["eligible"] == 1
    first = data["results"][0]
    assert first["key"] == "greenhouse:examplecorp:1001"
    assert first["company"] == "Example Corp"
    assert first["reasons"] and first["flags"] == []


def test_rank_with_no_jobs_points_to_source(
    demo_ws: Workspace, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["rank", "--home", str(demo_ws.root)]) == 0
    assert "getmeajob source" in capsys.readouterr().out


def test_explain_prints_reasons_and_flags(
    ranked_ws: Workspace, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["explain", "examplecorp:1002", "--home", str(ranked_ws.root)]) == 0
    out = capsys.readouterr().out
    assert "NOT eligible" in out
    assert "needs 8+ yrs (you: 4): too senior" in out
    assert "too_senior (blocks)" in out


def test_explain_unknown_key(ranked_ws: Workspace, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["explain", "nope", "--home", str(ranked_ws.root)]) == 2
    err = capsys.readouterr().err
    assert "No job with the key" in err and "hint:" in err


def test_explain_json(ranked_ws: Workspace, capsys: pytest.CaptureFixture[str]) -> None:
    assert (
        main(["explain", "greenhouse:examplecorp:1001", "--json", "--home", str(ranked_ws.root)])
        == 0
    )
    data = json.loads(capsys.readouterr().out)
    assert data["eligible"] is True and data["title"] == "Senior Backend Engineer"
