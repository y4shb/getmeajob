"""Form widget drivers: each fills one kind of field and returns a problem or None.

A problem is a short sentence about the field, never the planned answer itself, so it
can be stored and shown safely. Choices always go through the shared matcher
(`plan.options.match_option`); when nothing fits, or several options fit, the menu is
closed and nothing is chosen. The first option is never taken just because it is first.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Locator, Page

from getmeajob.apply.fields import by_id, fill_text, quote_attr, safely, upload_file
from getmeajob.apply.scripts import page_script
from getmeajob.apply.values import pick_location
from getmeajob.plan.options import MatchResult, match_option
from getmeajob.plan.profile import Profile
from getmeajob.textutil import norm_label

if TYPE_CHECKING:
    from getmeajob.apply.repeater import SectionResult

Matcher = Callable[[list[str]], MatchResult]
__all__ = [
    "Matcher",
    "ashby_boolean",
    "ashby_choice",
    "by_id",
    "check_multi",
    "choose",
    "close_menu",
    "field_box",
    "fill_repeater",
    "fill_text",
    "location_typeahead",
    "native_select",
    "react_select",
    "read_options",
    "safely",
    "upload_file",
]

_MENU_JS = page_script("menu")

_SELECTED_JS = page_script("selected")


def _no_fit(result: MatchResult, options: Sequence[str]) -> str:
    shown = ", ".join(options[:4]) + (", ..." if len(options) > 4 else "")
    if result.method == "ambiguous":
        return f"more than one option fits the planned answer; not guessing ({shown})"
    if not options:
        return "no options appeared"
    return f"none of the {len(options)} options fits the planned answer ({shown})"


# --------------------------------------------------------------- menus, choices


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


def _click_option(page: Page, box: Locator, label: str) -> bool:
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


def _sticks(page: Page, read: Callable[[], str], wanted: str, timeout: float = 1.0) -> bool:
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
            return _no_fit(result, options or listed)
        if not _click_option(page, box, result.option):
            close_menu(page, box, clear=True)
            return "the matched option disappeared before it could be chosen"
        if not _sticks(page, lambda: _selected(box), result.option):
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
        return _no_fit(result, options)
    box.select_option(label=result.option)
    return None


def choose(
    page: Page,
    field_id: str,
    desired: str,
    *,
    matcher: Matcher | None = None,
    query: str | None = None,
) -> str | None:
    """Fill a choice field by id, whatever it is: react-select, <select> or radio list."""
    found = by_id(page, field_id)
    if found.count():
        tag = str(found.first.evaluate("(e) => e.tagName.toLowerCase()"))
        if tag == "select":
            return safely(page, lambda: native_select(page, found.first, desired, matcher))
        return react_select(page, field_id, desired, matcher=matcher, query=query)
    return ashby_choice(page, field_id, desired)


def check_multi(page: Page, name: str, option_ids: Sequence[str]) -> str | None:
    """Tick the checkboxes `<name>_<option id>` (Greenhouse multi-selects)."""
    problems: list[str] = []
    for option_id in option_ids:

        def act(option_id: str = option_id) -> str | None:
            box = by_id(page, f"{name}_{option_id}")
            if box.count() == 0:
                return f"checkbox {option_id} not found"
            if not box.first.is_checked():
                label = page.locator(f'label[for="{quote_attr(name)}_{quote_attr(option_id)}"]')
                if box.first.is_visible():
                    box.first.check()
                elif label.count():
                    label.first.click()
            return None if box.first.is_checked() else f"checkbox {option_id} did not tick"

        problem = safely(page, act)
        if problem:
            problems.append(problem)
    return "; ".join(problems) or None


# ------------------------------------------------------------------------ Ashby


def field_box(page: Page, path: str) -> Locator:
    """The field container (class with `_fieldEntry`) of an Ashby question."""
    anchor = page.locator(
        f'[name="{quote_attr(path)}"], [id="{quote_attr(path)}"], label[for="{quote_attr(path)}"]'
    )
    return anchor.first.locator(
        "xpath=ancestor::*[contains(@class, '_fieldEntry') or contains(@class, 'fieldEntry')"
        " or contains(@class, '_field_')][1]"
    )


def _label_texts(page: Page, inputs: Locator) -> list[str]:
    texts: list[str] = []
    for i in range(inputs.count()):
        item = inputs.nth(i)
        item_id = item.get_attribute("id") or ""
        label = page.locator(f'label[for="{quote_attr(item_id)}"]') if item_id else None
        if label is not None and label.count():
            texts.append(" ".join(label.first.inner_text().split()))
        else:
            texts.append(item.get_attribute("value") or "")
    return texts


def ashby_choice(page: Page, path: str, desired: str | list[str]) -> str | None:
    """Pick one or more options in an Ashby choice question: a radio or checkbox list with
    `label[for]`, else a combobox, else a plain select."""
    wanted = desired if isinstance(desired, list) else [desired]

    def act() -> str | None:
        name = quote_attr(path)
        inputs = page.locator(
            f'input[type=radio][name="{name}"], input[type=checkbox][name="{name}"]'
        )
        if inputs.count() == 0:
            inputs = page.locator(
                f'input[type=radio][name$="{name}"], input[type=checkbox][name$="{name}"]'
            )
        if inputs.count():
            labels = _label_texts(page, inputs)
            for value in wanted:
                result = match_option(value, labels)
                if result.option is None:
                    return _no_fit(result, labels)
                index = labels.index(result.option)
                item = inputs.nth(index)
                item_id = item.get_attribute("id") or ""
                label = page.locator(f'label[for="{quote_attr(item_id)}"]')
                (label.first if label.count() else item).click()
                if not item.is_checked():
                    return "the choice did not stick"
            return None
        box = field_box(page, path)
        if box.count() == 0:
            return "not found on the page"
        combo = box.locator("[role=combobox]")
        if combo.count():
            combo_id = combo.first.get_attribute("id") or ""
            if combo_id and len(wanted) == 1:
                return react_select(page, combo_id, wanted[0])
        select = box.locator("select")
        if select.count() and len(wanted) == 1:
            return native_select(page, select.first, wanted[0])
        return "no choices found in this field"

    return safely(page, act)


def ashby_boolean(page: Page, path: str, desired: str | bool) -> str | None:
    """Click the Yes or No button of an Ashby yes/no question."""
    if isinstance(desired, str):
        word = norm_label(desired)
        want: bool | str = (
            True if word in {"yes", "true"} else False if word in {"no", "false"} else desired
        )
    else:
        want = desired

    def act() -> str | None:
        box = field_box(page, path)
        if box.count() == 0:
            return "not found on the page"
        buttons = box.first.locator("button")
        texts = [" ".join(t.split()) for t in buttons.all_inner_texts()]
        if not texts:
            return ashby_choice(
                page, path, "Yes" if want is True else "No" if want is False else str(want)
            )
        result = match_option(want, texts)
        if result.option is None:
            return _no_fit(result, texts)
        button = buttons.nth(texts.index(result.option))
        button.click()
        pressed = button.get_attribute("aria-pressed")
        return None if pressed in (None, "true") else "the button did not stay pressed"

    return safely(page, act)


# -------------------------------------------------------------------- location


def location_typeahead(
    page: Page, selector: str, profile: Profile, desired: str | None = None
) -> str | None:
    """Type the city and pick the one suggestion that is the candidate's city and region.

    Leaves the field empty and reports a problem when no suggestion fits, or several do.
    """
    city = profile.text("location.city")
    if not city:
        return "your profile has no location.city"

    def act() -> str | None:
        found = page.locator(selector)
        if found.count() == 0:
            return "not found on the page"
        box = found.first
        input_id = box.get_attribute("id") or ""
        if "select__input" in (box.get_attribute("class") or "") and input_id:
            return react_select(
                page,
                input_id,
                desired or city,
                matcher=lambda opts: pick_location(opts, profile, desired),
                query=city,
            )
        box.scroll_into_view_if_needed()
        box.click()
        box.fill("")
        box.press_sequentially(city, delay=40)
        options = read_options(page, box, timeout=6.0, settle=0.35)
        result = pick_location(options, profile, desired)
        if result.option is None:
            close_menu(page, box, clear=True)
            return _no_fit(result, options) if options else "no suggestions appeared for your city"
        if not _click_option(page, box, result.option):
            close_menu(page, box, clear=True)
            return "the matched suggestion disappeared before it could be chosen"
        if not _sticks(page, box.input_value, result.option):
            return "the suggestion did not stick"
        return None

    return safely(page, act)


def fill_repeater(page: Page, section: str, rows: Sequence[object]) -> SectionResult:
    """Fill an employment or education section row by row (see `apply.repeater`)."""
    from getmeajob.apply.repeater import fill_section

    return fill_section(page, section, rows)
