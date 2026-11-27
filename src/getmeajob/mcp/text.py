"""Small text helpers for MCP tool results: a length cap and a guard that turns every
error into a short message with a hint, so a client never sees a traceback."""

from __future__ import annotations

import functools
import logging
from collections.abc import Callable
from typing import Any, TypeVar

from getmeajob.errors import GetmeajobError
from getmeajob.textutil import truncate

MAX_CHARS = 2_000
CUT_NOTE = "\n... (cut to stay short; ask for fewer rows, or run the getmeajob CLI with --json)"
UNEXPECTED_HINT = (
    "Run the same step with the getmeajob command line (add --json) to see more. "
    "If it keeps happening, report it as a bug."
)

log = logging.getLogger("getmeajob.mcp")
_F = TypeVar("_F", bound=Callable[..., str])


def clip(text: str, limit: int = MAX_CHARS) -> str:
    """`text` cut to at most `limit` characters, at a line break when one is near."""
    if len(text) <= limit:
        return text
    keep = max(0, limit - len(CUT_NOTE))
    cut = text[:keep]
    newline = cut.rfind("\n")
    if newline > keep // 2:
        cut = cut[:newline]
    return cut + CUT_NOTE


def error_text(exc: BaseException) -> str:
    """The message a client sees for an error: `error:` and `hint:` lines."""
    if isinstance(exc, GetmeajobError):
        lines = [f"error: {exc.message}"]
        if exc.hint:
            lines.append(f"hint: {exc.hint}")
        return clip("\n".join(lines))
    detail = truncate(" ".join(str(exc).split()), 300)
    head = f"error: {type(exc).__name__}" + (f": {detail}" if detail else "")
    return f"{head}\nhint: {UNEXPECTED_HINT}"


def guarded(fn: _F) -> _F:
    """Wrap a tool so any exception comes back as text (the traceback goes to the log)."""

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> str:
        try:
            return fn(*args, **kwargs)
        except GetmeajobError as exc:
            return error_text(exc)
        except Exception as exc:
            log.exception("tool %s failed", fn.__name__)
            return error_text(exc)

    return wrapper  # type: ignore[return-value]


def bounded(value: int, low: int, high: int) -> int:
    """`value` kept between `low` and `high`."""
    return max(low, min(high, int(value)))
