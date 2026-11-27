"""The candidate profile (`profile.yaml`): the only source of facts for form answers.

`Profile.get("contact.email")` looks up a dotted path. Blank text, empty lists and
empty mappings count as missing and give None, so a rule never answers from an
empty field. The schema is documented in `config/profile.example.yaml`.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from getmeajob.textutil import short_hash
from getmeajob.workspace import Workspace
from getmeajob.yamlio import get_path, load_yaml


def is_blank(value: Any) -> bool:
    """True for None, blank text and empty containers."""
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, list | tuple | set | dict):
        return len(value) == 0
    return False


@dataclass
class Profile:
    """A thin wrapper over the profile YAML mapping."""

    data: dict[str, Any] = field(default_factory=dict)
    path: Path | None = None

    def get(self, dotted: str) -> Any | None:
        """The value at `a.b.c` (a number picks a list item), or None when blank."""
        value = get_path(self.data, dotted)
        return None if is_blank(value) else value

    def text(self, dotted: str) -> str | None:
        """The value as trimmed text (numbers become text), or None when blank."""
        value = self.get(dotted)
        if value is None or isinstance(value, Mapping | list):
            return None
        if isinstance(value, bool):
            return "Yes" if value else "No"
        if isinstance(value, float) and value.is_integer():
            return str(int(value))
        return str(value).strip()

    def strings(self, dotted: str) -> list[str]:
        """A list value as a list of non-blank strings (a single value becomes one item)."""
        value = self.get(dotted)
        if value is None:
            return []
        items = value if isinstance(value, list | tuple) else [value]
        return [str(v).strip() for v in items if not is_blank(v)]

    def digest(self) -> str:
        """A short hash of the whole profile, used to notice changes."""
        return short_hash(json.dumps(self.data, sort_keys=True, default=str))


def load_profile(ws: Workspace) -> Profile:
    """Read `profile.yaml` from the workspace (a friendly error when it is missing)."""
    data = load_yaml(ws.profile_path, required=True)
    return Profile(data=data, path=ws.profile_path)
