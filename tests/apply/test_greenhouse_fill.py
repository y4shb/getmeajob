"""Filling the mock Greenhouse form in headless Chromium."""

from __future__ import annotations

import copy
from collections.abc import Callable
from typing import Any

import pytest

from getmeajob.demo import examples_dir
from getmeajob.models import ApplyMode, ApplyStatus
from getmeajob.plan.profile import Profile
from getmeajob.workspace import Workspace
from getmeajob.yamlio import load_yaml

pytestmark = pytest.mark.browser
pytest.importorskip("playwright.sync_api")

GH = "greenhouse:examplecorp:1001"
LOCATION = "Springfield, Ontario, Canada"

_STATE_JS = """
() => {
  const v = (id) => document.getElementById(id) ? document.getElementById(id).value : null;
  const chosen = (id) => {
    const box = document.querySelector('.select__container[data-id="' + id + '"]');
    const sv = box ? box.querySelector('.select__single-value') : null;
    return sv && !sv.hidden ? sv.textContent : '';
  };
  return {
    submits: window.__submitCount,
    thanks: document.body.innerText.includes('Thank you for applying'),
    first: v('first_name'), phone: v('phone'), essay: v('question_2005'),
    resume: document.getElementById('resume').files.length,
    country: chosen('country'), years: chosen('question_2004'), city: chosen('candidate-location'),
    school: chosen('school--0'), degree: chosen('degree--0'), gender: chosen('demographic_4001'),
    company1: v('company-name-1'), current0: document.getElementById('current-role-0').checked,
    end1: chosen('end-date-month-1'), python: document.getElementById('question_2006[]_11').checked,
  };
}
"""


_CHOSEN_JS = """
(id) => {
  const box = document.querySelector('.select__container[data-id="' + id + '"]');
  const sv = box ? box.querySelector('.select__single-value') : null;
  return sv && !sv.hidden ? sv.textContent : '';
}
"""


def _chosen(page: Any, field_id: str) -> str:
    return str(page.evaluate(_CHOSEN_JS, field_id))


@pytest.fixture
def profile() -> Profile:
    return Profile(data=load_yaml(examples_dir() / "demo" / "profile.yaml"))


def test_dry_fills_all_and_never_submits(
    ready_ws: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    from getmeajob.apply.greenhouse import GreenhouseFiller
    from getmeajob.apply.runner import run_apply

    state: dict[str, Any] = {}
    real_fill = GreenhouseFiller.fill

    def fill_and_look(self: GreenhouseFiller, page: Any, *args: Any) -> Any:
        report = real_fill(self, page, *args)
        state.update(page.evaluate(_STATE_JS))
        return report

    def never(self: GreenhouseFiller, page: Any) -> None:
        raise AssertionError("a dry run clicked Submit")

    monkeypatch.setattr(GreenhouseFiller, "fill", fill_and_look)
    monkeypatch.setattr(GreenhouseFiller, "submit", never)
    entries = run_apply(
        ready_ws,
        [GH],
        mode=ApplyMode.dry,
        headed=False,
        click_submit=False,
        hold_timeout=900,
        limit=None,
    )
    assert [e.status for e in entries] == [ApplyStatus.dry_ok], entries[0].problems
    assert state["submits"] == 0 and not state["thanks"]
    assert state["first"] == "Alex" and state["phone"] == "5550100" and state["resume"] == 1
    assert state["essay"].startswith("I like building")
    assert (state["country"], state["years"], state["city"]) == ("Canada +1", "3-5", LOCATION)
    assert (state["school"], state["degree"]) == ("Example State University", "Bachelor's Degree")
    assert state["gender"] == "Decline to self-identify"
    assert (
        state["company1"] == "Globex Example Inc"
        and state["current0"]
        and state["end1"] == "August"
    )
    assert state["python"] is False  # an optional question the plan skipped stays untouched
    shot = ready_ws.root / (entries[0].screenshot or "")
    assert shot.name == "dry-greenhouse__examplecorp__1001-dry_ok.png" and shot.is_file()
    assert len(ready_ws.ledger_path.read_text(encoding="utf-8").splitlines()) == 1


def test_react_select_no_match_is_problem(open_mock: Callable[..., Any]) -> None:
    from getmeajob.apply.widgets import react_select

    page = open_mock("greenhouse")
    problem = react_select(page, "question_2004", "Fifteen")
    assert problem and "fits the planned answer" in problem and "Fifteen" not in problem
    ambiguous = react_select(page, "demographic_4003", "veteran")
    assert ambiguous and "not guessing" in ambiguous
    assert react_select(page, "question_9999", "Yes") == "not found on the page"
    assert _chosen(page, "question_2004") == "" and _chosen(page, "demographic_4003") == ""
    assert page.locator(".select__menu").count() == 0
    assert react_select(page, "question_2004", "4") is not None  # a bare number is not "3-5"
    assert react_select(page, "question_2004", "3-5") is None


def test_education_repeater(open_mock: Callable[..., Any], profile: Profile) -> None:
    from getmeajob.apply.values import education_rows, employment_rows
    from getmeajob.apply.widgets import fill_repeater

    page = open_mock("greenhouse")
    rows = education_rows(
        [
            "Example State University | Bachelor of Science | Computer Science | 2017-2021",
            "Sample University | Master's Degree | Mathematics | 2021-2023",
        ],
        profile,
    )
    result = fill_repeater(page, "education", rows)
    assert result.problems == [] and result.filled == 10
    assert page.locator('[id="school--1"]').count() == 1
    assert (
        page.locator('[id="company-name-1"]').count() == 0
    )  # the other section's button was not used
    assert _chosen(page, "school--1") == "Sample University"
    assert page.input_value('[id="end-year--1"]') == "2023"

    jobs = fill_repeater(page, "employment", employment_rows(profile))
    assert jobs.problems == []
    assert page.input_value('[id="company-name-1"]') == "Globex Example Inc"
    assert page.locator('[id="school--2"]').count() == 0


def test_location_typeahead_requires_match(open_mock: Callable[..., Any], profile: Profile) -> None:
    from getmeajob.apply.widgets import location_typeahead

    selector = '[id="candidate-location"]'
    page = open_mock("greenhouse")
    assert location_typeahead(page, selector, profile, desired=LOCATION) is None
    assert _chosen(page, "candidate-location") == LOCATION  # not the Illinois one listed first

    data = copy.deepcopy(profile.data)
    data["location"]["city"] = "Atlantis"
    page = open_mock("greenhouse")
    problem = location_typeahead(page, selector, Profile(data=data), desired="Atlantis")
    assert problem and _chosen(page, "candidate-location") == ""

    data = copy.deepcopy(profile.data)
    data["location"].update(state=None, country=None)
    page = open_mock("greenhouse")
    problem = location_typeahead(page, selector, Profile(data=data))
    assert problem and "not guessing" in problem and _chosen(page, "candidate-location") == ""
