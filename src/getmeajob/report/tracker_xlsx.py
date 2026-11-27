"""The Excel tracker: `write_tracker_xlsx` and `read_tracker_edits`.

Sheets, in order: Read me, Tracker, All jobs, Job descriptions, Queue, Questions.
You edit Status, Next action and Notes on the Tracker and bring them back with
`getmeajob track import-xlsx`. Writing the file again keeps edits you have not
imported yet (see `getmeajob.report.xlsx_read`).
"""

from __future__ import annotations

import io
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openpyxl import Workbook
from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import Font
from openpyxl.worksheet.datavalidation import DataValidation

from getmeajob.errors import GetmeajobError
from getmeajob.files import atomic_write_bytes, utc_text
from getmeajob.report.columns import (
    ALL_HEADERS,
    ALL_WIDTHS,
    HIDDEN,
    HOW_TO,
    JD_HEADERS,
    QUESTION_HEADERS,
    QUEUE_HEADERS,
    SHEETS,
    TRACKER_HEADERS,
    TRACKER_WIDTHS,
    TRACKER_WRAP,
)
from getmeajob.report.rows import (
    TrackerRow,
    all_job_rows,
    jd_text_for,
    open_questions,
    question_rows,
    queue_rows,
    tracker_rows,
)
from getmeajob.report.xlsx_read import (
    KEY,
    NEXT,
    NOTES,
    QUEUE,
    STATUS,
    SYNC,
    Edit,
    norm_word,
    read_tracker_edits,
    sync_value,
)
from getmeajob.report.xlsx_style import (
    BOLD,
    CELL_MAX,
    MUTED_FONT,
    WRAP,
    as_day,
    column_letter,
    fill,
    finish_data_sheet,
    header_row,
    link,
    put,
    table_sheet,
    widths,
    wrap_columns,
)
from getmeajob.track.snapshot import Snapshot, load_snapshot
from getmeajob.track.status import GREEN, GREY, LADDER, MEANING, counts_in_ladder_order
from getmeajob.workspace import Workspace

__all__ = ["Edit", "XlsxResult", "build_tracker_xlsx", "read_tracker_edits", "write_tracker_xlsx"]

GREEN_FILL, YELLOW_FILL, GREY_FILL = fill("E2F0D9"), fill("FFF2CC"), fill("E7E6E6")


@dataclass(slots=True)
class XlsxResult:
    path: Path
    tracker_rows: int
    all_jobs: int
    pending_kept: int


def _quoted_or(column: str, values: list[str]) -> str:
    return "OR(" + ",".join(f'${column}2="{v}"' for v in values) + ")"


def _tracker_sheet(
    sheet: Any, rows: list[TrackerRow], pending: dict[str, Edit], xlsx_dir: Path, ws: Workspace
) -> int:
    header_row(sheet, TRACKER_HEADERS)
    col = {name: i for i, name in enumerate(TRACKER_HEADERS, start=1)}
    kept = 0
    for r, row in enumerate(rows, start=2):
        status, notes, action = row.status, row.notes, row.next_action
        edit = pending.get(row.key)
        if edit is not None:  # your edits from the old file that were not imported yet
            if edit.status is not None and norm_word(edit.status) != row.status:
                status, kept = edit.status, kept + 1
            if edit.notes is not None and edit.notes != row.notes:
                notes, kept = edit.notes, kept + 1
            if edit.next_action is not None and edit.next_action != row.next_action:
                action, kept = edit.next_action, kept + 1
        values: dict[str, Any] = {
            KEY: row.key,
            "Company": row.company,
            "Role": row.role,
            "Location": row.location,
            "Tier": row.tier,
            "Score": row.score,
            "Eligible": row.eligible,
            "Why": row.why,
            STATUS: status,
            "Applied on": as_day(row.applied_on),
            NEXT: action,
            "Resume used": row.resume_used,
            "Plan status": row.plan_status,
            "Unknowns": row.unknowns,
            "Job link": row.job_link,
            "JD file": row.jd_file.relative_to(ws.root).as_posix() if row.jd_file else "",
            "Posted": as_day(row.posted),
            "First seen": as_day(row.first_seen),
            "New/closed since last run": row.change,
            NOTES: notes,
            QUEUE: row.open_queue,
            SYNC: sync_value(row.status, row.notes, row.next_action),
        }
        for name, value in values.items():
            put(sheet, r, col[name], value)
        sheet.cell(row=r, column=col[KEY]).font = MUTED_FONT
        link(sheet.cell(row=r, column=col["Job link"]), row.job_link)
        if row.jd_file is not None:
            target = os.path.relpath(row.jd_file, xlsx_dir).replace(os.sep, "/")
            link(sheet.cell(row=r, column=col["JD file"]), target)
    last = max(2, len(rows) + 1)
    widths(sheet, TRACKER_HEADERS, TRACKER_WIDTHS)
    wrap_columns(sheet, TRACKER_HEADERS, TRACKER_WRAP, len(rows) + 1)
    for name in HIDDEN:
        sheet.column_dimensions[column_letter(TRACKER_HEADERS, name)].hidden = True
    _status_rules(sheet, last)
    finish_data_sheet(sheet, TRACKER_HEADERS, len(rows) + 1, "D2")  # header, Key..Role
    return kept


def _status_rules(sheet: Any, last: int) -> None:
    status_col = column_letter(TRACKER_HEADERS, STATUS)
    plan_col = column_letter(TRACKER_HEADERS, "Plan status")
    queue_col = column_letter(TRACKER_HEADERS, QUEUE)
    values = [s.value for s in LADDER]
    validation = DataValidation(
        type="list",
        formula1='"' + ",".join(values) + '"',
        allow_blank=True,
        showErrorMessage=True,
        errorStyle="warning",
        errorTitle="Unknown status",
        error="Pick a status from the list. Unknown words are reported, not recorded.",
    )
    sheet.add_data_validation(validation)
    validation.add(f"{status_col}2:{status_col}{last}")
    area = f"A2:{column_letter(TRACKER_HEADERS, SYNC)}{last}"
    grey = sorted(s.value for s in GREY)
    green = [s.value for s in LADDER if s in GREEN]
    yellow = f'OR(${plan_col}2="needs_answers",N(${queue_col}2)>0)'
    for formula, color in (
        (_quoted_or(status_col, grey), GREY_FILL),
        (_quoted_or(status_col, green), GREEN_FILL),
        (yellow, YELLOW_FILL),
    ):
        rule = FormulaRule(formula=[formula], fill=color, stopIfTrue=True)
        sheet.conditional_formatting.add(area, rule)


def _read_me(sheet: Any, snap: Snapshot, rows: list[TrackerRow]) -> None:
    sheet.column_dimensions["A"].width = 22
    sheet.column_dimensions["B"].width = 80
    sheet.column_dimensions["C"].width = 16
    sheet.column_dimensions["D"].width = 14
    put(sheet, 1, 1, "getmeajob tracker").font = Font(bold=True, size=14)
    stamp = utc_text(snap.taken_at)
    put(sheet, 2, 1, "Exported")
    put(sheet, 2, 2, stamp)
    open_jobs = sum(1 for j in snap.jobs.values() if j.status != "closed")
    put(sheet, 3, 1, "Jobs found")
    put(sheet, 3, 2, f"{len(snap.jobs)} in total, {open_jobs} still open")
    run = snap.last_run
    put(sheet, 4, 1, "Last source run")
    if run is not None:
        when = utc_text(run.started) or run.run_id
        put(sheet, 4, 2, f"{when}: {len(run.new_keys)} new, {len(run.closed_keys)} closed")
    else:
        put(sheet, 4, 2, "none yet (run `getmeajob source`)")
    r = 6
    header_row(sheet, ["Sheet", "What it holds"], row=r)
    for name, text in SHEETS:
        r += 1
        put(sheet, r, 1, name).font = BOLD
        put(sheet, r, 2, text).alignment = WRAP
    r += 2
    header_row(sheet, ["How to edit", ""], row=r)
    for line in HOW_TO:
        r += 1
        put(sheet, r, 2, line).alignment = WRAP
    r += 2
    put(sheet, r, 1, "Jobs on the Tracker sheet by status ('Count now' follows your edits)")
    sheet.cell(row=r, column=1).font = BOLD
    r += 1
    header_row(sheet, ["Status", "Meaning", "Count now", "Count at export"], row=r)
    status_col = column_letter(TRACKER_HEADERS, STATUS)
    last = max(2, len(rows) + 1) + 500  # room for sorting and filtering; counts stay right
    at_export = counts_in_ladder_order(row.status for row in rows)
    for status in LADDER:
        r += 1
        put(sheet, r, 1, status.value)
        put(sheet, r, 2, MEANING[status])
        formula = f'=COUNTIF(Tracker!${status_col}$2:${status_col}${last},"{status.value}")'
        sheet.cell(row=r, column=3).value = formula
        put(sheet, r, 4, at_export[status.value])


def _jd_sheet(sheet: Any, ws: Workspace, snap: Snapshot, rows: list[TrackerRow]) -> None:
    header_row(sheet, JD_HEADERS)
    for r, row in enumerate(rows, start=2):
        text = jd_text_for(ws, snap, row.key).strip()
        if len(text) > CELL_MAX:
            note = f"\n\n(cut here; the whole text is in data/jd/{ws.jd_path(row.key).name})"
            text = text[: CELL_MAX - len(note)].rstrip() + note
        values = [row.key, row.company, row.role, row.job_link, text or "(no text stored)"]
        for c, value in enumerate(values, start=1):
            put(sheet, r, c, value)
        link(sheet.cell(row=r, column=4), row.job_link)
        sheet.row_dimensions[r].height = 150
    widths(sheet, JD_HEADERS, {"Key": 30, "Company": 18, "Role": 30, "Job link": 34})
    sheet.column_dimensions["E"].width = 100
    wrap_columns(sheet, JD_HEADERS, ["Job description", "Role"], len(rows) + 1)
    finish_data_sheet(sheet, JD_HEADERS, len(rows) + 1, "A2")


def _pending_edits(path: Path) -> dict[str, Edit]:
    """Edits in the file we are about to replace, so writing it again loses none."""
    if not path.exists():
        return {}
    try:
        return {e.key: e for e in read_tracker_edits(path)}
    except GetmeajobError as exc:
        raise GetmeajobError(
            f"The existing file {path} could not be read, so writing over it might lose "
            f"your edits ({exc.message})",
            hint="Move or rename that file, then run `getmeajob report` again.",
        ) from exc


def build_tracker_xlsx(ws: Workspace, path: Path, snap: Snapshot | None = None) -> XlsxResult:
    """Write the workbook (atomically) and say what went in."""
    path = path.resolve()
    snap = snap or load_snapshot(ws)
    pending = _pending_edits(path)
    rows = tracker_rows(snap)
    book = Workbook()
    book.properties.creator = "getmeajob"
    book.properties.title = "getmeajob tracker"
    readme = book.active
    readme.title = "Read me"
    kept = _tracker_sheet(book.create_sheet("Tracker"), rows, pending, path.parent, ws)
    all_rows = all_job_rows(snap)
    table_sheet(
        book.create_sheet("All jobs"),
        ALL_HEADERS,
        all_rows,
        ALL_WIDTHS,
        wrap=["Flags"],
        links=["Job link"],
        days=["First seen"],
    )
    _jd_sheet(book.create_sheet("Job descriptions"), ws, snap, rows)
    table_sheet(
        book.create_sheet("Queue"),
        QUEUE_HEADERS,
        queue_rows(snap),
        {"What we need from you": 60, "Key": 30, "Role": 28, "Detail": 50, "Link": 34},
        wrap=["What we need from you", "Detail"],
        links=["Link"],
        days=["Since"],
    )
    table_sheet(
        book.create_sheet("Questions"),
        QUESTION_HEADERS,
        question_rows(open_questions(snap)),
        {"Question": 50, "Companies": 24, "Options": 40, "Why unknown": 36},
        wrap=["Question", "Options", "Why unknown"],
    )
    _read_me(readme, snap, rows)
    buffer = io.BytesIO()
    book.save(buffer)
    atomic_write_bytes(path, buffer.getvalue())
    return XlsxResult(path, len(rows), len(all_rows), kept)


def write_tracker_xlsx(ws: Workspace, path: Path) -> Path:
    """Write the Excel tracker to `path` and return it."""
    return build_tracker_xlsx(ws, path).path
