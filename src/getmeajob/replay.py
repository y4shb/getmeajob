"""Offline replay: answer HTTP requests from recorded files instead of the network."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx

from getmeajob.errors import OfflineMiss
from getmeajob.files import read_json


def _content_type(path: Path) -> str:
    return {
        ".json": "application/json",
        ".html": "text/html; charset=utf-8",
        ".htm": "text/html; charset=utf-8",
        ".xml": "application/xml",
        ".txt": "text/plain; charset=utf-8",
    }.get(path.suffix.lower(), "application/octet-stream")


class FixtureTransport(httpx.BaseTransport):
    """Replays recorded replies from a folder instead of using the network.

    1. `root/routes.json`: a list of `{"method", "url_contains", "body_contains", "file",
       "status", "headers"}`, checked in order (`file` is relative to `root`).
    2. For GET: `root/http/<host>/<path>.json`, query ignored (`/` becomes `index`).
    3. Otherwise `OfflineMiss`. Requests for /robots.txt get a 404.
    """

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self._routes: list[dict[str, Any]] | None = None

    def _load_routes(self) -> list[dict[str, Any]]:
        if self._routes is None:
            data = read_json(self.root / "routes.json", default=[])
            items = data if isinstance(data, list) else []
            self._routes = [r for r in items if isinstance(r, dict)]
        return self._routes

    def _serve(self, request: httpx.Request, path: Path, status: int, extra: Any) -> httpx.Response:
        headers = {"content-type": _content_type(path)}
        if isinstance(extra, dict):
            headers.update({str(k).lower(): str(v) for k, v in extra.items()})
        return httpx.Response(status, headers=headers, content=path.read_bytes(), request=request)

    def path_for(self, url: httpx.URL) -> Path | None:
        """The recorded file a GET for `url` maps to (None if the path is unsafe)."""
        parts = [p for p in url.path.split("/") if p]
        if any(p in (".", "..") or "\\" in p for p in parts):
            return None
        rel = "/".join(parts) or "index"
        return self.root / "http" / (url.host or "_") / f"{rel}.json"

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if request.url.path == "/robots.txt":
            return httpx.Response(404, text="", request=request)
        body = request.read().decode("utf-8", "replace")
        routes_file = self.root / "routes.json"
        for route in self._load_routes():
            if str(route.get("method", "GET")).upper() != request.method.upper():
                continue
            if str(route.get("url_contains", "")) not in url:
                continue
            needle = route.get("body_contains")
            if needle is not None and str(needle) not in body:
                continue
            target = self.root / str(route.get("file", ""))
            if not target.is_file():
                raise OfflineMiss(
                    f"{routes_file} sends {request.method} {url} to {target}, which is missing.",
                    url=url,
                    hint="Fix the 'file' of that route or add the file.",
                )
            return self._serve(request, target, int(route.get("status", 200)), route.get("headers"))
        candidate = self.path_for(request.url) if request.method.upper() == "GET" else None
        if candidate is not None and candidate.is_file():
            return self._serve(request, candidate, 200, None)
        where = str(candidate) if candidate is not None else "(no file for this method)"
        raise OfflineMiss(
            f"Offline mode has no recorded reply for {request.method} {url}. "
            f"Looked in {routes_file} and {where}.",
            url=url,
            hint="Add a recorded reply there, or remove `fixtures` from settings.yaml.",
        )
