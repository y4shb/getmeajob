from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx

from getmeajob.http import HttpClient
from getmeajob.models import Board
from getmeajob.sources.workable import WorkableSource


def test_parses_widget_jobs(
    mock_client: Callable[..., HttpClient],
    reply: Callable[..., httpx.Response],
    fixture_json: Callable[[str], Any],
) -> None:
    payload = fixture_json("workable.json")
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        return reply(payload)

    board = Board(company="Sample Workshop", ats="workable", slug="sampleworkshop")
    with mock_client(handler) as client:
        result = WorkableSource().list_jobs(board, client)
    assert paths == ["/api/v1/widget/accounts/sampleworkshop"]
    assert result.board_name == "Sample Workshop"
    remote, office = result.jobs
    assert remote.key == "workable:sampleworkshop:AB12CD34EF"
    assert remote.location == "Remote - Canada" and remote.remote is True
    assert remote.description == "Write Python." and remote.posted == "2026-11-09"
    assert remote.apply_url == "https://apply.workable.com/j/AB12CD34EF/apply"
    assert office.job_id == "ZZ99YY88XX"  # taken from the URL when the shortcode is missing
    assert office.location == "Springfield, Ontario, Canada" and office.remote is None
    assert len(result.skipped) == 1 and "'None'" in result.skipped[0]
    assert WorkableSource().parse_url("https://apply.workable.com/sampleworkshop/") == (
        "sampleworkshop"
    )
    assert WorkableSource().parse_url("https://sampleworkshop.workable.com") == "sampleworkshop"
