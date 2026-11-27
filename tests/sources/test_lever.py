from __future__ import annotations

from collections.abc import Callable

import httpx

from getmeajob.http import HttpClient
from getmeajob.models import Board
from getmeajob.sources.lever import LeverSource, lever_region

POSTING = {
    "id": "eu000000-0000-4000-8000-000000000001",
    "text": "Backend Engineer",
    "categories": {"location": "Lisbon, Portugal", "team": "Core"},
    "workplaceType": "remote",
    "createdAt": 1794495600000,
    "hostedUrl": "https://jobs.eu.lever.co/eurowidgets/eu000000-0000-4000-8000-000000000001",
    "descriptionPlain": "Build things.",
    "lists": [{"text": "You have", "content": "<li>4+ years of Python</li>"}],
    "additionalPlain": "We are remote first.",
}


def _handler(hosts: list[str]) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        hosts.append(request.url.host)
        assert request.url.params.get("mode") == "json"
        if request.url.host == "api.lever.co":
            return httpx.Response(404, json={"ok": False, "error": "Document not found"})
        return httpx.Response(200, json=[POSTING])

    return handler


def test_eu_fallback(mock_client: Callable[..., HttpClient]) -> None:
    hosts: list[str] = []
    board = Board(company="Euro Widgets", ats="lever", slug="eurowidgets")
    with mock_client(_handler(hosts)) as client:
        result = LeverSource().list_jobs(board, client)
    assert hosts == ["api.lever.co", "api.eu.lever.co"]
    assert result.found and len(result.jobs) == 1
    job = result.jobs[0]
    assert job.key == "lever:eurowidgets:eu000000-0000-4000-8000-000000000001"
    assert job.location == "Remote - Lisbon, Portugal" and job.workplace == "remote"
    assert (
        job.description == "Build things.\n\nYou have\n- 4+ years of Python\n\nWe are remote first."
    )
    assert job.posted == "2026-11-12"
    assert result.notes and "region: eu" in result.notes[0]


def test_region_eu_goes_straight_to_eu_host(mock_client: Callable[..., HttpClient]) -> None:
    hosts: list[str] = []
    board = Board(company="Euro Widgets", ats="lever", slug="eurowidgets", region="eu")
    with mock_client(_handler(hosts)) as client:
        result = LeverSource().list_jobs(board, client)
    assert hosts == ["api.eu.lever.co"] and result.found and not result.notes


def test_missing_on_both_hosts_is_not_found(mock_client: Callable[..., HttpClient]) -> None:
    board = Board(company="Nobody", ats="lever", slug="nobody")
    with mock_client(lambda r: httpx.Response(404, json={"ok": False})) as client:
        result = LeverSource().list_jobs(board, client)
    assert not result.found and result.error is None


def test_demo_board(demo_client: HttpClient) -> None:
    board = Board(company="Demo Widgets", ats="lever", slug="demowidgets")
    result = LeverSource().list_jobs(board, demo_client)
    (job,) = result.jobs
    assert job.title == "Software Engineer II" and job.location == "Toronto, Ontario, Canada"
    assert job.comp == "CAD 95,000-120,000 a year"
    assert "Production experience with Go and gRPC" in job.description


def test_parse_url_and_region() -> None:
    source = LeverSource()
    assert source.parse_url("https://jobs.lever.co/demowidgets/7c0de000") == "demowidgets"
    assert source.parse_url("https://jobs.eu.lever.co/eurowidgets") == "eurowidgets"
    assert source.parse_url("https://api.lever.co/v0/postings/demowidgets?mode=json") == (
        "demowidgets"
    )
    assert lever_region("https://jobs.eu.lever.co/eurowidgets") == "eu"
    assert lever_region("https://jobs.lever.co/demowidgets") is None
