"""The Markdown tracker: the Tracker rows grouped by status, one small table per status.

Short on purpose, so a person can skim it and an agent can read it cheaply.
"""

from __future__ import annotations

from pathlib import Path

from getmeajob.files import atomic_write_text
from getmeajob.report.rows import TrackerRow, tracker_rows
from getmeajob.track.snapshot import Snapshot, load_snapshot
from getmeajob.track.status import LADDER, MEANING, nonzero
from getmeajob.workspace import Workspace

CELL_CHARS = 60


def _cell(text: object) -> str:
    value = " ".join(str(text if text is not None else "").split()).replace("|", "\\|")
    return value if len(value) <= CELL_CHARS else value[: CELL_CHARS - 1].rstrip() + "…"


def _link(url: str) -> str:
    return f"[open]({url.replace(')', '%29').replace(' ', '%20')})" if url else ""


def tracker_markdown(snap: Snapshot, rows: list[TrackerRow] | None = None) -> str:
    rows = tracker_rows(snap) if rows is None else rows
    stamp = snap.taken_at.replace("T", " ").replace("Z", " UTC")
    counts: dict[str, int] = {}
    for row in rows:
        counts[row.status] = counts.get(row.status, 0) + 1
    ordered = {s.value: counts.get(s.value, 0) for s in LADDER}
    lines = [
        "# Job tracker",
        "",
        f"Exported {stamp} by `getmeajob report`. {len(rows)} jobs tracked: {nonzero(ordered)}.",
    ]
    waiting = len(snap.queue_open)
    if waiting:
        lines.append(f"{waiting} item(s) wait on you: run `getmeajob queue`.")
    if not rows:
        lines += ["", "Nothing tracked yet. Run `getmeajob rank` to shortlist jobs."]
    for status in LADDER:
        group = [r for r in rows if r.status == status.value]
        if not group:
            continue
        lines += [
            "",
            f"## {status.value} ({len(group)})",
            "",
            f"{MEANING[status][:1].upper()}{MEANING[status][1:]}.",
            "",
            "| Company | Role | Score | Status | Link |",
            "|---|---|---|---|---|",
        ]
        for row in group:
            score = "" if row.score is None else str(row.score)
            cells = [_cell(row.company), _cell(row.role), score, row.status, _link(row.job_link)]
            lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def write_tracker_md(ws: Workspace, path: Path) -> Path:
    """Write the Markdown tracker to `path` and return it."""
    atomic_write_text(path, tracker_markdown(load_snapshot(ws)))
    return path
