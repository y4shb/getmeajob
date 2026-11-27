"""Which job sources exist: the built-ins plus plugins.

A plugin package adds a source with an entry point in the `getmeajob.sources` group:

    [project.entry-points."getmeajob.sources"]
    mysource = "my_package.module:MySource"

The entry point may name a class (made with no arguments) or a ready object. It must
have `name`, `list_jobs`, `probe` and `parse_url` (see `getmeajob.sources.base`).
A plugin cannot replace a built-in source; problems are kept in `plugin_problems()`.
"""

from __future__ import annotations

import functools
from importlib.metadata import entry_points

from getmeajob.errors import ConfigError
from getmeajob.sources.ashby import AshbySource
from getmeajob.sources.base import Source
from getmeajob.sources.greenhouse import GreenhouseSource
from getmeajob.sources.lever import LeverSource
from getmeajob.sources.recruitee import RecruiteeSource
from getmeajob.sources.smartrecruiters import SmartRecruitersSource
from getmeajob.sources.workable import WorkableSource

ENTRY_POINT_GROUP = "getmeajob.sources"
ATS_FOR_FORMS = frozenset({"greenhouse", "ashby"})
BUILTIN_ORDER = ("greenhouse", "ashby", "lever", "smartrecruiters", "workable", "recruitee")

_problems: list[str] = []


def builtin_sources() -> dict[str, Source]:
    sources: list[Source] = [
        GreenhouseSource(),
        AshbySource(),
        LeverSource(),
        SmartRecruitersSource(),
        WorkableSource(),
        RecruiteeSource(),
    ]
    return {s.name: s for s in sources}


def _load_plugins(known: set[str]) -> dict[str, Source]:
    found: dict[str, Source] = {}
    for ep in entry_points(group=ENTRY_POINT_GROUP):
        try:
            loaded = ep.load()
            source = loaded() if isinstance(loaded, type) else loaded
        except Exception as exc:  # a broken plugin must not break the built-ins
            _problems.append(f"plugin {ep.name!r} did not load: {type(exc).__name__}: {exc}")
            continue
        if not isinstance(source, Source) or not isinstance(getattr(source, "name", None), str):
            _problems.append(f"plugin {ep.name!r} is not a source (needs name, list_jobs, probe)")
            continue
        if source.name in known or source.name in found:
            _problems.append(f"plugin {ep.name!r} uses the taken source name {source.name!r}")
            continue
        found[source.name] = source
    return found


@functools.cache
def all_sources() -> dict[str, Source]:
    """Built-in sources, then plugin sources. Cached; `all_sources.cache_clear()` reloads."""
    _problems.clear()
    sources = builtin_sources()
    sources.update(_load_plugins(set(sources)))
    return sources


def plugin_problems() -> list[str]:
    all_sources()
    return list(_problems)


def get_source(name: str) -> Source:
    sources = all_sources()
    source = sources.get((name or "").strip().casefold())
    if source is None:
        raise ConfigError(
            f"There is no job source called {name!r}.",
            hint=f"Use one of: {', '.join(sources)}.",
        )
    return source
