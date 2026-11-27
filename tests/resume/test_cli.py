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
KEY = "greenhouse:examplecorp:1001"
JD = (
    "We want 3-5 years of professional experience. You will work in Python with PostgreSQL "
    "and Kubernetes. Terraform and gRPC are a plus."
)


@pytest.fixture
def ws(demo_ws: Workspace, make_job: MakeJob) -> Workspace:
    job = make_job("Senior Backend Engineer", key=KEY)
    JobStore(demo_ws).upsert([job], "2026-11-27T09:00:00+00:00")
    demo_ws.jd_path(KEY).write_text(JD, encoding="utf-8")
    return demo_ws


def run(ws: Workspace, *args: str) -> int:
    return main([*args, "--home", str(ws.root)])


@pytest.mark.parametrize(
    "command",
    [
        ["resume", "tailor", "x"],
        ["resume", "render", "x"],
        ["resume", "keywords", "x"],
        ["resume", "list"],
        ["resume", "pick", "x"],
        ["resume", "lint"],
    ],
)
def test_missing_workspace_friendly(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], command: list[str]
) -> None:
    assert main([*command, "--home", str(tmp_path / "nothing")]) == 2
    captured = capsys.readouterr()
    assert "getmeajob init" in captured.err
    assert "Traceback" not in captured.err


def test_tailor_prints_a_short_summary(ws: Workspace, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(ws, "resume", "tailor", KEY) == 0
    out = capsys.readouterr().out
    assert "Wrote roles/example-corp-senior-backend-engineer" in out
    assert "keywords covered:" in out
    assert "terraform" in out and "never added" in out
    assert "next: getmeajob resume render" in out
    assert len(out.splitlines()) < 12


def test_tailor_json_has_the_report_without_the_doc(
    ws: Workspace, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(ws, "resume", "tailor", "1001", "--json") == 0
    data = json.loads(capsys.readouterr().out)
    assert data["job_keys"] == [KEY]
    assert "gaps_not_in_bank" in data and "doc" not in data


def test_tailor_max_bullets(ws: Workspace) -> None:
    assert run(ws, "resume", "tailor", KEY, "--max-bullets", "1", "--quiet") == 0
    md = (ws.roles_dir / "example-corp-senior-backend-engineer" / "resume.md").read_text()
    experience = md.split("## Experience")[1].split("## Skills")[0]
    assert experience.count("\n- ") == 2


def test_unknown_job_is_friendly(ws: Workspace, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(ws, "resume", "tailor", "nope") == 2
    assert "No job with the key" in capsys.readouterr().err


def test_list_pick_and_keywords(ws: Workspace, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(ws, "resume", "list") == 0
    assert "No role folders yet" in capsys.readouterr().out
    assert run(ws, "resume", "pick", KEY) == 1
    assert "resume tailor" in capsys.readouterr().out
    assert run(ws, "resume", "tailor", KEY, "--quiet") == 0
    assert run(ws, "resume", "list") == 0
    out = capsys.readouterr().out
    assert out.splitlines()[0].split() == ["folder", "pdf", "jobs", "company", "title"]
    assert "example-corp-senior-backend-engineer" in out
    assert run(ws, "resume", "keywords", KEY) == 0
    out = capsys.readouterr().out
    assert "covered" in out and "missing" in out and "terraform" in out
    assert run(ws, "resume", "keywords", KEY, "--json") == 0
    data = json.loads(capsys.readouterr().out)
    assert "python" in data["matched"] and "terraform" in data["missing"]


def test_keywords_without_a_role_uses_the_bank(
    ws: Workspace, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(ws, "resume", "keywords", KEY, "--json") == 0
    data = json.loads(capsys.readouterr().out)
    assert "fact bank" in data["source"]
    assert "terraform" in data["missing"]


def test_keywords_with_a_file(
    ws: Workspace, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    other = tmp_path / "mine.md"
    other.write_text("Terraform and gRPC, nothing else.", encoding="utf-8")
    assert run(ws, "resume", "keywords", KEY, "--file", str(other), "--json") == 0
    data = json.loads(capsys.readouterr().out)
    assert set(data["matched"]) == {"terraform", "grpc"}
    assert run(ws, "resume", "keywords", KEY, "--file", str(tmp_path / "gone.md")) == 2
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF")
    assert run(ws, "resume", "keywords", KEY, "--file", str(pdf)) == 2


def test_lint_the_bank_and_a_file(
    ws: Workspace, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(ws, "resume", "lint") == 0
    assert "0 warnings" in capsys.readouterr().out
    bad = tmp_path / "r.md"
    bad.write_text("- Responsible for things \u2014 and more\n", encoding="utf-8")
    assert run(ws, "resume", "lint", str(bad)) == 0
    out = capsys.readouterr().out
    assert "weak opener" in out and "em dash" in out and "2 warnings" in out
    assert run(ws, "resume", "lint", str(bad), "--json") == 0
    assert len(json.loads(capsys.readouterr().out)["warnings"]) == 2


def test_render_unknown_target_is_friendly(
    ws: Workspace, capsys: pytest.CaptureFixture[str]
) -> None:
    pytest.importorskip("playwright")
    assert run(ws, "resume", "render", "nothing-here") == 2
    err = capsys.readouterr().err
    assert "No role folder" in err and "hint:" in err


@pytest.mark.browser
def test_render_by_key_then_pick(ws: Workspace, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(ws, "resume", "tailor", KEY, "--quiet") == 0
    assert run(ws, "resume", "render", KEY) == 0
    assert "resume.pdf" in capsys.readouterr().out
    assert run(ws, "resume", "pick", KEY, "--json") == 0
    pdf = json.loads(capsys.readouterr().out)["pdf"]
    assert pdf and pdf.endswith("resume.pdf")
