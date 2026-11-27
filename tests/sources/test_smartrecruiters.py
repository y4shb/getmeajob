from __future__ import annotations

from collections.abc import Callable

import httpx

from getmeajob.http import HttpClient
from getmeajob.models import Board
from getmeajob.sources.smartrecruiters import SmartRecruitersSource

BOARD = Board(company="Placeholder Labs", ats="smartrecruiters", slug="PlaceholderLabs")


def test_parses_list_and_detail(demo_client: HttpClient) -> None:
    result = SmartRecruitersSource().list_jobs(BOARD, demo_client)
    assert result.found and not result.partial and result.board_name == "Placeholder Labs"
    (job,) = result.jobs
    assert job.key == "smartrecruiters:PlaceholderLabs:744000000000001"
    assert job.title == "Backend Developer"
    assert job.location == "Remote - Canada" and job.remote is True
    assert job.url.endswith("/PlaceholderLabs/744000000000001-backend-developer")
    assert job.apply_url and "oga=true" in job.apply_url
    assert job.department == "Engineering" and job.posted == "2026-11-16"
    assert "A minimum of 2 years of professional experience" in job.description
    assert job.description.startswith("Company Description\n")


def test_partial_list_is_flagged(mock_client: Callable[..., HttpClient]) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/postings"):
            content = [{"id": "1", "name": "Engineer", "location": {"city": "Toronto"}}]
            return httpx.Response(200, json={"totalFound": 3, "content": content})
        return httpx.Response(500)

    with mock_client(handler) as client:
        result = SmartRecruitersSource().list_jobs(BOARD, client)
    assert result.partial and "read 1 of 3" in result.notes[0]
    assert result.jobs[0].description == ""
    assert any("failed to load" in note for note in result.notes)
