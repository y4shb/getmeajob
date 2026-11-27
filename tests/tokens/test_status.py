from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from getmeajob.cli import main
from getmeajob.models import QueueKind
from getmeajob.store import QueueLog
from getmeajob.workspace import Workspace

Cli = Callable[..., tuple[int, str, str]]


@pytest.mark.parametrize("command", [["status"], ["context", "x"]])
def test_missing_workspace_friendly(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], command: list[str]
) -> None:
    code = main([*command, "--home", str(tmp_path / "nothing")])
    captured = capsys.readouterr()
    assert code == 2
    assert "getmeajob init" in captured.err
    assert "Traceback" not in captured.err + captured.out


def test_status_fits_40_lines(pipeline_ws: Workspace, cli: Cli) -> None:
    log = QueueLog(pipeline_ws)
    for n in range(60):  # a busy workspace must still fit on one screen
        log.add(f"greenhouse:examplecorp:{9000 + n}", QueueKind.captcha, "bot check")
    code, out, _ = cli(pipeline_ws, "status")
    assert code == 0
    lines = out.splitlines()
    assert len(lines) <= 40
    assert lines[2] == "status: discovered 4, shortlisted 2, planned 1, ready 1"
    assert any(line.startswith("last source run") and "8 new, 0 closed" in line for line in lines)
    assert any("waiting on you: 61 queue item(s)" in line for line in lines)
    assert any("Why do you want to join Example Corp?" in line for line in lines)
    assert lines[-1] == "next: getmeajob queue"


def test_empty_workspace_suggests_source(demo_ws: Workspace, cli: Cli) -> None:
    code, out, _ = cli(demo_ws, "--json", "status")
    assert code == 0
    assert json.loads(out)["next"] == "getmeajob source"
    code, out, _ = cli(demo_ws, "status")
    assert "last source run: none yet" in out and out.splitlines()[-1] == "next: getmeajob source"


def test_status_json_after_the_pipeline(pipeline_ws: Workspace, cli: Cli) -> None:
    data = json.loads(cli(pipeline_ws, "--json", "status")[1])
    assert data["next"] == "getmeajob plan unknowns --stub todo.yaml"
    assert data["jobs"] == {"found": 8, "open": 8, "eligible": 4, "tracked": 4}
    assert data["queue"] == {"needs_answers": 1}
    assert data["plans"]["ready"] == 1 and data["plans"]["needs_answers"] == 1
    assert len(data["last_run"]["new"]) == 8


def test_questions_drop_once_applied(pipeline_ws: Workspace, cli: Cli) -> None:
    assert cli(pipeline_ws, "track", "set", "greenhouse:examplecorp:1001", "applied")[0] == 0
    data = json.loads(cli(pipeline_ws, "--json", "status")[1])
    assert data["questions"] == []
    assert data["queue"] == {}
    assert data["next"] == "getmeajob apply --mode dry"
