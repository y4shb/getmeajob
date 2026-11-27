"""Commands: `source`, `boards`, `discover`, `import-portals`, `check-live` and `jd`.

Every command needs a workspace (`getmeajob init`), prints a short table for people and
one JSON object with `--json`. The board commands live in `cli_boards.py`.
"""

from __future__ import annotations

import argparse
from typing import TYPE_CHECKING, Any

from getmeajob.errors import ConfigError
from getmeajob.http import client_for
from getmeajob.sources.boards import load_boards
from getmeajob.sources.cli_boards import register as register_board_commands
from getmeajob.sources.jd import jd_digest, jd_grep
from getmeajob.sources.pipeline import (
    SourceRunSummary,
    diff_rows,
    parse_feeds,
    run_source,
    select_boards,
)
from getmeajob.sources.registry import plugin_problems
from getmeajob.store import JobStore
from getmeajob.textutil import truncate
from getmeajob.yamlio import load_yaml

if TYPE_CHECKING:
    from getmeajob.cli import Context

__all__ = ["diff_rows", "parse_feeds", "register", "select_boards"]

DIFF_COLUMNS = ("change", "company", "title", "location", "key")
_WIDTHS = {"company": 28, "title": 40, "location": 40}
GREP_MAX_LINES = 40
FULL_MAX_CHARS = 12_000


def positive_int(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected a whole number, got {text!r}") from None
    if value < 1:
        raise argparse.ArgumentTypeError("must be 1 or more")
    return value


# ------------------------------------------------------------------ source


def _print_source(
    ctx: Context, summary: SourceRunSummary, rows: list[dict[str, Any]], limit: int
) -> None:
    out = ctx.out
    boards = len(summary.per_board)
    head = f"{boards} board{'s' if boards != 1 else ''}"
    if summary.empty_diff:
        out.line(f"{head}: no changes ({summary.unchanged} unchanged).")
    else:
        out.line(
            f"{head}: {summary.new} new, {summary.changed} changed, {summary.closed} closed, "
            f"{summary.unchanged} unchanged."
        )
        # Keys are never cut (people copy them); the other columns are.
        shown = [
            {**row, **{c: truncate(str(row[c]), w) for c, w in _WIDTHS.items()}}
            for row in rows[:limit]
        ]
        out.table(shown, DIFF_COLUMNS, max_col=0)
        if len(rows) > limit:
            out.line(f"... and {len(rows) - limit} more (raise --limit, or use --json)")
    for note in summary.notes[:3]:
        out.line(f"note: {note}")
    if summary.skipped:
        out.line(f"skipped {len(summary.skipped)} job(s), for example: {summary.skipped[0]}")
    if summary.harvested:
        seen = ", ".join(summary.harvested[:5])
        out.line(f"feeds link to {len(summary.harvested)} board(s) you do not follow: {seen}")
    if summary.errors:
        out.line(f"problems ({len(summary.errors)}):")
        for error in summary.errors[:5]:
            out.line(f"  {truncate(error, 160)}")
    out.done(f"Run details: {summary.run_path}", next_step="getmeajob rank")


def _cmd_source(args: argparse.Namespace, ctx: Context) -> int:
    ws = ctx.ws.require()
    feeds = parse_feeds(args.feeds)
    boards = select_boards(load_boards(ws), args.board, args.company)
    if not boards and not feeds:
        raise ConfigError(
            "companies.yaml has no enabled boards to fetch.",
            hint="Add companies to companies.yaml, or run `getmeajob discover FILE --write`.",
        )
    for problem in plugin_problems():
        ctx.out.warn(problem)
    with client_for(ws, ctx.settings_loader()) as client:
        summary = run_source(ws, client, boards, feeds=feeds)
    rows = diff_rows(summary, JobStore(ws).load())
    if ctx.out.json_mode:
        ctx.out.emit(
            {
                "boards": len(summary.per_board),
                "new": summary.new,
                "changed": summary.changed,
                "closed": summary.closed,
                "unchanged": summary.unchanged,
                "rows": rows[: args.limit],
                "more": max(0, len(rows) - args.limit),
                "errors": summary.errors[:10],
                "skipped": len(summary.skipped),
                "notes": summary.notes[:5],
                "harvested": summary.harvested[:20],
                "run": summary.run_path,
            }
        )
    else:
        _print_source(ctx, summary, rows, args.limit)
    failed = [r for r in summary.per_board if r["status"] == "error"]
    return 1 if summary.per_board and len(failed) == len(summary.per_board) else 0


# ---------------------------------------------------------------------- jd


def _cmd_jd(args: argparse.Namespace, ctx: Context) -> int:
    ws = ctx.ws.require()
    job = JobStore(ws).find(args.key)
    path = ws.jd_path(job.key)
    text = path.read_text(encoding="utf-8") if path.exists() else job.description
    out = ctx.out
    if args.grep is not None:
        lines = jd_grep(text, args.grep, context=max(0, args.context))
        more = max(0, len(lines) - GREP_MAX_LINES)
        if out.json_mode:
            out.emit({"key": job.key, "pattern": args.grep, "lines": lines[:GREP_MAX_LINES]})
            return 0
        for line in lines[:GREP_MAX_LINES] or [f"no line matches {args.grep!r}"]:
            out.line(line)
        if more:
            out.line(f"... {more} more lines; narrow the pattern")
        return 0
    if args.full:
        cut = len(text) > FULL_MAX_CHARS
        shown = truncate(text, FULL_MAX_CHARS)
        if out.json_mode:
            out.emit({"key": job.key, "text": shown, "cut": cut, "path": str(path)})
            return 0
        out.line(shown or "(no text stored for this job)")
        if cut:
            out.line(f"(cut at {FULL_MAX_CHARS:,} characters; the whole text is in {path})")
        return 0
    prefs = load_yaml(ws.preferences_path, required=False)
    digest = jd_digest(job, text, prefs)
    if out.json_mode:
        out.emit({"key": job.key, "digest": digest})
    else:
        for line in digest:
            out.line(line)
    return 0


# ---------------------------------------------------------------- register


def register(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    p = sub.add_parser(
        "source",
        help="fetch jobs from your boards and show what changed",
        description="Fetch the enabled boards in companies.yaml and print only what changed.",
    )
    p.add_argument("--board", action="append", metavar="ATS:SLUG", help="only this board")
    p.add_argument("--company", action="append", metavar="NAME", help="only this company")
    p.add_argument("--feeds", metavar="LIST", help="also read feeds: remotive,remoteok,hn")
    p.add_argument("--limit", type=positive_int, default=25, help="rows to show (default 25)")
    p.set_defaults(func=_cmd_source)

    p = sub.add_parser(
        "jd",
        help="a short digest of a job's text (or --grep, --full)",
        description="Show a digest of a job's text, search it, or print it.",
    )
    p.add_argument("key", metavar="KEY", help="job key, like greenhouse:examplecorp:1001")
    p.add_argument("--grep", metavar="RE", help="show lines matching this pattern")
    p.add_argument("--context", type=int, default=1, help="lines around each match")
    p.add_argument("--full", action="store_true", help="print the text (capped)")
    p.set_defaults(func=_cmd_jd)

    register_board_commands(sub, positive_int)
