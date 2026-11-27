"""Small openpyxl helpers: safe cells, header style, widths, links and filters.

Kept to features that Excel, LibreOffice and Numbers all open without a repair prompt:
plain and inline strings, real dates, hyperlinks under 2,000 characters, list
validation under 255 characters and formula-based conditional fills.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any

from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

CELL_MAX = 32_000  # Excel refuses more than 32,767 characters in a cell
LINK_MAX = 2_000  # Excel breaks on longer hyperlink targets
HEADER_FILL = PatternFill(start_color="1F3A5F", end_color="1F3A5F", fill_type="solid")
HEADER_FONT = Font(bold=True, color="FFFFFF")
LINK_FONT = Font(color="0563C1", underline="single")
MUTED_FONT = Font(color="666666")
BOLD = Font(bold=True)
WRAP = Alignment(wrap_text=True, vertical="top")
TOP = Alignment(vertical="top")
_ILLEGAL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def fill(color: str) -> PatternFill:
    return PatternFill(start_color=color, end_color=color, fill_type="solid")


def clean_text(value: str, limit: int = CELL_MAX) -> str:
    """Text a spreadsheet cell can hold: no control characters, at most `limit` chars."""
    text = _ILLEGAL.sub("", value)
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return text


def as_day(text: str) -> date | str:
    """A real date for `YYYY-MM-DD` text (so the column sorts as dates), else the text."""
    if _DAY.match(text):
        try:
            return date.fromisoformat(text)
        except ValueError:
            return text
    return text


def put(sheet: Any, row: int, col: int, value: Any) -> Any:
    """Write one cell. Text always stays text (a leading "=" never becomes a formula),
    dates get a `yyyy-mm-dd` format, booleans become yes/no."""
    cell = sheet.cell(row=row, column=col)
    if value is None or value == "":
        return cell
    if isinstance(value, bool):
        cell.value = "yes" if value else "no"
    elif isinstance(value, int | float):
        cell.value = value
    elif isinstance(value, date):
        cell.value = value
        cell.number_format = "yyyy-mm-dd"
    else:
        cell.value = clean_text(str(value))
        cell.data_type = "s"
    return cell


def put_formula(sheet: Any, row: int, col: int, formula: str) -> Any:
    cell = sheet.cell(row=row, column=col)
    cell.value = formula
    return cell


def link(cell: Any, target: str) -> None:
    """Make a cell a real hyperlink (web address or relative file path)."""
    if not target or len(target) > LINK_MAX:
        return
    cell.hyperlink = target
    cell.font = LINK_FONT


def header_row(sheet: Any, headers: Sequence[str], row: int = 1) -> None:
    for col, name in enumerate(headers, start=1):
        cell = put(sheet, row, col, name)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(wrap_text=True, vertical="center")
    sheet.row_dimensions[row].height = 30


def widths(sheet: Any, headers: Sequence[str], sizes: Mapping[str, float]) -> None:
    for col, name in enumerate(headers, start=1):
        sheet.column_dimensions[get_column_letter(col)].width = sizes.get(name, 14)


def wrap_columns(sheet: Any, headers: Sequence[str], names: Sequence[str], last_row: int) -> None:
    for col, name in enumerate(headers, start=1):
        style = WRAP if name in names else TOP
        for row in range(2, last_row + 1):
            sheet.cell(row=row, column=col).alignment = style


def finish_data_sheet(sheet: Any, headers: Sequence[str], last_row: int, freeze: str) -> None:
    """Frozen header and an autofilter over every column (hidden ones too, so sorting
    keeps each row together)."""
    sheet.freeze_panes = freeze
    last_col = get_column_letter(len(headers))
    sheet.auto_filter.ref = f"A1:{last_col}{max(1, last_row)}"


def column_letter(headers: Sequence[str], name: str) -> str:
    return str(get_column_letter(list(headers).index(name) + 1))


def table_sheet(
    sheet: Any,
    headers: Sequence[str],
    rows: Sequence[Mapping[str, Any]],
    sizes: Mapping[str, float],
    *,
    wrap: Sequence[str] = (),
    links: Sequence[str] = (),
    days: Sequence[str] = (),
) -> int:
    """A simple data sheet: header, one row per mapping, links, widths, filter, freeze.
    Returns the last row number."""
    header_row(sheet, headers)
    for r, values in enumerate(rows, start=2):
        for c, name in enumerate(headers, start=1):
            value = values.get(name)
            if name in days and isinstance(value, str):
                value = as_day(value)
            cell = put(sheet, r, c, value)
            if name in links:
                link(cell, str(values.get(name) or ""))
    last = len(rows) + 1
    widths(sheet, headers, sizes)
    wrap_columns(sheet, headers, wrap, last)
    finish_data_sheet(sheet, headers, last, "A2")
    return last
