"""Job text tools: a short digest and a grep, so nobody has to read the whole text.

The digest only points at phrases (experience asked for, skills, sponsorship or
location wording); judging them is the ranker's job.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

from getmeajob.errors import ConfigError
from getmeajob.models import Job
from getmeajob.textutil import truncate

MAX_DIGEST_LINES = 12

_YEARS = re.compile(
    r"(?:\b(?:at least|minimum of|min\.?|over)\s+)?\b\d{1,2}\s*(?:\+|-|–|to|or more)?\s*"
    r"\d{0,2}\+?\s*(?:years?|yrs?)\b[^.\n;]{0,50}",
    re.IGNORECASE,
)
_WATCH = re.compile(
    r"(?:unable|not able) to sponsor[^.\n]{0,30}|no (?:visa )?sponsorship[^.\n]{0,20}|"
    r"(?:not|cannot|can't|won't) (?:offer |provide )?(?:visa )?sponsor\w*[^.\n]{0,20}|"
    r"(?:legally )?authori[sz]ed to work in[^.\n]{0,30}|must (?:be based|reside|live) in"
    r"[^.\n]{0,30}|security clearance[^.\n]{0,20}|citizenship[^.\n]{0,30}",
    re.IGNORECASE,
)


def _skill_names(value: Any) -> list[str]:
    if isinstance(value, Mapping):
        return [str(k) for k in value]
    if isinstance(value, list):
        return [str(v) for v in value if isinstance(v, str | int | float)]
    return []


def mentions(text: str, skill: str) -> bool:
    """Whether the text names a skill as a whole word ("go" needs "Go" or "golang")."""
    name = skill.strip()
    if not name:
        return False
    if len(name) <= 2:
        if name.casefold() == "go" and re.search(r"\bgolang\b", text, re.IGNORECASE):
            return True
        forms = {name.capitalize(), name.upper()}
        return any(re.search(rf"(?<![\w.]){re.escape(f)}(?![\w])", text) for f in forms)
    return re.search(rf"(?<!\w){re.escape(name)}(?!\w)", text, re.IGNORECASE) is not None


def _snippets(pattern: re.Pattern[str], text: str, limit: int) -> list[str]:
    found: list[str] = []
    for match in pattern.finditer(text):
        snippet = " ".join(match.group(0).split())
        if snippet.casefold() not in (f.casefold() for f in found):
            found.append(truncate(snippet, 70))
        if len(found) >= limit:
            break
    return found


def _quoted(items: Iterable[str]) -> str:
    return "; ".join(f'"{item}"' for item in items)


def jd_digest(job: Job, text: str, prefs: Mapping[str, Any] | None = None) -> list[str]:
    """At most 12 short lines about a job and its text."""
    lines = [f"{job.title} at {job.company}"]
    where = job.location or "location not given"
    if job.workplace and job.workplace not in where.casefold():
        where += f" ({job.workplace})"
    lines.append(f"where: {where}")
    meta = [
        f"{label}: {value}"
        for label, value in (("posted", job.posted), ("team", job.department), ("pay", job.comp))
        if value
    ]
    if meta:
        lines.append("; ".join(meta))
    lines.append(f"key: {job.key} (status {job.status})")
    lines.append(f"link: {job.url}")
    if not text.strip():
        lines.append("text: none stored yet (run `getmeajob source`)")
        return lines[:MAX_DIGEST_LINES]
    years = _snippets(_YEARS, text, 2)
    lines.append(f"experience: {_quoted(years)}" if years else "experience: no years mentioned")
    skills = (prefs or {}).get("skills")
    skills = skills if isinstance(skills, Mapping) else {}
    have = [s for s in _skill_names(skills.get("have")) if mentions(text, s)]
    lack = [s for s in _skill_names(skills.get("lack")) if mentions(text, s)]
    if have:
        lines.append(f"skills you have: {', '.join(have)}")
    if lack:
        lines.append(f"skills you lack: {', '.join(lack)}")
    watch = _snippets(_WATCH, text, 3)
    if watch:
        lines.append(f"watch: {_quoted(watch)}")
    lines.append(f"text: {len(text):,} characters; more with --grep RE or --full")
    return lines[:MAX_DIGEST_LINES]


def jd_grep(text: str, pattern: str, context: int = 1) -> list[str]:
    """Matching lines (case-insensitive) with `context` lines around them, numbered.
    Separate groups are split by a `--` line."""
    try:
        regex = re.compile(pattern, re.IGNORECASE)
    except re.error as exc:
        raise ConfigError(
            f"'{pattern}' is not a valid search pattern ({exc.msg}).",
            hint="Use a plain word, or put a backslash before ( ) [ ] + ? * and similar.",
        ) from exc
    lines = text.splitlines()
    hits = [i for i, line in enumerate(lines) if regex.search(line)]
    keep: list[int] = []
    for i in hits:
        for j in range(max(0, i - context), min(len(lines), i + context + 1)):
            if not keep or j > keep[-1]:
                keep.append(j)
    out: list[str] = []
    for index, number in enumerate(keep):
        if index and number != keep[index - 1] + 1:
            out.append("--")
        out.append(f"{number + 1}: {truncate(lines[number], 200)}")
    return out
