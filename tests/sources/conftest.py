"""Helpers for the sources tests: fake clients over recorded or hand-made replies."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from getmeajob.demo import examples_dir
from getmeajob.http import FixtureTransport, HttpClient

FIXTURES = Path(__file__).parent / "fixtures"
Handler = Callable[[httpx.Request], httpx.Response]


class FakeSleep:
    def __init__(self) -> None:
        self.calls: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


def load_fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def fixture_json() -> Callable[[str], Any]:
    """Load a JSON file from tests/sources/fixtures."""
    return load_fixture


@pytest.fixture
def fixture_text() -> Callable[[str], str]:
    return lambda name: (FIXTURES / name).read_text(encoding="utf-8")


@pytest.fixture
def mock_client() -> Callable[..., HttpClient]:
    """Build an HttpClient over a request handler: no waiting, no retries by default."""

    def build(handler: Handler, *, retries: int = 0) -> HttpClient:
        return HttpClient(
            transport=httpx.MockTransport(handler),
            sleep=FakeSleep(),
            min_interval=0.0,
            retries=retries,
        )

    return build


@pytest.fixture
def demo_client() -> HttpClient:
    """An HttpClient that replays the demo fixtures in examples/fixtures."""
    return HttpClient(
        transport=FixtureTransport(examples_dir() / "fixtures"),
        sleep=FakeSleep(),
        min_interval=0.0,
        retries=0,
    )


def json_reply(data: Any, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=data)


@pytest.fixture
def reply() -> Callable[..., httpx.Response]:
    return json_reply
