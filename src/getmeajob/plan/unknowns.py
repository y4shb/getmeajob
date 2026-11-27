"""Unknown questions across all plans, deduplicated, and the review table.

You answer each distinct question once: `collect_unknowns` groups unknowns by their
dedupe key (normalised label plus a hash of the options), `write_stub` writes them as
an answers file to fill in, and `review_table` shows one row per label and answer.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from getmeajob.files import atomic_write_text
from getmeajob.models import Plan, PlanStatus, QuestionType
from getmeajob.plan.plans import all_plans
from getmeajob.serial import to_jsonable
from getmeajob.textutil import norm_label, truncate
from getmeajob.workspace import Workspace

STUB_HEADER = """\
# Questions getmeajob could not answer from your profile. Answer each one once.
# Leave an answer empty ("") to skip it for now. Then run: getmeajob plan answer THIS_FILE
# Use the exact option text for choices; for multi-choice questions use a list [A, B].
# Only write what is true for you. These answers go into your applications.
"""


@dataclass
class UnknownGroup:
    dedupe_key: str
    label: str
    type: QuestionType
    options: list[str]
    required: bool
    jobs: list[str] = field(default_factory=list)
    companies: list[str] = field(default_factory=list)
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "dedupe_key": self.dedupe_key,
            "label": self.label,
            "type": self.type.value,
            "options": self.options,
            "required": self.required,
            "jobs": self.jobs,
            "companies": self.companies,
            "reason": self.reason,
        }


@dataclass
class ReviewTable:
    rows: list[tuple[str, str, str, int]] = field(default_factory=list)
    unknowns: list[UnknownGroup] = field(default_factory=list)
    needs_review: list[dict[str, Any]] = field(default_factory=list)
    skipped: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "rows": [
                {"label": label, "answer": answer, "source": source, "count": count}
                for label, answer, source, count in self.rows
            ],
            "unknowns": [g.to_dict() for g in self.unknowns],
            "needs_review": to_jsonable(self.needs_review),
            "skipped": self.skipped,
        }


def _plans(ws: Workspace, keys: Sequence[str] | None) -> list[Plan]:
    plans = all_plans(ws)
    if keys:
        wanted = set(keys)
        plans = [p for p in plans if p.job_key in wanted]
    return plans


def _group(plans: Sequence[Plan]) -> list[UnknownGroup]:
    groups: dict[str, UnknownGroup] = {}
    for plan in plans:
        if plan.status != PlanStatus.needs_answers:
            continue
        for u in plan.unknowns:
            group = groups.get(u.dedupe_key)
            if group is None:
                group = UnknownGroup(
                    u.dedupe_key, u.label, u.type, list(u.options), u.required, reason=u.reason
                )
                groups[u.dedupe_key] = group
            group.required = group.required or u.required
            if plan.job_key not in group.jobs:
                group.jobs.append(plan.job_key)
            if plan.company not in group.companies:
                group.companies.append(plan.company)
    return sorted(groups.values(), key=lambda g: (-len(g.jobs), not g.required, g.label.casefold()))


def collect_unknowns(ws: Workspace) -> list[UnknownGroup]:
    """Every unknown across the stored plans, once per label and option set."""
    return _group(all_plans(ws))


def _board(job_key: str) -> str:
    parts = job_key.split(":")
    return parts[1] if len(parts) >= 3 else ""


def _stub_entry(group: UnknownGroup, indent: str) -> list[str]:
    need = "required" if group.required else "optional"
    count = f"{len(group.jobs)} job" + ("s" if len(group.jobs) != 1 else "")
    lines = [f"{indent}# {group.type.value}, {need}, {count}"]
    if group.options:
        shown = " | ".join(truncate(o, 40) for o in group.options[:8])
        more = " | ..." if len(group.options) > 8 else ""
        lines.append(f"{indent}# options: {shown}{more}")
    empty = "[]" if group.type == QuestionType.multiselect else '""'
    lines.append(f"{indent}{json.dumps(group.label, ensure_ascii=False)}: {empty}")
    return lines


def write_stub(groups: Sequence[UnknownGroup], path: Path) -> int:
    """Write an answers file to fill in. Questions seen at one company go under
    `by_company.<slug>`, the rest under `global`. Returns the number of questions."""
    shared: list[UnknownGroup] = []
    per_company: dict[str, list[UnknownGroup]] = {}
    for group in groups:
        boards = {_board(k) for k in group.jobs if _board(k)}
        if len(boards) == 1:
            per_company.setdefault(boards.pop(), []).append(group)
        else:
            shared.append(group)
    lines = [STUB_HEADER.rstrip("\n"), ""]
    lines.append("global:" if shared else "global: {}")
    for group in shared:
        lines += _stub_entry(group, "  ")
    lines.append("by_company:" if per_company else "by_company: {}")
    for board, items in per_company.items():
        lines.append(f"  {json.dumps(board)}:")
        for group in items:
            lines += _stub_entry(group, "    ")
    lines.append("by_job: {}")
    atomic_write_text(path, "\n".join(lines) + "\n")
    return len(groups)


def _shown(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    return str(value)


def review_table(ws: Workspace, keys: Sequence[str] | None) -> ReviewTable:
    """One row per (label, answer, source) across the plans, plus unknowns and drafts."""
    plans = _plans(ws, keys)
    table = ReviewTable(unknowns=_group(plans))
    counts: dict[tuple[str, str, str], int] = {}
    labels: dict[tuple[str, str, str], str] = {}
    for plan in plans:
        for answer in plan.answers:
            if answer.source == "skip" or answer.value is None:
                table.skipped += 1
                continue
            shown = _shown(answer.value)
            if answer.type == QuestionType.file:
                shown = Path(shown).name
            row_key = (norm_label(answer.label), shown, answer.source)
            counts[row_key] = counts.get(row_key, 0) + 1
            labels.setdefault(row_key, answer.label)
            if answer.needs_review:
                table.needs_review.append(
                    {
                        "job_key": plan.job_key,
                        "question_id": answer.question_id,
                        "label": answer.label,
                        "value": truncate(shown, 200),
                    }
                )
    for row_key in sorted(counts, key=lambda k: (k[0], k[1])):
        table.rows.append((labels[row_key], row_key[1], row_key[2], counts[row_key]))
    return table
