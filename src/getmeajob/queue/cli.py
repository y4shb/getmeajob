"""`getmeajob queue`: what is waiting on you, grouped by kind.

getmeajob queue                      open items, grouped by kind
getmeajob queue --all --kind manual  also resolved items, one kind only
getmeajob queue resolve ID --note "applied by hand"
getmeajob queue add KEY --kind manual --note "ask about the team"
"""

from __future__ import annotations

import argparse
from typing import TYPE_CHECKING

from getmeajob.errors import GetmeajobError
from getmeajob.models import QueueKind
from getmeajob.queue.view import group_items, item_row, queue_view
from getmeajob.store import JobStore, QueueLog
from getmeajob.textutil import truncate

if TYPE_CHECKING:
    from getmeajob.cli import Context

DEFAULT_LIMIT = 20
COLUMNS = ["id", "key", "company", "role", "detail"]


def _kind(text: str) -> QueueKind:
    try:
        return QueueKind(text.strip().casefold())
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"unknown kind {text!r}; kinds are {', '.join(k.value for k in QueueKind)}"
        ) from None


def _cmd_list(args: argparse.Namespace, ctx: Context) -> int:
    ctx.ws.require()
    if ctx.out.json_mode:
        ctx.out.emit(queue_view(ctx.ws, include_resolved=args.all, kind=args.kind))
        return 0
    log = QueueLog(ctx.ws)
    items = log.all_items() if args.all else log.open_items()
    if args.kind is not None:
        items = [i for i in items if i.kind == args.kind]
    jobs = JobStore(ctx.ws).load()
    groups = group_items(items)
    open_count = sum(1 for i in items if i.resolved_at is None)
    if not groups:
        ctx.out.done("Nothing is waiting on you.", next_step="getmeajob status")
        return 0
    left = max(1, args.limit)
    hidden = 0
    for group in groups:
        ctx.out.line(f"{group.kind.value} ({len(group.items)}): {group.need}")
        shown, rest = group.items[:left], group.items[left:]
        left = max(0, left - len(shown))
        hidden += len(rest)
        rows = []
        for item in shown:
            row = item_row(item, jobs)
            done = item.resolved_at is not None
            rows.append(
                {
                    "id": item.id,
                    "key": item.job_key,
                    "company": truncate(row["company"], 20),
                    "role": truncate(row["role"], 30),
                    "detail": truncate(item.detail, 60),
                    "resolved": (item.resolved_at or "")[:10] if done else "open",
                }
            )
        if shown:
            ctx.out.table(rows, [*COLUMNS, "resolved"] if args.all else COLUMNS, max_col=0)
    note = f"{open_count} open item(s)"
    if hidden:
        note += f"; {hidden} more not shown (use --limit)"
    ctx.out.done(note + ".", next_step="getmeajob queue resolve ID --note TEXT")
    return 0


def _cmd_resolve(args: argparse.Namespace, ctx: Context) -> int:
    ctx.ws.require()
    log = QueueLog(ctx.ws)
    item_id = str(args.id).strip()
    known = {i.id: i for i in log.all_items()}
    if item_id not in known:
        raise GetmeajobError(
            f"There is no queue item {item_id}.",
            hint="Run `getmeajob queue` to see the open items and their ids.",
        )
    resolution = (args.note or "").strip() or "done by hand"
    if not log.resolve_id(item_id, resolution):
        raise GetmeajobError(
            f"Queue item {item_id} is already resolved.",
            hint="Run `getmeajob queue --all` to see resolved items.",
        )
    item = known[item_id]
    if ctx.out.json_mode:
        ctx.out.emit({"resolved": item_id, "key": item.job_key, "resolution": resolution})
        return 0
    ctx.out.done(f"Resolved item {item_id} ({item.kind.value}, {item.job_key}).")
    return 0


def _cmd_add(args: argparse.Namespace, ctx: Context) -> int:
    ctx.ws.require()
    job = JobStore(ctx.ws).find(args.key)
    note = (args.note or "").strip()
    if not note:
        raise GetmeajobError(
            "A queue item needs a note saying what to do.",
            hint='For example: --note "ask the recruiter about the team".',
        )
    log = QueueLog(ctx.ws)
    before = {i.id for i in log.open_items()}
    item = log.add(job.key, args.kind, note, job.url)
    updated = item.id in before
    if ctx.out.json_mode:
        ctx.out.emit({"id": item.id, "key": job.key, "kind": item.kind.value, "updated": updated})
        return 0
    verb = "Updated" if updated else "Added"
    ctx.out.done(f"{verb} item {item.id} ({item.kind.value}) for {job.key}.")
    return 0


def register(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = sub.add_parser(
        "queue",
        help="what is waiting on you, grouped by kind; resolve or add items",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--all", action="store_true", help="also show resolved items")
    parser.add_argument("--kind", type=_kind, metavar="K", help="only this kind")
    parser.add_argument(
        "--limit", type=int, default=DEFAULT_LIMIT, metavar="N", help="rows to show (default 20)"
    )
    parser.set_defaults(func=_cmd_list)
    actions = parser.add_subparsers(dest="queue_command", metavar="ACTION")

    resolve = actions.add_parser("resolve", help="mark an item as done")
    resolve.add_argument("id", metavar="ID", help="the item id from `getmeajob queue`")
    resolve.add_argument("--note", metavar="TEXT", help="what you did (kept with the item)")
    resolve.set_defaults(func=_cmd_resolve)

    add = actions.add_parser("add", help="add your own reminder for a job")
    add.add_argument("key", metavar="KEY", help="job key, or enough of it to match one job")
    add.add_argument(
        "--kind",
        type=_kind,
        default=QueueKind.manual,
        metavar="K",
        help="kind of item (default manual)",
    )
    add.add_argument("--note", metavar="TEXT", required=True, help="what needs doing")
    add.set_defaults(func=_cmd_add)
