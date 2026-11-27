"""The one polite HTTP client every network call goes through.

- timeouts (connect 10 s, read 25 s), retries on 429, 5xx and timeouts with backoff
  and jitter, honouring Retry-After; never retries 404 or 410
- a minimum interval between requests to the same host, and a small thread pool
- a disk cache with a TTL and ETag / Last-Modified revalidation
- stops at once on bot checks (`BotWallError`), never tries to get past them
- optional robots.txt check for HTML pages (`RobotsDisallowed`)
- `FixtureTransport` replays recorded files for offline demos and tests
"""

from __future__ import annotations

import json
import random
import threading
import time
import urllib.robotparser
from collections.abc import Callable, Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Any, TypeVar
from urllib.parse import urlsplit

import httpx

from getmeajob import __version__
from getmeajob.errors import (
    BotWallError,
    HttpError,
    RobotsDisallowed,
)
from getmeajob.files import write_json_atomic
from getmeajob.httputil import (
    cache_key,
    host_of,
    looks_like_bot_wall,
    parse_retry_after,
    read_cache_entry,
    write_cache_entry,
)
from getmeajob.replay import FixtureTransport, NoNetworkTransport
from getmeajob.settings import Settings, load_settings
from getmeajob.workspace import Workspace

__all__ = [
    "USER_AGENT",
    "FixtureTransport",
    "HttpClient",
    "Response",
    "client_for",
]

T = TypeVar("T")
R = TypeVar("R")

USER_AGENT = f"getmeajob/{__version__} (+personal job search tool)"
MAX_BACKOFF = 60.0
_CACHE_HEADERS = ("content-type", "etag", "last-modified")


@dataclass
class Response:
    url: str
    status: int
    headers: dict[str, str]
    text: str
    from_cache: bool = False

    def json(self) -> Any:
        try:
            return json.loads(self.text)
        except json.JSONDecodeError as exc:
            raise HttpError(
                f"{host_of(self.url) or self.url} sent a reply that is not valid JSON "
                f"({exc.msg} at line {exc.lineno}).",
                url=self.url,
                status=self.status,
                hint="The site may be down or may have changed. Try again later.",
            ) from exc


class HttpClient:
    """Polite HTTP client. Returns a `Response` for final statuses below 500 (except 429);
    callers check `.status`. Raises `HttpError` when retries run out."""

    def __init__(
        self,
        *,
        cache_dir: Path | None = None,
        timeout: float = 25.0,
        connect_timeout: float = 10.0,
        retries: int = 3,
        min_interval: float = 1.0,
        user_agent: str | None = None,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        max_workers: int = 4,
    ) -> None:
        self.cache_dir = cache_dir
        self.retries = max(0, retries)
        self.min_interval = max(0.0, min_interval)
        self.user_agent = user_agent or USER_AGENT
        self.max_workers = max(1, max_workers)
        self.backoff_base = 1.0
        self.clock: Callable[[], float] = time.monotonic
        self._sleep = sleep
        self._rng = random.Random()
        self._client = httpx.Client(
            timeout=httpx.Timeout(timeout, connect=connect_timeout),
            transport=transport,
            headers={"User-Agent": self.user_agent},
            follow_redirects=True,
        )
        self._lock = threading.Lock()
        self._host_locks: dict[str, threading.Lock] = {}
        self._last_request: dict[str, float] = {}
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}

    # ------------------------------------------------------------ lifecycle

    def __enter__(self) -> HttpClient:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    # ---------------------------------------------------------------- public

    def get(
        self,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        ttl: float | None = None,
        check_robots: bool = False,
    ) -> Response:
        """GET `url`. With `ttl` (seconds) and a cache folder, a fresh cached copy is used
        and an older one is revalidated. `check_robots=True` is for HTML pages."""
        if check_robots:
            self._check_robots(url)
        return self._cached("GET", url, params=params, headers=headers, body=b"", ttl=ttl)

    def post_json(
        self,
        url: str,
        payload: Any,
        *,
        headers: Mapping[str, str] | None = None,
        ttl: float | None = None,
    ) -> Response:
        body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        merged = {"Content-Type": "application/json", **(headers or {})}
        return self._cached("POST", url, params=None, headers=merged, body=body, ttl=ttl)

    def map(self, fn: Callable[[T], R], items: Iterable[T]) -> list[R | Exception]:
        """Run `fn` over `items` in a small thread pool. Keeps order; exceptions are
        returned in place of results, not raised."""
        work = list(items)
        if not work:
            return []
        results: list[R | Exception] = []
        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            futures = [pool.submit(fn, item) for item in work]
            for future in futures:
                try:
                    results.append(future.result())
                except Exception as exc:
                    results.append(exc)
        return results

    # ----------------------------------------------------------------- cache

    def _cache_path(self, key: str) -> Path | None:
        return None if self.cache_dir is None else self.cache_dir / f"{key}.json"

    def _cached(
        self,
        method: str,
        url: str,
        *,
        params: Mapping[str, Any] | None,
        headers: Mapping[str, str] | None,
        body: bytes,
        ttl: float | None,
    ) -> Response:
        path = None if ttl is None else self._cache_path(cache_key(method, url, params, body))
        entry = read_cache_entry(path) if path is not None else None
        send_headers = dict(headers or {})
        if entry is not None and ttl is not None:
            age = time.time() - float(entry["fetched_at"])
            if age < ttl:
                return self._from_entry(entry)
            if entry.get("etag"):
                send_headers["If-None-Match"] = str(entry["etag"])
            if entry.get("last_modified"):
                send_headers["If-Modified-Since"] = str(entry["last_modified"])
        resp = self._send(method, url, params=params, headers=send_headers, body=body)
        if path is not None and entry is not None and resp.status_code == 304:
            entry["fetched_at"] = time.time()
            write_json_atomic(path, entry)
            return self._from_entry(entry)
        result = Response(
            url=str(resp.url),
            status=resp.status_code,
            headers={k.lower(): v for k, v in resp.headers.items()},
            text=resp.text,
        )
        if path is not None and resp.status_code == 200:
            write_cache_entry(path, result.url, result.status, result.headers, result.text)
        return result

    @staticmethod
    def _from_entry(entry: Mapping[str, Any]) -> Response:
        headers = {
            name: str(entry[name.replace("-", "_")])
            for name in _CACHE_HEADERS
            if entry.get(name.replace("-", "_"))
        }
        return Response(
            url=str(entry.get("url", "")),
            status=int(entry.get("status", 200)),
            headers=headers,
            text=str(entry.get("text", "")),
            from_cache=True,
        )

    # --------------------------------------------------------------- sending

    def _throttle(self, host: str) -> None:
        """Wait so requests to one host start at least `min_interval` seconds apart."""
        with self._lock:
            lock = self._host_locks.setdefault(host, threading.Lock())
        with lock:
            now = self.clock()
            last = self._last_request.get(host)
            if last is not None and self.min_interval > 0:
                wait = self.min_interval - (now - last)
                if wait > 0:
                    self._sleep(wait)
                    now = max(self.clock(), last + self.min_interval)
            self._last_request[host] = now

    def _backoff(self, attempt: int) -> float:
        return min(MAX_BACKOFF, self.backoff_base * 2.0**attempt) + self._rng.uniform(0, 0.5)

    def _send(
        self,
        method: str,
        url: str,
        *,
        params: Mapping[str, Any] | None,
        headers: Mapping[str, str],
        body: bytes,
    ) -> httpx.Response:
        host = host_of(url) or url
        attempts = self.retries + 1
        problem = ""
        status: int | None = None
        for attempt in range(attempts):
            self._throttle(host)
            delay = self._backoff(attempt)
            try:
                resp = self._client.request(
                    method, url, params=params, headers=headers, content=body or None
                )
            except httpx.TimeoutException:
                problem, status = "the request timed out", None
            except (httpx.NetworkError, httpx.RemoteProtocolError) as exc:
                problem, status = f"the connection failed ({type(exc).__name__})", None
            except (httpx.HTTPError, httpx.InvalidURL) as exc:
                raise HttpError(
                    f"Could not fetch {url}: {exc}",
                    url=url,
                    hint="Check that the address is right.",
                ) from exc
            else:
                code = resp.status_code
                lowered = {k.lower(): v for k, v in resp.headers.items()}
                if looks_like_bot_wall(code, lowered, resp.text):
                    raise BotWallError(
                        f"{host} showed a bot check (HTTP {code}), so getmeajob stopped.",
                        url=url,
                        status=code,
                        hint=(
                            "getmeajob never tries to get past bot checks. Open the page in "
                            "your own browser instead, or skip this site."
                        ),
                    )
                if code != 429 and code < 500:
                    return resp
                problem, status = f"it answered HTTP {code}", code
                wait = parse_retry_after(resp.headers.get("retry-after"))
                if wait is not None:
                    if wait > MAX_BACKOFF:
                        raise HttpError(
                            f"{host} asked us to wait {wait:.0f} seconds before trying again.",
                            url=url,
                            status=code,
                            hint="Run the command again later.",
                        )
                    delay = wait
            if attempt + 1 < attempts:
                self._sleep(delay)
        raise HttpError(
            f"Could not get {url}: {problem} ({attempts} tries).",
            url=url,
            status=status,
            hint=(
                "Check your internet connection. If it works, the site may be busy or down; "
                "try again in a few minutes."
            ),
        )

    # ---------------------------------------------------------------- robots

    def _check_robots(self, url: str) -> None:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        with self._lock:
            known = origin in self._robots
            parser = self._robots.get(origin)
        if not known:
            parser = self._fetch_robots(origin, url)
            with self._lock:
                self._robots[origin] = parser
        if parser is not None and not parser.can_fetch(self.user_agent, url):
            raise RobotsDisallowed(
                f"{parts.netloc}/robots.txt asks tools like getmeajob not to read {parts.path}.",
                url=url,
                hint="getmeajob respects robots.txt. Open the page in your own browser instead.",
            )

    def _fetch_robots(self, origin: str, url: str) -> urllib.robotparser.RobotFileParser | None:
        robots_url = f"{origin}/robots.txt"
        try:
            resp = self._send("GET", robots_url, params=None, headers={}, body=b"")
        except BotWallError:
            raise
        except HttpError as exc:
            raise RobotsDisallowed(
                f"Could not read {robots_url}, so getmeajob will not read {url} for now.",
                url=url,
                status=exc.status,
                hint="Try again later, or open the page in your own browser.",
            ) from exc
        if resp.status_code >= 400:
            return None  # no robots.txt (or not readable by anyone): allowed
        parser = urllib.robotparser.RobotFileParser(robots_url)
        parser.parse(resp.text.splitlines())
        return parser


def client_for(ws: Workspace, settings: Settings | None = None) -> HttpClient:
    """The HTTP client for a workspace. With fixtures set it replays them (no cache, no
    waiting between requests); with `offline: true` alone every request is refused."""
    settings = settings if settings is not None else load_settings(ws)
    if settings.fixtures is not None:
        return HttpClient(
            cache_dir=None,
            timeout=settings.timeout,
            retries=settings.retries,
            min_interval=0.0,
            transport=FixtureTransport(settings.fixtures),
            max_workers=settings.max_workers,
        )
    if settings.offline:
        return HttpClient(
            cache_dir=None,
            retries=0,
            min_interval=0.0,
            transport=NoNetworkTransport(),
            max_workers=settings.max_workers,
        )
    return HttpClient(
        cache_dir=ws.http_cache_dir,
        timeout=settings.timeout,
        retries=settings.retries,
        min_interval=settings.min_interval,
        max_workers=settings.max_workers,
    )
