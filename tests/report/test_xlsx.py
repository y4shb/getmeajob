from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from openpyxl import load_workbook

from getmeajob.cli import main
from getmeajob.files import read_jsonl
from getmeajob.models import AppStatus
from getmeajob.report.tracker_xlsx import build_tracker_xlsx, read_tracker_edits
from getmeajob.store import JobStore, StatusLog
from getmeajob.track.notes import NotesLog, notes_path
from getmeajob.workspace import Workspace

Cli = Callable[..., tuple[int, str, str]]
GH = "greenhouse:examplecorp:1001"
LEVER = "lever:demowidgets:7c0de000-0000-4000-8000-000000000001"
SHEETS = ["Read me", "Tracker", "All jobs", "Job descriptions", "Queue", "Questions"]
TRACKER = [
    "Key",
    "Company",
    "Role",
    "Location",
    "Tier",
    "Score",
    "Eligible",
    "Why",
    "Status",
    "Applied on",
    "Next action",
    "Resume used",
    "Plan status",
    "Unknowns",
    "Job link",
    "JD file",
    "Posted",
    "First seen",
    "New/closed since last run",
    "Notes",
]


def _headers(sheet: Any) -> list[str]:
    return [c.value for c in sheet[1] if c.value is not None]


def _row_for(sheet: Any, key: str) -> int:
    for row in range(2, sheet.max_row + 1):
        if sheet.cell(row=row, column=1).value == key:
            return int(row)
    raise AssertionError(f"{key} not on the sheet")


def _edit(path: Path, key: str, **values: str) -> None:
    book = load_workbook(path)
    sheet = book["Tracker"]
    headers = _headers(sheet)
    row = _row_for(sheet, key)
    for name, value in values.items():
        sheet.cell(row=row, column=headers.index(name) + 1).value = value
    book.save(path)


def test_missing_workspace_friendly(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["report", "--home", str(tmp_path / "nothing")])
    captured = capsys.readouterr()
    assert code == 2
    assert "getmeajob init" in captured.err
    assert "Traceback" not in captured.err + captured.out


def test_sheets_columns_validation_links(pipeline_ws: Workspace, cli: Cli) -> None:
    code, out, _ = cli(pipeline_ws, "report")
    assert code == 0 and "exports/tracker.xlsx" in out
    path = pipeline_ws.exports_dir / "tracker.xlsx"
    assert (pipeline_ws.exports_dir / "tracker.md").is_file()
    book = load_workbook(path)
    assert book.sheetnames == SHEETS
    tracker = book["Tracker"]
    headers = _headers(tracker)
    assert headers[: len(TRACKER)] == TRACKER
    assert headers[len(TRACKER) :] == ["Open queue items", "Sync (do not edit)"]
    hidden = {k for k, dim in tracker.column_dimensions.items() if dim.hidden}
    assert hidden == {"U", "V"}
    assert tracker.freeze_panes == "D2"
    assert tracker.auto_filter.ref == f"A1:V{tracker.max_row}"
    assert tracker["A1"].font.bold and tracker["A1"].fill.fgColor.rgb.endswith("1F3A5F")
    for name in SHEETS[1:]:
        assert book[name].auto_filter.ref and book[name].freeze_panes == (
            "D2" if name == "Tracker" else "A2"
        )

    keys = [tracker.cell(row=r, column=1).value for r in range(2, tracker.max_row + 1)]
    assert GH in keys and len(keys) == 4
    validation = tracker.data_validations.dataValidation[0]
    allowed = validation.formula1.strip('"').split(",")
    assert sorted(allowed) == sorted(s.value for s in AppStatus)
    assert str(validation.sqref) == f"I2:I{tracker.max_row}"
    row = _row_for(tracker, GH)
    link = tracker.cell(row=row, column=headers.index("Job link") + 1)
    assert link.hyperlink.target == "https://job-boards.greenhouse.io/examplecorp/jobs/1001"
    jd = tracker.cell(row=row, column=headers.index("JD file") + 1)
    assert jd.value == "data/jd/greenhouse__examplecorp__1001.txt"
    assert jd.hyperlink.target == "../data/jd/greenhouse__examplecorp__1001.txt"
    assert tracker.cell(row=row, column=headers.index("Plan status") + 1).value == "needs_answers"
    assert "Why do you want to join" in tracker.cell(row=row, column=14).value
    rules = [r.formula[0] for cf in tracker.conditional_formatting for r in cf.rules]
    assert any('"applied"' in f for f in rules) and any('"rejected"' in f for f in rules)
    assert any("needs_answers" in f for f in rules)

    readme = book["Read me"]
    formulas = [c.value for c in readme["C"] if isinstance(c.value, str)]
    assert any(f.startswith("=COUNTIF(Tracker!$I$2:") for f in formulas)
    assert readme["A2"].value == "Exported"
    jd_sheet = book["Job descriptions"]
    assert _headers(jd_sheet) == ["Key", "Company", "Role", "Job link", "Job description"]
    assert "Example Corp" in jd_sheet.cell(row=_row_for(jd_sheet, GH), column=5).value
    assert book["All jobs"].max_row == 9
    assert book["Queue"].cell(row=2, column=2).value == "needs_answers"
    assert book["Questions"].cell(row=2, column=1).value == "Why do you want to join Example Corp?"


def test_roundtrip_import_records_changes_once(pipeline_ws: Workspace, cli: Cli) -> None:
    path = build_tracker_xlsx(pipeline_ws, pipeline_ws.exports_dir / "tracker.xlsx").path
    assert read_tracker_edits(path) == []
    _edit(path, GH, Status="Applied", Notes="Sent through the careers page")
    _edit(path, LEVER, **{"Next action": "Ask about Go"})

    events = len(read_jsonl(pipeline_ws.events_path))
    code, out, _ = cli(pipeline_ws, "track", "import-xlsx", "exports/tracker.xlsx")
    assert code == 0 and "planned -> applied" in out
    assert len(read_jsonl(pipeline_ws.events_path)) == events + 1
    last = StatusLog(pipeline_ws).history(GH)[-1]
    assert (last.status, last.source) == (AppStatus.applied, "xlsx")
    assert NotesLog(pipeline_ws).get(GH).notes == "Sent through the careers page"
    assert NotesLog(pipeline_ws).get(LEVER).next_action == "Ask about Go"

    sizes = (len(read_jsonl(pipeline_ws.events_path)), len(read_jsonl(notes_path(pipeline_ws))))
    queue = pipeline_ws.queue_path.read_text(encoding="utf-8")
    code, out, _ = cli(pipeline_ws, "track", "import-xlsx", str(path))
    assert code == 0 and "nothing new" in out
    assert sizes == (
        len(read_jsonl(pipeline_ws.events_path)),
        len(read_jsonl(notes_path(pipeline_ws))),
    )
    assert pipeline_ws.queue_path.read_text(encoding="utf-8") == queue

    assert cli(pipeline_ws, "report")[0] == 0
    book = load_workbook(path)
    tracker = book["Tracker"]
    headers = _headers(tracker)
    row = _row_for(tracker, GH)
    assert tracker.cell(row=row, column=headers.index("Status") + 1).value == "applied"
    notes = tracker.cell(row=row, column=headers.index("Notes") + 1).value
    assert notes == "Sent through the careers page"
    assert read_tracker_edits(path) == []


def test_rewrite_keeps_unimported_edits(pipeline_ws: Workspace, cli: Cli) -> None:
    path = build_tracker_xlsx(pipeline_ws, pipeline_ws.exports_dir / "tracker.xlsx").path
    _edit(path, GH, Status="withdrawn", Notes="Not for me")
    code, out, _ = cli(pipeline_ws, "report")
    assert code == 0 and "Kept 2 edit(s)" in out
    edits = read_tracker_edits(path)
    assert [(e.key, e.status, e.notes) for e in edits] == [(GH, "withdrawn", "Not for me")]
    assert StatusLog(pipeline_ws).current(GH) == AppStatus.planned
    assert cli(pipeline_ws, "track", "import-xlsx", str(path))[0] == 0
    assert StatusLog(pipeline_ws).current(GH) == AppStatus.withdrawn


def test_untouched_rows_in_an_old_copy_change_nothing(pipeline_ws: Workspace, cli: Cli) -> None:
    path = build_tracker_xlsx(pipeline_ws, pipeline_ws.exports_dir / "tracker.xlsx").path
    assert cli(pipeline_ws, "track", "set", GH, "interviewing")[0] == 0
    assert cli(pipeline_ws, "track", "import-xlsx", str(path))[0] == 0  # still says "planned"
    assert StatusLog(pipeline_ws).current(GH) == AppStatus.interviewing


def test_unknown_status_reported_not_recorded(pipeline_ws: Workspace, cli: Cli) -> None:
    path = build_tracker_xlsx(pipeline_ws, pipeline_ws.exports_dir / "tracker.xlsx").path
    _edit(path, GH, Status="interviewd")
    events = len(read_jsonl(pipeline_ws.events_path))
    code, out, _ = cli(pipeline_ws, "--json", "track", "import-xlsx", str(path))
    data = json.loads(out)
    assert code == 0 and data["written"] == 0
    assert data["unknown_status"] == [{"key": GH, "row": 4, "value": "interviewd"}]
    assert len(read_jsonl(pipeline_ws.events_path)) == events


def test_columns_found_by_header_name(pipeline_ws: Workspace) -> None:
    path = build_tracker_xlsx(pipeline_ws, pipeline_ws.exports_dir / "tracker.xlsx").path
    book = load_workbook(path)
    sheet = book["Tracker"]
    sheet.insert_cols(1)  # someone adds a column in front of Key
    sheet.cell(row=1, column=1).value = "My column"
    headers = _headers(sheet)
    row = _row_for_col(sheet, GH, headers.index("Key") + 1)
    sheet.cell(row=row, column=headers.index("Status") + 1).value = "rejected"
    book.save(path)
    edits = read_tracker_edits(path)
    assert [(e.key, e.status) for e in edits] == [(GH, "rejected")]


def _row_for_col(sheet: Any, key: str, col: int) -> int:
    for row in range(2, sheet.max_row + 1):
        if sheet.cell(row=row, column=col).value == key:
            return int(row)
    raise AssertionError(key)


def test_text_never_becomes_a_formula_and_long_jd_is_capped(pipeline_ws: Workspace) -> None:
    store = JobStore(pipeline_ws)
    job = store.get(GH)
    assert job is not None
    job.title = "=HYPERLINK(1)"
    store.upsert([job], "2026-11-27T12:00:00Z")
    pipeline_ws.jd_path(GH).write_text("word \x07" * 20_000, encoding="utf-8")
    NotesLog(pipeline_ws).set(GH, "notes", "=1+1", "xlsx")
    path = build_tracker_xlsx(pipeline_ws, pipeline_ws.exports_dir / "tracker.xlsx").path
    book = load_workbook(path)
    tracker = book["Tracker"]
    row = _row_for(tracker, GH)
    assert tracker.cell(row=row, column=3).value == "=HYPERLINK(1)"
    assert tracker.cell(row=row, column=3).data_type == "s"
    jd = book["Job descriptions"]
    text = jd.cell(row=_row_for(jd, GH), column=5).value
    assert len(text) <= 32_000 and "\x07" not in text and "the whole text is in" in text
    assert read_tracker_edits(path) == []


def test_not_an_excel_file_is_friendly(pipeline_ws: Workspace, cli: Cli) -> None:
    bad = pipeline_ws.exports_dir / "tracker.xlsx"
    bad.write_text("not a workbook", encoding="utf-8")
    code, out, err = cli(pipeline_ws, "track", "import-xlsx", str(bad))
    assert code == 2 and "could not be read as an Excel file" in err
    assert "Traceback" not in out + err


def test_report_never_overwrites_an_unreadable_file(pipeline_ws: Workspace, cli: Cli) -> None:
    bad = pipeline_ws.exports_dir / "tracker.xlsx"
    bad.write_text("not a workbook", encoding="utf-8")
    code, out, err = cli(pipeline_ws, "report")
    assert code == 2 and "Move or rename" in err and "Traceback" not in out + err
    assert bad.read_text(encoding="utf-8") == "not a workbook"
