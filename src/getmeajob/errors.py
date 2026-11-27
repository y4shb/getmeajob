"""Errors with a plain-language message and a hint.

The CLI prints `error: <message>` and `hint: <hint>` for these and exits with code 2,
so a user never sees a traceback for something they can fix.
"""

from __future__ import annotations

INIT_HINT = (
    "Run `getmeajob init` to create a workspace (or `getmeajob init --demo` to try the "
    "sample data). Use --home PATH or GETMEAJOB_HOME to point at another folder."
)


class GetmeajobError(Exception):
    """Base error: `message` says what went wrong, `hint` says what to do about it."""

    def __init__(self, message: str, *, hint: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint

    def __str__(self) -> str:
        return self.message


class ConfigError(GetmeajobError):
    """A config file (YAML) is missing, unreadable or has a wrong value."""


class StoreError(GetmeajobError):
    """A data file in the workspace (JSON or JSONL) is damaged or has a bad record."""


class WorkspaceMissing(GetmeajobError):
    """No workspace at the resolved path. The default hint points to `getmeajob init`."""

    def __init__(self, message: str, *, hint: str | None = None) -> None:
        super().__init__(message, hint=hint if hint is not None else INIT_HINT)


class HttpError(GetmeajobError):
    """A request failed for good (after retries), or a reply could not be read."""

    def __init__(
        self,
        message: str,
        *,
        url: str = "",
        status: int | None = None,
        hint: str | None = None,
    ) -> None:
        super().__init__(message, hint=hint)
        self.url = url
        self.status = status


class BotWallError(HttpError):
    """The site showed a bot check. getmeajob stops and never tries to get past it."""


class RobotsDisallowed(HttpError):
    """The site's robots.txt asks tools like getmeajob not to read this page."""


class OfflineMiss(HttpError):
    """Offline mode has no recorded reply for this request."""
