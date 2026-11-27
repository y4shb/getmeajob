"""Find skills in job text, using the patterns in `skills_default.yaml`."""

from __future__ import annotations

import re
from functools import cache
from pathlib import Path
from typing import Any

import yaml

from getmeajob.rank.prefs import Preferences

DATA_FILE = Path(__file__).with_name("skills_default.yaml")
GAP_WINDOW = 6000
_EDGE_BEFORE = r"(?<![A-Za-z0-9_])"
_EDGE_AFTER = r"(?![A-Za-z0-9_])"


@cache
def _catalog() -> dict[str, re.Pattern[str]]:
    """Canonical skill name (and each alias) to its compiled pattern."""
    raw = yaml.safe_load(DATA_FILE.read_text(encoding="utf-8")) or {}
    catalog: dict[str, re.Pattern[str]] = {}
    for name, spec in raw.items():
        entry: dict[str, Any] = spec if isinstance(spec, dict) else {"regex": spec}
        parts = entry["regex"] if isinstance(entry["regex"], list) else [entry["regex"]]
        body = "|".join(f"(?:{p})" for p in parts)
        if not entry.get("raw"):
            body = f"{_EDGE_BEFORE}(?:{body}){_EDGE_AFTER}"
        flags = 0 if entry.get("case_sensitive") else re.IGNORECASE
        pattern = re.compile(body, flags)
        for key in [str(name).lower(), *[str(a).lower() for a in entry.get("aliases", [])]]:
            catalog.setdefault(key, pattern)
    return catalog


def canonical_names() -> list[str]:
    """The skills that have their own pattern (aliases left out)."""
    raw = yaml.safe_load(DATA_FILE.read_text(encoding="utf-8")) or {}
    return [str(name).lower() for name in raw]


@cache
def skill_regex(name: str) -> re.Pattern[str]:
    """The pattern for one skill name. Unknown names are searched for as plain text."""
    key = name.strip().lower()
    known = _catalog().get(key)
    if known is not None:
        return known
    return re.compile(f"{_EDGE_BEFORE}{re.escape(key)}{_EDGE_AFTER}", re.IGNORECASE)


def mentions(text: str, name: str) -> bool:
    """Does `text` mention this skill?"""
    return skill_regex(name).search(text) is not None


def find_skills(text: str) -> dict[str, int]:
    """Every catalog skill found in `text`, with how many times it appears."""
    found: dict[str, int] = {}
    for name in canonical_names():
        count = len(skill_regex(name).findall(text))
        if count:
            found[name] = count
    return found


def skill_matches(text: str, prefs: Preferences) -> tuple[list[str], list[str]]:
    """(skills you have that the job names, skills you lack that the job names).

    The first list is ordered by the weight you gave each skill. Gaps are looked for in
    the first 6000 characters, where requirements usually sit.
    """
    have = sorted(
        (name for name in prefs.skills_have if mentions(text, name)),
        key=lambda n: (-prefs.skills_have[n], n),
    )
    head = text[:GAP_WINDOW]
    gaps = [name for name in prefs.skills_lack if mentions(head, name)]
    return have, gaps
