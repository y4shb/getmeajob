from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path

import pytest

from getmeajob.errors import GetmeajobError
from getmeajob.models import Job
from getmeajob.resume.bank import Bank, parse_bank
from getmeajob.resume.doc import ResumeDoc
from getmeajob.resume.tailor import build_doc, tailor, verify_truthful
from getmeajob.workspace import Workspace
from getmeajob.yamlio import load_yaml

from .conftest import JD_BACKEND  # noqa: TID252  (a plain constant shared by the resume tests)

MakeJob = Callable[..., Job]
WORD = re.compile(r"[A-Za-z0-9+#.']+")
FIXED_WORDS = {"summary", "experience", "projects", "skills", "education", "to"}


def words(text: str) -> set[str]:
    return {w.strip(".").lower() for w in WORD.findall(text)} - {""}


def bank_words(bank: Bank) -> set[str]:
    return words(bank.search_text()) | words(
        " ".join(
            [
                bank.header.name,
                bank.header.email,
                bank.header.phone,
                bank.header.location,
                *bank.header.links,
                *(f"{r.start} {r.end}" for r in bank.experience),
                *(f"{e.start} {e.end}" for e in bank.education),
            ]
        )
    )


def test_only_bank_text_used(demo_ws: Workspace, bank: Bank, make_job: MakeJob) -> None:
    result = tailor(demo_ws, make_job(), JD_BACKEND, bank)
    markdown = (result.path / "resume.md").read_text(encoding="utf-8")
    html_text = (result.path / "resume.html").read_text(encoding="utf-8")
    html_body = re.sub(r"<style>.*?</style>", " ", html_text, flags=re.S)
    html_body = re.sub(r"<[^>]+>", " ", html_body)
    allowed = bank_words(bank) | FIXED_WORDS | {"resume", "-", "#", "##", "###"}
    allowed |= {w for label in bank.skills for w in words(label.replace("_", " "))}
    for label, text in (("md", markdown), ("html", html_body)):
        stray = words(text) - allowed - {"amp"}
        assert not stray, f"{label} has words that are not in the bank: {sorted(stray)}"
    sentences = bank.sentences()
    bullets = [line[2:] for line in markdown.splitlines() if line.startswith("- ")]
    texts = [b for b in bullets if b in sentences]
    assert len(texts) == 6  # four for the first role, two for the second
    assert markdown.split("## Summary")[1].split("##")[0].strip() in sentences


def test_gaps_never_added(demo_ws: Workspace, bank: Bank, make_job: MakeJob) -> None:
    result = tailor(demo_ws, make_job(), JD_BACKEND, bank)
    report = result.report
    for gap in ("terraform", "grpc", "rust", "ci/cd"):
        assert gap in report["gaps_not_in_bank"]
        for name in ("resume.md", "resume.html"):
            assert gap not in (result.path / name).read_text(encoding="utf-8").lower()
    assert "api" in report["unused_in_bank"] or "api" in report["matched_keywords"]
    assert not set(report["gaps_not_in_bank"]) & set(report["matched_keywords"])


def test_report_has_the_documented_keys(demo_ws: Workspace, bank: Bank, make_job: MakeJob) -> None:
    result = tailor(demo_ws, make_job(), JD_BACKEND, bank)
    report = json.loads((result.path / "report.json").read_text(encoding="utf-8"))
    for key in (
        "matched_keywords",
        "unused_in_bank",
        "gaps_not_in_bank",
        "bullets_selected",
        "bank_hash",
        "job_keys",
    ):
        assert key in report
    assert report["bank_hash"] == bank.hash
    assert report["job_keys"] == ["greenhouse:examplecorp:1001"]
    assert {b["id"] for b in report["bullets_selected"]} <= {b.id for b in bank.all_bullets()}


def test_role_folder_layout(demo_ws: Workspace, bank: Bank, make_job: MakeJob) -> None:
    result = tailor(demo_ws, make_job(), JD_BACKEND, bank)
    assert result.path == demo_ws.roles_dir / "example-corp-senior-backend-engineer"
    for name in ("jd.txt", "resume.md", "resume.html", "report.json", "meta.yaml"):
        assert (result.path / name).is_file()
    meta = load_yaml(result.path / "meta.yaml")
    assert meta["job_keys"] == ["greenhouse:examplecorp:1001"]


def test_deterministic_output(
    demo_ws: Workspace, tmp_path: Path, bank: Bank, make_job: MakeJob
) -> None:
    first = tailor(demo_ws, make_job(), JD_BACKEND, bank)
    snapshot = {p.name: p.read_bytes() for p in first.path.iterdir()}
    again = tailor(demo_ws, make_job(), JD_BACKEND, bank)
    assert {p.name: p.read_bytes() for p in again.path.iterdir()} == snapshot
    other = Workspace(tmp_path / "other")
    other.ensure_dirs()
    third = tailor(other, make_job(), JD_BACKEND, bank)
    assert {p.name: p.read_bytes() for p in third.path.iterdir()} == snapshot


def test_best_matching_bullets_come_first(
    demo_ws: Workspace, bank: Bank, make_job: MakeJob
) -> None:
    jd = "Kubernetes, Kubernetes and Docker. 3 years of experience running Kubernetes."
    result = tailor(demo_ws, make_job(), jd, bank, max_bullets_per_role=2)
    markdown = (result.path / "resume.md").read_text(encoding="utf-8")
    first_bullet = next(line for line in markdown.splitlines() if line.startswith("- "))
    assert "Kubernetes" in first_bullet
    experience = markdown.split("## Experience")[1].split("## Skills")[0]
    assert experience.count("\n- ") == 4  # two per role
    skills = markdown.split("## Skills")[1].splitlines()
    assert skills[2].startswith("- Infrastructure:")
    assert "Kubernetes, Docker, AWS" in skills[2]


def test_jd_named_skills_move_first_but_none_are_added(
    demo_ws: Workspace, bank: Bank, make_job: MakeJob
) -> None:
    result = tailor(demo_ws, make_job(), "We use AWS and Rust. 3 years of experience.", bank)
    skills = (result.path / "resume.md").read_text(encoding="utf-8").split("## Skills")[1]
    assert "- Infrastructure: AWS, Kubernetes, Docker" in skills
    assert "rust" not in skills.lower()


def test_second_job_in_the_same_role_merges_job_keys(
    demo_ws: Workspace, bank: Bank, make_job: MakeJob
) -> None:
    tailor(demo_ws, make_job(), JD_BACKEND, bank)
    other = make_job(key="greenhouse:examplecorp:1009")
    result = tailor(demo_ws, other, JD_BACKEND, bank)
    assert result.report["job_keys"] == [
        "greenhouse:examplecorp:1001",
        "greenhouse:examplecorp:1009",
    ]


def test_empty_description_is_a_friendly_error(
    demo_ws: Workspace, bank: Bank, make_job: MakeJob
) -> None:
    with pytest.raises(GetmeajobError) as err:
        tailor(demo_ws, make_job(), "   \u200b ", bank)
    assert err.value.hint


def test_text_that_is_not_in_the_bank_is_refused(bank: Bank) -> None:
    doc = build_doc(bank, JD_BACKEND, ["python"], 4)
    verify_truthful(doc, bank)
    forged = ResumeDoc.from_dict(doc.to_dict())
    forged.experience[0].bullets[0].text += " and led a team of 50"
    with pytest.raises(GetmeajobError):
        verify_truthful(forged, bank)
    forged = ResumeDoc.from_dict(doc.to_dict())
    forged.skills[0].items.append("Haskell")
    with pytest.raises(GetmeajobError):
        verify_truthful(forged, bank)


def test_projects_appear_only_when_they_match(demo_ws: Workspace, make_job: MakeJob) -> None:
    data = load_yaml(demo_ws.resume_bank_path)
    data["projects"] = [
        {
            "name": "Kite tracker",
            "bullets": [
                {"id": "kite-1", "text": "Wrote a Rust tool that tracks kites.", "tags": []}
            ],
        },
        {
            "name": "Pipeline kit",
            "bullets": [{"id": "pipe-1", "text": "Built a Kubernetes demo cluster.", "tags": []}],
        },
    ]
    bank = parse_bank(data)
    result = tailor(demo_ws, make_job(), "Kubernetes. 3 years of experience.", bank)
    markdown = (result.path / "resume.md").read_text(encoding="utf-8")
    assert "## Projects" in markdown
    assert "Pipeline kit" in markdown
    assert "Kite tracker" not in markdown
