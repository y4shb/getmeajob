"""Drop-down menus: read the options, choose one through the shared matcher, close the menu.

A problem is a short sentence about the field, never the planned answer itself, so it
can be stored and shown safely. Choices always go through the shared matcher
(`plan.options.match_option`); when nothing fits, or several options fit, the menu is
closed and nothing is chosen. The first option is never taken just because it is first.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable, Sequence

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Locator, Page

from getmeajob.apply.fields import by_id, safely
from getmeajob.apply.scripts import page_script
from getmeajob.plan.options import MatchResult, match_option
from getmeajob.textutil import norm_label

Matcher = Callable[[list[str]], MatchResult]

_MENU_JS = page_script("menu")

_SELECTED_JS = page_script("selected")


def no_fit(result: MatchResult, options: Sequence[str]) -> str:
    """The problem sentence for a choice the matcher could not make."""
    shown = ", ".join(options[:4]) + (", ..." if len(options) > 4 else "")
    if result.method == "ambiguous":
        return f"more than one option fits the planned answer; not guessing ({shown})"
    if not options:
        return "no options appeared"
    return f"none of the {len(options)} options fits the planned answer ({shown})"


def read_options(page: Page, box: Locator, *, timeout: float, settle: float = 0.0) -> list[str]:
    """The visible options of the menu that belongs to `box`, once they stop changing."""
    if settle:
        page.wait_for_timeout(settle * 1000)
    deadline = time.monotonic() + timeout
    last: list[str] | None = None
    while True:
        state = box.evaluate(_MENU_JS, None)
        options = [str(o) for o in state.get("options") or [] if str(o).strip()]
        notice = str(state.get("notice") or "").casefold()
        loading = "loading" in notice
        if options and not loading:
            if options == last:
                return options
            last = options
        elif notice and not loading:
            return []  # "No options", "Type to search" and the like
        if time.monotonic() >= deadline:
            return [] if loading else options
        page.wait_for_timeout(80)


def click_option(page: Page, box: Locator, label: str) -> bool:
    """Click the option of `box`'s menu whose text is `label`; False when it is gone."""
    state = box.evaluate(_MENU_JS, label)
    if not state.get("marked"):
        return False
    page.locator('[data-getmeajob-pick="1"]').first.click()
    return True


def close_menu(page: Page, box: Locator, *, clear: bool) -> None:
    try:
        box.press("Escape")
        if clear and box.input_value():
            box.fill("")
        box.evaluate("(e) => e.blur()")
    except PlaywrightError:
        if page.is_closed():
            raise


def _selected(box: Locator) -> str:
    return str(box.evaluate(_SELECTED_JS) or "")


def sticks(page: Page, read: Callable[[], str], wanted: str, timeout: float = 1.0) -> bool:
    """Whether the field shows `wanted` within `timeout` seconds of choosing it."""
    deadline = time.monotonic() + timeout
    while norm_label(read()) != norm_label(wanted):
        if time.monotonic() >= deadline:
            return False
        page.wait_for_timeout(50)
    return True


def react_select(
    page: Page,
    input_id: str,
    desired: str,
    *,
    matcher: Matcher | None = None,
    query: str | None = None,
    kind: str = "text",
) -> str | None:
    """Choose an option in a react-select style widget.

    Opens the menu and matches the options shown. When nothing fits, types `query`
    (default: the answer, first 30 characters), waits for the list to settle (some load
    late) and matches again. Clicks only the matched option, then checks it stuck.
    """
    pick_fn: Matcher = matcher or (lambda opts: match_option(desired, opts, kind=kind))

    def act() -> str | None:
        found = by_id(page, input_id)
        if found.count() == 0:
            return "not found on the page"
        box = found.first
        control = box.locator(
            "xpath=ancestor::*[contains(concat(' ', normalize-space(@class), ' '), "
            "' select__control ')][1]"
        )
        target = control.first if control.count() else box
        target.scroll_into_view_if_needed()
        target.click()
        options = listed = read_options(page, box, timeout=1.0)
        result = pick_fn(options) if options else MatchResult(None, "none", "no options")
        typed = (query if query is not None else desired)[:30]
        if not result.ok and typed.strip():
            box.press_sequentially(typed, delay=30)
            options = read_options(page, box, timeout=5.0, settle=0.35)
            result = pick_fn(options) if options else MatchResult(None, "none", "no options")
        if result.option is None:
            close_menu(page, box, clear=True)
            return no_fit(result, options or listed)
        if not click_option(page, box, result.option):
            close_menu(page, box, clear=True)
            return "the matched option disappeared before it could be chosen"
        if not sticks(page, lambda: _selected(box), result.option):
            return "the choice did not stick"
        return None

    return safely(page, act)


def native_select(
    page: Page, box: Locator, desired: str, matcher: Matcher | None = None
) -> str | None:
    """Choose in a plain <select> by matching its option texts."""
    options = [o.strip() for o in box.locator("option").all_inner_texts() if o.strip()]
    options = [o for o in options if not re.match(r"^(select|choose|please select)\b", o, re.I)]
    result = matcher(options) if matcher else match_option(desired, options)
    if result.option is None:
        return no_fit(result, options)
    box.select_option(label=result.option)
    return None
