"""Your own Notes and Next action per job, as an append-only log in `data/notes.jsonl`.

One record per change: `{"ts", "job_key", "field": "notes" | "next_action", "value",
"source"}`. The latest record per job and field wins. Writing the value a field already
has is a no-op, so importing the same spreadsheet twice adds nothing.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from getmeajob.files import append_jsonl, now_iso, read_jsonl
from getmeajob.workspace import Workspace

FIELDS = ("notes", "next_action")


def notes_path(ws: Workspace) -> Path:
    return ws.data_dir / "notes.jsonl"


def clean_note(value: object) -> str:
    """Text as stored: line breaks made plain, outer spaces trimmed."""
    if value is None:
        return ""
    text = str(value).replace("\r\n", "\n").replace("\r", "\n")
    return text.strip()


@dataclass(slots=True)
class JobNotes:
    notes: str = ""
    next_action: str = ""


class NotesLog:
    def __init__(self, ws: Workspace) -> None:
        self.path = notes_path(ws)

    def current(self) -> dict[str, JobNotes]:
        latest: dict[str, JobNotes] = {}
        for record in read_jsonl(self.path):
            key = str(record.get("job_key") or "")
            field = record.get("field")
            if not key or field not in FIELDS:
                continue
            entry = latest.setdefault(key, JobNotes())
            setattr(entry, str(field), clean_note(record.get("value")))
        return {k: v for k, v in latest.items() if v.notes or v.next_action}

    def get(self, key: str) -> JobNotes:
        return self.current().get(key, JobNotes())

    def set(self, key: str, field: str, value: object, source: str) -> bool:
        """Store a new value. Returns False (and writes nothing) when it is unchanged."""
        if field not in FIELDS:
            raise ValueError(f"unknown notes field {field!r}")
        text = clean_note(value)
        if getattr(self.get(key), field) == text:
            return False
        record = {"ts": now_iso(), "job_key": key, "field": field, "value": text}
        append_jsonl(self.path, {**record, "source": source})
        return True
