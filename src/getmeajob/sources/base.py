"""The contract every job source follows.

A source reads one kind of public job board (Greenhouse, Ashby, ...). It turns the
board's reply into `Job` records and never writes anything itself; the pipeline does
the storing. Plugins add sources through the `getmeajob.sources` entry-point group.

Outcomes of `list_jobs`:
- `found=True, error=None`: the board answered; `jobs` is the full list (unless
  `partial`), so jobs missing from it are gone.
- `found=False, error=None`: the board does not exist (HTTP 404).
- `error` set: the board could not be read this time. Nothing is closed because of it.
Transport failures may also raise `HttpError`; `BotWallError` always propagates.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from getmeajob.http import HttpClient
from getmeajob.models import Board, Job


@dataclass
class SourceResult:
    found: bool
    jobs: list[Job]
    board_name: str | None = None
    error: str | None = None
    # Additions beyond the planned contract (all optional):
    skipped: list[str] = field(default_factory=list)  # one reason per job left out
    notes: list[str] = field(default_factory=list)  # things worth telling the user
    partial: bool = False  # the list was cut short, so missing jobs are not closed


@dataclass
class ProbeResult:
    found: bool
    board_name: str | None
    count: int


@runtime_checkable
class Source(Protocol):
    """One kind of job board. `name` is the `ats` value used in companies.yaml."""

    name: str

    def list_jobs(self, board: Board, client: HttpClient) -> SourceResult:
        """All open jobs on the board."""
        ...

    def probe(self, slug: str, client: HttpClient) -> ProbeResult:
        """Whether a board with this slug exists, its name and how many jobs it has."""
        ...

    def parse_url(self, url: str) -> str | None:
        """The board slug from a board or job URL of this kind, else None."""
        ...
