"""Tool settings from `settings.yaml` in the workspace (all optional)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from getmeajob.errors import ConfigError
from getmeajob.workspace import Workspace
from getmeajob.yamlio import load_yaml

FIXTURES_ENV = "GETMEAJOB_FIXTURES"


@dataclass
class Settings:
    fixtures: Path | None = None
    offline: bool = False
    min_interval: float = 1.0
    timeout: float = 25.0
    retries: int = 3
    max_workers: int = 4


def _bad(path: Path, key: str, expected: str, value: Any) -> ConfigError:
    return ConfigError(
        f"{path.name}: '{key}' should be {expected}, not {value!r}.",
        hint=f"Fix '{key}' in {path}, or delete the line to use the default.",
    )


def _number(path: Path, data: dict[str, Any], key: str, default: float, minimum: float) -> float:
    value = data.get(key)
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int | float) or value < minimum:
        raise _bad(path, key, f"a number of at least {minimum:g}", value)
    return float(value)


def _integer(path: Path, data: dict[str, Any], key: str, default: int, minimum: int) -> int:
    value = data.get(key)
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise _bad(path, key, f"a whole number of at least {minimum}", value)
    return value


def load_settings(ws: Workspace) -> Settings:
    """Settings from `settings.yaml` (defaults when missing).

    GETMEAJOB_FIXTURES overrides `fixtures` and turns on offline mode. A relative
    `fixtures` path in the file is relative to the workspace folder.
    """
    path = ws.settings_path
    data = load_yaml(path, required=False)
    defaults = Settings()

    fixtures: Path | None = None
    raw_fixtures = data.get("fixtures")
    if raw_fixtures not in (None, ""):
        if not isinstance(raw_fixtures, str):
            raise _bad(path, "fixtures", "a folder path", raw_fixtures)
        fixtures = Path(raw_fixtures).expanduser()
        if not fixtures.is_absolute():
            fixtures = ws.root / fixtures

    offline = data.get("offline", defaults.offline)
    if offline is None:
        offline = defaults.offline
    if not isinstance(offline, bool):
        raise _bad(path, "offline", "true or false", offline)

    env_fixtures = os.environ.get(FIXTURES_ENV, "").strip()
    if env_fixtures:
        fixtures = Path(env_fixtures).expanduser().resolve()
        offline = True

    return Settings(
        fixtures=fixtures,
        offline=offline,
        min_interval=_number(path, data, "min_interval", defaults.min_interval, 0.0),
        timeout=_number(path, data, "timeout", defaults.timeout, 1.0),
        retries=_integer(path, data, "retries", defaults.retries, 0),
        max_workers=_integer(path, data, "max_workers", defaults.max_workers, 1),
    )
