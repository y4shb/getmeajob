"""`getmeajob plan ...`: plan form answers, list unknowns, answer them, review, draft.

plan [KEY...] [--refresh] [--min-score N]    plan jobs (default: the shortlist)
plan show KEY                                one plan in full
plan unknowns [--stub FILE]                  open questions, once per label
plan answer FILE                             merge answers into answers.yaml
plan review [KEY...]                         label -> answer table, unknowns, drafts
plan draft [--budget N] [--provider P] [KEY...]   draft free-text answers to review
plan approve KEY | --all                     mark drafts and agent answers as reviewed
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from getmeajob.errors import GetmeajobError
from getmeajob.models import Plan, PlanStatus
from getmeajob.plan.draft import draft_unknowns, provider_named
from getmeajob.plan.overrides import SECTIONS, approve_job, merge_answers
from getmeajob.plan.planner import load_plan, plan_run
from getmeajob.plan.unknowns import collect_unknowns, review_table, write_stub
from getmeajob.textutil import truncate
from getmeajob.yamlio import load_yaml

if TYPE_CHECKING:
    from getmeajob.cli import Context

SUBCOMMANDS = ("show", "unknowns", "answer", "review", "draft", "approve")


def _summary(plan: Plan, reused: bool) -> dict[str, Any]:
    answered = sum(1 for a in plan.answers if a.source != "skip")
    return {
        "key": plan.job_key,
        "status": plan.status.value,
        "answered": answered,
        "skipped": len(plan.answers) - answered,
        "unknowns": len(plan.unknowns),
        "note": "reused" if reused else (plan.blocked_reason or ""),
        "form_url": plan.form_url,
    }


def _need(words: list[str], count: int, usage: str) -> list[str]:
    if len(words) != count:
        raise GetmeajobError(f"Usage: getmeajob {usage}", hint="See getmeajob plan --help.")
    return words


def _plan(args: argparse.Namespace, ctx: Context, words: list[str]) -> int:
    run = plan_run(ctx.ws, words or None, min_score=args.min_score, refresh=bool(args.refresh))
    out = ctx.out
    rows = [_summary(p, p.job_key in run.reused) for p in run.plans]
    if out.json_mode:
        out.emit(
            {
                "plans": rows,
                "reused": run.reused,
                "skipped": [{"key": k, "reason": r} for k, r in run.skipped],
                "ranked_missing": run.ranked_missing,
            }
        )
        return 0
    if run.ranked_missing:
        out.done(
            "No ranked jobs yet (data/ranked.jsonl is missing), so nothing was planned.",
            next_step="getmeajob rank   (or: getmeajob plan KEY ...)",
        )
        return 0
    shown = rows[: args.limit]
    out.table(shown, ["key", "status", "answered", "unknowns", "note"], max_col=60)
    if len(rows) > len(shown):
        out.line(f"... and {len(rows) - len(shown)} more (use --limit or --json)")
    for key, reason in run.skipped[:5]:
        out.line(f"skipped {key}: {reason}")
    counts = {s: sum(1 for p in run.plans if p.status == s) for s in PlanStatus}
    if not run.plans:
        out.done(
            "Nothing to plan: no eligible ranked job with a form at the shortlist score.",
            next_step="getmeajob rank --all   (or: getmeajob plan KEY ...)",
        )
        return 0
    parts = [
        f"{counts[PlanStatus.ready]} ready",
        f"{counts[PlanStatus.needs_answers]} need answers",
    ]
    for status in (PlanStatus.blocked, PlanStatus.schema_unavailable):
        if counts[status]:
            parts.append(f"{counts[status]} {status.value.replace('_', ' ')}")
    reused = f" ({len(run.reused)} unchanged, reused)" if run.reused else ""
    nxt = "getmeajob plan unknowns" if counts[PlanStatus.needs_answers] else "getmeajob plan review"
    out.done(f"Planned {len(run.plans)} job(s): {', '.join(parts)}.{reused}", next_step=nxt)
    return 0


def _show(args: argparse.Namespace, ctx: Context, words: list[str]) -> int:
    (key,) = _need(words, 1, "plan show KEY")
    plan = load_plan(ctx.ws, key)
    if plan is None:
        raise GetmeajobError(f"There is no plan for {key} yet.", hint=f"Run: getmeajob plan {key}")
    out = ctx.out
    if out.json_mode:
        out.emit(plan.to_dict())
        return 0
    out.line(f"{plan.job_key}  {plan.status.value}  {plan.title} at {plan.company}")
    out.line(f"form: {plan.form_url}")
    if plan.blocked_reason:
        out.line(f"reason: {plan.blocked_reason}")
    rows = [
        {
            "question": a.label,
            "answer": a.value if a.value is not None else "(blank)",
            "source": a.source + (" (review)" if a.needs_review else ""),
        }
        for a in plan.answers
    ]
    out.table(rows[: args.limit], ["question", "answer", "source"], max_col=44)
    if plan.unknowns:
        out.line(f"unknowns ({len(plan.unknowns)}):")
        out.table([u.to_dict() for u in plan.unknowns], ["label", "type", "reason"], max_col=50)
    return 0


def _unknowns(args: argparse.Namespace, ctx: Context, words: list[str]) -> int:
    _need(words, 0, "plan unknowns [--stub FILE]")
    groups = collect_unknowns(ctx.ws)
    stub = Path(args.stub).expanduser() if args.stub else None
    if stub is not None and groups:
        write_stub(groups, stub)
    out = ctx.out
    if out.json_mode:
        out.emit({"unknowns": [g.to_dict() for g in groups], "stub": str(stub) if stub else None})
        return 0
    if not groups:
        out.done("No unknown questions: every planned form is answered.", "getmeajob plan review")
        return 0
    rows = [
        {
            "label": g.label,
            "type": g.type.value,
            "options": " | ".join(truncate(o, 18) for o in g.options[:6]),
            "jobs": len(g.jobs),
            "required": g.required,
        }
        for g in groups
    ]
    out.table(rows[: args.limit], ["label", "type", "options", "jobs", "required"], max_col=50)
    if stub is not None:
        out.done(
            f"Wrote {len(groups)} question(s) to {stub}.",
            next_step=f"fill it in, then: getmeajob plan answer {stub}",
        )
    else:
        out.done(
            f"{len(groups)} question(s) need your answer.",
            next_step="getmeajob plan unknowns --stub answers-todo.yaml",
        )
    return 0


def _answer(args: argparse.Namespace, ctx: Context, words: list[str]) -> int:
    (name,) = _need(words, 1, "plan answer FILE")
    data = load_yaml(Path(name).expanduser(), required=True)
    extra = [k for k in data if k not in SECTIONS]
    if extra:
        ctx.out.warn(f"{name}: ignored unknown section(s): {', '.join(map(str, extra))}")
    saved = merge_answers(ctx.ws, data)
    if ctx.out.json_mode:
        ctx.out.emit({"saved": saved, "answers_file": str(ctx.ws.answers_path)})
        return 0
    ctx.out.done(f"Saved {saved} answer(s) to {ctx.ws.answers_path.name}.", "getmeajob plan")
    return 0


def _review(args: argparse.Namespace, ctx: Context, words: list[str]) -> int:
    table = review_table(ctx.ws, words or None)
    out = ctx.out
    if out.json_mode:
        out.emit(table.to_dict())
        return 0
    rows = [{"question": q, "answer": a, "source": s, "jobs": n} for q, a, s, n in table.rows]
    out.table(rows[: args.limit], ["question", "answer", "source", "jobs"], max_col=44)
    if len(rows) > args.limit:
        out.line(f"... and {len(rows) - args.limit} more rows (use --limit or --json)")
    if table.unknowns:
        out.line(f"unknowns ({len(table.unknowns)}):")
        urows = [
            {"label": g.label, "type": g.type.value, "jobs": len(g.jobs)} for g in table.unknowns
        ]
        out.table(urows[:10], ["label", "type", "jobs"], max_col=60)
    if table.needs_review:
        out.line(f"drafts to review ({len(table.needs_review)}):")
        out.table(table.needs_review[:10], ["job_key", "label", "value"], max_col=50)
    nxt = "getmeajob plan unknowns" if table.unknowns else None
    if table.needs_review:
        nxt = "check the drafts, then: getmeajob plan approve KEY (or --all)"
    out.done(f"{len(rows)} answer row(s), {table.skipped} left blank on purpose.", nxt)
    return 0


def _draft(args: argparse.Namespace, ctx: Context, words: list[str]) -> int:
    ctx.ws.require()
    provider = provider_named(args.provider)
    report = draft_unknowns(ctx.ws, provider, budget_tokens=args.budget, keys=words or None)
    out = ctx.out
    if out.json_mode:
        out.emit(report.to_dict())
        return 0
    for item in report.drafted[: args.limit]:
        out.line(f"drafted  {item['job_key']}  {truncate(item['label'], 60)}")
    budget = " Stopped at the token budget." if report.stopped_at_budget else ""
    out.done(
        f"Drafted {len(report.drafted)} answer(s) ({report.from_cache} from cache), "
        f"{len(report.asked_human)} left for you, {len(report.skipped)} not draftable; "
        f"about {report.tokens_used} tokens used.{budget}",
        next_step="getmeajob plan, then getmeajob plan review" if report.drafted else None,
    )
    return 0


def _approve(args: argparse.Namespace, ctx: Context, words: list[str]) -> int:
    key = None if args.all else _need(words, 1, "plan approve KEY  (or --all)")[0]
    count = approve_job(ctx.ws, key)
    scope = "in answers.yaml" if key is None else f"for {key}"
    if ctx.out.json_mode:
        ctx.out.emit({"key": key, "approved": count})
        return 0
    if count:
        ctx.out.done(f"Approved {count} answer(s) {scope}.", f"getmeajob plan {key or ''}".strip())
    else:
        ctx.out.done(f"No answers are waiting for review {scope}.")
    return 0


HANDLERS: dict[str, Callable[[argparse.Namespace, Context, list[str]], int]] = {
    "show": _show,
    "unknowns": _unknowns,
    "answer": _answer,
    "review": _review,
    "draft": _draft,
    "approve": _approve,
}


def _cmd_plan(args: argparse.Namespace, ctx: Context) -> int:
    ctx.ws.require()
    words = [str(w) for w in args.words]
    command = words[0] if words and words[0] in SUBCOMMANDS else None
    if args.stub and command != "unknowns":
        raise GetmeajobError("--stub only works with `getmeajob plan unknowns`.")
    if args.all and command != "approve":
        raise GetmeajobError("--all only works with `getmeajob plan approve`.")
    if command is None:
        return _plan(args, ctx, words)
    return HANDLERS[command](args, ctx, words[1:])


def register(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = sub.add_parser(
        "plan",
        help="plan form answers; show, unknowns, answer, review, draft, approve",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "words",
        nargs="*",
        metavar="KEY_OR_COMMAND",
        help="job keys, or one of: " + ", ".join(SUBCOMMANDS),
    )
    parser.add_argument("--refresh", action="store_true", help="fetch the form questions again")
    parser.add_argument(
        "--min-score",
        type=int,
        default=None,
        metavar="N",
        help="plan ranked jobs scoring at least N (default: thresholds.shortlist)",
    )
    parser.add_argument("--stub", metavar="FILE", help="plan unknowns: write a file to fill in")
    parser.add_argument(
        "--all", action="store_true", help="plan approve: every answer waiting for review"
    )
    parser.add_argument(
        "--budget",
        type=int,
        default=4000,
        metavar="N",
        help="plan draft: token budget (estimate), default 4000",
    )
    parser.add_argument(
        "--provider",
        choices=["anthropic", "command"],
        default=None,
        help="plan draft: who writes drafts (default: command if "
        "GETMEAJOB_LLM_COMMAND is set, else anthropic)",
    )
    parser.add_argument(
        "--limit", type=int, default=30, metavar="N", help="show at most N rows (default 30)"
    )
    parser.set_defaults(func=_cmd_plan)
