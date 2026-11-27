"""`getmeajob track`: application status, one job or all of them.

getmeajob track set KEY applied --note "sent through a referral"
getmeajob track show KEY          the timeline of one job
getmeajob track list [--status S]
getmeajob track stats             counts per status (the funnel)
getmeajob track ghost [--days 21] [--apply]
getmeajob track import-xlsx exports/tracker.xlsx
"""

from __future__ import annotations

import argparse
from typing import TYPE_CHECKING, Any

from getmeajob.errors import GetmeajobError
from getmeajob.files import minute_text
from getmeajob.models import AppStatus
from getmeajob.store import JobStore, StatusLog
from getmeajob.textutil import truncate
from getmeajob.track.ghost import DEFAULT_DAYS, apply_ghosts, ghost_candidates
from getmeajob.track.paths import find_user_file, shown
from getmeajob.track.snapshot import funnel, load_snapshot
from getmeajob.track.status import (
    LADDER,
    nonzero,
    parse_status,
    record_by_person,
    status_names,
)
from getmeajob.track.xlsx_import import import_tracker

if TYPE_CHECKING:
    from getmeajob.cli import Context

DEFAULT_LIMIT = 30


def _status_arg(text: str) -> AppStatus:
    status = parse_status(text)
    if status is None:
        raise argparse.ArgumentTypeError(f"unknown status {text!r}; use one of {status_names()}")
    return status


# ----------------------------------------------------------------- set / show


def _cmd_set(args: argparse.Namespace, ctx: Context) -> int:
    ws = ctx.ws.require()
    job = JobStore(ctx.ws).find(args.key)
    before = StatusLog(ws).current(job.key)
    written = record_by_person(ws, job.key, args.status, "manual", (args.note or "").strip())
    if ctx.out.json_mode:
        ctx.out.emit(
            {
                "key": job.key,
                "from": before.value if before else None,
                "to": args.status.value,
                "written": written,
            }
        )
        return 0
    if not written:
        ctx.out.done(f"{job.key} is already {args.status.value}; nothing written.")
        return 0
    was = before.value if before else "no status"
    ctx.out.done(
        f"{job.key}: {was} -> {args.status.value}.", next_step=f"getmeajob track show {job.key}"
    )
    return 0


def _cmd_show(args: argparse.Namespace, ctx: Context) -> int:
    ws = ctx.ws.require()
    job = JobStore(ctx.ws).find(args.key)
    snap = load_snapshot(ws)
    key = job.key
    timeline: list[dict[str, Any]] = [
        {"when": e.ts, "what": e.status.value, "by": e.source, "note": e.note}
        for e in snap.history.get(key, [])
    ]
    timeline += [
        {
            "when": a.ts,
            "what": f"apply {a.mode.value}: {a.status.value}",
            "by": "apply",
            "note": a.detail,
        }
        for a in snap.ledger.get(key, [])
    ]
    timeline.sort(key=lambda row: str(row["when"]))
    notes = snap.notes.get(key)
    plan = snap.plans.get(key)
    queue = [{"id": i.id, "kind": i.kind.value, "detail": i.detail} for i in snap.queue_for(key)]
    data = {
        "key": key,
        "company": job.company,
        "title": job.title,
        "status": snap.status_of(key).value,
        "score": snap.score_of(key),
        "plan": plan.status.value if plan else None,
        "timeline": timeline,
        "notes": notes.notes if notes else "",
        "next_action": notes.next_action if notes else "",
        "queue": queue,
    }
    if ctx.out.json_mode:
        ctx.out.emit(data)
        return 0
    ctx.out.line(f"{job.title} at {job.company} ({key})")
    score = data["score"] if data["score"] is not None else "not ranked"
    ctx.out.line(f"status: {data['status']}; score: {score}; plan: {data['plan'] or 'none'}")
    rows = [
        {**row, "when": minute_text(str(row["when"])), "note": truncate(str(row["note"]), 50)}
        for row in timeline[-25:]
    ]
    ctx.out.table(rows, ["when", "what", "by", "note"], max_col=0)
    if len(timeline) > 25:
        ctx.out.line(f"({len(timeline) - 25} older entries not shown; --json has them all)")
    if data["notes"]:
        ctx.out.line(f"notes: {truncate(str(data['notes']), 200)}")
    if data["next_action"]:
        ctx.out.line(f"next action: {truncate(str(data['next_action']), 200)}")
    for item in queue:
        ctx.out.line(f"waiting on you: {item['kind']} (item {item['id']}): {item['detail']}")
    return 0


# ------------------------------------------------------------- list / stats


def _cmd_list(args: argparse.Namespace, ctx: Context) -> int:
    ws = ctx.ws.require()
    snap = load_snapshot(ws)
    if args.status is not None:
        keys = sorted(
            (k for k in snap.jobs if snap.status_of(k) == args.status), key=snap.order_key
        )
    else:
        keys = snap.tracked_keys()
    limit = max(1, args.limit)
    rows = [
        {
            "status": snap.status_of(k).value,
            "score": snap.score_of(k),
            "company": truncate(snap.jobs[k].company, 22),
            "role": truncate(snap.jobs[k].title, 36),
            "key": k,
        }
        for k in keys
    ]
    if ctx.out.json_mode:
        ctx.out.emit({"total": len(rows), "jobs": rows[:limit]})
        return 0
    ctx.out.table(rows[:limit], ["status", "score", "company", "role", "key"], max_col=0)
    more = f"; {len(rows) - limit} more (use --limit)" if len(rows) > limit else ""
    what = f"with status {args.status.value}" if args.status else "tracked"
    ctx.out.done(f"{len(rows)} job(s) {what}{more}.")
    return 0


def _cmd_stats(args: argparse.Namespace, ctx: Context) -> int:
    ws = ctx.ws.require()
    data = funnel(ws)
    if ctx.out.json_mode:
        ctx.out.emit(data)
        return 0
    rows = [
        {
            "status": s.value,
            "now": data["now"][s.value],
            "reached": data["reached"].get(s.value, "-"),
        }
        for s in LADDER
    ]
    ctx.out.table(rows, ["status", "now", "reached"])
    applied = data["reached"][AppStatus.applied.value]
    ctx.out.done(
        f"{data['total']} jobs; {data['reached'][AppStatus.shortlisted.value]} shortlisted at "
        f"some point; {applied} applied. 'reached' counts jobs that got that far."
    )
    return 0


# ------------------------------------------------------------ ghost / import


def _cmd_ghost(args: argparse.Namespace, ctx: Context) -> int:
    ws = ctx.ws.require()
    if args.days < 1:
        raise GetmeajobError("--days must be 1 or more.", hint="For example: --days 21")
    found = ghost_candidates(load_snapshot(ws), args.days)
    written = apply_ghosts(ws, found) if args.apply else []
    if ctx.out.json_mode:
        ctx.out.emit(
            {
                "days": args.days,
                "candidates": [c.to_dict() for c in found],
                "recorded": written,
            }
        )
        return 0
    if not found:
        ctx.out.done(f"No applied or screening job has been quiet for {args.days} days.")
        return 0
    rows = [{**c.to_dict(), "last_event": minute_text(c.last_event)} for c in found[: args.limit]]
    ctx.out.table(rows, ["key", "status", "last_event", "days_quiet"], max_col=0)
    if args.apply:
        ctx.out.done(f"Recorded ghosted for {len(written)} job(s).")
    else:
        ctx.out.done(
            f"{len(found)} job(s) look ghosted; nothing written.",
            next_step=f"getmeajob track ghost --days {args.days} --apply",
        )
    return 0


def _cmd_import(args: argparse.Namespace, ctx: Context) -> int:
    ws = ctx.ws.require()
    path = find_user_file(args.path, ws)
    result = import_tracker(ws, path)
    if ctx.out.json_mode:
        ctx.out.emit(result.to_dict())
        return 0
    for change in result.statuses[:20]:
        ctx.out.line(f"{change['key']}: {change['from'] or 'no status'} -> {change['to']}")
    for bad in result.unknown_status[:10]:
        ctx.out.line(
            f"not recorded: row {bad['row']} ({bad['key']}) has status {bad['value']!r}, "
            "which is not a known status"
        )
    if result.unknown_status:
        ctx.out.line(f"known statuses: {status_names()}")
    if result.unknown_keys:
        ctx.out.line(
            f"not recorded: {len(result.unknown_keys)} row(s) with a key getmeajob "
            f"does not know ({', '.join(result.unknown_keys[:3])})"
        )
    counts = {
        "status change(s)": len(result.statuses),
        "note(s)": len(result.notes),
        "next action(s)": len(result.next_actions),
    }
    summary = nonzero(counts) if result.written else "nothing new"
    ctx.out.done(
        f"Imported {shown(path, ws)}: {summary}.",
        next_step="getmeajob report" if result.written else None,
    )
    return 0


def register(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    track = sub.add_parser(
        "track",
        help="application status: set, show, list, stats, ghost, import-xlsx",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    actions = track.add_subparsers(dest="track_command", metavar="ACTION", required=True)

    p = actions.add_parser("set", help="set a job's status yourself (any change is allowed)")
    p.add_argument("key", metavar="KEY", help="job key, or enough of it to match one job")
    p.add_argument("status", type=_status_arg, metavar="STATUS", help=status_names())
    p.add_argument("--note", metavar="TEXT", help="kept with the status change")
    p.set_defaults(func=_cmd_set)

    p = actions.add_parser("show", help="the timeline of one job")
    p.add_argument("key", metavar="KEY", help="job key, or enough of it to match one job")
    p.set_defaults(func=_cmd_show)

    p = actions.add_parser("list", help="tracked jobs, or every job with one status")
    p.add_argument("--status", type=_status_arg, metavar="S", help="only jobs with this status")
    p.add_argument("--limit", type=int, default=DEFAULT_LIMIT, metavar="N", help="default 30")
    p.set_defaults(func=_cmd_list)

    p = actions.add_parser("stats", help="how many jobs are at each status (the funnel)")
    p.set_defaults(func=_cmd_stats)

    p = actions.add_parser("ghost", help="find applied jobs with no news for N days")
    p.add_argument("--days", type=int, default=DEFAULT_DAYS, metavar="N", help="default 21")
    p.add_argument("--apply", action="store_true", help="record ghosted for them")
    p.add_argument("--limit", type=int, default=DEFAULT_LIMIT, metavar="N", help="default 30")
    p.set_defaults(func=_cmd_ghost)

    p = actions.add_parser("import-xlsx", help="record your edits from the Excel tracker")
    p.add_argument("path", metavar="PATH", help="the .xlsx file, e.g. exports/tracker.xlsx")
    p.set_defaults(func=_cmd_import)
