from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from getmeajob.errors import ConfigError
from getmeajob.http import HttpClient
from getmeajob.models import Board
from getmeajob.sources import registry
from getmeajob.sources.base import ProbeResult, SourceResult


class SampleSource:
    name = "samplesource"

    def list_jobs(self, board: Board, client: HttpClient) -> SourceResult:
        return SourceResult(found=True, jobs=[])

    def probe(self, slug: str, client: HttpClient) -> ProbeResult:
        return ProbeResult(found=False, board_name=None, count=0)

    def parse_url(self, url: str) -> str | None:
        return None


class FakeEntryPoint:
    def __init__(self, name: str, target: Any) -> None:
        self.name = name
        self._target = target

    def load(self) -> Any:
        if isinstance(self._target, Exception):
            raise self._target
        return self._target


@pytest.fixture
def plugins(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[FakeEntryPoint]]:
    found: list[FakeEntryPoint] = []
    monkeypatch.setattr(registry, "entry_points", lambda group: list(found))
    registry.all_sources.cache_clear()
    yield found
    registry.all_sources.cache_clear()


def test_builtins_and_plugins(plugins: list[FakeEntryPoint]) -> None:
    taken = SampleSource()
    taken.name = "greenhouse"
    plugins += [
        FakeEntryPoint("sample", SampleSource),
        FakeEntryPoint("broken", ImportError("missing module")),
        FakeEntryPoint("notasource", object()),
        FakeEntryPoint("clash", taken),
    ]
    sources = registry.all_sources()
    assert list(sources)[:6] == list(registry.builtin_sources())
    assert isinstance(sources["samplesource"], SampleSource)
    assert type(sources["greenhouse"]).__name__ == "GreenhouseSource"
    problems = "\n".join(registry.plugin_problems())
    assert "'broken' did not load" in problems and "'notasource' is not a source" in problems
    assert "taken source name 'greenhouse'" in problems
    assert registry.get_source("SampleSource").name == "samplesource"
    assert sorted(registry.ATS_FOR_FORMS) == ["ashby", "greenhouse"]


def test_unknown_source_is_a_friendly_error(plugins: list[FakeEntryPoint]) -> None:
    with pytest.raises(ConfigError) as info:
        registry.get_source("workday")
    assert info.value.hint and "greenhouse" in info.value.hint
