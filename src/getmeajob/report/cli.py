"""`getmeajob report`: write the Excel and Markdown trackers.

    getmeajob report                         exports/tracker.xlsx and exports/tracker.md
    getmeajob report --xlsx ~/jobs.xlsx      another place for the Excel file

Your Status, Next action and Notes edits in an existing Excel file are kept until you
import them with `getmeajob track import-xlsx`.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import TYPE_CHECKING

from getmeajob.report.write import write_reports
from getmeajob.track.paths import shown

if TYPE_CHECKING:
    from getmeajob.cli import Context

__all__ = ["register", "write_reports"]


def _cmd_report(args: argparse.Namespace, ctx: Context) -> int:
    ws = ctx.ws.require()
    xlsx = Path(args.xlsx).expanduser() if args.xlsx else None
    md = Path(args.md).expanduser() if args.md else None
    result = write_reports(ws, xlsx, md)
    if ctx.out.json_mode:
        ctx.out.emit(result.to_dict())
        return 0
    where = shown(result.xlsx, ws)
    ctx.out.line(
        f"Wrote {where} ({result.tracker_rows} jobs on the Tracker, {result.all_jobs} in "
        f"All jobs) and {shown(result.md, ws)} ({result.md_lines} lines)."
    )
    if result.pending_kept:
        ctx.out.line(
            f"Kept {result.pending_kept} edit(s) from the old file that are not imported yet."
        )
    ctx.out.done(
        "Edit Status, Next action and Notes in the Tracker sheet, then import them.",
        next_step=f"getmeajob track import-xlsx {where}",
    )
    return 0


def register(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = sub.add_parser(
        "report",
        help="write the Excel and Markdown trackers (exports/tracker.xlsx and .md)",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--xlsx", metavar="PATH", help="Excel file (default exports/tracker.xlsx)")
    parser.add_argument("--md", metavar="PATH", help="Markdown file (default exports/tracker.md)")
    parser.set_defaults(func=_cmd_report)
