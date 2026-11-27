from __future__ import annotations

from collections.abc import Callable

import httpx

from getmeajob.http import HttpClient
from getmeajob.sources.discover import discover, name_matches, parse_line, slug_candidates


def test_url_inputs_parse_directly(mock_client: Callable[..., HttpClient]) -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(500)

    lines = [
        "# comment lines and blank lines are skipped",
        "",
        "https://job-boards.greenhouse.io/examplecorp/jobs/1001",
        "Sample Systems, https://jobs.ashbyhq.com/samplesystems",
        "Euro Widgets | jobs.eu.lever.co/eurowidgets/abc",
        "https://jobs.smartrecruiters.com/PlaceholderLabs/744000000000001",
        "sampleshop.recruitee.com",
    ]
    with mock_client(handler) as client:
        results = discover(lines, client)
    assert calls == []  # board URLs never need the network
    assert [r.confidence for r in results] == ["url"] * 5
    boards = [r.board for r in results]
    assert all(b is not None for b in boards)
    got = [(b.ats, b.slug, b.company, b.region) for b in boards if b is not None]
    assert got == [
        ("greenhouse", "examplecorp", "examplecorp", None),
        ("ashby", "samplesystems", "Sample Systems", None),
        ("lever", "eurowidgets", "Euro Widgets", "eu"),
        ("smartrecruiters", "PlaceholderLabs", "PlaceholderLabs", None),
        ("recruitee", "sampleshop", "sampleshop", None),
    ]
    assert "company name is the slug" in results[0].note


def test_slug_candidates_rules() -> None:
    assert slug_candidates("Example Corp") == [
        "examplecorp",
        "example-corp",
        "example",
        "exampleai",
        "examplehq",
        "exampleinc",
        "examplelabs",
        "exampletech",
    ]
    assert slug_candidates("Sample Systems, Inc.")[:4] == [
        "samplesystemsinc",
        "sample-systems-inc",
        "sample",
        "sampleai",
    ]
    assert slug_candidates("Ünïcode & Friends (Canada)")[:2] == [
        "unicodeandfriends",
        "unicode-and-friends",
    ]
    assert slug_candidates("Demo Widgets")[:3] == ["demowidgets", "demo-widgets", "demowidgetsai"]
    for name in ("Example Corp", "A B", "X" * 60, "Placeholder Labs"):
        candidates = slug_candidates(name)
        assert len(candidates) <= 8 and len(set(candidates)) == len(candidates)
        assert all(3 <= len(c) <= 39 for c in candidates)
    assert slug_candidates("AI") == []


def test_name_matching() -> None:
    assert name_matches("Example Corp", "Example Corp") is True
    assert name_matches("Example Corp", "Example") is True
    assert name_matches("Sample Systems", "Sample Systms Inc") is True
    assert name_matches("Example Corp", "Totally Different Holdings") is False
    assert name_matches("Example Corp", None) is None
    assert parse_line("Example Corp") == ("Example Corp", None)


def test_name_mismatch_rejected(mock_client: Callable[..., HttpClient]) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "boards-api.greenhouse.io":
            if request.url.path == "/v1/boards/examplecorp/jobs":
                return httpx.Response(200, json={"jobs": [{"id": 1, "title": "Engineer"}]})
            if request.url.path == "/v1/boards/examplecorp":
                return httpx.Response(200, json={"name": "Totally Different Holdings"})
        return httpx.Response(404, json={})

    with mock_client(handler) as client:
        (result,) = discover(["Example Corp"], client)
    assert result.board is None and result.confidence == "none"
    assert "Totally Different Holdings" in result.note and "rejected" in result.note
    assert "greenhouse:examplecorp" in result.tried
    assert not any(t.startswith("recruitee:") for t in result.tried)
    assert len(result.tried) == 8 * 5


def test_name_match_accepted_and_unnamed_board_unverified(
    mock_client: Callable[..., HttpClient],
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/boards/examplecorp/jobs":
            return httpx.Response(200, json={"jobs": [{"id": 1, "title": "Engineer"}]})
        if request.url.path == "/v1/boards/examplecorp":
            return httpx.Response(200, json={"name": "Example Corp"})
        if request.url.host == "api.lever.co" and request.url.path.endswith("/demowidgets"):
            return httpx.Response(200, json=[{"id": "x", "text": "Engineer"}])
        return httpx.Response(404, json={})

    with mock_client(handler) as client:
        verified, unnamed = discover(["Example Corp", "Demo Widgets"], client)
    assert verified.confidence == "verified" and verified.board is not None
    assert (verified.board.ats, verified.board.slug, verified.board.verified) == (
        "greenhouse",
        "examplecorp",
        True,
    )
    assert unnamed.confidence == "unverified" and unnamed.board is not None
    assert unnamed.board.ats == "lever" and unnamed.board.verified is False


def test_careers_page_scan_respects_robots(mock_client: Callable[..., HttpClient]) -> None:
    fetched: list[str] = []
    page = (
        '<html><body><a href="/about">About</a>'
        '<a href="https://jobs.lever.co/samplewidgets">Open roles</a></body></html>'
    )

    def handler(request: httpx.Request) -> httpx.Response:
        fetched.append(str(request.url))
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /private/\n")
        if request.url.host == "www.example.com" and request.url.path == "/careers":
            return httpx.Response(200, text=page, headers={"content-type": "text/html"})
        if request.url.host == "api.lever.co":
            return httpx.Response(200, json=[{"id": "1", "text": "Engineer"}])
        return httpx.Response(404)

    lines = [
        "Sample Widgets, https://www.example.com/careers",
        "https://www.example.com/private/jobs",
    ]
    with mock_client(handler) as client:
        found, refused = discover(lines, client)
    assert found.confidence == "verified" and found.board is not None
    assert (found.board.ats, found.board.slug) == ("lever", "samplewidgets")
    assert found.board.careers_url == "https://www.example.com/careers"
    assert refused.board is None and "robots.txt" in refused.note
    assert "https://www.example.com/private/jobs" not in fetched
