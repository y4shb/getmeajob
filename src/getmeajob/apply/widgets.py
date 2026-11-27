"""Field drivers built on the menus in `apply.menus`: a choice field by id, checkbox
groups, Ashby choice and yes/no questions, and the location type-ahead.

Each driver fills one field and returns a problem sentence or None (see `apply.menus`
for what a problem may say and how choices are matched).
"""

from __future__ import annotations

from collections.abc import Sequence

from playwright.sync_api import Locator, Page

from getmeajob.apply.fields import by_id, click, quote_attr, safely
from getmeajob.apply.menus import (
    Matcher,
    click_option,
    close_menu,
    native_select,
    no_fit,
    react_select,
    read_options,
    sticks,
)
from getmeajob.apply.values import pick_location
from getmeajob.plan.options import match_option
from getmeajob.plan.profile import Profile
from getmeajob.textutil import norm_label


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
                    return no_fit(result, labels)
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
            return no_fit(result, texts)
        button = buttons.nth(texts.index(result.option))
        problem = click(button)
        if problem:
            return problem
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
            return no_fit(result, options) if options else "no suggestions appeared for your city"
        if not click_option(page, box, result.option):
            close_menu(page, box, clear=True)
            return "the matched suggestion disappeared before it could be chosen"
        if not sticks(page, box.input_value, result.option):
            return "the suggestion did not stick"
        return None

    return safely(page, act)
