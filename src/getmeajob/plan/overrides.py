"""Your own answers (`answers.yaml`), which win over the rules.

Layout:
    global:     {"<question label>": value}
    by_company: {"<board slug or company name>": {"<question label>": value}}
    by_job:     {"<job key>": {"<question id or label>": value | {value, needs_review}}}

The most specific answer wins: by_job (question id, then label), by_company, global.
Labels are compared after normalising (case, "*", "(required)", trailing "?" ignored).
Blank values count as "not answered yet". Drafts are stored as
`{value: ..., needs_review: true, source: draft}` until you approve them.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import yaml

from getmeajob.errors import ConfigError
from getmeajob.files import atomic_write_text
from getmeajob.models import Job, Question
from getmeajob.plan.profile import is_blank
from getmeajob.textutil import norm_label, short_hash
from getmeajob.workspace import Workspace
from getmeajob.yamlio import load_yaml

SECTIONS = ("global", "by_company", "by_job")
HEADER = """\
# Your own answers to form questions. The most specific answer wins:
# by_job (question id or label), then by_company (board slug), then global (label).
# `getmeajob plan unknowns --stub FILE` writes open questions to fill in, and
# `getmeajob plan answer FILE` merges them here. Drafts carry needs_review: true
# until you check them and run `getmeajob plan approve KEY`.
"""


@dataclass
class Answers:
    global_: dict[str, Any] = field(default_factory=dict)
    by_company: dict[str, dict[str, Any]] = field(default_factory=dict)
    by_job: dict[str, dict[str, Any]] = field(default_factory=dict)

    def raw(self) -> dict[str, Any]:
        return {"global": self.global_, "by_company": self.by_company, "by_job": self.by_job}

    def digest(self) -> str:
        return short_hash(json.dumps(self.raw(), sort_keys=True, default=str))


def _mapping(value: Any, where: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ConfigError(
            f"answers.yaml: `{where}` should be a list of `question: answer` lines.",
            hint="Compare it with config/answers.example.yaml.",
        )
    return {str(k): v for k, v in value.items()}


def answers_from_data(data: Mapping[str, Any]) -> Answers:
    by_company = {
        k: _mapping(v, f"by_company.{k}")
        for k, v in _mapping(data.get("by_company"), "by_company").items()
    }
    by_job = {
        k: _mapping(v, f"by_job.{k}") for k, v in _mapping(data.get("by_job"), "by_job").items()
    }
    return Answers(
        global_=_mapping(data.get("global"), "global"), by_company=by_company, by_job=by_job
    )


def load_answers(ws: Workspace) -> Answers:
    """Read `answers.yaml` (a missing file means no answers yet)."""
    return answers_from_data(load_yaml(ws.answers_path, required=False))


def entry_value(entry: Any) -> tuple[Any, bool, str | None]:
    """(value, needs_review, source) of an answer that may be `{value, needs_review}`."""
    if isinstance(entry, Mapping):
        return entry.get("value"), entry.get("needs_review") is True, entry.get("source")
    return entry, False, None


def _filled(entry: Any) -> bool:
    return not is_blank(entry_value(entry)[0])


def _by_label(table: Mapping[str, Any], label: str) -> Any | None:
    want = norm_label(label)
    for key, entry in table.items():
        if norm_label(key) == want and _filled(entry):
            return entry
    return None


def lookup(answers: Answers, job: Job, q: Question) -> tuple[Any, str] | None:
    """Your saved answer for this question and where it came from, or None.

    The first item is the stored entry (a value, or `{value, needs_review, source}`;
    use `entry_value` to unpack). The second is override:job, override:company or
    override:global.
    """
    per_job = answers.by_job.get(job.key) or {}
    entry = per_job.get(q.id)
    if entry is not None and _filled(entry):
        return entry, "override:job"
    entry = _by_label(per_job, q.label)
    if entry is not None:
        return entry, "override:job"
    wanted = {job.board.casefold(), norm_label(job.company)}
    for company, table in answers.by_company.items():
        if company.casefold() in wanted or norm_label(company) in wanted:
            entry = _by_label(table, q.label)
            if entry is not None:
                return entry, "override:company"
    entry = _by_label(answers.global_, q.label)
    if entry is not None:
        return entry, "override:global"
    return None


def merge_answers(ws: Workspace, new: Mapping[str, Any]) -> int:
    """Merge `{global, by_company, by_job}` into answers.yaml. Blank values are ignored.

    Returns how many answers were added or changed. The file is rewritten with a short
    header (comments in the old file are not kept).
    """
    current = load_yaml(ws.answers_path, required=False)
    merged = answers_from_data(current).raw()
    incoming = answers_from_data(new).raw()
    changed = 0
    for key, value in incoming["global"].items():
        if _filled(value) and merged["global"].get(key) != value:
            merged["global"][key] = value
            changed += 1
    for section in ("by_company", "by_job"):
        for scope, table in incoming[section].items():
            target = merged[section].setdefault(scope, {})
            for key, value in table.items():
                if _filled(value) and target.get(key) != value:
                    target[key] = value
                    changed += 1
    if changed:
        write_answers(ws, merged)
    return changed


def write_answers(ws: Workspace, data: Mapping[str, Any]) -> None:
    body = yaml.safe_dump(dict(data), sort_keys=False, allow_unicode=True, width=100)
    atomic_write_text(ws.answers_path, HEADER + "\n" + body)


def approve_job(ws: Workspace, job_key: str) -> int:
    """Mark the drafted answers of one job as reviewed. Returns how many changed."""
    data = answers_from_data(load_yaml(ws.answers_path, required=False)).raw()
    table = data["by_job"].get(job_key) or {}
    changed = 0
    for key, entry in table.items():
        if isinstance(entry, Mapping) and entry.get("needs_review") is True:
            table[key] = {**entry, "needs_review": False}
            changed += 1
    if changed:
        write_answers(ws, data)
    return changed
