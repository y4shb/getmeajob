"""The role folders under `roles/` and choosing one for a job.

Layout: `roles/<company>-<title>/{jd.txt, resume.md, resume.html, resume.pdf, report.json,
meta.yaml}`. `meta.yaml` lists the job keys the folder is used for under `job_keys`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from getmeajob.rank.score import job_text
from getmeajob.resume.keywords import coverage
from getmeajob.store import JobStore
from getmeajob.workspace import Workspace
from getmeajob.yamlio import dump_yaml, load_yaml


@dataclass(slots=True)
class RoleSummary:
    path: Path
    name: str
    company: str
    title: str
    job_keys: list[str]
    has_pdf: bool
    bank_hash: str


def _keys(meta: dict[str, object]) -> list[str]:
    raw = meta.get("job_keys")
    return [str(k) for k in raw] if isinstance(raw, list) else []


def list_roles(ws: Workspace) -> list[RoleSummary]:
    """Every role folder that has a `meta.yaml`, sorted by folder name."""
    roles: list[RoleSummary] = []
    if not ws.roles_dir.is_dir():
        return roles
    for path in sorted(p for p in ws.roles_dir.iterdir() if p.is_dir()):
        if not (path / "meta.yaml").is_file():
            continue
        meta = load_yaml(path / "meta.yaml", required=False)
        roles.append(
            RoleSummary(
                path=path,
                name=path.name,
                company=str(meta.get("company") or ""),
                title=str(meta.get("title") or ""),
                job_keys=_keys(meta),
                has_pdf=(path / "resume.pdf").is_file(),
                bank_hash=str(meta.get("bank_hash") or ""),
            )
        )
    return roles


def role_for_key(ws: Workspace, key: str) -> Path | None:
    """The role folder that lists this job key, if any."""
    for role in list_roles(ws):
        if key in role.job_keys:
            return role.path
    return None


def _set_keys(path: Path, keys: list[str]) -> None:
    meta = load_yaml(path / "meta.yaml", required=False)
    meta["job_keys"] = sorted(set(keys))
    dump_yaml(path / "meta.yaml", meta)


def assign_key(ws: Workspace, key: str, path: Path) -> None:
    """List `key` in this role's meta.yaml and take it out of every other role."""
    for role in list_roles(ws):
        if role.path == path:
            if key not in role.job_keys:
                _set_keys(role.path, [*role.job_keys, key])
        elif key in role.job_keys:
            _set_keys(role.path, [k for k in role.job_keys if k != key])


def pick_for_job(ws: Workspace, key: str) -> Path | None:
    """The `resume.pdf` to use for a job, or None when no rendered resume fits.

    A role folder that already lists the key wins. Otherwise the folder whose resume
    covers the largest share of the job's keywords is chosen (at least one keyword), and
    the key is written into its `meta.yaml`.
    """
    roles = [r for r in list_roles(ws) if r.has_pdf]
    for role in roles:
        if key in role.job_keys:
            return role.path / "resume.pdf"
    job = JobStore(ws).get(key)
    if job is None or not roles:
        return None
    text = job_text(ws, job)
    best: tuple[float, int, RoleSummary] | None = None
    for role in roles:
        md = role.path / "resume.md"
        if not md.is_file():
            continue
        cover = coverage(text, md.read_text(encoding="utf-8"))
        if not cover.matched:
            continue
        score = (cover.ratio, len(cover.matched))
        if best is None or score > best[:2]:
            best = (score[0], score[1], role)
    if best is None:
        return None
    assign_key(ws, key, best[2].path)
    return best[2].path / "resume.pdf"
