from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from getmeajob.models import Job
from getmeajob.resume.bank import Bank
from getmeajob.resume.store import assign_key, list_roles, pick_for_job, role_for_key
from getmeajob.resume.tailor import tailor
from getmeajob.store import JobStore
from getmeajob.workspace import Workspace
from getmeajob.yamlio import load_yaml

MakeJob = Callable[..., Job]

JD_K8S = "3 years of experience with Kubernetes, Docker and AWS."
JD_DB = "3 years of experience with PostgreSQL and Python. PostgreSQL tuning matters."


def _role(ws: Workspace, bank: Bank, job: Job, jd: str, *, pdf: bool = True) -> Path:
    JobStore(ws).upsert([job], "2026-11-27T09:00:00+00:00")
    ws.jd_path(job.key).write_text(jd, encoding="utf-8")
    path = tailor(ws, job, jd, bank).path
    if pdf:
        (path / "resume.pdf").write_bytes(b"%PDF-1.4 fake")
    return path


def test_list_roles(demo_ws: Workspace, bank: Bank, make_job: MakeJob) -> None:
    assert list_roles(demo_ws) == []
    path = _role(demo_ws, bank, make_job(), JD_K8S, pdf=False)
    [role] = list_roles(demo_ws)
    assert role.path == path
    assert (role.company, role.title) == ("Example Corp", "Senior Backend Engineer")
    assert role.job_keys == ["greenhouse:examplecorp:1001"]
    assert role.has_pdf is False


def test_pick_prefers_the_role_that_lists_the_key(
    demo_ws: Workspace, bank: Bank, make_job: MakeJob
) -> None:
    job = make_job()
    path = _role(demo_ws, bank, job, JD_K8S)
    assert pick_for_job(demo_ws, job.key) == path / "resume.pdf"
    assert role_for_key(demo_ws, job.key) == path


def test_pick_chooses_by_keyword_coverage_and_records_the_key(
    demo_ws: Workspace, bank: Bank, make_job: MakeJob
) -> None:
    infra = _role(
        demo_ws, bank, make_job("Platform Engineer", key="ashby:s:1", company="S"), JD_K8S
    )
    data = _role(demo_ws, bank, make_job("Data Engineer", key="ashby:s:2", company="T"), JD_DB)
    new_job = make_job("Database Engineer", key="lever:d:3", company="U")
    JobStore(demo_ws).upsert([new_job], "2026-11-27T09:00:00+00:00")
    demo_ws.jd_path(new_job.key).write_text(
        "Python and PostgreSQL. PostgreSQL schema design.", encoding="utf-8"
    )
    chosen = pick_for_job(demo_ws, new_job.key)
    assert chosen is not None and chosen.parent in {infra, data}
    meta = load_yaml(chosen.parent / "meta.yaml")
    assert new_job.key in meta["job_keys"]
    again = pick_for_job(demo_ws, new_job.key)
    assert again == chosen


def test_pick_ignores_roles_without_a_pdf_and_unknown_jobs(
    demo_ws: Workspace, bank: Bank, make_job: MakeJob
) -> None:
    job = make_job()
    _role(demo_ws, bank, job, JD_K8S, pdf=False)
    assert pick_for_job(demo_ws, job.key) is None
    assert pick_for_job(demo_ws, "lever:nobody:9") is None


def test_pick_returns_none_when_nothing_overlaps(
    demo_ws: Workspace, bank: Bank, make_job: MakeJob
) -> None:
    _role(demo_ws, bank, make_job(), JD_K8S)
    other = make_job("Embedded Engineer", key="lever:x:1", company="X")
    JobStore(demo_ws).upsert([other], "2026-11-27T09:00:00+00:00")
    demo_ws.jd_path(other.key).write_text("Rust, firmware and C++ drivers.", encoding="utf-8")
    assert pick_for_job(demo_ws, other.key) is None


def test_assign_key_moves_it_between_roles(
    demo_ws: Workspace, bank: Bank, make_job: MakeJob
) -> None:
    a = _role(demo_ws, bank, make_job(), JD_K8S)
    b = _role(demo_ws, bank, make_job("Data Engineer", key="ashby:s:2", company="T"), JD_DB)
    assign_key(demo_ws, "greenhouse:examplecorp:1001", b)
    assert role_for_key(demo_ws, "greenhouse:examplecorp:1001") == b
    assert "greenhouse:examplecorp:1001" not in load_yaml(a / "meta.yaml")["job_keys"]
