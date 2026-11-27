"""Filling the mock Ashby form in headless Chromium."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from getmeajob.plan.plans import load_plan
from getmeajob.plan.profile import load_profile
from getmeajob.workspace import Workspace

pytestmark = pytest.mark.browser
pytest.importorskip("playwright.sync_api")

ASHBY = "ashby:samplesystems:5a1e0000-0000-4000-8000-000000000001"
A = "c0ffee00-0000-4000-8000-0000000000a"


def test_dry_fills_booleans_choices_location_number(
    ready_ws: Workspace, open_mock: Callable[..., Any]
) -> None:
    from getmeajob.apply.ashby import AshbyFiller
    from getmeajob.apply.widgets import fill_text

    plan = load_plan(ready_ws, ASHBY)
    assert plan is not None
    page = open_mock("ashby")
    filler = AshbyFiller(fast=True)
    notes = filler.prepare(page)
    report = filler.fill(page, plan, load_profile(ready_ws), ready_ws)
    assert report.problems == [] and report.filled == 8
    assert notes == ["declined optional cookies"]
    assert page.evaluate("window.__cookieChoice") == "necessary"
    assert page.evaluate("window.__submitCount") == 0
    assert page.input_value('[id="_systemfield_name"]') == "Alex Example"
    assert page.evaluate("document.getElementById('_systemfield_resume').files.length") == 1
    pressed = page.locator(f'[data-yesno="{A}2"] button[aria-pressed="true"]')
    assert pressed.inner_text() == "No"
    assert page.is_checked(f'[id="{A}5-labeled-radio-1"]')  # Hybrid
    assert not page.is_checked(f'[id="{A}5-labeled-radio-0"]')
    assert page.input_value(f'[id="{A}3"]') == "Springfield, Ontario, Canada"
    assert page.input_value(f'[id="{A}4"]') == "4"
    assert page.input_value(f'[id="{A}6"]') == ""  # skipped in the plan, left alone

    # A number field gets bare digits, whatever words came with the answer.
    assert fill_text(page, f'[id="{A}4"]', "4 years") is None
    assert page.input_value(f'[id="{A}4"]') == "4"
    assert (
        fill_text(page, f'[id="{A}4"]', "several")
        == "needs a number and the planned answer has none"
    )


def test_ashby_choice_and_boolean_refuse_to_guess(open_mock: Callable[..., Any]) -> None:
    from getmeajob.apply.widgets import ashby_boolean, ashby_choice

    page = open_mock("ashby")
    assert ashby_choice(page, f"{A}5", "Part-time") is not None
    assert page.locator(f'input[name="{A}5"]:checked').count() == 0
    assert ashby_boolean(page, f"{A}2", "Maybe") is not None
    assert page.locator(f'[data-yesno="{A}2"] button[aria-pressed="true"]').count() == 0
