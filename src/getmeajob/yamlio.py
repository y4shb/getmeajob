"""Reading and writing the YAML config files, with friendly errors."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml

from getmeajob.errors import ConfigError
from getmeajob.files import atomic_write_text


def load_yaml(path: Path, *, required: bool = True) -> dict[str, Any]:
    """Load a YAML file whose top level is a mapping.

    A missing optional file gives `{}`. An empty file gives `{}`. A parse error raises
    `ConfigError` naming the file and line.
    """
    if not path.exists():
        if not required:
            return {}
        raise ConfigError(
            f"{path.name} is missing (looked for {path}).",
            hint="Run `getmeajob init` to create it from the template, then fill it in.",
        )
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ConfigError(
            f"{path} is not plain UTF-8 text.",
            hint="Save the file as UTF-8 text in your editor and try again.",
        ) from exc
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        where = f" on line {mark.line + 1}" if mark is not None else ""
        problem = getattr(exc, "problem", None) or "it could not be read"
        raise ConfigError(
            f"{path} has a formatting problem{where}: {problem}.",
            hint=(
                "YAML is picky about indentation and colons. Check that line and the one "
                "above it (use spaces, not tabs)."
            ),
        ) from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigError(
            f"{path} should hold named settings (`name: value` lines) at the top level, "
            f"but it holds a {type(data).__name__}.",
            hint="Compare it with the matching file in config/ or examples/demo/.",
        )
    return data


def dump_yaml(path: Path, data: Any, *, header: str = "", width: int | None = None) -> None:
    """Write YAML atomically, keeping key order and non-ASCII text as is.

    `header` (comment lines, say) goes first, as is. `width` is where long text wraps
    (PyYAML's default, 80, when None).
    """
    text = yaml.safe_dump(
        data, sort_keys=False, allow_unicode=True, default_flow_style=False, width=width
    )
    atomic_write_text(path, header + text)


def string_list(value: Any) -> list[str] | None:
    """A YAML value as a list of trimmed, non-empty strings.

    Nothing gives `[]` and one string a one-item list. Anything else that is not a list
    gives None, so the caller can say what it expected.
    """
    if value is None:
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, list | tuple):
        return [str(v).strip() for v in value if v is not None and str(v).strip()]
    return None


def get_path(data: Mapping[str, Any], dotted: str) -> Any | None:
    """Look up `a.b.c` in nested mappings (a number picks a list item). Missing gives None."""
    node: Any = data
    for part in dotted.split("."):
        if isinstance(node, Mapping):
            if part not in node:
                return None
            node = node[part]
        elif isinstance(node, Sequence) and not isinstance(node, str) and part.isdigit():
            index = int(part)
            if index >= len(node):
                return None
            node = node[index]
        else:
            return None
    return node
