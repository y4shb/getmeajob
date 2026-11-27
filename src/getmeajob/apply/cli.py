"""`getmeajob apply` and `getmeajob inspect`.

apply [KEY...] [--mode dry|hold|submit] [--headed] [--click-submit]
      [--hold-timeout SECONDS] [--limit N]      fill planned forms (default: dry)
inspect URL [--limit N]                          list a form's fields, labels, options
"""

from __future__ import annotations

import argparse
from collections import Counter
from typing import TYPE_CHECKING

from getmeajob.models import ApplyMode, ApplyStatus, LedgerEntry

if TYPE_CHECKING:
    from getmeajob.cli import Context

NEXT = {
    ApplyStatus.dry_ok: "getmeajob apply --mode hold --headed   (you click Submit)",
    ApplyStatus.fill_problem: "getmeajob queue   (what to fix), then a dry run again",
    ApplyStatus.needs_email_code: "getmeajob apply KEY --mode hold --headed --click-submit",
    ApplyStatus.captcha: "getmeajob queue",
    ApplyStatus.account_required: "getmeajob queue",
    ApplyStatus.automation_refused: "getmeajob queue",
    ApplyStatus.validation_error: "getmeajob queue",
    ApplyStatus.awaiting_human: "getmeajob queue",
}


def _row(entry: LedgerEntry) -> dict[str, object]:
    detail = entry.detail
    if entry.problems:
        detail = f"{detail}; {len(entry.problems)} problem(s): {entry.problems[0]}"
    return {
        "key": entry.job_key,
        "status": entry.status.value,
        "detail": detail,
        "screenshot": entry.screenshot or "",
    }


def _apply(args: argparse.Namespace, ctx: Context) -> int:
    from getmeajob.apply.runner import run_apply

    ws = ctx.ws.require()
    out = ctx.out
    entries = run_apply(
        ws,
        args.keys or None,
        mode=ApplyMode(args.mode),
        headed=bool(args.headed),
        click_submit=bool(args.click_submit),
        hold_timeout=float(args.hold_timeout),
        limit=args.limit,
        notify=out.line,
    )
    if out.json_mode:
        out.emit({"mode": args.mode, "results": [e.to_dict() for e in entries]})
        return 0
    if not entries:
        out.done(
            "Nothing to apply to: no stored plans for Greenhouse or Ashby jobs.",
            next_step="getmeajob plan",
        )
        return 0
    out.table([_row(e) for e in entries], ["key", "status", "detail", "screenshot"], max_col=60)
    counts = Counter(e.status for e in entries)
    summary = ", ".join(f"{n} {s.value}" for s, n in counts.most_common())
    attempted = sum(1 for e in entries if not e.status.value.startswith("skipped"))
    if args.limit is not None and attempted >= args.limit:
        summary += f" (stopped at --limit {args.limit})"
    nxt = next((NEXT[s] for s in NEXT if s in counts), None)
    if args.mode == ApplyMode.dry.value and counts.get(ApplyStatus.dry_ok):
        nxt = "look at the screenshots in shots/, then: " + NEXT[ApplyStatus.dry_ok]
    out.done(f"{args.mode} run: {summary}.", next_step=nxt)
    return 0


def _inspect(args: argparse.Namespace, ctx: Context) -> int:
    from getmeajob.apply.inspect import inspect_form

    ctx.ws.require()
    result = inspect_form(args.url, ctx.settings_loader())
    out = ctx.out
    if out.json_mode:
        out.emit(result.to_dict())
        return 0
    rows = [
        {
            "field": f.field,
            "kind": f.kind,
            "req": f.required,
            "label": f.label,
            "options": ", ".join(f.options[:6]) + (", ..." if len(f.options) > 6 else ""),
        }
        for f in result.fields
    ]
    out.table(rows[: args.limit], ["field", "kind", "req", "label", "options"], max_col=40)
    if len(rows) > args.limit:
        out.line(f"... and {len(rows) - args.limit} more (use --limit or --json)")
    for signal in result.signals:
        out.line(f"note: {signal}")
    out.done(f"{len(rows)} field(s) on {args.url}.")
    return 0


def register(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Add `apply` and `inspect`."""
    p = sub.add_parser(
        "apply",
        help="fill planned forms: dry (default), hold (you submit) or submit",
        description=(
            "Fill application forms from your plans. dry fills and takes a screenshot, never "
            "submitting. hold opens a window, fills it, and you finish it (click Submit, type "
            "an emailed code). submit clicks Submit once, only for boards listed in "
            "apply.submit_boards in preferences.yaml."
        ),
    )
    p.add_argument("keys", nargs="*", metavar="KEY", help="job keys (default: every planned job)")
    p.add_argument(
        "--mode",
        choices=[m.value for m in ApplyMode],
        default=ApplyMode.dry.value,
        help="dry (default), hold or submit",
    )
    p.add_argument("--headed", action="store_true", help="show the browser window (hold needs it)")
    p.add_argument(
        "--click-submit",
        action="store_true",
        help="in a hold run, let getmeajob click Submit once after filling",
    )
    p.add_argument(
        "--hold-timeout",
        type=float,
        default=900.0,
        metavar="SECONDS",
        help="how long a hold run waits for you per job (default 900)",
    )
    p.add_argument("--limit", type=int, default=None, metavar="N", help="try at most N jobs")
    p.set_defaults(func=_apply)

    q = sub.add_parser("inspect", help="list a form's fields, labels and options")
    q.add_argument("url", metavar="URL", help="form link (or a local .html file)")
    q.add_argument("--limit", type=int, default=40, metavar="N", help="rows to show (default 40)")
    q.set_defaults(func=_inspect)
