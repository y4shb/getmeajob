from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from getmeajob.errors import GetmeajobError
from getmeajob.models import Job
from getmeajob.resume.bank import Bank, parse_bank
from getmeajob.resume.doc import ResumeDoc, to_markdown
from getmeajob.resume.render import _next_victim, count_pages, render_pdf
from getmeajob.resume.tailor import tailor
from getmeajob.workspace import Workspace

from .conftest import JD_BACKEND  # noqa: TID252  (a plain constant shared by the resume tests)

MakeJob = Callable[..., Job]
LONG = (
    "Designed, built and operated the billing platform for several product teams, including "
    "the queue consumers, the retry logic, the reporting tables and the runbooks for on-call. "
)


def _big_bank(*, with_short: bool, roles: int = 4, bullets: int = 9) -> Bank:
    experience: list[dict[str, Any]] = []
    for r in range(roles):
        items = [
            {
                "id": f"r{r}b{b}",
                "text": f"{LONG}Item {r}-{b} used Python and PostgreSQL.",
                "tags": ["python"],
                **({"short": f"Short item {r}-{b} in Python."} if with_short else {}),
            }
            for b in range(bullets)
        ]
        experience.append(
            {
                "company": f"Company {r}",
                "title": "Engineer",
                "start": "2020",
                "end": "2021",
                "bullets": items,
            }
        )
    return parse_bank({"header": {"name": "Alex Example"}, "experience": experience})


@pytest.mark.browser
def test_one_page_pdf_written(demo_ws: Workspace, bank: Bank, make_job: MakeJob) -> None:
    result = tailor(demo_ws, make_job(), JD_BACKEND, bank)
    pdf = render_pdf(result.path)
    assert pdf == result.path / "resume.pdf"
    data = pdf.read_bytes()
    assert data.startswith(b"%PDF")
    assert count_pages(data) == 1
    assert "compaction" not in json.loads((result.path / "report.json").read_text("utf-8"))


@pytest.mark.browser
def test_overflow_compacts(demo_ws: Workspace, make_job: MakeJob) -> None:
    bank = _big_bank(with_short=False)
    result = tailor(demo_ws, make_job(), JD_BACKEND, bank, max_bullets_per_role=9)
    before = (result.path / "resume.md").read_text(encoding="utf-8")
    pdf = render_pdf(result.path)
    assert count_pages(pdf.read_bytes()) == 1
    report = json.loads((result.path / "report.json").read_text(encoding="utf-8"))
    dropped = report["compaction"]["dropped"]
    assert dropped
    after = (result.path / "resume.md").read_text(encoding="utf-8")
    assert len(after) < len(before)
    for entry in dropped:
        assert entry not in {b["id"] for b in report["bullets_selected"]}
    doc = ResumeDoc.from_dict(report["doc"])
    assert all(len(role.bullets) >= 2 for role in doc.experience)
    assert after == to_markdown(doc)
    # every remaining bullet is still bank text
    sentences = bank.sentences()
    assert all(b.text in sentences for role in doc.experience for b in role.bullets)


@pytest.mark.browser
def test_short_wordings_are_tried_before_dropping(demo_ws: Workspace, make_job: MakeJob) -> None:
    bank = _big_bank(with_short=True, roles=4, bullets=7)
    result = tailor(demo_ws, make_job(), JD_BACKEND, bank, max_bullets_per_role=7)
    render_pdf(result.path)
    report = json.loads((result.path / "report.json").read_text(encoding="utf-8"))
    assert report["compaction"]["used_short_wording"] is True
    assert report["compaction"]["dropped"] == []
    sentences = bank.sentences()
    doc = ResumeDoc.from_dict(report["doc"])
    assert all(b.text in sentences for role in doc.experience for b in role.bullets)


@pytest.mark.browser
def test_cannot_fit_gives_a_clear_error(demo_ws: Workspace, make_job: MakeJob) -> None:
    bank = _big_bank(with_short=False, roles=14, bullets=2)
    result = tailor(demo_ws, make_job(), JD_BACKEND, bank, max_bullets_per_role=2)
    with pytest.raises(GetmeajobError) as err:
        render_pdf(result.path)
    assert "one page" in err.value.message
    assert err.value.hint
    assert not (result.path / "resume.pdf").exists()
    pdf = render_pdf(result.path, one_page=False)
    assert count_pages(pdf.read_bytes()) > 1


def test_victims_are_lowest_scoring_and_keep_two_per_role() -> None:
    doc = _doc_with_scores([[3.0, 1.0, 2.0], [0.5, 0.5]])
    assert _next_victim(doc, set()) == "r0b1"
    assert _next_victim(doc, {"r0b1"}) is None  # both roles are down to two bullets


def test_ties_drop_later_bullets_in_later_roles_first() -> None:
    doc = _doc_with_scores([[1.0, 1.0, 1.0], [1.0, 1.0, 1.0]])
    assert _next_victim(doc, set()) == "r1b2"


def test_count_pages() -> None:
    assert count_pages(b"/Type /Pages /Type /Page /Type /Page") == 2
    assert count_pages(b"") == 0


def _doc_with_scores(scores: list[list[float]]) -> ResumeDoc:
    from getmeajob.resume.doc import DocBullet, DocRole

    return ResumeDoc(
        name="A",
        experience=[
            DocRole(
                heading="E",
                bullets=[DocBullet(id=f"r{r}b{b}", text="t", score=s) for b, s in enumerate(row)],
            )
            for r, row in enumerate(scores)
        ],
    )


def test_missing_role_folder_is_a_friendly_error(tmp_path: Path) -> None:
    pytest.importorskip("playwright")
    with pytest.raises(GetmeajobError) as err:
        render_pdf(tmp_path)
    assert "resume tailor" in (err.value.hint or "")
