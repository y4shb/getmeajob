from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx

from getmeajob.http import HttpClient
from getmeajob.models import Board
from getmeajob.sources.recruitee import RecruiteeSource


def test_parses_published_offers(
    mock_client: Callable[..., HttpClient],
    reply: Callable[..., httpx.Response],
    fixture_json: Callable[[str], Any],
) -> None:
    payload = fixture_json("recruitee.json")
    urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        urls.append(str(request.url))
        return reply(payload)

    board = Board(company="Sample Shop", ats="recruitee", slug="sampleshop")
    with mock_client(handler) as client:
        result = RecruiteeSource().list_jobs(board, client)
    assert urls == ["https://sampleshop.recruitee.com/api/offers/"]
    assert result.board_name == "Sample Shop"
    hybrid, remote = result.jobs
    assert hybrid.key == "recruitee:sampleshop:4101"
    assert (
        hybrid.location == "Springfield, Ontario, Canada (Hybrid)" and hybrid.workplace == "hybrid"
    )
    assert hybrid.description == "Build the shop backend.\n\n- 3+ years with Python"
    assert hybrid.posted == "2026-11-11"
    assert remote.location == "Remote - Canada" and remote.remote is True
    assert remote.url == "https://sampleshop.recruitee.com/o/4103"
    assert "1 unpublished left out" in result.skipped[0]
    assert RecruiteeSource().parse_url("https://sampleshop.recruitee.com/o/backend") == "sampleshop"
    assert RecruiteeSource().parse_url("https://www.recruitee.com") is None
