"""`getmeajob inspect URL`: list a form's fields so a changed form can be adapted to.

Opens the page headless and reads every input, its label, whether it is required and
the options it shows. It never types and never clicks, except to open a closed
dropdown so its options can be read (and Escape to close it again).
"""

from __future__ import annotations

import contextlib
import dataclasses
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from getmeajob.apply.browser import BrowserSession, require_playwright
from getmeajob.apply.forms import form_target
from getmeajob.apply.guards import account_wall_in, captcha_in, refusal_in, scan_page
from getmeajob.apply.scripts import page_script
from getmeajob.errors import GetmeajobError
from getmeajob.settings import Settings

MAX_MENUS = 40

_FIELDS_JS = page_script("fields")


@dataclass(slots=True)
class FieldRow:
    field: str
    kind: str
    label: str
    required: bool
    options: list[str] = dataclasses.field(default_factory=list)


@dataclass(slots=True)
class Inspection:
    url: str
    fields: list[FieldRow]
    signals: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "signals": self.signals,
            "fields": [asdict(f) for f in self.fields],
        }


def _as_url(target: str) -> str:
    path = Path(target).expanduser()
    if "://" not in target and path.exists():
        return path.resolve().as_uri()
    return target


def _menu_options(page: Any, row: FieldRow) -> list[str]:
    """Open a closed dropdown, read its options, close it again. Never types."""
    from getmeajob.apply.fields import by_id
    from getmeajob.apply.menus import close_menu, read_options

    box = by_id(page, row.field)
    if not row.field or box.count() == 0:
        return []
    control = box.first.locator(
        "xpath=ancestor::*[contains(concat(' ', normalize-space(@class), ' '), "
        "' select__control ')][1]"
    )
    (control.first if control.count() else box.first).click()
    options = read_options(page, box.first, timeout=1.0)
    close_menu(page, box.first, clear=False)
    return options


def inspect_form(url: str, settings: Settings, *, timeout_ms: int = 30_000) -> Inspection:
    """Read the fields of the form at `url` (a local file path works too)."""
    api = require_playwright()
    target = form_target(_as_url(url), settings)
    local = settings.fixtures is not None
    with BrowserSession(headed=False, local_only=local) as session:
        context, page = session.new_page()
        try:
            page.goto(target, wait_until="domcontentloaded", timeout=timeout_ms)
            with contextlib.suppress(api.Error):
                page.wait_for_selector("input, textarea, select", timeout=timeout_ms)
            raw = page.evaluate(_FIELDS_JS)
            rows = [
                FieldRow(
                    field=str(r.get("field") or ""),
                    kind=str(r.get("kind") or ""),
                    label=" ".join(str(r.get("label") or "").split()).rstrip("*✱ "),
                    required=bool(r.get("required")),
                    options=[str(o) for o in r.get("options") or [] if str(o).strip()],
                )
                for r in raw
                if isinstance(r, dict)
            ]
            menus = [r for r in rows if r.kind in ("react-select", "combobox") and not r.options]
            for row in menus[:MAX_MENUS]:
                try:
                    row.options = _menu_options(page, row)
                except api.Error:
                    row.options = []
            scan = scan_page(page)
            signals = [
                f"{name}: {seen}"
                for name, seen in (
                    ("bot check", captcha_in(scan)),
                    ("account wall", account_wall_in(scan)),
                    ("asks for no automated tools", refusal_in(scan.form)),
                )
                if seen
            ]
        except api.Error as exc:
            raise GetmeajobError(
                f"Could not read the form at {url}: {str(exc).splitlines()[0]}",
                hint="Check the link in a normal browser, then try again.",
            ) from exc
        finally:
            session.close_context(context)
    return Inspection(url=url, fields=rows, signals=signals)
