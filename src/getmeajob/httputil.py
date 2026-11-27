"""Pure helpers for the HTTP client: replies, host checks, bot walls, Retry-After, cache."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import socket
import time
from collections.abc import Mapping
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

from getmeajob.errors import GetmeajobError, HttpError
from getmeajob.files import read_json, write_json_atomic

BOT_WALL_STATUSES = frozenset({403, 429, 503})
BOT_WALL_MARKERS = (
    "just a moment...",
    "attention required! | cloudflare",
    "cf-chl",
    "captcha",
    "are you a robot",
)
_CACHE_HEADERS = ("content-type", "etag", "last-modified")


def host_of(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


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


def read_response(resp: httpx.Response, url: str, limit: int) -> Response:
    """A streamed reply as a `Response`, reading at most `limit` bytes of it."""
    data = bytearray()
    for chunk in resp.iter_bytes():
        data += chunk
        if len(data) > limit:
            raise HttpError(
                f"{host_of(url) or url} sent more than {limit // 2**20} MB, so getmeajob "
                "stopped reading.",
                url=url,
                status=resp.status_code,
                hint="No job page is that big. Check the link, or skip this site.",
            )
    headers = {k.lower(): v for k, v in resp.headers.items()}
    text = data.decode(resp.encoding or "utf-8", "replace")
    return Response(str(resp.url), resp.status_code, headers, text)


def private_host(host: str, *, lookup: bool) -> bool:
    """Whether `host` is, or with `lookup` resolves to, a loopback, private, link-local or
    reserved address. A name that does not resolve is left to the request to report."""
    try:
        addresses = [ipaddress.ip_address(host)]
    except ValueError:
        if not lookup:
            return False
        try:
            infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
        except (OSError, UnicodeError):
            return False
        addresses = [ipaddress.ip_address(info[4][0]) for info in infos]
    return any(not address.is_global for address in addresses)


def parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    value = value.strip()
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, when.timestamp() - time.time())


def looks_like_bot_wall(status: int, headers: Mapping[str, str], text: str) -> bool:
    if status not in BOT_WALL_STATUSES:
        return False
    if "challenge" in headers.get("cf-mitigated", "").lower():
        return True
    sample = text[:20000].lower()
    return any(marker in sample for marker in BOT_WALL_MARKERS)


def cache_key(method: str, url: str, params: Mapping[str, Any] | None, body: bytes) -> str:
    pairs = sorted((str(k), str(v)) for k, v in (params or {}).items())
    material = "\n".join([method.upper(), url, json.dumps(pairs), body.decode("utf-8", "replace")])
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def read_cache_entry(path: Path) -> dict[str, Any] | None:
    """A cache entry, or None when it is missing or damaged (then it is refetched)."""
    try:
        loaded = read_json(path, default=None)
    except (GetmeajobError, OSError):
        return None
    if not isinstance(loaded, dict) or not isinstance(loaded.get("text"), str):
        return None
    if not isinstance(loaded.get("fetched_at"), int | float):
        return None
    return loaded


def write_cache_entry(
    path: Path, url: str, status: int, headers: Mapping[str, str], text: str
) -> None:
    write_json_atomic(
        path,
        {
            "url": url,
            "status": status,
            "etag": headers.get("etag"),
            "last_modified": headers.get("last-modified"),
            "content_type": headers.get("content-type"),
            "text": text,
            "fetched_at": time.time(),
        },
    )


def response_from_entry(entry: Mapping[str, Any]) -> Response:
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
