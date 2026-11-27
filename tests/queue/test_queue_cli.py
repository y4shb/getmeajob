from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from getmeajob.cli import main
from getmeajob.models import QueueKind
from getmeajob.queue.view import NEED, group_items, need_line
from getmeajob.store import QueueLog
from getmeajob.workspace import Workspace

Cli = Callable[..., tuple[int, str, str]]
KEY = "greenhouse:examplecorp:1001"
LEVER = "lever:demowidgets:7c0de000-0000-4000-8000-000000000001"


@pytest.mark.parametrize(
    "command",
    [["queue"], ["queue", "resolve", "1"], ["queue", "add", "x", "--note", "call back"]],
)
def test_missing_workspace_friendly(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], command: list[str]
) -> None:
    code = main([*command, "--home", str(tmp_path / "nothing")])
    captured = capsys.readouterr()
    assert code == 2
    assert "getmeajob init" in captured.err
    assert "Traceback" not in captured.err + captured.out


def test_every_kind_says_what_we_need() -> None:
    assert set(NEED) == set(QueueKind)
    code = need_line(QueueKind.needs_email_code, KEY)
    assert f"getmeajob apply {KEY} --mode hold --headed" in code
    assert "code from your email" in code
    assert all("\n" not in line and len(line) < 220 for line in NEED.values())


def test_groups_follow_fixed_order(tmp_ws: Workspace) -> None:
    log = QueueLog(tmp_ws)
    log.add("a:b:1", QueueKind.manual, "call back")
    log.add("a:b:2", QueueKind.needs_email_code, "code sent")
    log.add("a:b:3", QueueKind.needs_answers, "1 question")
    kinds = [g.kind for g in group_items(log.open_items())]
    assert kinds == [QueueKind.needs_email_code, QueueKind.needs_answers, QueueKind.manual]


def test_demo_queue_grouped_with_need_line(pipeline_ws: Workspace, cli: Cli) -> None:
    code, out, _ = cli(pipeline_ws, "queue")
    assert code == 0
    lines = out.splitlines()
    assert lines[0].startswith("needs_answers (1): Answer the open questions")
    assert KEY in out
    assert len(lines) <= 40


def test_add_then_resolve_with_note(pipeline_ws: Workspace, cli: Cli) -> None:
    code, out, _ = cli(pipeline_ws, "queue", "add", "demowidgets", "--note", "ask about Go")
    assert code == 0 and "Added item" in out
    item = next(i for i in QueueLog(pipeline_ws).open_items() if i.job_key == LEVER)
    assert item.kind == QueueKind.manual

    code, out, _ = cli(pipeline_ws, "--json", "queue", "--kind", "manual")
    data = json.loads(out)
    assert data["open"] == 1
    assert data["groups"][0]["kind"] == "manual"
    assert data["groups"][0]["items"][0]["detail"] == "ask about Go"

    code, out, _ = cli(pipeline_ws, "queue", "resolve", item.id, "--note", "asked")
    assert code == 0 and f"Resolved item {item.id}" in out
    resolved = next(i for i in QueueLog(pipeline_ws).all_items() if i.id == item.id)
    assert resolved.resolution == "asked"

    code, _, err = cli(pipeline_ws, "queue", "resolve", item.id)
    assert code == 2 and "already resolved" in err
    code, out, _ = cli(pipeline_ws, "queue", "--all", "--kind", "manual")
    assert "resolved" in out.splitlines()[1]


def test_resolve_unknown_id_is_friendly(pipeline_ws: Workspace, cli: Cli) -> None:
    code, out, err = cli(pipeline_ws, "queue", "resolve", "999")
    assert code == 2
    assert "no queue item 999" in err and "hint:" in err
    assert "Traceback" not in out + err


def test_empty_queue_says_so(demo_ws: Workspace, cli: Cli) -> None:
    code, out, _ = cli(demo_ws, "queue")
    assert code == 0
    assert "Nothing is waiting on you." in out
