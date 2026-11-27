"""`getmeajob rank` and `getmeajob explain`."""

from __future__ import annotations

import argparse
from typing import TYPE_CHECKING, Any

from getmeajob.errors import GetmeajobError
from getmeajob.files import now_iso
from getmeajob.models import Job, RankResult
from getmeajob.rank.prefs import load_preferences
from getmeajob.rank.score import job_text, rank_all, rank_job
from getmeajob.store import JobStore
from getmeajob.textutil import truncate

if TYPE_CHECKING:
    from getmeajob.cli import Context

DEFAULT_LIMIT = 25


def _row(result: RankResult, jobs: dict[str, Job]) -> dict[str, Any]:
    job = jobs.get(result.key)
    return {
        "score": result.score,
        "eligible": result.eligible,
        "tier": result.tier,
        "company": job.company if job else "",
        "title": job.title if job else "",
        "key": result.key,
    }


def _cmd_rank(args: argparse.Namespace, ctx: Context) -> int:
    ctx.ws.require()
    results = rank_all(ctx.ws, min_score=args.min_score)
    jobs = JobStore(ctx.ws).load()
    eligible = [r for r in results if r.eligible]
    shown = results if args.all else eligible
    limit = max(1, args.limit)
    rows = [_row(r, jobs) for r in shown[:limit]]
    if ctx.out.json_mode:
        payload = [{**r.to_dict(), **_row(r, jobs)} for r in shown[:limit]]
        ctx.out.emit(
            {
                "total": len(results),
                "eligible": len(eligible),
                "shown": len(payload),
                "results": payload,
            }
        )
        return 0
    if not results:
        ctx.out.done("No jobs to rank yet.", next_step="getmeajob source")
        return 0
    shown_rows = [
        {**r, "company": truncate(r["company"], 24), "title": truncate(r["title"], 40)}
        for r in rows
    ]
    # Keys are never cut: you paste them into other commands.
    ctx.out.table(shown_rows, ["score", "eligible", "tier", "company", "title", "key"], max_col=0)
    hidden = len(shown) - len(rows)
    notes = [f"{len(eligible)} of {len(results)} jobs are eligible"]
    if hidden > 0:
        notes.append(f"{hidden} more not shown (use --limit)")
    if not args.all and len(results) > len(eligible):
        notes.append("--all lists the ineligible ones too")
    first = rows[0]["key"] if rows else None
    ctx.out.done("; ".join(notes) + ".", next_step=f"getmeajob explain {first}" if first else None)
    return 0


def find_job(ctx: Context, key: str) -> Job:
    """The job with this key, or the one job whose key contains `key`."""
    matches = JobStore(ctx.ws).matching(key)
    if len(matches) == 1:
        return matches[0]
    if matches:
        listed = ", ".join(j.key for j in matches[:5])
        raise GetmeajobError(
            f"'{key}' matches {len(matches)} jobs ({listed}).",
            hint="Give more of the key so only one job matches.",
        )
    raise GetmeajobError(
        f"No job with the key '{key}'.",
        hint="Run `getmeajob rank --all` to see the keys, or `getmeajob source` to fetch jobs.",
    )


def _cmd_explain(args: argparse.Namespace, ctx: Context) -> int:
    ctx.ws.require()
    job = find_job(ctx, args.key)
    prefs = load_preferences(ctx.ws)
    result = rank_job(job, job_text(ctx.ws, job), prefs, now_iso())
    if ctx.out.json_mode:
        ctx.out.emit({**result.to_dict(), "company": job.company, "title": job.title})
        return 0
    verdict = "eligible" if result.eligible else "NOT eligible"
    ctx.out.line(f"{job.title} at {job.company} ({job.key})")
    ctx.out.line(f"score {result.score}/100, {verdict}; tier: {result.tier}; track: {result.track}")
    ctx.out.line("reasons:")
    for reason in result.reasons:
        ctx.out.line(f"  - {reason}")
    if result.flags:
        ctx.out.line("flags:")
        for flag in result.flags:
            kind = "blocks" if flag.hard else "warning"
            ctx.out.line(f"  - {flag.code} ({kind}): {flag.reason}")
    else:
        ctx.out.line("flags: none")
    return 0


def register(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    rank = sub.add_parser(
        "rank",
        help="score every job against your preferences",
        description="Score jobs from 0 to 100, write data/ranked.jsonl and list the best.",
    )
    rank.add_argument("--min-score", type=int, metavar="N", help="hide jobs scoring below N")
    rank.add_argument(
        "--limit", type=int, default=DEFAULT_LIMIT, metavar="N", help="rows to show (default 25)"
    )
    rank.add_argument("--all", action="store_true", help="also list ineligible jobs")
    rank.set_defaults(func=_cmd_rank)

    explain = sub.add_parser(
        "explain",
        help="show why a job got its score and flags",
        description="Show the reasons and flags behind one job's score.",
    )
    explain.add_argument("key", help="job key, or enough of it to match one job")
    explain.set_defaults(func=_cmd_explain)
