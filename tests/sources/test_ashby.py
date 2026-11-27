from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx

from getmeajob.http import HttpClient
from getmeajob.models import Board
from getmeajob.sources.ashby import AshbySource

DEMO = Board(company="Sample Systems", ats="ashby", slug="samplesystems")
MESSY = Board(company="Messy Co", ats="ashby", slug="messyco")


def test_skips_unlisted_and_joins_locations(
    mock_client: Callable[..., HttpClient],
    reply: Callable[..., httpx.Response],
    fixture_json: Callable[[str], Any],
) -> None:
    payload = fixture_json("ashby_messy.json")
    asked: list[httpx.URL] = []

    def handler(request: httpx.Request) -> httpx.Response:
        asked.append(request.url)
        return reply(payload)

    with mock_client(handler) as client:
        result = AshbySource().list_jobs(MESSY, client)
    assert asked[0].params.get("includeCompensation") == "true"
    assert [j.job_id[-1] for j in result.jobs] == ["1", "3"]
    first, second = result.jobs
    assert first.location == "Toronto | Springfield | Montreal, Canada"
    assert first.workplace == "onsite" and first.remote is False
    assert first.description == "Build APIs. Use Python.\n\nShip often."
    assert first.posted == "2026-11-01"
    assert second.location == "Remote - Canada | United Kingdom"
    assert second.remote is True and second.description == "Help customers\n\n- 2+ years"
    assert second.url == "https://jobs.ashbyhq.com/messyco/aa000000-0000-4000-8000-000000000003"
    reasons = "\n".join(result.skipped)
    assert "1 unlisted job(s) left out" in reasons and "no usable job id ('null')" in reasons


def test_demo_board(demo_client: HttpClient) -> None:
    result = AshbySource().list_jobs(DEMO, demo_client)
    by_title = {j.title: j for j in result.jobs}
    platform = by_title["Platform Engineer"]
    assert platform.location == "Springfield, Ontario, Canada (Hybrid)"
    assert platform.workplace == "hybrid" and platform.comp == "CA$110K - CA$135K"
    assert platform.apply_url and platform.apply_url.endswith("/application")
    assert by_title["Data Analyst"].location == "Remote - Canada"
    assert "2+ years of experience" in platform.description


def test_probe_counts_listed_jobs(
    mock_client: Callable[..., HttpClient],
    reply: Callable[..., httpx.Response],
    fixture_json: Callable[[str], Any],
) -> None:
    payload = fixture_json("ashby_messy.json")
    with mock_client(lambda r: reply(payload)) as client:
        probe = AshbySource().probe("messyco", client)
    assert probe.found and probe.count == 3 and probe.board_name is None


def test_parse_url() -> None:
    source = AshbySource()
    assert source.parse_url("https://jobs.ashbyhq.com/samplesystems/5a1e0000") == "samplesystems"
    assert source.parse_url("https://api.ashbyhq.com/posting-api/job-board/samplesystems") == (
        "samplesystems"
    )
    assert source.parse_url("https://www.example.com/jobs") is None
