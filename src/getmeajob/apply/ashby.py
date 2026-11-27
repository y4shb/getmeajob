"""Filling an Ashby application form (`jobs.ashbyhq.com/<org>/<id>/application`).

Conventions this relies on: inputs carry the question path as `id` or `name`; every
question sits in a box whose class contains `_fieldEntry`; yes/no questions are two
buttons; single choices are radio lists with `label[for]`; the location is a combobox
with `role=option` suggestions; number fields take bare digits.

Order: decline optional cookies, attach the resume first (Ashby reads it and may fill
fields from it), wait for that, then fill the rest in plan order.
"""

from __future__ import annotations

import re

from playwright.sync_api import Page

from getmeajob.apply.base import FillReport, click_submit, missing_required
from getmeajob.apply.fields import click, fill_text, quote_attr, safely, upload_file
from getmeajob.apply.widgets import ashby_boolean, ashby_choice, location_typeahead
from getmeajob.models import Plan, PlannedAnswer, QuestionType
from getmeajob.plan.answering import allowed_file
from getmeajob.plan.profile import Profile
from getmeajob.workspace import Workspace

COOKIE_CHOICE = re.compile(
    r"necessary only|only necessary|necessary cookies only|reject all|decline all|"
    r"essential only|only essential|reject (optional|non-essential)",
    re.I,
)
BANNERS = (
    '[role=dialog], [class*="cookie" i], [id*="cookie" i], [class*="consent" i], [id*="consent" i]'
)
SUBMIT = re.compile(r"^\s*submit( application)?\s*$", re.I)
TEXTLIKE = {
    QuestionType.text,
    QuestionType.textarea,
    QuestionType.email,
    QuestionType.url,
    QuestionType.phone,
    QuestionType.number,
    QuestionType.date,
    QuestionType.unknown,
}


def _sel(path: str) -> str:
    safe = quote_attr(path)
    return f'[id="{safe}"], [name="{safe}"]'


def dismiss_cookie_banner(page: Page) -> str | None:
    """Click the privacy-preserving choice of a cookie banner, if one is showing.

    Only "necessary only" style buttons inside a banner are clicked; "accept" never is.
    """

    def act() -> str | None:
        button = page.locator(BANNERS).get_by_role("button", name=COOKIE_CHOICE)
        if button.count() == 0 or not button.first.is_visible():
            return None
        return click(button.first) or "declined optional cookies"

    return safely(page, act)


class AshbyFiller:
    ats = "ashby"
    ready_selector = '[id="_systemfield_name"], [name="_systemfield_name"]'

    def __init__(self, *, fast: bool = False) -> None:
        self.fast = fast

    def prepare(self, page: Page) -> list[str]:
        note = dismiss_cookie_banner(page)
        return [note] if note else []

    def fill(self, page: Page, plan: Plan, profile: Profile, ws: Workspace) -> FillReport:
        report = FillReport()
        answers = [a for a in plan.answers if a.value not in (None, "", [])]
        files = [a for a in answers if a.type == QuestionType.file]
        for answer in files:
            path, problem = allowed_file(ws, profile, str(answer.value))
            if path:
                report.add(
                    answer.question_id,
                    answer.label,
                    upload_file(page, _sel(answer.question_id), ws.root / path),
                )
            else:
                report.add(answer.question_id, answer.label, problem)
        if files:
            page.wait_for_timeout(400 if self.fast else 2500)
        for answer in answers:
            if answer.type in (QuestionType.file, QuestionType.hidden):
                continue
            report.add(answer.question_id, answer.label, self._one(page, answer, profile))
        for field_id in missing_required(page):
            report.add(field_id, "", "required, and still empty after filling")
        return report

    def _one(self, page: Page, answer: PlannedAnswer, profile: Profile) -> str | None:
        path = answer.question_id
        value = answer.value
        if answer.type == QuestionType.education_history:
            return "Ashby education history fields are not supported; fill it in a hold run"
        if answer.type == QuestionType.multiselect:
            return ashby_choice(page, path, value if isinstance(value, list) else [str(value)])
        if isinstance(value, list):
            return "expected one answer but the plan has a list"
        text = str(value)
        if answer.type == QuestionType.boolean:
            return ashby_boolean(page, path, text)
        if answer.type == QuestionType.select:
            return ashby_choice(page, path, text)
        if answer.type == QuestionType.location:
            return location_typeahead(page, _sel(path), profile, desired=text)
        if answer.type in TEXTLIKE:
            return fill_text(page, _sel(path), text, label=answer.label)
        return ashby_choice(page, path, text)

    def submit(self, page: Page) -> None:
        click_submit(page, SUBMIT, "button[type=submit]")
