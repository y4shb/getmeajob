"""`getmeajob resume ...`: tailor, render, keywords, list, pick, lint."""

from __future__ import annotations

import argparse
import contextlib
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from getmeajob.errors import GetmeajobError
from getmeajob.rank.score import job_text
from getmeajob.resume.bank import load_bank, parse_bank
from getmeajob.resume.keywords import coverage
from getmeajob.resume.lint import lint_text
from getmeajob.resume.store import list_roles, pick_for_job, role_for_key
from getmeajob.resume.tailor import DEFAULT_MAX_BULLETS, bank_terms, tailor
from getmeajob.store import JobStore
from getmeajob.textutil import truncate
from getmeajob.yamlio import load_yaml

if TYPE_CHECKING:
    from getmeajob.cli import Context

SHOW_GAPS = 8


def _shown(path: Path, ctx: Context) -> str:
    try:
        return str(path.relative_to(ctx.ws.root))
    except ValueError:
        return str(path)


def _cmd_tailor(args: argparse.Namespace, ctx: Context) -> int:
    ctx.ws.require()
    job = JobStore(ctx.ws).find(args.key)
    bank = load_bank(ctx.ws)
    result = tailor(ctx.ws, job, job_text(ctx.ws, job), bank, max_bullets_per_role=args.max_bullets)
    report = result.report
    if ctx.out.json_mode:
        ctx.out.emit(
            {
                "role_dir": str(result.path),
                **{k: v for k, v in report.items() if k != "doc"},
            }
        )
        return 0
    matched, total = len(report["matched_keywords"]), len(report["jd_keywords"])
    ctx.out.line(f"Wrote {_shown(result.path, ctx)}")
    ctx.out.line(f"keywords covered: {matched} of {total}")
    gaps = report["gaps_not_in_bank"]
    if gaps:
        ctx.out.line(
            f"not in your bank (never added): {', '.join(gaps[:SHOW_GAPS])}"
            + (" and more" if len(gaps) > SHOW_GAPS else "")
        )
    unused = report["unused_in_bank"]
    if unused:
        ctx.out.line(f"in your bank but not used: {', '.join(unused[:SHOW_GAPS])}")
    if report["lint"]:
        ctx.out.line(f"{len(report['lint'])} wording warnings; see report.json or `resume lint`")
    ctx.out.done("Resume text ready.", next_step=f"getmeajob resume render {result.path.name}")
    return 0


def resolve_role_dir(ctx: Context, target: str) -> Path:
    """A role folder from a path, a folder name under roles/, or a job key."""
    for candidate in (Path(target), ctx.ws.roles_dir / target):
        if (candidate / "resume.html").is_file() or (candidate / "report.json").is_file():
            return candidate.resolve()
    found = role_for_key(ctx.ws, target)
    if found is not None:
        return found
    named = [r.path for r in list_roles(ctx.ws) if target.lower() in r.name.lower()]
    if len(named) == 1:
        return named[0]
    job = None
    with contextlib.suppress(GetmeajobError):
        job = JobStore(ctx.ws).find(target)
    if job is not None:
        found = role_for_key(ctx.ws, job.key)
        if found is not None:
            return found
    raise GetmeajobError(
        f"No role folder matches '{target}'.",
        hint="Run `getmeajob resume list` to see the folders, or `resume tailor KEY` to make one.",
    )


def _cmd_render(args: argparse.Namespace, ctx: Context) -> int:
    from getmeajob.resume.render import render_pdf

    ctx.ws.require()
    role_dir = resolve_role_dir(ctx, args.target)
    pdf = render_pdf(role_dir, one_page=not args.allow_multipage)
    compaction: dict[str, Any] = {}
    report_path = role_dir / "report.json"
    if report_path.is_file():
        compaction = json.loads(report_path.read_text(encoding="utf-8")).get("compaction") or {}
    if ctx.out.json_mode:
        ctx.out.emit({"pdf": str(pdf), "compaction": compaction})
        return 0
    ctx.out.line(f"Wrote {_shown(pdf, ctx)}")
    dropped = compaction.get("dropped") or []
    if compaction.get("used_short_wording"):
        ctx.out.line("used your shorter wordings to fit one page")
    if dropped:
        ctx.out.line(f"dropped {len(dropped)} lowest-scoring bullets to fit: {', '.join(dropped)}")
    ctx.out.done("PDF ready.")
    return 0


def _cmd_keywords(args: argparse.Namespace, ctx: Context) -> int:
    ctx.ws.require()
    job = JobStore(ctx.ws).find(args.key)
    if args.file:
        path = Path(args.file)
        if not path.is_file():
            raise GetmeajobError(
                f"No file at {path}.", hint="Give the path to a .md or .txt copy of your resume."
            )
        if path.suffix.lower() == ".pdf":
            raise GetmeajobError(
                "A PDF cannot be read here.", hint="Pass the resume.md or a .txt copy instead."
            )
        source, text = str(path), path.read_text(encoding="utf-8", errors="replace")
        extra: list[str] = []
    else:
        role = role_for_key(ctx.ws, job.key)
        if role is not None and (role / "resume.md").is_file():
            source, text = _shown(role / "resume.md", ctx), (role / "resume.md").read_text("utf-8")
            extra = []
        else:
            bank = load_bank(ctx.ws)
            source, text = "your fact bank (everything you could say)", bank.search_text()
            extra = bank_terms(bank)
    cover = coverage(job_text(ctx.ws, job), text, extra)
    if ctx.out.json_mode:
        ctx.out.emit(
            {
                "key": job.key,
                "source": source,
                "matched": cover.matched,
                "missing": cover.missing,
                "ratio": round(cover.ratio, 2),
            }
        )
        return 0
    ctx.out.line(f"{job.title} at {job.company}; checked against {source}")
    ctx.out.line(f"covered ({len(cover.matched)}): {', '.join(cover.matched) or 'none'}")
    ctx.out.line(f"missing ({len(cover.missing)}): {', '.join(cover.missing) or 'none'}")
    return 0


def _cmd_list(args: argparse.Namespace, ctx: Context) -> int:
    ctx.ws.require()
    roles = list_roles(ctx.ws)
    rows = [
        {
            "folder": r.name,
            "pdf": r.has_pdf,
            "jobs": len(r.job_keys),
            "company": r.company,
            "title": r.title,
        }
        for r in roles
    ]
    if ctx.out.json_mode:
        ctx.out.emit(
            [
                {**row, "path": str(r.path), "job_keys": r.job_keys}
                for row, r in zip(rows, roles, strict=True)
            ]
        )
        return 0
    if not rows:
        ctx.out.done("No role folders yet.", next_step="getmeajob resume tailor KEY")
        return 0
    ctx.out.table(rows, ["folder", "pdf", "jobs", "company", "title"])
    return 0


def _cmd_pick(args: argparse.Namespace, ctx: Context) -> int:
    ctx.ws.require()
    job = JobStore(ctx.ws).find(args.key)
    pdf = pick_for_job(ctx.ws, job.key)
    if ctx.out.json_mode:
        ctx.out.emit({"key": job.key, "pdf": str(pdf) if pdf else None})
        return 0 if pdf else 1
    if pdf is None:
        ctx.out.done(
            "No rendered resume covers this job yet.",
            next_step=f"getmeajob resume tailor {job.key}",
        )
        return 1
    ctx.out.done(f"Use {_shown(pdf, ctx)} for {job.key}.")
    return 0


def _cmd_lint(args: argparse.Namespace, ctx: Context) -> int:
    ctx.ws.require()
    path = Path(args.path) if args.path else ctx.ws.resume_bank_path
    if not path.is_file():
        raise GetmeajobError(
            f"No file at {path}.", hint="Give a resume .md or your bank.yaml, or run `resume lint`."
        )
    if path.suffix.lower() in {".yaml", ".yml"}:
        bank = parse_bank(load_yaml(path))
        text = "\n".join([s.text for s in bank.summaries] + [x.text for x in bank.all_bullets()])
    else:
        text = path.read_text(encoding="utf-8", errors="replace")
    warnings = lint_text(text)
    if ctx.out.json_mode:
        ctx.out.emit({"path": str(path), "warnings": warnings})
        return 0
    for warning in warnings:
        ctx.out.line(truncate(warning, 100))
    ctx.out.done(f"{len(warnings)} warnings in {_shown(path, ctx)}.")
    return 0


def register(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    resume = sub.add_parser(
        "resume",
        help="a resume per role, picked from your fact bank",
        description="Make a one-page resume for a job from facts you wrote. Nothing is invented.",
    )
    actions = resume.add_subparsers(dest="resume_command", metavar="ACTION", required=True)

    tailor_p = actions.add_parser("tailor", help="select and order bank text for one job")
    tailor_p.add_argument("key", help="job key, or enough of it to match one job")
    tailor_p.add_argument(
        "--max-bullets",
        type=int,
        default=DEFAULT_MAX_BULLETS,
        metavar="N",
        help="most bullets per role (default 4)",
    )
    tailor_p.set_defaults(func=_cmd_tailor)

    render_p = actions.add_parser("render", help="make resume.pdf for a role folder")
    render_p.add_argument("target", help="role folder (path or name) or a job key")
    render_p.add_argument(
        "--allow-multipage", action="store_true", help="do not shorten to fit one page"
    )
    render_p.set_defaults(func=_cmd_render)

    keywords_p = actions.add_parser("keywords", help="which job keywords a resume covers")
    keywords_p.add_argument("key", help="job key, or enough of it to match one job")
    keywords_p.add_argument("--file", metavar="PATH", help="a .md or .txt resume to check")
    keywords_p.set_defaults(func=_cmd_keywords)

    list_p = actions.add_parser("list", help="list the role folders")
    list_p.set_defaults(func=_cmd_list)

    pick_p = actions.add_parser("pick", help="choose the best rendered resume for a job")
    pick_p.add_argument("key", help="job key, or enough of it to match one job")
    pick_p.set_defaults(func=_cmd_pick)

    lint_p = actions.add_parser("lint", help="check resume wording")
    lint_p.add_argument("path", nargs="?", help="a resume .md or bank.yaml (default: your bank)")
    lint_p.set_defaults(func=_cmd_lint)
