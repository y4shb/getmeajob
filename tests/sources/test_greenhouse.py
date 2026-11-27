from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
import pytest

from getmeajob.errors import BotWallError
from getmeajob.http import HttpClient
from getmeajob.models import Board
from getmeajob.sources.greenhouse import GreenhouseSource

BOARD = Board(company="Example Corp", ats="greenhouse", slug="examplecorp")
MESSY = Board(company="Messy Co", ats="greenhouse", slug="messyco")


def test_parses_fixture_jobs(demo_client: HttpClient) -> None:
    result = GreenhouseSource().list_jobs(BOARD, demo_client)
    assert result.found and result.error is None and result.board_name == "Example Corp"
    by_key = {job.key: job for job in result.jobs}
    assert sorted(by_key) == [f"greenhouse:examplecorp:{n}" for n in (1001, 1002, 1003, 1004)]
    top = by_key["greenhouse:examplecorp:1001"]
    assert top.title == "Senior Backend Engineer"
    assert top.location == "Remote - Worldwide" and top.remote is True
    assert top.url == "https://job-boards.greenhouse.io/examplecorp/jobs/1001"
    assert top.posted == "2026-11-03" and top.department == "Engineering"
    assert "3-5 years of professional experience" in top.description
    assert "<" not in top.description and "&lt;" not in top.description
    assert "&nbsp;" not in top.description and "shops and the people" in top.description
    payments = by_key["greenhouse:examplecorp:1003"]
    assert payments.location == "Remote - US"
    assert "unable to sponsor visas" in payments.description


def test_timeout_falls_back_to_list_without_content(
    mock_client: Callable[..., HttpClient], reply: Callable[..., httpx.Response]
) -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if request.url.path.endswith("/jobs"):
            if request.url.params.get("content") == "true":
                raise httpx.ReadTimeout("too slow", request=request)
            return reply({"jobs": [{"id": 1001, "title": "Senior Backend Engineer"}]})
        return reply({"name": "Example Corp"})

    with mock_client(handler) as client:
        result = GreenhouseSource().list_jobs(BOARD, client)
    assert result.found and [j.job_id for j in result.jobs] == ["1001"]
    assert result.jobs[0].description == ""
    assert result.notes and "listed jobs only" in result.notes[0]
    assert seen[0].endswith("/v1/boards/examplecorp/jobs?content=true")
    assert seen[1].endswith("/v1/boards/examplecorp/jobs")


def test_broken_json_with_content_also_falls_back(
    mock_client: Callable[..., HttpClient], reply: Callable[..., httpx.Response]
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("content") == "true":
            return httpx.Response(200, text='{"jobs": [{"content": "\\uZZZZ"}]}')
        if request.url.path.endswith("/jobs"):
            return reply({"jobs": [{"id": 7, "title": "Engineer"}]})
        return reply({"name": "Example Corp"})

    with mock_client(handler) as client:
        result = GreenhouseSource().list_jobs(BOARD, client)
    assert [j.key for j in result.jobs] == ["greenhouse:examplecorp:7"] and result.notes


def test_skips_null_ids(
    mock_client: Callable[..., HttpClient],
    reply: Callable[..., httpx.Response],
    fixture_json: Callable[[str], Any],
) -> None:
    payload = fixture_json("greenhouse_messy.json")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/jobs"):
            return reply(payload)
        return httpx.Response(404, json={"status": 404})

    with mock_client(handler) as client:
        result = GreenhouseSource().list_jobs(MESSY, client)
    keys = [j.key for j in result.jobs]
    assert keys == ["greenhouse:messyco:2001", "greenhouse:messyco:2002", "greenhouse:messyco:2004"]
    assert result.board_name is None
    reasons = "\n".join(result.skipped)
    for raw in ("None", "'None'", "'null'", "''"):
        assert f"no usable job id ({raw})" in reasons
    assert (
        "not a job record" in reasons and "no title" in reasons and "duplicate id 2001" in reasons
    )
    first, second, third = result.jobs
    assert first.title == "Site Reliability Engineer"
    assert first.location == "Remote - Canada | Springfield, Ontario"
    assert first.description == "Keep things up & running.\n\n- 3+ years on call"
    assert second.job_id == "2002" and second.location == "Toronto, Ontario | Remote"
    assert second.description == ""
    assert third.location == "Springfield"


def test_missing_board_is_not_found(mock_client: Callable[..., HttpClient]) -> None:
    with mock_client(lambda r: httpx.Response(404, json={})) as client:
        result = GreenhouseSource().list_jobs(BOARD, client)
    assert not result.found and result.error is None and result.jobs == []


def test_bot_wall_is_not_swallowed(mock_client: Callable[..., HttpClient]) -> None:
    wall = httpx.Response(403, headers={"cf-mitigated": "challenge"}, text="Just a moment...")
    with mock_client(lambda r: wall) as client, pytest.raises(BotWallError):
        GreenhouseSource().list_jobs(BOARD, client)


@pytest.mark.parametrize(
    ("url", "slug"),
    [
        ("https://boards.greenhouse.io/examplecorp", "examplecorp"),
        ("https://job-boards.eu.greenhouse.io/examplecorp/jobs/1001", "examplecorp"),
        ("https://boards.greenhouse.io/embed/job_board?for=examplecorp", "examplecorp"),
        ("job-boards.greenhouse.io/embed/job_app?for=examplecorp&token=1", "examplecorp"),
        ("https://boards-api.greenhouse.io/v1/boards/examplecorp/jobs", "examplecorp"),
        ("https://boards.greenhouse.io/embed/job_board/js", None),
        ("https://www.example.com/careers?gh_jid=1001", None),
    ],
)
def test_parse_url(url: str, slug: str | None) -> None:
    assert GreenhouseSource().parse_url(url) == slug
