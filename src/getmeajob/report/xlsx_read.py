"""Reading your edits back from the Excel tracker.

Columns are found by their header names, so moving or adding columns is fine. Each
Tracker row carries a hidden "Sync (do not edit)" cell with what getmeajob wrote there
(the status, and short fingerprints of Notes and Next action). A value counts as your
edit only when it differs from that, so an old copy of the file never undoes newer
changes in rows you did not touch.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

from getmeajob.errors import GetmeajobError
from getmeajob.textutil import short_hash
from getmeajob.track.notes import clean_note
from getmeajob.track.status import norm_word

TRACKER_SHEET = "Tracker"
KEY = "Key"
STATUS = "Status"
NOTES = "Notes"
NEXT = "Next action"
QUEUE = "Open queue items"
SYNC = "Sync (do not edit)"


@dataclass(slots=True)
class Edit:
    """Your changes in one Tracker row. None means "not changed"; "" means "cleared"."""

    key: str
    status: str | None
    notes: str | None
    next_action: str | None
    row: int = 0


def fingerprint(text: str) -> str:
    """Short hash of a Notes or Next action value ("" for an empty one)."""
    text = clean_note(text)
    return short_hash(text) if text else ""


def sync_value(status: str, notes: str, next_action: str) -> str:
    data = {"status": status, "notes": fingerprint(notes), "next": fingerprint(next_action)}
    return json.dumps(data, separators=(",", ":"))


def _norm_header(value: Any) -> str:
    return " ".join(str(value).replace("_", " ").split()).casefold() if value is not None else ""


def cell_text(value: Any) -> str:
    """A cell value as text, the way you see it (dates as YYYY-MM-DD)."""
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.date().isoformat() if value.time() == datetime.min.time() else str(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _baseline(value: Any) -> dict[str, str] | None:
    try:
        data = json.loads(cell_text(value))
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    return {k: str(data.get(k) or "") for k in ("status", "notes", "next")}


def _open(path: Path) -> Any:
    if not path.is_file():
        raise GetmeajobError(
            f"There is no file at {path}.",
            hint="Run `getmeajob report` to write exports/tracker.xlsx, then edit that file.",
        )
    try:
        return load_workbook(path, read_only=True, data_only=True)
    except Exception as exc:  # zip, XML and openpyxl's own errors for a broken file
        raise GetmeajobError(
            f"{path} could not be read as an Excel file ({exc.__class__.__name__}).",
            hint="Save it as .xlsx (Excel Workbook) and try again, or run `getmeajob report`.",
        ) from exc


def _tracker_sheet(book: Any, path: Path) -> Any:
    for name in book.sheetnames:
        if str(name).strip().casefold() == TRACKER_SHEET.casefold():
            return book[name]
    raise GetmeajobError(
        f"{path} has no sheet named {TRACKER_SHEET}.",
        hint="Use the file written by `getmeajob report`, and keep the sheet names.",
    )


def _changed(text: str, baseline: dict[str, str] | None, field: str) -> str | None:
    if baseline is None:
        return text or None
    return text if fingerprint(text) != baseline[field] else None


def read_tracker_edits(path: Path) -> list[Edit]:
    """Your edits to Status, Notes and Next action on the Tracker sheet, by Key."""
    book = _open(path)
    try:
        sheet = _tracker_sheet(book, path)
        if hasattr(sheet, "reset_dimensions"):  # some apps save a wrong size; read it all
            sheet.reset_dimensions()
        rows = sheet.iter_rows(values_only=True)
        header = next(rows, None) or ()
        columns = {_norm_header(h): i for i, h in enumerate(header) if h is not None}
        if _norm_header(KEY) not in columns:
            raise GetmeajobError(
                f"The {TRACKER_SHEET} sheet in {path} has no {KEY} column.",
                hint="getmeajob matches your edits by the Key column; keep it in the sheet.",
            )

        def get(values: tuple[Any, ...], name: str) -> Any:
            index = columns.get(_norm_header(name))
            return values[index] if index is not None and index < len(values) else None

        edits: list[Edit] = []
        for number, values in enumerate(rows, start=2):
            key = cell_text(get(values, KEY)).strip()
            if not key:
                continue
            base = _baseline(get(values, SYNC))
            status = cell_text(get(values, STATUS)).strip()
            status_edit = None
            if status and (base is None or norm_word(status) != norm_word(base["status"])):
                status_edit = status
            notes = clean_note(cell_text(get(values, NOTES)))
            action = clean_note(cell_text(get(values, NEXT)))
            notes_edit = _changed(notes, base, "notes") if _has(columns, NOTES) else None
            next_edit = _changed(action, base, "next") if _has(columns, NEXT) else None
            if status_edit is None and notes_edit is None and next_edit is None:
                continue
            edits.append(Edit(key, status_edit, notes_edit, next_edit, number))
        return edits
    finally:
        book.close()


def _has(columns: dict[str, int], name: str) -> bool:
    return _norm_header(name) in columns
