"""The tailored resume as data, and how it becomes Markdown and HTML.

A `ResumeDoc` holds only text copied from the fact bank. Rendering never adds words
except the fixed section headings and the separators between fields.
"""

from __future__ import annotations

import dataclasses
import html
from pathlib import Path

from getmeajob.serial import Model

TEMPLATE = Path(__file__).with_name("template.html")


@dataclasses.dataclass(slots=True)
class DocBullet(Model):
    id: str
    text: str
    score: float = 0.0
    short: str = ""


@dataclasses.dataclass(slots=True)
class DocRole(Model):
    heading: str  # a job title, or a project name
    company: str = ""
    dates: str = ""
    bullets: list[DocBullet] = dataclasses.field(default_factory=list)


@dataclasses.dataclass(slots=True)
class DocSkills(Model):
    label: str
    items: list[str] = dataclasses.field(default_factory=list)


@dataclasses.dataclass(slots=True)
class ResumeDoc(Model):
    name: str
    contact: list[str] = dataclasses.field(default_factory=list)
    links: list[str] = dataclasses.field(default_factory=list)
    summary_id: str = ""
    summary: str = ""
    experience: list[DocRole] = dataclasses.field(default_factory=list)
    projects: list[DocRole] = dataclasses.field(default_factory=list)
    skills: list[DocSkills] = dataclasses.field(default_factory=list)
    education: list[str] = dataclasses.field(default_factory=list)


def bullet_text(bullet: DocBullet, *, use_short: bool) -> str:
    return bullet.short if use_short and bullet.short else bullet.text


def view(doc: ResumeDoc, *, drop: set[str] | None = None, use_short: bool = False) -> ResumeDoc:
    """A copy with some bullets removed and, optionally, your shorter wordings swapped in."""
    gone = drop or set()

    def keep(roles: list[DocRole]) -> list[DocRole]:
        return [
            dataclasses.replace(
                role,
                bullets=[
                    dataclasses.replace(b, text=bullet_text(b, use_short=use_short), short="")
                    for b in role.bullets
                    if b.id not in gone
                ],
            )
            for role in roles
        ]

    return dataclasses.replace(doc, experience=keep(doc.experience), projects=keep(doc.projects))


def _role_line(role: DocRole) -> str:
    left = ", ".join(p for p in (role.heading, role.company) if p)
    return f"{left} ({role.dates})" if role.dates else left


def to_markdown(doc: ResumeDoc) -> str:
    lines = [f"# {doc.name}", ""]
    if doc.contact:
        lines.append(" | ".join(doc.contact))
    if doc.links:
        lines.append(" | ".join(doc.links))
    if doc.summary:
        lines += ["", "## Summary", "", doc.summary]
    if doc.experience:
        lines += ["", "## Experience"]
        for role in doc.experience:
            lines += ["", f"### {_role_line(role)}", ""]
            lines += [f"- {b.text}" for b in role.bullets]
    if doc.projects:
        lines += ["", "## Projects"]
        for role in doc.projects:
            lines += ["", f"### {_role_line(role)}", ""]
            lines += [f"- {b.text}" for b in role.bullets]
    if doc.skills:
        lines += ["", "## Skills", ""]
        lines += [f"- {row.label}: {', '.join(row.items)}" for row in doc.skills]
    if doc.education:
        lines += ["", "## Education", ""]
        lines += [f"- {entry}" for entry in doc.education]
    return "\n".join(lines).rstrip() + "\n"


def _e(text: str) -> str:
    return html.escape(text, quote=True)


def _link(url: str) -> str:
    safe = _e(url)
    shown = _e(url.removeprefix("https://").removeprefix("http://").rstrip("/"))
    return f'<a href="{safe}">{shown}</a>'


def _html_roles(roles: list[DocRole]) -> list[str]:
    out: list[str] = []
    for role in roles:
        title = f"<strong>{_e(role.heading)}</strong>"
        if role.company:
            title += f", {_e(role.company)}"
        dates = f'<span class="dates">{_e(role.dates)}</span>' if role.dates else ""
        out.append(f'<div class="role"><div class="role-head"><span>{title}</span>{dates}</div>')
        out.append("<ul>")
        for bullet in role.bullets:
            out.append(
                f'<li data-id="{_e(bullet.id)}" data-score="{bullet.score:g}">'
                f"{_e(bullet.text)}</li>"
            )
        out.append("</ul></div>")
    return out


def to_html(doc: ResumeDoc) -> str:
    parts = [f"<h1>{_e(doc.name)}</h1>"]
    if doc.contact or doc.links:
        items = [_e(c) for c in doc.contact] + [_link(u) for u in doc.links]
        parts.append('<p class="contact">' + "".join(f"<span>{i}</span>" for i in items) + "</p>")
    if doc.summary:
        parts.append(f'<h2>Summary</h2><p class="summary">{_e(doc.summary)}</p>')
    if doc.experience:
        parts.append("<h2>Experience</h2>")
        parts += _html_roles(doc.experience)
    if doc.projects:
        parts.append("<h2>Projects</h2>")
        parts += _html_roles(doc.projects)
    if doc.skills:
        parts.append("<h2>Skills</h2>")
        for row in doc.skills:
            names = _e(", ".join(row.items))
            parts.append(f'<p class="skills"><strong>{_e(row.label)}:</strong> {names}</p>')
    if doc.education:
        parts.append("<h2>Education</h2>")
        parts += [f'<p class="edu">{_e(entry)}</p>' for entry in doc.education]
    template = TEMPLATE.read_text(encoding="utf-8")
    return (
        template.replace("{{title}}", _e(f"{doc.name} - resume"))
        .replace("{{body}}", "\n".join(parts))
        .replace("{{lang}}", "en")
    )
