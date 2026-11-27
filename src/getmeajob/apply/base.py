"""What every board filler provides, and helpers they share.

A filler knows one board's form: which element shows the form has loaded, how to fill
a plan into it, and how to click its submit button once.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

from getmeajob.apply.scripts import page_script
from getmeajob.errors import GetmeajobError
from getmeajob.files import read_json
from getmeajob.models import Plan
from getmeajob.plan.profile import Profile
from getmeajob.textutil import truncate
from getmeajob.workspace import Workspace

if TYPE_CHECKING:
    from playwright.sync_api import Page

    from getmeajob.apply.repeater import SectionResult

_MISSING_JS = page_script("missing")


class SubmitButtonMissing(GetmeajobError):
    """The form has no submit button that getmeajob recognises."""


@dataclass(slots=True)
class FillReport:
    filled: int = 0
    problems: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def add(self, field_id: str, label: str, problem: str | None) -> None:
        """Count a filled field, or record its problem as `id (label): problem`."""
        if problem is None:
            self.filled += 1
            return
        name = f"{field_id} ({truncate(label, 40)})" if label and label != field_id else field_id
        self.problems.append(f"{name}: {problem}")

    def merge(self, section: SectionResult) -> None:
        self.filled += section.filled
        self.problems.extend(section.problems)
        self.notes.extend(section.notes)


class Filler(Protocol):
    ats: str
    ready_selector: str

    def prepare(self, page: Page) -> list[str]:
        """Steps before filling (for example declining optional cookies). Returns notes."""
        ...

    def fill(self, page: Page, plan: Plan, profile: Profile, ws: Workspace) -> FillReport: ...

    def submit(self, page: Page) -> None:
        """Click the form's submit button exactly once."""
        ...


def filler_for(ats: str, *, fast: bool = False) -> Filler:
    """The filler for a board (greenhouse or ashby)."""
    if ats == "greenhouse":
        from getmeajob.apply.greenhouse import GreenhouseFiller

        return GreenhouseFiller(fast=fast)
    if ats == "ashby":
        from getmeajob.apply.ashby import AshbyFiller

        return AshbyFiller(fast=fast)
    raise GetmeajobError(
        f"getmeajob cannot fill {ats} forms yet.",
        hint="Only Greenhouse and Ashby forms are supported. Apply to this one by hand.",
    )


def missing_required(page: Page) -> list[str]:
    """Ids of required fields that are still empty after filling."""
    raw = page.evaluate(_MISSING_JS)
    return [str(x) for x in raw] if isinstance(raw, list) else []


def schema_options(ws: Workspace, key: str) -> dict[str, list[tuple[str, str]]]:
    """Option labels and board option ids per question, from `data/schemas/<key>.json`."""
    try:
        data: Any = read_json(ws.schema_path(key), default=None)
    except GetmeajobError:
        return {}
    questions = data.get("questions") if isinstance(data, dict) else data
    out: dict[str, list[tuple[str, str]]] = {}
    for q in questions if isinstance(questions, list) else []:
        if not isinstance(q, dict) or not q.get("id"):
            continue
        pairs = [
            (str(o.get("label") or ""), str(o.get("value") or ""))
            for o in q.get("options") or []
            if isinstance(o, dict)
        ]
        out[str(q["id"])] = [(label, value) for label, value in pairs if label]
    return out
