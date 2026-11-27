"""Reading stored plans from `data/plans/`."""

from __future__ import annotations

from getmeajob.errors import GetmeajobError
from getmeajob.files import read_json
from getmeajob.models import Plan
from getmeajob.workspace import Workspace


def load_plan(ws: Workspace, key: str) -> Plan | None:
    """The stored plan for a job, or None (also when the file is damaged)."""
    try:
        data = read_json(ws.plan_path(key), default=None)
        return Plan.from_dict(data) if isinstance(data, dict) else None
    except GetmeajobError:
        return None


def all_plans(ws: Workspace) -> list[Plan]:
    """Every stored plan; damaged files are skipped."""
    plans: list[Plan] = []
    for path in sorted(ws.plans_dir.glob("*.json")):
        try:
            data = read_json(path, default=None)
            if isinstance(data, dict):
                plans.append(Plan.from_dict(data))
        except GetmeajobError:
            continue
    return plans
