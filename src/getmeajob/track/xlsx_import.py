"""`track import-xlsx`: bring your Excel edits back into the workspace.

Status changes go through `StatusLog.record` with source `xlsx` (a person, so any
change is allowed). Notes and Next action go to `data/notes.jsonl`. A value that matches
what is already stored writes nothing, so importing the same file twice is safe.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from getmeajob.report.xlsx_read import read_tracker_edits
from getmeajob.store import JobStore, StatusLog
from getmeajob.track.notes import NotesLog
from getmeajob.track.status import parse_status, record_by_person
from getmeajob.workspace import Workspace

IMPORT_NOTE = "edited in the Excel tracker"


@dataclass
class ImportResult:
    path: Path
    statuses: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)
    unknown_status: list[dict[str, Any]] = field(default_factory=list)
    unknown_keys: list[str] = field(default_factory=list)

    @property
    def written(self) -> int:
        return len(self.statuses) + len(self.notes) + len(self.next_actions)

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "written": self.written,
            "statuses": self.statuses,
            "notes": self.notes,
            "next_actions": self.next_actions,
            "unknown_status": self.unknown_status,
            "unknown_keys": self.unknown_keys,
        }


def import_tracker(ws: Workspace, path: Path) -> ImportResult:
    edits = read_tracker_edits(path)
    jobs = JobStore(ws).load()
    log = StatusLog(ws)
    notes = NotesLog(ws)
    result = ImportResult(path)
    for edit in edits:
        if edit.key not in jobs:
            if edit.key not in result.unknown_keys:
                result.unknown_keys.append(edit.key)
            continue
        if edit.status is not None:
            status = parse_status(edit.status)
            if status is None:
                result.unknown_status.append(
                    {"key": edit.key, "row": edit.row, "value": edit.status}
                )
            else:
                before = log.current(edit.key)
                if record_by_person(ws, edit.key, status, "xlsx", IMPORT_NOTE):
                    result.statuses.append(
                        {
                            "key": edit.key,
                            "from": before.value if before else None,
                            "to": status.value,
                        }
                    )
        if edit.notes is not None and notes.set(edit.key, "notes", edit.notes, "xlsx"):
            result.notes.append(edit.key)
        if edit.next_action is not None and notes.set(
            edit.key, "next_action", edit.next_action, "xlsx"
        ):
            result.next_actions.append(edit.key)
    return result
