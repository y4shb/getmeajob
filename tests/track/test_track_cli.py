from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from getmeajob.cli import main
from getmeajob.files import append_jsonl, read_jsonl, write_jsonl_atomic
from getmeajob.models import AppStatus, QueueKind, StatusEvent
from getmeajob.store import QueueLog, StatusLog
from getmeajob.track.ghost import ghost_candidates
from getmeajob.track.snapshot import load_snapshot
from getmeajob.workspace import Workspace

Cli = Callable[..., tuple[int, str, str]]
GH = "greenhouse:examplecorp:1001"
LEVER = "lever:demowidgets:7c0de000-0000-4000-8000-000000000001"
SR = "smartrecruiters:PlaceholderLabs:744000000000001"


@pytest.mark.parametrize(
    "command",
    [
        ["track", "set", "x", "applied"],
        ["track", "show", "x"],
        ["track", "list"],
        ["track", "stats"],
        ["track", "ghost"],
        ["track", "import-xlsx", "tracker.xlsx"],
    ],
)
def test_missing_workspace_friendly(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], command: list[str]
) -> None:
    code = main([*command, "--home", str(tmp_path / "nothing")])
    captured = capsys.readouterr()
    assert code == 2
    assert "getmeajob init" in captured.err
    assert "Traceback" not in captured.err + captured.out


def test_set_manual_backward_allowed(pipeline_ws: Workspace, cli: Cli) -> None:
    code, out, _ = cli(pipeline_ws, "track", "set", GH, "applied", "--note", "by hand")
    assert code == 0 and "planned -> applied" in out
    code, out, _ = cli(pipeline_ws, "track", "set", GH, "Shortlisted")
    assert code == 0 and "applied -> shortlisted" in out
    history = StatusLog(pipeline_ws).history(GH)
    assert [(e.status, e.source) for e in history[-2:]] == [
        (AppStatus.applied, "manual"),
        (AppStatus.shortlisted, "manual"),
    ]
    assert history[-2].note == "by hand"
    # automatic steps still cannot move it back
    assert not StatusLog(pipeline_ws).record(GH, AppStatus.discovered, "rank")


def test_set_same_status_writes_nothing(pipeline_ws: Workspace, cli: Cli) -> None:
    before = len(StatusLog(pipeline_ws).history(GH))
    code, out, _ = cli(pipeline_ws, "track", "set", GH, "planned")
    assert code == 0 and "already planned" in out
    assert len(StatusLog(pipeline_ws).history(GH)) == before


def test_set_unknown_status_is_a_usage_error(pipeline_ws: Workspace, cli: Cli) -> None:
    code, _, err = cli(pipeline_ws, "track", "set", GH, "interviewed")
    assert code == 2
    assert "unknown status" in err and "Traceback" not in err


def test_set_applied_resolves_open_queue_items(pipeline_ws: Workspace, cli: Cli) -> None:
    assert any(i.job_key == GH for i in QueueLog(pipeline_ws).open_items())
    assert cli(pipeline_ws, "track", "set", GH, "applied")[0] == 0
    assert not any(i.job_key == GH for i in QueueLog(pipeline_ws).open_items())
    item = next(i for i in QueueLog(pipeline_ws).all_items() if i.job_key == GH)
    assert item.kind == QueueKind.needs_answers
    assert item.resolution == "status set to applied"


def test_show_timeline(pipeline_ws: Workspace, cli: Cli) -> None:
    code, out, _ = cli(pipeline_ws, "track", "show", "1001")
    assert code == 0
    assert out.splitlines()[0] == f"Senior Backend Engineer at Example Corp ({GH})"
    assert "shortlisted  rank" in out and "planned" in out
    assert "waiting on you: needs_answers" in out
    code, out, _ = cli(pipeline_ws, "--json", "track", "show", GH)
    data = json.loads(out)
    assert [row["what"] for row in data["timeline"]] == ["discovered", "shortlisted", "planned"]


def test_stats_counts(pipeline_ws: Workspace, cli: Cli) -> None:
    code, out, _ = cli(pipeline_ws, "--json", "track", "stats")
    assert code == 0
    data = json.loads(out)
    assert data["total"] == 8
    now = {k: v for k, v in data["now"].items() if v}
    assert now == {"discovered": 4, "shortlisted": 2, "planned": 1, "ready": 1}
    assert list(data["now"])[:5] == ["discovered", "shortlisted", "planned", "ready", "applied"]
    reached = data["reached"]
    assert (reached["discovered"], reached["shortlisted"]) == (8, 4)
    assert (reached["planned"], reached["ready"], reached["applied"]) == (2, 1, 0)
    code, out, _ = cli(pipeline_ws, "track", "stats")
    assert out.splitlines()[0].split() == ["status", "now", "reached"]


def test_list_tracked_and_by_status(pipeline_ws: Workspace, cli: Cli) -> None:
    code, out, _ = cli(pipeline_ws, "--json", "track", "list")
    keys = [row["key"] for row in json.loads(out)["jobs"]]
    assert set(keys) == {GH, LEVER, SR, "ashby:samplesystems:5a1e0000-0000-4000-8000-000000000001"}
    code, out, _ = cli(pipeline_ws, "--json", "track", "list", "--status", "discovered")
    assert json.loads(out)["total"] == 4


def _event(ws: Workspace, key: str, status: AppStatus, when: datetime) -> None:
    stamp = when.strftime("%Y-%m-%dT%H:%M:%SZ")
    event = StatusEvent(ts=stamp, job_key=key, status=status, source="manual")
    append_jsonl(ws.events_path, event.to_dict())


def _age_history(ws: Workspace, key: str, when: datetime) -> None:
    """Move the existing events of one job back in time (as if sourced long ago)."""
    stamp = when.strftime("%Y-%m-%dT%H:%M:%SZ")
    records = [{**r, "ts": stamp} if r["job_key"] == key else r for r in read_jsonl(ws.events_path)]
    write_jsonl_atomic(ws.events_path, records)


def test_ghost_only_after_days(pipeline_ws: Workspace, cli: Cli) -> None:
    now = datetime.now(UTC)
    _age_history(pipeline_ws, SR, now - timedelta(days=40))
    _age_history(pipeline_ws, LEVER, now - timedelta(days=10))
    _event(pipeline_ws, SR, AppStatus.applied, now - timedelta(days=30))
    _event(pipeline_ws, LEVER, AppStatus.applied, now - timedelta(days=5))
    found = ghost_candidates(load_snapshot(pipeline_ws), 21, now)
    assert [c.key for c in found] == [SR]
    assert found[0].days_quiet == 30
    assert ghost_candidates(load_snapshot(pipeline_ws), 3, now)[-1].key == LEVER

    code, out, _ = cli(pipeline_ws, "track", "ghost", "--days", "21")
    assert code == 0 and SR in out and LEVER not in out and "nothing written" in out
    assert StatusLog(pipeline_ws).current(SR) == AppStatus.applied

    code, out, _ = cli(pipeline_ws, "track", "ghost", "--apply")
    assert code == 0 and "Recorded ghosted for 1 job(s)." in out
    last = StatusLog(pipeline_ws).history(SR)[-1]
    assert (last.status, last.source) == (AppStatus.ghosted, "ghost")
    assert StatusLog(pipeline_ws).current(LEVER) == AppStatus.applied
    code, out, _ = cli(pipeline_ws, "track", "ghost")
    assert "No applied or screening job" in out


def test_import_missing_file_is_friendly(pipeline_ws: Workspace, cli: Cli) -> None:
    code, out, err = cli(pipeline_ws, "track", "import-xlsx", "exports/none.xlsx")
    assert code == 2
    assert "There is no file" in err and "getmeajob report" in err
    assert "Traceback" not in out + err
