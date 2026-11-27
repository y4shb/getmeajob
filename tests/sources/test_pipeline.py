from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx

from getmeajob.http import HttpClient
from getmeajob.models import AppStatus, Board
from getmeajob.sources.boards import load_boards
from getmeajob.sources.pipeline import run_source
from getmeajob.store import JobStore, StatusLog
from getmeajob.workspace import Workspace

BOARD = Board(company="Example Corp", ats="greenhouse", slug="examplecorp")


def _board_handler(state: dict[str, Any]) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        if state.get("fail"):
            return httpx.Response(503)
        if request.url.path.endswith("/jobs"):
            title = "Engineer {}" + state.get("suffix", "")
            jobs = [
                {"id": i, "title": title.format(i), "location": {"name": "Remote"}}
                for i in state["ids"]
            ]
            return httpx.Response(200, json={"jobs": jobs})
        return httpx.Response(200, json={"name": "Example Corp"})

    return handler


def test_second_run_is_empty_diff(demo_ws: Workspace, demo_client: HttpClient) -> None:
    boards = load_boards(demo_ws)
    first = run_source(demo_ws, demo_client, boards)
    assert (first.new, first.changed, first.closed, first.unchanged) == (8, 0, 0, 0)
    assert not first.errors and len(first.per_board) == 4
    assert all(row["status"] == "ok" for row in first.per_board)
    events = StatusLog(demo_ws)
    assert events.current("greenhouse:examplecorp:1001") == AppStatus.discovered
    assert demo_ws.jd_path("greenhouse:examplecorp:1001").read_text().startswith("About Example")

    second = run_source(demo_ws, demo_client, boards)
    assert second.empty_diff and second.unchanged == 8
    assert second.new_keys == second.changed_keys == second.closed_keys == []
    assert len(JobStore(demo_ws).all()) == 8  # no duplicates
    assert len(events.history("greenhouse:examplecorp:1001")) == 1
    runs = sorted(demo_ws.runs_dir.glob("*.json"))
    assert len(runs) == 2
    record = json.loads(runs[-1].read_text())
    assert record["unchanged"] == 8 and record["started"] and record["feeds"] == []


def test_vanished_job_marked_closed_and_event_written(
    tmp_ws: Workspace, mock_client: Callable[..., HttpClient]
) -> None:
    state: dict[str, Any] = {"ids": [1, 2, 3]}
    with mock_client(_board_handler(state)) as client:
        run_source(tmp_ws, client, [BOARD])
        state["ids"] = [1, 3]
        summary = run_source(tmp_ws, client, [BOARD])
    assert summary.closed_keys == ["greenhouse:examplecorp:2"] and summary.new == 0
    job = JobStore(tmp_ws).get("greenhouse:examplecorp:2")
    assert job is not None and job.status == "closed"
    history = StatusLog(tmp_ws).history("greenhouse:examplecorp:2")
    assert [e.status for e in history] == [AppStatus.discovered, AppStatus.closed]
    assert history[-1].source == "source"


def test_source_reopens_only_jobs_it_closed(
    tmp_ws: Workspace, mock_client: Callable[..., HttpClient]
) -> None:
    mine, gone = "greenhouse:examplecorp:1", "greenhouse:examplecorp:2"
    state: dict[str, Any] = {"ids": [1, 2]}
    with mock_client(_board_handler(state)) as client:
        run_source(tmp_ws, client, [BOARD])
        StatusLog(tmp_ws).record(mine, AppStatus.closed, "manual")
        state["suffix"] = " (edited)"
        assert mine in run_source(tmp_ws, client, [BOARD]).changed_keys
        state["ids"] = []
        run_source(tmp_ws, client, [BOARD])  # both vanish, so both postings close
        state["ids"] = [1, 2]
        back = run_source(tmp_ws, client, [BOARD])
    assert sorted(back.changed_keys) == [mine, gone]
    log = StatusLog(tmp_ws)
    assert log.current(mine) == AppStatus.closed and log.history(mine)[-1].source == "manual"
    assert log.current(gone) == AppStatus.discovered
    assert log.history(gone)[-1].note == "back on the board"


def test_failed_board_never_closes_jobs(
    tmp_ws: Workspace, mock_client: Callable[..., HttpClient]
) -> None:
    state: dict[str, Any] = {"ids": [1, 2]}
    with mock_client(_board_handler(state)) as client:
        run_source(tmp_ws, client, [BOARD])
        state["fail"] = True
        summary = run_source(tmp_ws, client, [BOARD])
    assert summary.closed == 0 and summary.errors
    assert summary.per_board[0]["status"] == "error"
    assert all(job.status == "open" for job in JobStore(tmp_ws).all())


def test_changed_job_is_reported(tmp_ws: Workspace, mock_client: Callable[..., HttpClient]) -> None:
    state: dict[str, Any] = {"ids": [1]}
    with mock_client(_board_handler(state)) as client:
        run_source(tmp_ws, client, [BOARD])

    def renamed(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/jobs"):
            return httpx.Response(200, json={"jobs": [{"id": 1, "title": "Lead Engineer"}]})
        return httpx.Response(200, json={"name": "Example Corp"})

    with mock_client(renamed) as client:
        summary = run_source(tmp_ws, client, [BOARD])
    assert summary.changed_keys == ["greenhouse:examplecorp:1"]


def test_bot_wall_skips_rest_of_that_ats(
    tmp_ws: Workspace, mock_client: Callable[..., HttpClient]
) -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(403, headers={"cf-mitigated": "challenge"}, text="")

    other = Board(company="Second Co", ats="greenhouse", slug="secondco")
    with mock_client(handler) as client:
        summary = run_source(tmp_ws, client, [BOARD, other])
    assert len(calls) == 1
    assert "bot check" in summary.errors[0] and "skipped" in summary.errors[1]


def test_feed_jobs_are_stored_harvested_and_never_closed(
    tmp_ws: Workspace,
    mock_client: Callable[..., HttpClient],
    fixture_json: Callable[[str], Any],
) -> None:
    payload = fixture_json("remoteok.json")
    hosts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        hosts.append(request.url.host)
        return httpx.Response(200, json=payload)

    with mock_client(handler) as client:
        first = run_source(tmp_ws, client, [], feeds=["remoteok"])
        payload[:] = payload[:1]  # the feed drops the job
        second = run_source(tmp_ws, client, [], feeds=["remoteok"])
    assert hosts == ["remoteok.com", "remoteok.com"]  # one request per run
    assert first.new_keys == ["remoteok:remoteok:5001"]
    assert sorted(first.harvested) == ["ashby:sampleremote", "lever:sampleremote"]
    assert len(first.skipped) == 2
    assert second.closed == 0 and JobStore(tmp_ws).get("remoteok:remoteok:5001") is not None


def test_feeds_are_off_unless_named(
    tmp_ws: Workspace, mock_client: Callable[..., HttpClient]
) -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(500)

    with mock_client(handler) as client:
        summary = run_source(tmp_ws, client, [])
    assert calls == [] and summary.empty_diff and summary.per_board == []
