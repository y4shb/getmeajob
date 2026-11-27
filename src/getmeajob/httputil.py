"""Pure helpers for the HTTP client: bot-wall checks, Retry-After and the disk cache."""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Mapping
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from getmeajob.errors import GetmeajobError
from getmeajob.files import read_json, write_json_atomic

BOT_WALL_STATUSES = frozenset({403, 429, 503})
BOT_WALL_MARKERS = (
    "just a moment...",
    "attention required! | cloudflare",
    "cf-chl",
    "captcha",
    "are you a robot",
)


def host_of(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


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
