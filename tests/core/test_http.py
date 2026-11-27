from __future__ import annotations

import json
import socket
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from getmeajob.errors import BotWallError, HttpError, OfflineMiss, RobotsDisallowed
from getmeajob.http import USER_AGENT, FixtureTransport, HttpClient, client_for
from getmeajob.httputil import private_host
from getmeajob.settings import Settings
from getmeajob.workspace import Workspace

Handler = Callable[[httpx.Request], httpx.Response]


class FakeSleep:
    def __init__(self) -> None:
        self.calls: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


def _client(handler: Handler, sleep: FakeSleep, **kwargs: object) -> HttpClient:
    return HttpClient(
        transport=httpx.MockTransport(handler),
        sleep=sleep,
        min_interval=kwargs.pop("min_interval", 0.0),  # type: ignore[arg-type]
        **kwargs,  # type: ignore[arg-type]
    )


def test_retries_then_succeeds_on_503() -> None:
    sleep = FakeSleep()
    answers = iter([503, 502, 200])
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers["user-agent"])
        return httpx.Response(next(answers), text='{"ok": true}')

    with _client(handler, sleep) as client:
        resp = client.get("https://api.example.com/jobs")
    assert resp.status == 200 and resp.json() == {"ok": True}
    assert len(seen) == 3 and seen[0] == USER_AGENT
    assert len(sleep.calls) == 2
    assert 1.0 <= sleep.calls[0] <= 1.5 and 2.0 <= sleep.calls[1] <= 2.5  # backoff with jitter


def test_retries_run_out_raises_http_error() -> None:
    sleep = FakeSleep()
    with (
        _client(lambda r: httpx.Response(500), sleep, retries=2) as client,
        pytest.raises(HttpError) as info,
    ):
        client.get("https://api.example.com/jobs")
    assert info.value.status == 500 and info.value.hint
    assert len(sleep.calls) == 2


def test_timeouts_are_retried() -> None:
    sleep = FakeSleep()
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            raise httpx.ReadTimeout("slow", request=request)
        return httpx.Response(200, text="ok")

    with _client(handler, sleep) as client:
        assert client.get("https://api.example.com/x").text == "ok"
    assert len(calls) == 2


def test_no_retry_on_404() -> None:
    sleep = FakeSleep()
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(404, text="gone")

    with _client(handler, sleep) as client:
        resp = client.get("https://api.example.com/missing")
    assert resp.status == 404 and len(calls) == 1 and sleep.calls == []


def test_honours_retry_after() -> None:
    sleep = FakeSleep()
    answers = iter([httpx.Response(429, headers={"Retry-After": "7"}), httpx.Response(200)])
    with _client(lambda r: next(answers), sleep) as client:
        assert client.get("https://api.example.com/x").status == 200
    assert sleep.calls == [7.0]


def test_long_retry_after_gives_up_politely() -> None:
    sleep = FakeSleep()
    reply = httpx.Response(429, headers={"Retry-After": "3600"})
    with _client(lambda r: reply, sleep) as client, pytest.raises(HttpError) as info:
        client.get("https://api.example.com/x")
    assert "3600" in info.value.message and sleep.calls == []


def test_bot_wall_raises_without_retry() -> None:
    sleep = FakeSleep()
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(503, text="<title>Just a moment...</title>")

    with _client(handler, sleep) as client, pytest.raises(BotWallError):
        client.get("https://careers.example.com/jobs")
    assert len(calls) == 1 and sleep.calls == []

    header_wall = httpx.Response(403, headers={"cf-mitigated": "challenge"})
    with _client(lambda r: header_wall, sleep) as client, pytest.raises(BotWallError):
        client.get("https://careers.example.com/jobs")
    plain_403 = httpx.Response(403, text="forbidden")
    with _client(lambda r: plain_403, sleep) as client:
        assert client.get("https://careers.example.com/jobs").status == 403


def test_cache_hit_within_ttl(tmp_path: Path) -> None:
    sleep = FakeSleep()
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, text='{"n": 1}', headers={"content-type": "application/json"})

    with _client(handler, sleep, cache_dir=tmp_path) as client:
        first = client.get("https://api.example.com/jobs", params={"b": 2, "a": 1}, ttl=3600)
        second = client.get("https://api.example.com/jobs", params={"a": 1, "b": 2}, ttl=3600)
        third = client.get("https://api.example.com/jobs", params={"a": 1, "b": 2})  # no ttl
    assert not first.from_cache and second.from_cache and not third.from_cache
    assert second.json() == {"n": 1} and second.headers["content-type"] == "application/json"
    assert len(calls) == 2


def test_post_json_cache_key_includes_body(tmp_path: Path) -> None:
    sleep = FakeSleep()
    bodies: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        assert request.headers["content-type"] == "application/json"
        return httpx.Response(200, text="{}")

    with _client(handler, sleep, cache_dir=tmp_path) as client:
        client.post_json("https://api.example.com/graphql", {"q": 1}, ttl=60)
        client.post_json("https://api.example.com/graphql", {"q": 1}, ttl=60)
        client.post_json("https://api.example.com/graphql", {"q": 2}, ttl=60)
    assert bodies == [{"q": 1}, {"q": 2}]


def test_revalidates_with_etag_304(tmp_path: Path) -> None:
    sleep = FakeSleep()
    seen: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("if-none-match"))
        if request.headers.get("if-none-match") == '"v1"':
            return httpx.Response(304)
        return httpx.Response(200, text="body-v1", headers={"etag": '"v1"'})

    with _client(handler, sleep, cache_dir=tmp_path) as client:
        first = client.get("https://api.example.com/board", ttl=0)
        second = client.get("https://api.example.com/board", ttl=0)
    assert first.text == "body-v1" and not first.from_cache
    assert second.text == "body-v1" and second.from_cache and second.status == 200
    assert seen == [None, '"v1"']


def test_robots_disallow_raises() -> None:
    sleep = FakeSleep()
    fetched: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        fetched.append(request.url.path)
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: getmeajob\nDisallow: /private\n")
        return httpx.Response(200, text="<html>ok</html>")

    with _client(handler, sleep) as client:
        assert client.get("https://careers.example.com/jobs", check_robots=True).status == 200
        with pytest.raises(RobotsDisallowed):
            client.get("https://careers.example.com/private/page", check_robots=True)
    assert fetched.count("/robots.txt") == 1  # once per host per client
    assert "/private/page" not in fetched

    missing = HttpClient(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(404 if r.url.path == "/robots.txt" else 200)
        ),
        sleep=sleep,
        min_interval=0,
    )
    assert missing.get("https://other.example.com/x", check_robots=True).status == 200


def test_per_host_min_interval() -> None:
    sleep = FakeSleep()
    with _client(lambda r: httpx.Response(200), sleep, min_interval=1.0) as client:
        client.get("https://a.example.com/1")
        client.get("https://b.example.com/1")  # another host: no wait
        assert sleep.calls == []
        client.get("https://a.example.com/2")
        assert len(sleep.calls) == 1 and 0.9 < sleep.calls[0] <= 1.0


def test_map_keeps_order_and_returns_exceptions() -> None:
    client = HttpClient(transport=httpx.MockTransport(lambda r: httpx.Response(200)))

    def work(n: int) -> int:
        if n == 2:
            raise ValueError("two")
        return n * 10

    results = client.map(work, [1, 2, 3])
    assert results[0] == 10 and isinstance(results[1], ValueError) and results[2] == 30
    client.close()


def test_fixture_transport_routes_then_path_then_miss(tmp_path: Path) -> None:
    (tmp_path / "files").mkdir()
    (tmp_path / "files" / "graphql.json").write_text('{"route": true}', encoding="utf-8")
    routes = [
        {
            "method": "POST",
            "url_contains": "jobs.example.com/api",
            "body_contains": "ApiJobPosting",
            "file": "files/graphql.json",
        }
    ]
    (tmp_path / "routes.json").write_text(json.dumps(routes), encoding="utf-8")
    board = tmp_path / "http" / "boards-api.example.com" / "v1" / "boards" / "examplecorp"
    board.mkdir(parents=True)
    (board / "jobs.json").write_text('{"jobs": []}', encoding="utf-8")
    (tmp_path / "http" / "boards-api.example.com" / "index.json").write_text("{}", "utf-8")

    client = HttpClient(transport=FixtureTransport(tmp_path), min_interval=0, retries=0)
    routed = client.post_json("https://jobs.example.com/api/x", {"operationName": "ApiJobPosting"})
    assert routed.json() == {"route": True}
    by_path = client.get(
        "https://boards-api.example.com/v1/boards/examplecorp/jobs", params={"content": "true"}
    )
    assert by_path.json() == {"jobs": []}
    assert client.get("https://boards-api.example.com/").json() == {}
    assert client.get("https://boards-api.example.com/robots.txt").status == 404
    with pytest.raises(OfflineMiss) as info:
        client.get("https://boards-api.example.com/v1/boards/nobody/jobs")
    assert "routes.json" in info.value.message and "nobody" in info.value.message
    with pytest.raises(OfflineMiss):
        client.post_json("https://jobs.example.com/api/x", {"operationName": "Other"})
    with pytest.raises(OfflineMiss):
        client.get("https://boards-api.example.com/../../etc/passwd")


def test_client_for_uses_fixtures(tmp_ws: Workspace, tmp_path: Path) -> None:
    fixtures = tmp_path / "fx"
    (fixtures / "http" / "api.example.com").mkdir(parents=True)
    (fixtures / "http" / "api.example.com" / "ping.json").write_text('"pong"', encoding="utf-8")
    with client_for(tmp_ws, Settings(fixtures=fixtures)) as client:
        assert client.get("https://api.example.com/ping").json() == "pong"
        with pytest.raises(OfflineMiss):
            client.get("https://api.example.com/other")


def test_refuses_private_addresses_and_redirects_to_them() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(302, headers={"location": "http://169.254.169.254/latest"})

    with _client(handler, FakeSleep()) as client:
        for url in ("http://127.0.0.1:8000/", "http://[::1]/", "http://10.0.0.8/x"):
            with pytest.raises(HttpError, match="private network"):
                client.get(url)
        with pytest.raises(HttpError, match="private network"):
            client.get("https://jobs.example.com/a")
    assert seen == ["https://jobs.example.com/a"]  # nothing private was ever requested
    assert not private_host("8.8.8.8", lookup=False)
    assert not private_host("intranet.example.com", lookup=False)


def test_a_name_that_resolves_to_a_private_address_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def lookup(*args: object, **kwargs: object) -> list[tuple[object, ...]]:
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.1.2.3", 0))]

    monkeypatch.setattr(socket, "getaddrinfo", lookup)
    assert private_host("intranet.example.com", lookup=True)
    real = HttpClient(retries=0, min_interval=0)  # the real transport, so names resolve
    with real, pytest.raises(HttpError, match="private network"):
        real.get("https://intranet.example.com/jobs")


def test_robots_is_checked_on_every_redirect() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(f"{request.url.host}{request.url.path}")
        if request.url.path == "/robots.txt":
            closed = request.url.host == "other.example.org"
            return httpx.Response(200, text="User-agent: *\nDisallow: /private\n" if closed else "")
        if request.url.host == "jobs.example.com":
            return httpx.Response(301, headers={"location": "https://other.example.org/private/1"})
        return httpx.Response(200, text="ok")

    with _client(handler, FakeSleep()) as client, pytest.raises(RobotsDisallowed):
        client.get("https://jobs.example.com/job/1", check_robots=True)
    assert "other.example.org/robots.txt" in seen
    assert "other.example.org/private/1" not in seen


def test_redirects_and_reply_size_are_capped(monkeypatch: pytest.MonkeyPatch) -> None:
    hops: list[str] = []

    def loop(request: httpx.Request) -> httpx.Response:
        hops.append(request.url.path)
        return httpx.Response(302, headers={"location": f"/r{len(hops)}"})

    with _client(loop, FakeSleep()) as client, pytest.raises(HttpError, match="redirects"):
        client.get("https://jobs.example.com/r0")
    assert len(hops) == 6  # the first request and 5 redirects

    monkeypatch.setattr("getmeajob.http.MAX_BODY_BYTES", 1000)
    big = _client(lambda r: httpx.Response(200, content=b"x" * 1001), FakeSleep())
    with big, pytest.raises(HttpError, match="stopped reading"):
        big.get("https://jobs.example.com/big")
    small = _client(lambda r: httpx.Response(200, content=b"x" * 1000), FakeSleep())
    with small:
        assert small.get("https://jobs.example.com/ok").text == "x" * 1000
