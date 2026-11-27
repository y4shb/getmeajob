"""Pick and order the right facts from your bank for one job.

Nothing is written or reworded. For a job description the code scores each bank bullet by
how many of the job's keywords it mentions, keeps the best few per role, orders them best
first, and puts the skills the job names first in each skills row. Words the job asks for
that are not in the bank are listed in `report.json` as gaps and never added. The same
inputs always give the same files.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from getmeajob.errors import GetmeajobError
from getmeajob.files import atomic_write_text, write_json_atomic
from getmeajob.models import Job
from getmeajob.resume.bank import Bank, Bullet, Education, Role
from getmeajob.resume.doc import (
    DocBullet,
    DocRole,
    DocSkills,
    ResumeDoc,
    to_html,
    to_markdown,
)
from getmeajob.resume.keywords import jd_keywords, term_present
from getmeajob.resume.lint import lint_text
from getmeajob.textutil import short_hash, slugify, strip_invisible
from getmeajob.workspace import Workspace
from getmeajob.yamlio import dump_yaml, load_yaml

DEFAULT_MAX_BULLETS = 4
MAX_PROJECTS = 2
MAX_PROJECT_BULLETS = 2
TAG_WEIGHT = 0.5  # a keyword that is only in a bullet's tags counts half


@dataclass(slots=True)
class RoleDir:
    path: Path
    report: dict[str, Any]


def role_dir_name(job: Job) -> str:
    """The folder name for a job: `<company>-<title>`, as short plain slugs."""
    return f"{slugify(job.company, 30)}-{slugify(job.title, 40)}"


def _bullet_score(bullet: Bullet, keywords: list[str]) -> float:
    tags = " ".join(bullet.tags)
    score = 0.0
    for word in keywords:
        if term_present(bullet.text, word):
            score += 1.0
        elif tags and term_present(tags, word):
            score += TAG_WEIGHT
    return score


def _pick_bullets(bullets: list[Bullet], keywords: list[str], limit: int) -> list[DocBullet]:
    scored = [(_bullet_score(b, keywords), i, b) for i, b in enumerate(bullets)]
    best = sorted(scored, key=lambda item: (-item[0], item[1]))[:limit]
    return [DocBullet(id=b.id, text=b.text, score=score, short=b.short) for score, _i, b in best]


def _dates(start: str, end: str) -> str:
    if start and end:
        return f"{start} to {end}"
    return start or end


def _education_line(entry: Education) -> str:
    what = ", ".join(p for p in (entry.degree, entry.field) if p)
    where = ", ".join(p for p in (what, entry.school) if p)
    years = _dates(entry.start, entry.end)
    return f"{where} ({years})" if years else where


def _skill_rows(bank: Bank, jd_text: str) -> list[DocSkills]:
    rows: list[tuple[int, int, DocSkills]] = []
    for order, (label, items) in enumerate(bank.skills.items()):
        if not items:
            continue
        named = [i for i in items if term_present(jd_text, i)]
        rest = [i for i in items if i not in named]
        shown = label.replace("_", " ").strip().capitalize()
        rows.append((-len(named), order, DocSkills(shown, [*named, *rest])))
    return [row for _n, _o, row in sorted(rows, key=lambda r: (r[0], r[1]))]


def _pick_summary(bank: Bank, keywords: list[str]) -> tuple[str, str]:
    best: tuple[float, int] | None = None
    for i, summary in enumerate(bank.summaries):
        pseudo = Bullet(summary.id, summary.text, summary.tags)
        score = _bullet_score(pseudo, keywords)
        if best is None or score > best[0]:
            best = (score, i)
    if best is None:
        return "", ""
    chosen = bank.summaries[best[1]]
    return chosen.id, chosen.text


def _roles(roles: list[Role], keywords: list[str], limit: int) -> list[DocRole]:
    return [
        DocRole(
            heading=role.title,
            company=role.company,
            dates=_dates(role.start, role.end),
            bullets=_pick_bullets(role.bullets, keywords, limit),
        )
        for role in roles
    ]


def build_doc(bank: Bank, jd_text: str, keywords: list[str], max_bullets: int) -> ResumeDoc:
    """Choose and order bank text for these keywords."""
    summary_id, summary = _pick_summary(bank, keywords)
    head = bank.header
    projects = [
        DocRole(
            heading=p.name,
            bullets=_pick_bullets(p.bullets, keywords, MAX_PROJECT_BULLETS),
        )
        for p in bank.projects
    ]
    projects = [p for p in projects if any(b.score > 0 for b in p.bullets)]
    projects.sort(key=lambda p: -max(b.score for b in p.bullets))  # stable for ties
    return ResumeDoc(
        name=head.name,
        contact=[c for c in (head.email, head.phone, head.location) if c],
        links=list(head.links),
        summary_id=summary_id,
        summary=summary,
        experience=_roles(bank.experience, keywords, max_bullets),
        projects=projects[:MAX_PROJECTS],
        skills=_skill_rows(bank, jd_text),
        education=[_education_line(e) for e in bank.education],
    )


def verify_truthful(doc: ResumeDoc, bank: Bank) -> None:
    """Refuse a resume that holds any text the bank does not hold, word for word."""
    allowed = bank.sentences()
    problems: list[str] = []
    if doc.summary and doc.summary not in allowed:
        problems.append("summary")
    for role in [*doc.experience, *doc.projects]:
        for bullet in role.bullets:
            if bullet.text not in allowed:
                problems.append(f"bullet {bullet.id}")
    for row in doc.skills:
        known = {item for items in bank.skills.values() for item in items}
        problems += [f"skill {i}" for i in row.items if i not in known]
    if problems:
        raise GetmeajobError(
            "The tailored resume holds text that is not in your fact bank: "
            + ", ".join(problems[:5])
            + ".",
            hint="This is a bug in getmeajob. Nothing was written. Please report it.",
        )


def _keyword_split(
    keywords: list[str], resume_text: str, bank_text: str
) -> tuple[list[str], list[str], list[str]]:
    matched = [k for k in keywords if term_present(resume_text, k)]
    rest = [k for k in keywords if k not in matched]
    unused = [k for k in rest if term_present(bank_text, k)]
    gaps = [k for k in rest if k not in unused]
    return matched, unused, gaps


def bank_terms(bank: Bank) -> list[str]:
    """Words from the bank worth looking for in a job: skills and tags."""
    terms: list[str] = [i for items in bank.skills.values() for i in items]
    for bullet in bank.all_bullets():
        terms += bullet.tags
    for summary in bank.summaries:
        terms += summary.tags
    return list(dict.fromkeys(t.strip() for t in terms if t.strip()))


def selected_ids(doc: ResumeDoc) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for role in [*doc.experience, *doc.projects]:
        label = ", ".join(p for p in (role.heading, role.company) if p)
        out += [{"id": b.id, "role": label, "score": b.score} for b in role.bullets]
    return out


def write_role_files(path: Path, doc: ResumeDoc, report: dict[str, Any]) -> None:
    atomic_write_text(path / "resume.md", to_markdown(doc))
    atomic_write_text(path / "resume.html", to_html(doc))
    write_json_atomic(path / "report.json", report)


def tailor(
    ws: Workspace,
    job: Job,
    jd_text: str,
    bank: Bank,
    *,
    max_bullets_per_role: int = DEFAULT_MAX_BULLETS,
) -> RoleDir:
    """Write `roles/<company>-<title>/` with the job text, a resume and a report."""
    jd = strip_invisible(jd_text).strip()
    if not jd:
        raise GetmeajobError(
            f"There is no job description for {job.key}.",
            hint="Run `getmeajob source` to fetch it, or save the text in data/jd/.",
        )
    limit = max(1, max_bullets_per_role)
    keywords = jd_keywords(jd, bank_terms(bank))
    doc = build_doc(bank, jd, keywords, limit)
    verify_truthful(doc, bank)
    markdown = to_markdown(doc)
    matched, unused, gaps = _keyword_split(keywords, markdown, bank.search_text())
    path = ws.roles_dir / role_dir_name(job)
    path.mkdir(parents=True, exist_ok=True)
    previous = load_yaml(path / "meta.yaml", required=False).get("job_keys") or []
    job_keys = sorted({str(k) for k in previous} | {job.key})
    report: dict[str, Any] = {
        "company": job.company,
        "title": job.title,
        "job_keys": job_keys,
        "bank_hash": bank.hash,
        "jd_keywords": keywords,
        "matched_keywords": matched,
        "unused_in_bank": unused,
        "gaps_not_in_bank": gaps,
        "bullets_selected": selected_ids(doc),
        "summary_id": doc.summary_id,
        "max_bullets_per_role": limit,
        "lint": lint_text(markdown),
        "doc": doc.to_dict(),
    }
    atomic_write_text(path / "jd.txt", jd + "\n")
    write_role_files(path, doc, report)
    dump_yaml(
        path / "meta.yaml",
        {
            "company": job.company,
            "title": job.title,
            "job_keys": job_keys,
            "bank_hash": bank.hash,
            "jd_hash": short_hash(jd),
        },
    )
    return RoleDir(path, report)
