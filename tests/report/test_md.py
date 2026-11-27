from __future__ import annotations

from collections.abc import Callable

from getmeajob.report.tracker_md import tracker_markdown, write_tracker_md
from getmeajob.store import JobStore
from getmeajob.track.snapshot import load_snapshot
from getmeajob.workspace import Workspace

Cli = Callable[..., tuple[int, str, str]]
GH = "greenhouse:examplecorp:1001"


def test_grouped_by_status_in_ladder_order(pipeline_ws: Workspace) -> None:
    path = write_tracker_md(pipeline_ws, pipeline_ws.exports_dir / "tracker.md")
    text = path.read_text(encoding="utf-8")
    headings = [line for line in text.splitlines() if line.startswith("## ")]
    assert headings == ["## shortlisted (2)", "## planned (1)", "## ready (1)"]
    assert text.count("| Company | Role | Score | Status | Link |") == 3
    assert (
        "| Example Corp | Senior Backend Engineer | 99 | planned | "
        "[open](https://job-boards.greenhouse.io/examplecorp/jobs/1001) |"
    ) in text
    assert "1 item(s) wait on you" in text


def test_demo_is_short(pipeline_ws: Workspace, cli: Cli) -> None:
    assert cli(pipeline_ws, "report")[0] == 0
    text = (pipeline_ws.exports_dir / "tracker.md").read_text(encoding="utf-8")
    assert len(text.splitlines()) < 150
    assert chr(0x2014) not in text  # no em dashes


def test_cells_are_escaped(pipeline_ws: Workspace) -> None:
    store = JobStore(pipeline_ws)
    job = store.get(GH)
    assert job is not None
    job.title = "Backend | Platform\nEngineer"
    store.upsert([job], "2026-11-27T12:00:00Z")
    text = tracker_markdown(load_snapshot(pipeline_ws))
    assert "| Backend \\| Platform Engineer |" in text


def test_empty_workspace(demo_ws: Workspace) -> None:
    text = tracker_markdown(load_snapshot(demo_ws))
    assert "Nothing tracked yet" in text
