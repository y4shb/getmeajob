from __future__ import annotations

from collections.abc import Callable

import httpx

from getmeajob.files import now_iso
from getmeajob.http import HttpClient
from getmeajob.models import AppStatus, Job
from getmeajob.sources.liveness import check_live
from getmeajob.store import JobStore, StatusLog
from getmeajob.workspace import Workspace


def _feed_job(job_id: str) -> Job:
    return Job(
        key=f"remotive:remotive:{job_id}",
        ats="remotive",
        board="remotive",
        job_id=job_id,
        company="Sample Remote Co",
        title="Engineer",
        url=f"https://remotive.com/remote-jobs/software-dev/engineer-{job_id}",
    )


def _page(status: int, body: str = "") -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(status, text=body, headers={"content-type": "text/html"})

    return handler


def _store(ws: Workspace, *jobs: Job) -> None:
    JobStore(ws).upsert(jobs, now_iso())


def test_403_is_unknown_not_closed(
    tmp_ws: Workspace, mock_client: Callable[..., HttpClient]
) -> None:
    _store(tmp_ws, _feed_job("1"))
    with mock_client(_page(403, "Forbidden")) as client:
        (result,) = check_live(tmp_ws, client, None)
    assert result.state == "unknown" and "403" in result.why
    assert JobStore(tmp_ws).get("remotive:remotive:1").status == "open"  # type: ignore[union-attr]
    assert StatusLog(tmp_ws).current("remotive:remotive:1") is None


def test_404_closed(tmp_ws: Workspace, mock_client: Callable[..., HttpClient]) -> None:
    _store(tmp_ws, _feed_job("2"))
    with mock_client(_page(404)) as client:
        (result,) = check_live(tmp_ws, client, ["remotive:remotive:2"])
    assert result.state == "closed" and "404" in result.why
    assert JobStore(tmp_ws).get("remotive:remotive:2").status == "closed"  # type: ignore[union-attr]
    (event,) = StatusLog(tmp_ws).history("remotive:remotive:2")
    assert event.status == AppStatus.closed and event.source == "liveness"


def test_closed_text_marker(tmp_ws: Workspace, mock_client: Callable[..., HttpClient]) -> None:
    _store(tmp_ws, _feed_job("3"))
    closed = "<html><body><h1>Engineer</h1><p>This position has been filled.</p></body></html>"
    with mock_client(_page(200, closed)) as client:
        (result,) = check_live(tmp_ws, client, None)
    assert result.state == "closed" and "position has been filled" in result.why


def test_closed_words_next_to_an_apply_button_stay_open(
    tmp_ws: Workspace, mock_client: Callable[..., HttpClient]
) -> None:
    _store(tmp_ws, _feed_job("4"))
    page = "<p>Our last role is no longer available, but this one is.</p><button>Apply now</button>"
    with mock_client(_page(200, page)) as client:
        (result,) = check_live(tmp_ws, client, None)
    assert result.state == "open"


def test_network_error_is_unknown(
    tmp_ws: Workspace, mock_client: Callable[..., HttpClient]
) -> None:
    _store(tmp_ws, _feed_job("5"))

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route", request=request)

    with mock_client(handler) as client:
        (result,) = check_live(tmp_ws, client, None)
    assert result.state == "unknown"


def test_board_check_comes_first(tmp_ws: Workspace, mock_client: Callable[..., HttpClient]) -> None:
    def gh(job_id: str) -> Job:
        return Job(
            key=f"greenhouse:examplecorp:{job_id}",
            ats="greenhouse",
            board="examplecorp",
            job_id=job_id,
            company="Example Corp",
            title="Engineer",
            url=f"https://job-boards.greenhouse.io/examplecorp/jobs/{job_id}",
        )

    _store(tmp_ws, gh("1"), gh("2"))
    pages: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "boards-api.greenhouse.io":
            if request.url.path.endswith("/jobs"):
                return httpx.Response(200, json={"jobs": [{"id": 1, "title": "Engineer"}]})
            return httpx.Response(200, json={"name": "Example Corp"})
        pages.append(str(request.url))
        return httpx.Response(500)

    with mock_client(handler) as client:
        results = check_live(tmp_ws, client, None)
    assert [(r.key[-1], r.state) for r in results] == [("1", "open"), ("2", "closed")]
    assert pages == []  # the board answered, so no job page was fetched
