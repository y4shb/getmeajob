"""The simplest field drivers: find a field by id, type text, attach a file.

Every driver returns a problem sentence or None. `safely` turns a browser error into a
problem, except when the page is gone, which is raised so the run can record it.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Locator, Page

from getmeajob.apply.values import coerce_date, coerce_number


def by_id(page: Page, field_id: str) -> Locator:
    """The element whose id is exactly `field_id` (ids may hold `[]` and dashes)."""
    return page.locator(f'[id="{quote_attr(field_id)}"]')


def quote_attr(value: str) -> str:
    """`value` escaped for a double-quoted CSS attribute selector."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


def safely(page: Page, action: Callable[[], str | None]) -> str | None:
    """Run one widget action; a Playwright error becomes a problem, unless the page is gone
    (then it is raised, so the run records a closed window instead of a fill problem)."""
    try:
        return action()
    except PlaywrightError as exc:
        if page.is_closed():
            raise
        first = str(exc).strip().splitlines()[0] if str(exc).strip() else type(exc).__name__
        return f"the browser could not use this field ({first[:120]})"


def fill_text(page: Page, selector: str, value: str, *, label: str = "") -> str | None:
    """Type a value into an input or textarea, coercing numbers and dates first."""

    def act() -> str | None:
        found = page.locator(selector)
        if found.count() == 0:
            return "not found on the page"
        box = found.first
        kind = (box.get_attribute("type") or "").casefold()
        text = str(value)
        if kind == "number":
            number = coerce_number(text, label)
            if number is None:
                return "needs a number and the planned answer has none"
            text = number
        elif kind == "date":
            day = coerce_date(text)
            if day is None:
                return "needs a date as YYYY-MM-DD"
            text = day
        box.fill(text)
        if box.input_value() != text:
            return "the field did not keep the value (too long, or reformatted)"
        return None

    return safely(page, act)


def upload_file(page: Page, selector: str, path: str | Path) -> str | None:
    """Attach a file to a file input (hidden inputs work too)."""
    file = Path(path).expanduser()
    if not file.is_file():
        return f"the file {file.name} does not exist"

    def act() -> str | None:
        found = page.locator(selector)
        if found.count() == 0:
            return "not found on the page"
        found.first.set_input_files(str(file))
        count = found.first.evaluate("(e) => (e.files ? e.files.length : 0)")
        return None if count else "the file did not attach"

    return safely(page, act)
