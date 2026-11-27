from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path

import pytest

from getmeajob.cli import main
from getmeajob.files import now_iso
from getmeajob.models import LedgerEntry, QueueKind
from getmeajob.store import Ledger, QueueLog
from getmeajob.workspace import Workspace

Cli = Callable[..., tuple[int, str, str]]
GH = "greenhouse:examplecorp:1001"
ASHBY = "ashby:samplesystems:5a1e0000-0000-4000-8000-000000000001"


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
    assert data["next"] == "getmeajob plan unknowns --stub answers-todo.yaml"
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


def test_after_a_dry_run_status_suggests_the_hold_run(pipeline_ws: Workspace, cli: Cli) -> None:
    assert cli(pipeline_ws, "track", "set", GH, "applied")[0] == 0
    entry = {"ts": now_iso(), "run_id": "r1", "job_key": ASHBY, "company": "", "title": ""}
    Ledger(pipeline_ws).append(LedgerEntry.from_dict({**entry, "mode": "dry", "status": "dry_ok"}))
    data = json.loads(cli(pipeline_ws, "--json", "status")[1])
    assert data["next"] == "getmeajob apply --mode hold --headed"


def test_status_suggests_nothing_once_the_tracker_is_current(
    pipeline_ws: Workspace, cli: Cli
) -> None:
    for key in (GH, ASHBY):
        assert cli(pipeline_ws, "track", "set", key, "applied")[0] == 0
    assert json.loads(cli(pipeline_ws, "--json", "status")[1])["next"] == "getmeajob report"
    assert cli(pipeline_ws, "report")[0] == 0
    code, out, _ = cli(pipeline_ws, "status")
    assert code == 0 and out.splitlines()[-1] == "next: nothing to do; the tracker is up to date"
    later = (pipeline_ws.exports_dir / "tracker.xlsx").stat().st_mtime + 10
    os.utime(pipeline_ws.events_path, (later, later))  # the data changed after the report
    assert json.loads(cli(pipeline_ws, "--json", "status")[1])["next"] == "getmeajob report"


def test_stale_plans_send_you_back_to_plan(pipeline_ws: Workspace, cli: Cli) -> None:
    profile = pipeline_ws.profile_path
    profile.write_text(profile.read_text().replace("Alex", "Alexa", 1))
    code, out, _ = cli(pipeline_ws, "status")
    assert code == 0
    assert "next: getmeajob plan" in out
