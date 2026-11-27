"""Write both trackers (Excel and Markdown) from one snapshot."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from getmeajob.files import atomic_write_text
from getmeajob.report.tracker_md import tracker_markdown
from getmeajob.report.tracker_xlsx import build_tracker_xlsx
from getmeajob.track.snapshot import load_snapshot
from getmeajob.workspace import Workspace


@dataclass(slots=True)
class ReportResult:
    xlsx: Path
    md: Path
    tracker_rows: int
    all_jobs: int
    md_lines: int
    pending_kept: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "xlsx": str(self.xlsx),
            "md": str(self.md),
            "tracker_rows": self.tracker_rows,
            "all_jobs": self.all_jobs,
            "md_lines": self.md_lines,
            "pending_kept": self.pending_kept,
        }


def write_reports(ws: Workspace, xlsx: Path | None = None, md: Path | None = None) -> ReportResult:
    """Write both trackers from one snapshot. Default paths are under `exports/`."""
    xlsx = xlsx or ws.exports_dir / "tracker.xlsx"
    md = md or ws.exports_dir / "tracker.md"
    snap = load_snapshot(ws)
    result = build_tracker_xlsx(ws, xlsx, snap)
    text = tracker_markdown(snap)
    atomic_write_text(md, text)
    return ReportResult(
        xlsx=result.path,
        md=md,
        tracker_rows=result.tracker_rows,
        all_jobs=result.all_jobs,
        md_lines=text.count("\n"),
        pending_kept=result.pending_kept,
    )
