from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx

from getmeajob.http import HttpClient
from getmeajob.models import Job
from getmeajob.sources.feeds import FEED_ATTRIBUTION, harvest_boards, hn, remoteok, remotive


def test_remoteok_skips_notice(
    mock_client: Callable[..., HttpClient],
    reply: Callable[..., httpx.Response],
    fixture_json: Callable[[str], Any],
) -> None:
    payload = fixture_json("remoteok.json")
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return reply(payload)

    skipped: list[str] = []
    with mock_client(handler) as client:
        jobs = remoteok(client, skipped)
    assert calls == ["https://remoteok.com/api"]  # one request per run
    (job,) = jobs
    assert job.key == "remoteok:remoteok:5001" and job.company == "Sample Remote Co"
    assert job.title == "Python Engineer" and job.location == "Remote - Worldwide"
    assert job.url.startswith("https://remoteok.com/remote-jobs/")  # link back to the feed
    assert job.source == f"feed:remoteok ({FEED_ATTRIBUTION['remoteok']})"
    assert job.comp == "USD 90,000-120,000 a year" and job.posted == "2026-11-12"
    assert not any("legal" in reason for reason in skipped)
    assert len(skipped) == 2  # the null id and the empty title, not the notice


def test_remotive_parses_and_keeps_attribution(
    mock_client: Callable[..., HttpClient],
    reply: Callable[..., httpx.Response],
    fixture_json: Callable[[str], Any],
) -> None:
    payload = fixture_json("remotive.json")
    with mock_client(lambda r: reply(payload)) as client:
        (job,) = remotive(client)
    assert job.key == "remotive:remotive:7001" and job.location == "Remote - Canada"
    assert job.source == "feed:remotive (https://remotive.com)"
    assert job.url.startswith("https://remotive.com/remote-jobs/")
    assert "We use Python." in job.description


def test_hn_parses_pipe_convention(
    mock_client: Callable[..., HttpClient],
    reply: Callable[..., httpx.Response],
    fixture_json: Callable[[str], Any],
) -> None:
    search, item = fixture_json("hn_search.json"), fixture_json("hn_item.json")
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        return reply(search if "search" in request.url.path else item)

    skipped: list[str] = []
    with mock_client(handler) as client:
        jobs = hn(client, skipped)
    assert paths == ["/api/v1/search_by_date", "/api/v1/items/9000"]  # the hiring thread
    first, second = jobs
    assert first.key == "hn:hn:9001" and first.company == "Sample Widgets Co"
    assert first.title == "Senior Backend Engineer" and first.location == "Remote (Canada, US)"
    assert first.remote is True and first.url == "https://news.ycombinator.com/item?id=9001"
    assert first.apply_url == "https://jobs.lever.co/samplewidgets/0000-1111"
    assert "https://jobs.lever.co/samplewidgets/0000-1111" in first.description
    assert second.company == "Example Labs" and second.title == "Data Engineer, Platform Developer"
    assert second.location == "Toronto, ON" and second.remote is None
    assert second.apply_url == "https://boards.greenhouse.io/examplelabs"
    reasons = "\n".join(skipped)
    assert "not 'Company | Role | Place'" in reasons and "deleted or empty" in reasons
    assert all(job.source == "feed:hn (https://news.ycombinator.com)" for job in jobs)


def _job(**fields: Any) -> Job:
    base: dict[str, Any] = {
        "key": "hn:hn:1",
        "ats": "hn",
        "board": "hn",
        "job_id": "1",
        "company": "Sample Co",
        "title": "Engineer",
        "url": "https://news.ycombinator.com/item?id=1",
    }
    base.update(fields)
    return Job(**base)


def test_harvest_boards_from_links() -> None:
    jobs = [
        _job(
            apply_url="https://jobs.ashbyhq.com/sampleco/123",
            description=(
                "Links:\n- https://jobs.eu.lever.co/sampleco-eu/abc.\n"
                "- https://boards.greenhouse.io/embed/job_board?for=samplegh\n"
                "- https://www.example.com/careers\n"
                "- https://apply.workable.com/j/AB12CD34EF"
            ),
        ),
        _job(
            key="hn:hn:2", job_id="2", company="Other Co", url="https://jobs.ashbyhq.com/SampleCo"
        ),
    ]
    boards = harvest_boards(jobs)
    found = {(b.ats, b.slug): b for b in boards}
    assert set(found) == {
        ("ashby", "sampleco"),
        ("lever", "sampleco-eu"),
        ("greenhouse", "samplegh"),
    }
    assert found[("lever", "sampleco-eu")].region == "eu"
    assert all(not b.verified and b.notes == "seen in the hn feed" for b in boards)
    assert found[("ashby", "sampleco")].company == "Sample Co"  # first sighting wins
