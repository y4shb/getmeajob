"""Command output: compact tables for people, one line of JSON for agents (`--json`).

`emit()` is the machine result; `line()`, `table()` and `done()` print nothing with
`--json`; `--quiet` silences everything except `warn()`.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping, Sequence
from typing import Any, TextIO

import yaml

from getmeajob.serial import to_jsonable
from getmeajob.textutil import truncate


def _cell(value: Any, max_col: int) -> str:
    if value is None:
        text = ""
    elif isinstance(value, bool):
        text = "yes" if value else "no"
    elif isinstance(value, float):
        text = f"{value:g}"
    elif isinstance(value, list | tuple | set | frozenset):
        text = ", ".join(_cell(v, max_col) for v in value)
    else:
        text = str(to_jsonable(value))
    text = " ".join(text.split())
    return truncate(text, max_col) if max_col > 0 else text


class Output:
    def __init__(
        self, json_mode: bool = False, quiet: bool = False, stream: TextIO | None = None
    ) -> None:
        self.json_mode = json_mode
        self.quiet = quiet
        self._stream = stream

    @property
    def stream(self) -> TextIO:
        """The output stream (stdout unless one was given), looked up when used."""
        return self._stream if self._stream is not None else sys.stdout

    @property
    def human(self) -> bool:
        """True when human-readable output should be printed."""
        return not self.json_mode and not self.quiet

    def _write(self, text: str) -> None:
        self.stream.write(text if text.endswith("\n") else text + "\n")

    def line(self, text: str) -> None:
        if self.human:
            self._write(text)

    def warn(self, text: str) -> None:
        """A warning on stderr. Printed in every mode, so agents see it too."""
        sys.stderr.write(f"warning: {text}\n")

    def table(
        self,
        rows: Sequence[Mapping[str, Any]],
        columns: Sequence[str],
        *,
        max_col: int = 48,
    ) -> None:
        """Aligned plain-text table; long cells are cut with an ellipsis."""
        if not self.human:
            return
        if not rows:
            self._write("(nothing to show)")
            return
        cells = [[_cell(row.get(col), max_col) for col in columns] for row in rows]
        widths = [max(len(str(col)), *(len(r[i]) for r in cells)) for i, col in enumerate(columns)]
        header = "  ".join(str(col).ljust(widths[i]) for i, col in enumerate(columns))
        lines = [header.rstrip()]
        for r in cells:
            lines.append("  ".join(r[i].ljust(widths[i]) for i in range(len(columns))).rstrip())
        self._write("\n".join(lines))

    def emit(self, data: Any) -> None:
        """The command's result: JSON with --json, a readable dump otherwise."""
        plain = to_jsonable(data)
        if self.json_mode:
            self._write(json.dumps(plain, ensure_ascii=False, default=str))
            return
        if self.quiet:
            return
        if isinstance(plain, str):
            self._write(plain)
            return
        dumped = yaml.safe_dump(plain, sort_keys=False, allow_unicode=True, width=100)
        self._write(dumped.rstrip("\n").removesuffix("\n..."))

    def done(self, summary: str, next_step: str | None = None) -> None:
        """One summary line, and optionally one `next:` line with the command to run next."""
        if not self.human:
            return
        self._write(summary)
        if next_step:
            self._write(f"next: {next_step}")
