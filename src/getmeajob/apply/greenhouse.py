"""Filling a Greenhouse application form (the `job-boards.greenhouse.io/embed/job_app` page).

Conventions this relies on: element ids equal the question names from the board API;
choices are react-select widgets (`.select__control`, `input.select__input`,
`.select__menu .select__option`); multi-select checkboxes have ids `<name>_<option id>`;
`#country` sets the phone's dial code; `#candidate-location` is a type-ahead.

Order: country first (changing it resets the phone number), then the plan's answers,
then employment rows from the profile, then education, then the city last.
"""

from __future__ import annotations

import re

from playwright.sync_api import Page

from getmeajob.apply.base import FillReport, click_submit, missing_required, schema_options
from getmeajob.apply.values import dial_code, education_rows, employment_rows, local_phone
from getmeajob.apply.widgets import (
    Matcher,
    ashby_choice,
    by_id,
    check_multi,
    choose,
    fill_repeater,
    fill_text,
    location_typeahead,
    quote_attr,
    react_select,
    upload_file,
)
from getmeajob.models import Plan, PlannedAnswer, QuestionType
from getmeajob.plan.options import MatchResult, match_option
from getmeajob.plan.profile import Profile
from getmeajob.workspace import Workspace

LAST = (QuestionType.location, QuestionType.education_history)
TEXTLIKE = {
    QuestionType.text,
    QuestionType.textarea,
    QuestionType.email,
    QuestionType.url,
    QuestionType.number,
    QuestionType.date,
    QuestionType.phone,
    QuestionType.unknown,
}
SUBMIT = re.compile(r"^\s*(submit application|submit)\s*$", re.I)


def _sel(field_id: str) -> str:
    return f'[id="{quote_attr(field_id)}"]'


def _country_matcher(country: str, profile: Profile) -> Matcher:
    code = (profile.text("contact.phone_country_code") or "").strip()

    def matcher(options: list[str]) -> MatchResult:
        result = match_option(country, options)
        if result.option and code and dial_code(result.option) not in (None, code):
            return MatchResult(None, "none", "the country option has another dial code")
        return result

    return matcher


class GreenhouseFiller:
    ats = "greenhouse"
    ready_selector = '[id="first_name"]'

    def __init__(self, *, fast: bool = False) -> None:
        self.fast = fast

    def prepare(self, page: Page) -> list[str]:
        return []

    def fill(self, page: Page, plan: Plan, profile: Profile, ws: Workspace) -> FillReport:
        report = FillReport()
        has_country = by_id(page, "country").count() > 0
        if has_country:
            country = profile.text("location.country")
            if country:
                matcher = _country_matcher(country, profile)
                problem = choose(page, "country", country, matcher=matcher)
                report.add("country", "Country", problem)
            else:
                report.add("country", "Country", "your profile has no location.country")
        options = schema_options(ws, plan.job_key)
        answers = [a for a in plan.answers if a.value not in (None, "", [])]
        for answer in answers:
            if answer.type in LAST or answer.type == QuestionType.hidden:
                continue
            problem = self._one(page, answer, profile, options, has_country)
            report.add(answer.question_id, answer.label, problem)
        report.merge(fill_repeater(page, "employment", employment_rows(profile)))
        for answer in answers:
            if answer.type == QuestionType.education_history:
                rows = education_rows(answer.value, profile)
                report.merge(fill_repeater(page, "education", rows))
        for answer in answers:
            if answer.type == QuestionType.location:
                problem = location_typeahead(
                    page, _sel(answer.question_id), profile, desired=str(answer.value)
                )
                report.add(answer.question_id, answer.label, problem)
        for field_id in missing_required(page):
            report.add(field_id, "", "required, and still empty after filling")
        return report

    def _one(
        self,
        page: Page,
        answer: PlannedAnswer,
        profile: Profile,
        options: dict[str, list[tuple[str, str]]],
        has_country: bool,
    ) -> str | None:
        qid = answer.question_id
        value = answer.value
        if answer.type == QuestionType.file:
            return upload_file(page, _sel(qid), str(value))
        if answer.type == QuestionType.multiselect:
            return self._multi(page, qid, value, options.get(qid, []))
        if isinstance(value, list):
            return "expected one answer but the plan has a list"
        text = str(value)
        if answer.type == QuestionType.phone and has_country:
            text = local_phone(text, profile)
        box = by_id(page, qid)
        if box.count() == 0:
            return "not found on the page"
        if "select__input" in (box.first.get_attribute("class") or ""):
            return react_select(page, qid, text)
        if answer.type in TEXTLIKE:
            return fill_text(page, _sel(qid), text, label=answer.label)
        return choose(page, qid, text)

    def _multi(
        self,
        page: Page,
        qid: str,
        value: str | list[str] | None,
        pairs: list[tuple[str, str]],
    ) -> str | None:
        wanted = value if isinstance(value, list) else [str(value)]
        labels = [label for label, _ in pairs]
        ids: list[str] = []
        for item in wanted:
            result = match_option(item, labels) if labels else MatchResult(None, "none", "")
            if result.option is None:
                ids = []
                break
            ids.append(dict(pairs)[result.option])
        if ids and all(by_id(page, f"{qid}_{i}").count() for i in ids):
            return check_multi(page, qid, ids)
        return ashby_choice(page, qid, list(wanted))

    def submit(self, page: Page) -> None:
        click_submit(page, SUBMIT, "button[type=submit], input[type=submit]")
