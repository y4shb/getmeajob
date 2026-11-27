"""Greenhouse employment and education sections, filled row by row.

Each section has its own "Add another" button. The button is looked up inside the
section that holds the first row, never as the first such button on the page (that
one may belong to the other section). A field that is missing from the page is left
alone; a field that is there but cannot be filled is a problem when it is required and
a note when it is optional.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field

from playwright.sync_api import Locator, Page

from getmeajob.apply.fields import by_id, click, fill_text, safely
from getmeajob.apply.menus import react_select
from getmeajob.apply.values import EducationRow, EmploymentRow, match_degree
from getmeajob.apply.widgets import choose
from getmeajob.plan.options import MatchResult, match_option

ANCHORS = {"education": "school--{i}", "employment": "company-name-{i}"}
ADD_ANOTHER = re.compile(r"add another", re.I)


@dataclass(slots=True)
class SectionResult:
    filled: int = 0
    problems: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def note(self, page: Page, field_id: str, problem: str | None) -> None:
        if problem is None:
            self.filled += 1
            return
        line = f"{field_id}: {problem}"
        if _required(by_id(page, field_id)):
            self.problems.append(line)
        else:
            self.notes.append(line)


def _required(box: Locator) -> bool:
    if box.count() == 0:
        return False
    first = box.first
    return (
        first.get_attribute("aria-required") == "true"
        or first.get_attribute("required") is not None
    )


def _exists(page: Page, field_id: str) -> bool:
    return by_id(page, field_id).count() > 0


def _ensure_row(page: Page, section: str, i: int) -> bool:
    """Make sure row `i` exists, clicking this section's own "Add another" when needed."""
    anchor = ANCHORS[section]
    if _exists(page, anchor.format(i=i)):
        return True
    first = by_id(page, anchor.format(i=0))
    holder = first.first.locator(
        "xpath=ancestor::*[.//button[contains(translate(normalize-space(.), 'ADNOTHER', "
        "'adnother'), 'add another')]][1]"
    )
    if holder.count() == 0:
        return False
    button = holder.first.locator("button", has_text=ADD_ANOTHER)
    if button.count() == 0 or click(button.first):
        return False
    try:
        by_id(page, anchor.format(i=i)).first.wait_for(state="attached", timeout=4000)
    except Exception:
        return False
    return True


def _first_existing(page: Page, ids: Sequence[str]) -> str | None:
    return next((i for i in ids if _exists(page, i)), None)


def _school(page: Page, i: int, row: EducationRow) -> str | None:
    field_id = f"school--{i}"
    names = [row.school, *row.school_aliases]

    def matcher(options: list[str]) -> MatchResult:
        for name in names:
            result = match_option(name, options)
            if result.ok or result.method == "ambiguous":
                return result
        return MatchResult(None, "none", "no school option fits")

    problem: str | None = "no school option fits"
    for name in names:
        problem = react_select(page, field_id, row.school, matcher=matcher, query=name)
        if problem is None:
            return None
    return problem


def _education(page: Page, i: int, row: EducationRow, result: SectionResult) -> None:
    if _exists(page, f"school--{i}"):
        result.note(page, f"school--{i}", _school(page, i, row))
    if row.degree or row.degree_level:
        degree_id = f"degree--{i}"
        if _exists(page, degree_id):
            pick = choose(page, degree_id, row.degree, matcher=lambda o: match_degree(row, o))
            result.note(page, degree_id, pick)
    if row.discipline and _exists(page, f"discipline--{i}"):
        result.note(page, f"discipline--{i}", choose(page, f"discipline--{i}", row.discipline))
    for ids, value in (
        ((f"start-year--{i}", f"start-date-year--{i}"), row.start_year),
        ((f"end-year--{i}", f"end-date-year--{i}"), row.end_year),
    ):
        target = _first_existing(page, ids)
        if target and value:
            result.note(page, target, fill_text(page, f'[id="{target}"]', value))


def _current_box(page: Page, i: int) -> Locator | None:
    for field_id in (f"current-role-{i}", f"currently-working-{i}", f"current-{i}"):
        if _exists(page, field_id):
            return by_id(page, field_id).first
    row = by_id(page, f"company-name-{i}").first.locator(
        "xpath=ancestor::*[.//input[@type='checkbox']][1]"
    )
    if row.count() == 0:
        return None
    for box in row.first.locator("input[type=checkbox]").all():
        box_id = box.get_attribute("id") or ""
        label = page.locator(f'label[for="{box_id}"]') if box_id else None
        text = label.first.inner_text() if label is not None and label.count() else ""
        if re.search(r"current", text, re.I):
            return box
    return None


def _employment(page: Page, i: int, row: EmploymentRow, result: SectionResult) -> None:
    for field_id, value in ((f"company-name-{i}", row.company), (f"title-{i}", row.title)):
        if value and _exists(page, field_id):
            result.note(page, field_id, fill_text(page, f'[id="{field_id}"]', value))
    dates = [("start", row.start_month, row.start_year)]
    if row.current:
        box = _current_box(page, i)
        if box is None:
            result.notes.append(f"row {i}: no 'currently work here' box; end date left empty")
        else:
            problem = safely(page, lambda: None if box.is_checked() else box.check())
            result.note(page, box.get_attribute("id") or f"current-{i}", problem)
    else:
        dates.append(("end", row.end_month, row.end_year))
    for which, month, year in dates:
        month_id = f"{which}-date-month-{i}"
        if month and _exists(page, month_id):
            result.note(page, month_id, choose(page, month_id, month))
        year_id = f"{which}-date-year-{i}"
        if year and _exists(page, year_id):
            result.note(page, year_id, fill_text(page, f'[id="{year_id}"]', year))


def fill_section(page: Page, section: str, rows: Sequence[object]) -> SectionResult:
    """Fill `rows` (EducationRow or EmploymentRow) into the `education` or `employment`
    section. Does nothing when the page has no such section."""
    result = SectionResult()
    if section not in ANCHORS or not _exists(page, ANCHORS[section].format(i=0)):
        return result
    for i, row in enumerate(rows):
        if not _ensure_row(page, section, i):
            result.notes.append(f"{section}: only {i} row(s) fit on this form")
            break
        if section == "education" and isinstance(row, EducationRow):
            _education(page, i, row, result)
        elif section == "employment" and isinstance(row, EmploymentRow):
            _employment(page, i, row, result)
    return result
