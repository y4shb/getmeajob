"""The one polite HTTP client every network call goes through: timeouts, retries,
a per-host interval, a disk cache, bot-check stops, robots.txt and public hosts only.
"""

from __future__ import annotations

import json
import random
import threading
import time
import urllib.robotparser
from collections.abc import Callable, Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor
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
    Response,
    cache_key,
    host_of,
    looks_like_bot_wall,
    parse_retry_after,
    private_host,
    read_cache_entry,
    read_response,
    response_from_entry,
    write_cache_entry,
)
from getmeajob.replay import FixtureTransport
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
MAX_REDIRECTS = 5
MAX_BODY_BYTES = 10 * 1024 * 1024
_ROBOTS = "getmeajob_robots"


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
        self._lookup = transport is None
        self._client = httpx.Client(
            timeout=httpx.Timeout(timeout, connect=connect_timeout),
            transport=transport,
            headers={"User-Agent": self.user_agent},
            follow_redirects=True,
            max_redirects=MAX_REDIRECTS,
            event_hooks={"request": [self._check_hop]},
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
        and an older one is revalidated. `check_robots=True` is for HTML pages: robots.txt
        is checked for the URL and for every redirect."""
        return self._cached(
            "GET", url, params=params, headers=headers, body=b"", ttl=ttl, robots=check_robots
        )

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
        robots: bool = False,
    ) -> Response:
        path = None if ttl is None else self._cache_path(cache_key(method, url, params, body))
        entry = read_cache_entry(path) if path is not None else None
        send_headers = dict(headers or {})
        if entry is not None and ttl is not None:
            age = time.time() - float(entry["fetched_at"])
            if age < ttl:
                return response_from_entry(entry)
            if entry.get("etag"):
                send_headers["If-None-Match"] = str(entry["etag"])
            if entry.get("last_modified"):
                send_headers["If-Modified-Since"] = str(entry["last_modified"])
        result = self._send(
            method, url, params=params, headers=send_headers, body=body, robots=robots
        )
        if path is not None and entry is not None and result.status == 304:
            entry["fetched_at"] = time.time()
            write_json_atomic(path, entry)
            return response_from_entry(entry)
        if path is not None and result.status == 200:
            write_cache_entry(path, result.url, result.status, result.headers, result.text)
        return result

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

    def _check_hop(self, request: httpx.Request) -> None:
        """Runs before every request, redirects included."""
        url = str(request.url)
        if private_host(request.url.host, lookup=self._lookup):
            raise HttpError(
                f"getmeajob does not fetch {url}: it points at this computer or a private network.",
                url=url,
                hint="getmeajob only reads public sites. Check the link, or open it yourself.",
            )
        if request.extensions.get(_ROBOTS):
            self._check_robots(url)

    def _send(
        self,
        method: str,
        url: str,
        *,
        params: Mapping[str, Any] | None,
        headers: Mapping[str, str],
        body: bytes,
        robots: bool = False,
    ) -> Response:
        host = host_of(url) or url
        attempts = self.retries + 1
        problem = ""
        status: int | None = None
        for attempt in range(attempts):
            self._throttle(host)
            delay = self._backoff(attempt)
            try:
                with self._client.stream(
                    method,
                    url,
                    params=params,
                    headers=headers,
                    content=body or None,
                    extensions={_ROBOTS: True} if robots else None,
                ) as stream:
                    resp = read_response(stream, url, MAX_BODY_BYTES)
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
                code = resp.status
                if looks_like_bot_wall(code, resp.headers, resp.text):
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
        if resp.status >= 400:
            return None  # no robots.txt (or not readable by anyone): allowed
        parser = urllib.robotparser.RobotFileParser(robots_url)
        parser.parse(resp.text.splitlines())
        return parser


def client_for(ws: Workspace, settings: Settings | None = None) -> HttpClient:
    """The HTTP client for a workspace. With fixtures set it replays them (no cache, no
    waiting between requests)."""
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
    return HttpClient(
        cache_dir=ws.http_cache_dir,
        timeout=settings.timeout,
        retries=settings.retries,
        min_interval=settings.min_interval,
        max_workers=settings.max_workers,
    )
