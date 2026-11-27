"""Token-saving commands: `status`, `context KEY` and `tokens estimate FILE...`.

getmeajob status                    the whole search on one screen
getmeajob context KEY               a small pack about one job, for an agent
getmeajob tokens estimate FILE...   characters / 4 per file (an estimate)
"""

from __future__ import annotations

import argparse
from typing import TYPE_CHECKING

from getmeajob.rank.cli import find_job
from getmeajob.tokens.context import context_pack, context_text
from getmeajob.tokens.estimate import METHOD, estimate_files
from getmeajob.tokens.status import status_digest, status_lines
from getmeajob.track.paths import find_user_file

if TYPE_CHECKING:
    from getmeajob.cli import Context


def _cmd_status(args: argparse.Namespace, ctx: Context) -> int:
    digest = status_digest(ctx.ws.require())
    if ctx.out.json_mode:
        ctx.out.emit(digest)
        return 0
    for line in status_lines(digest):
        ctx.out.line(line)
    return 0


def _cmd_context(args: argparse.Namespace, ctx: Context) -> int:
    ws = ctx.ws.require()
    job = find_job(ctx, args.key)
    pack = context_pack(ws, job)
    text = context_text(pack)
    if ctx.out.json_mode:
        ctx.out.emit({**pack, "text": text})
        return 0
    ctx.out.line(text)
    return 0


def _cmd_estimate(args: argparse.Namespace, ctx: Context) -> int:
    # No workspace needed: any file can be measured. Relative paths are tried from the
    # current folder first, then from the workspace folder.
    pairs = [(find_user_file(name, ctx.ws), name) for name in args.files]
    data = estimate_files(pairs)
    if ctx.out.json_mode:
        ctx.out.emit(data)
        return 0
    rows = [
        {
            "file": f["path"],
            "chars": f"{f['chars']:,}",
            "tokens (estimate)": f"~{f['tokens_estimate']:,}",
        }
        for f in data["files"]
    ]
    ctx.out.table(rows, ["file", "chars", "tokens (estimate)"], max_col=0)
    ctx.out.line(
        f"total: {data['total_chars']:,} chars, ~{data['total_tokens_estimate']:,} tokens "
        f"({METHOD})"
    )
    return 0


def register(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    status = sub.add_parser(
        "status",
        help="the whole search on one screen, with one suggested next command",
        description="Counts per status, the latest source run, what waits on you, plans "
        "needing answers and one suggested next command. At most 40 lines.",
    )
    status.set_defaults(func=_cmd_status)

    context = sub.add_parser(
        "context",
        help="a small pack about one job for an agent (under 2,000 characters)",
        description="Job, JD digest, rank reasons and flags, plan unknowns and resume gaps.",
    )
    context.add_argument("key", metavar="KEY", help="job key, or enough of it to match one job")
    context.set_defaults(func=_cmd_context)

    tokens = sub.add_parser(
        "tokens",
        help="estimate how many tokens files cost an agent (characters / 4)",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    actions = tokens.add_subparsers(dest="tokens_command", metavar="ACTION", required=True)
    estimate = actions.add_parser("estimate", help="characters / 4 per file and in total")
    estimate.add_argument("files", nargs="+", metavar="FILE", help="files to measure")
    estimate.set_defaults(func=_cmd_estimate)
