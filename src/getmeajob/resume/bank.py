"""The fact bank: everything you are willing to say about yourself, written by you.

Tailoring only selects and orders what is in `resume/bank.yaml`. It never writes a new
sentence. The format is described in `docs/resumes.md`.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from getmeajob.errors import ConfigError
from getmeajob.workspace import Workspace
from getmeajob.yamlio import load_yaml


@dataclass(slots=True)
class Header:
    name: str
    email: str = ""
    phone: str = ""
    location: str = ""
    links: list[str] = field(default_factory=list)


@dataclass(slots=True)
class Summary:
    id: str
    text: str
    tags: list[str] = field(default_factory=list)


@dataclass(slots=True)
class Bullet:
    id: str
    text: str
    tags: list[str] = field(default_factory=list)
    short: str = ""  # an optional shorter wording you wrote, used only to fit one page


@dataclass(slots=True)
class Role:
    company: str
    title: str
    start: str = ""
    end: str = ""
    bullets: list[Bullet] = field(default_factory=list)


@dataclass(slots=True)
class Project:
    name: str
    bullets: list[Bullet] = field(default_factory=list)


@dataclass(slots=True)
class Education:
    school: str
    degree: str = ""
    field: str = ""
    start: str = ""
    end: str = ""


@dataclass(slots=True)
class Bank:
    header: Header
    summaries: list[Summary] = field(default_factory=list)
    experience: list[Role] = field(default_factory=list)
    projects: list[Project] = field(default_factory=list)
    skills: dict[str, list[str]] = field(default_factory=dict)
    education: list[Education] = field(default_factory=list)
    hash: str = ""

    def all_bullets(self) -> list[Bullet]:
        found = [b for role in self.experience for b in role.bullets]
        return found + [b for project in self.projects for b in project.bullets]

    def search_text(self) -> str:
        """Every word in the bank, tags included, for "is this in the bank at all?"."""
        parts: list[str] = [s.text + " " + " ".join(s.tags) for s in self.summaries]
        parts += [b.text + " " + " ".join(b.tags) for b in self.all_bullets()]
        parts += [f"{r.title} {r.company}" for r in self.experience]
        parts += [p.name for p in self.projects]
        parts += [item for items in self.skills.values() for item in items]
        parts += [f"{e.degree} {e.field} {e.school}" for e in self.education]
        return "\n".join(parts)

    def sentences(self) -> set[str]:
        """Every text the resume may contain word for word."""
        found: set[str] = set()
        found.update(s.text for s in self.summaries)
        for bullet in self.all_bullets():
            found.add(bullet.text)
            if bullet.short:
                found.add(bullet.short)
        return found


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _list(value: Any, where: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, list):
        return [_text(v) for v in value if _text(v)]
    raise ConfigError(
        f"resume/bank.yaml: '{where}' should be a list.",
        hint="Write it like `[one, two]` or one `- item` per line.",
    )


def _bullets(raw: Any, where: str, seen: set[str]) -> list[Bullet]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ConfigError(
            f"resume/bank.yaml: '{where}' should be a list of bullets.",
            hint="Each bullet needs an `id` and a `text`.",
        )
    out: list[Bullet] = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict) or not _text(item.get("id")) or not _text(item.get("text")):
            raise ConfigError(
                f"resume/bank.yaml: bullet {i + 1} under '{where}' needs an `id` and a `text`.",
                hint="Example: `- id: api-1` then `text: Built a billing API.` on the next line.",
            )
        bullet_id = _text(item["id"])
        if bullet_id in seen:
            raise ConfigError(
                f"resume/bank.yaml: the bullet id '{bullet_id}' is used twice.",
                hint="Give every bullet its own short id.",
            )
        seen.add(bullet_id)
        out.append(
            Bullet(
                id=bullet_id,
                text=_text(item["text"]),
                tags=_list(item.get("tags"), f"{where}.{bullet_id}.tags"),
                short=_text(item.get("short")),
            )
        )
    return out


def _dicts(raw: Any, where: str) -> list[dict[str, Any]]:
    if raw is None:
        return []
    if not isinstance(raw, list) or not all(isinstance(i, dict) for i in raw):
        raise ConfigError(
            f"resume/bank.yaml: '{where}' should be a list of entries.",
            hint="Compare it with examples/demo/resume/bank.yaml.",
        )
    return raw


def parse_bank(data: dict[str, Any]) -> Bank:
    """Build a `Bank` from the parsed YAML, with friendly errors."""
    head = data.get("header")
    if not isinstance(head, dict) or not _text(head.get("name")):
        raise ConfigError(
            "resume/bank.yaml has no header with your name.",
            hint="Add `header:` with at least `name:`. See examples/demo/resume/bank.yaml.",
        )
    seen: set[str] = set()
    summaries: list[Summary] = []
    for i, item in enumerate(_dicts(data.get("summaries"), "summaries")):
        if not _text(item.get("id")) or not _text(item.get("text")):
            raise ConfigError(
                f"resume/bank.yaml: summary {i + 1} needs an `id` and a `text`.",
                hint="Example: `- id: sum-1` then `text: ...`.",
            )
        summaries.append(
            Summary(_text(item["id"]), _text(item["text"]), _list(item.get("tags"), "summary tags"))
        )
    experience = [
        Role(
            company=_text(item.get("company")),
            title=_text(item.get("title")),
            start=_text(item.get("start")),
            end=_text(item.get("end")),
            bullets=_bullets(item.get("bullets"), f"experience.{_text(item.get('company'))}", seen),
        )
        for item in _dicts(data.get("experience"), "experience")
    ]
    projects = [
        Project(
            name=_text(item.get("name")),
            bullets=_bullets(item.get("bullets"), f"projects.{_text(item.get('name'))}", seen),
        )
        for item in _dicts(data.get("projects"), "projects")
    ]
    skills_raw = data.get("skills") or {}
    if not isinstance(skills_raw, dict):
        raise ConfigError(
            "resume/bank.yaml: 'skills' should be `category: [items]` lines.",
            hint="Example: `languages: [Python, SQL]`.",
        )
    education = [
        Education(
            school=_text(item.get("school")),
            degree=_text(item.get("degree")),
            field=_text(item.get("field")),
            start=_text(item.get("start")),
            end=_text(item.get("end")),
        )
        for item in _dicts(data.get("education"), "education")
    ]
    digest = hashlib.sha256(
        json.dumps(data, sort_keys=True, default=str, ensure_ascii=False).encode("utf-8")
    ).hexdigest()[:16]
    return Bank(
        header=Header(
            name=_text(head["name"]),
            email=_text(head.get("email")),
            phone=_text(head.get("phone")),
            location=_text(head.get("location")),
            links=_list(head.get("links"), "header.links"),
        ),
        summaries=summaries,
        experience=experience,
        projects=projects,
        skills={str(k): _list(v, f"skills.{k}") for k, v in skills_raw.items()},
        education=education,
        hash=digest,
    )


def load_bank(ws: Workspace) -> Bank:
    """Read `resume/bank.yaml` from the workspace."""
    if not ws.resume_bank_path.exists():
        raise ConfigError(
            f"No fact bank found (looked for {ws.resume_bank_path}).",
            hint="Copy examples/demo/resume/bank.yaml there and replace it with your own facts.",
        )
    return parse_bank(load_yaml(ws.resume_bank_path))
