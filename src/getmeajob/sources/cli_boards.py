"""Board commands: `boards`, `discover`, `import-portals` and `check-live`."""

from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from getmeajob.errors import ConfigError
from getmeajob.http import client_for
from getmeajob.models import Board
from getmeajob.sources.boards import board_entry, board_id, load_boards, merge_boards, save_boards
from getmeajob.sources.discover import discover
from getmeajob.sources.liveness import check_live
from getmeajob.sources.portals_yaml import import_portals
from getmeajob.store import JobStore

if TYPE_CHECKING:
    from getmeajob.cli import Context


def _more(ctx: Context, total: int, limit: int) -> None:
    if total > limit:
        ctx.out.line(f"... and {total - limit} more (raise --limit, or use --json)")


def _read_lines(path: Path) -> list[str]:
    if not path.is_file():
        raise ConfigError(
            f"{path} does not exist.",
            hint="Make a text file with one company name or URL per line.",
        )
    try:
        return path.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise ConfigError(f"{path} is not plain UTF-8 text.", hint="Save it as UTF-8.") from exc


def _write(ctx: Context, found: list[Board], write: bool) -> list[Board]:
    """Add new boards to companies.yaml when `write`; returns the boards that are new."""
    existing = load_boards(ctx.ws)
    merged, added = merge_boards(existing, found)
    if write and added:
        save_boards(ctx.ws, merged)
    return added


def _cmd_boards(args: argparse.Namespace, ctx: Context) -> int:
    ws = ctx.ws.require()
    boards = load_boards(ws)
    open_jobs = Counter(
        (j.ats.casefold(), j.board.casefold()) for j in JobStore(ws).all() if j.status != "closed"
    )
    rows = [{**board_entry(b), "open_jobs": open_jobs[board_id(b)]} for b in boards]
    if ctx.out.json_mode:
        ctx.out.emit({"count": len(rows), "boards": rows[: args.limit]})
        return 0
    if not boards:
        ctx.out.done(
            "companies.yaml lists no boards yet.",
            next_step="getmeajob discover FILE --write   (one company name or URL per line)",
        )
        return 0
    enabled = sum(1 for b in boards if b.enabled)
    ctx.out.line(f"{len(boards)} boards in companies.yaml ({enabled} enabled).")
    table = [
        {
            "company": b.company,
            "ats": b.ats,
            "slug": b.slug,
            "enabled": b.enabled,
            "verified": b.verified,
            "open jobs": open_jobs[board_id(b)],
        }
        for b in boards
    ]
    columns = ("company", "ats", "slug", "enabled", "verified", "open jobs")
    ctx.out.table(table[: args.limit], columns, max_col=32)
    _more(ctx, len(table), args.limit)
    return 0


def _cmd_discover(args: argparse.Namespace, ctx: Context) -> int:
    ws = ctx.ws.require()
    lines = _read_lines(Path(args.file))
    with client_for(ws, ctx.settings_loader()) as client:
        results = discover(lines, client)
    found = [r.board for r in results if r.board is not None]
    added = _write(ctx, found, args.write)
    if ctx.out.json_mode:
        items: list[dict[str, Any]] = [
            {
                "input": r.input,
                "company": r.company,
                "board": board_entry(r.board) if r.board else None,
                "confidence": r.confidence,
                "note": r.note,
                "tried": len(r.tried),
            }
            for r in results
        ]
        ctx.out.emit({"results": items[: args.limit], "new": len(added), "written": args.write})
        return 0
    rows = [
        {
            "input": r.input,
            "board": f"{r.board.ats}:{r.board.slug}" if r.board else "",
            "confidence": r.confidence,
            "note": r.note,
        }
        for r in results
    ]
    ctx.out.table(rows[: args.limit], ("input", "board", "confidence", "note"), max_col=40)
    _more(ctx, len(rows), args.limit)
    summary = f"Found boards for {len(found)} of {len(results)} lines; {len(added)} are new."
    if args.write:
        ctx.out.done(summary + " Saved to companies.yaml.", next_step="getmeajob source")
    else:
        ctx.out.done(
            summary, next_step=f"getmeajob discover {args.file} --write" if added else None
        )
    return 0


def _cmd_import_portals(args: argparse.Namespace, ctx: Context) -> int:
    ctx.ws.require()
    result = import_portals(Path(args.file))
    added = _write(ctx, result.boards, args.write)
    filters = {
        "title_include": result.title_include,
        "title_exclude": result.title_exclude,
        "location_rules": result.location_rules,
        "aliases": result.aliases,
    }
    if ctx.out.json_mode:
        ctx.out.emit(
            {
                "boards": [board_entry(b) for b in result.boards][: args.limit],
                "new": len(added),
                "written": args.write,
                "unsupported": [{"name": n, "reason": r} for n, r in result.unsupported],
                "filters": filters,
            }
        )
        return 0
    out = ctx.out
    out.line(
        f"Read {len(result.boards)} boards ({len(added)} new to companies.yaml) and "
        f"{len(result.unsupported)} unsupported entries."
    )
    rows = [
        {"company": b.company, "ats": b.ats, "slug": b.slug, "enabled": b.enabled}
        for b in result.boards
    ]
    out.table(rows[: args.limit], ("company", "ats", "slug", "enabled"), max_col=32)
    _more(ctx, len(rows), args.limit)
    if result.unsupported:
        out.line("unsupported:")
        unsupported = [{"name": n, "reason": r} for n, r in result.unsupported]
        out.table(unsupported[: args.limit], ("name", "reason"), max_col=60)
        _more(ctx, len(unsupported), args.limit)
    if any(filters.values()):
        out.line(
            f"filters: {len(result.title_include)} title includes, "
            f"{len(result.title_exclude)} excludes, {len(result.location_rules)} location lists, "
            f"{len(result.aliases)} aliases (see --json); copy what you need into "
            "preferences.yaml, they are not written for you."
        )
    if args.write:
        out.done("Saved new boards to companies.yaml.", next_step="getmeajob source")
    else:
        out.done("Nothing written.", next_step=f"getmeajob import-portals {args.file} --write")
    return 0


def _cmd_check_live(args: argparse.Namespace, ctx: Context) -> int:
    ws = ctx.ws.require()
    with client_for(ws, ctx.settings_loader()) as client:
        results = check_live(ws, client, list(args.keys) or None)
    counts = Counter(r.state for r in results)
    rows = [{"key": r.key, "state": r.state, "why": r.why} for r in results]
    if ctx.out.json_mode:
        ctx.out.emit({"counts": dict(counts), "results": rows[: args.limit]})
        return 0
    if not rows:
        ctx.out.done("No open jobs to check.", next_step="getmeajob source")
        return 0
    interesting = [r for r in rows if r["state"] != "open"] + [
        r for r in rows if r["state"] == "open"
    ]
    ctx.out.table(interesting[: args.limit], ("key", "state", "why"), max_col=60)
    _more(ctx, len(rows), args.limit)
    ctx.out.done(
        f"{counts['open']} open, {counts['closed']} closed, {counts['unknown']} unknown "
        "(unknown is never treated as closed)."
    )
    return 0


def register(
    sub: argparse._SubParsersAction[argparse.ArgumentParser],
    positive_int: Callable[[str], int],
) -> None:
    p = sub.add_parser("boards", help="list the boards in companies.yaml")
    p.add_argument("--limit", type=positive_int, default=40, help="rows to show (default 40)")
    p.set_defaults(func=_cmd_boards)

    p = sub.add_parser(
        "discover",
        help="find job boards from company names or URLs",
        description="Find the ATS and slug for each line of FILE (a name, a URL, or both).",
    )
    p.add_argument("file", metavar="FILE", help="text file, one company name or URL per line")
    p.add_argument("--write", action="store_true", help="add the boards found to companies.yaml")
    p.add_argument("--limit", type=positive_int, default=40, help="rows to show (default 40)")
    p.set_defaults(func=_cmd_discover)

    p = sub.add_parser(
        "import-portals",
        help="read boards and filters from a portals.yml file",
        description="Read a career-ops-style portals.yml file into boards and filters.",
    )
    p.add_argument("file", metavar="FILE", help="the portals.yml file")
    p.add_argument("--write", action="store_true", help="add the boards to companies.yaml")
    p.add_argument("--limit", type=positive_int, default=40, help="rows to show (default 40)")
    p.set_defaults(func=_cmd_import_portals)

    p = sub.add_parser(
        "check-live",
        help="check whether stored jobs are still open",
        description="Check jobs against their board, then their page. Unknown never closes.",
    )
    p.add_argument("keys", metavar="KEY", nargs="*", help="job keys (default: all open jobs)")
    p.add_argument("--limit", type=positive_int, default=25, help="rows to show (default 25)")
    p.set_defaults(func=_cmd_check_live)
