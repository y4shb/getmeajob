"""Which jobs a run may touch, and where a form is opened. No browser needed."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from getmeajob.apply import policy
from getmeajob.apply.forms import FormUnavailable, form_target
from getmeajob.errors import ConfigError
from getmeajob.models import (
    ApplyMode,
    ApplyStatus,
    AppStatus,
    LedgerEntry,
    Plan,
    PlannedAnswer,
    PlanStatus,
    QuestionType,
)
from getmeajob.settings import Settings
from getmeajob.workspace import Workspace

NOW = datetime(2026, 11, 27, 12, 0, tzinfo=UTC)


def _plan(key: str = "greenhouse:examplecorp:1001", company: str = "Example Corp") -> Plan:
    return Plan(
        job_key=key,
        ats=key.split(":")[0],
        company=company,
        title="Senior Backend Engineer",
        url="https://job-boards.greenhouse.io/examplecorp/jobs/1001",
        form_url="https://job-boards.greenhouse.io/embed/job_app?for=examplecorp&token=1001",
        status=PlanStatus.ready,
        answers=[
            PlannedAnswer("email", "Email", QuestionType.email, "alex@example.com", "rule:email")
        ],
        unknowns=[],
    )


def _entry(
    key: str, status: ApplyStatus, days_ago: float = 0, company: str = "Example Corp"
) -> LedgerEntry:
    ts = (NOW - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return LedgerEntry(ts, "r1", key, company, "t", ApplyMode.submit, status)


def test_prefs_defaults_and_errors(ready_ws: Workspace, set_apply: Callable[..., None]) -> None:
    prefs = policy.load_apply_prefs(ready_ws)
    assert prefs == policy.ApplyPrefs(submit_boards=[], per_company_cap=2, exclude=[])
    set_apply(ready_ws, per_company_cap="lots")
    with pytest.raises(ConfigError, match="per_company_cap"):
        policy.load_apply_prefs(ready_ws)
    set_apply(ready_ws, per_company_cap=0, submit_boards="greenhouse")
    with pytest.raises(ConfigError, match="submit_boards"):
        policy.load_apply_prefs(ready_ws)


def test_exclusion_matches_slug_key_or_name_part() -> None:
    plan = _plan()
    assert policy.excluded_by(plan, ["examplecorp"]) == "examplecorp"
    assert policy.excluded_by(plan, ["EXAMPLE corp"]) == "EXAMPLE corp"
    assert policy.excluded_by(plan, [plan.job_key]) == plan.job_key
    assert policy.excluded_by(plan, ["sample systems", "corp inc"]) is None


def test_duplicates_and_waiting_jobs() -> None:
    plan = _plan()
    key = plan.job_key
    dry = ApplyMode.dry
    assert policy.duplicate_reason(plan, dry, [_entry(key, ApplyStatus.dry_ok)], None) is None
    assert policy.duplicate_reason(plan, dry, [_entry(key, ApplyStatus.submitted)], None)
    assert policy.duplicate_reason(plan, dry, [], AppStatus.interviewing)
    assert policy.duplicate_reason(plan, dry, [], AppStatus.ready) is None
    for status in (ApplyStatus.captcha, ApplyStatus.account_required, ApplyStatus.awaiting_human):
        assert policy.duplicate_reason(plan, ApplyMode.hold, [_entry(key, status)], None)
    code = [_entry(key, ApplyStatus.needs_email_code)]
    assert policy.duplicate_reason(plan, ApplyMode.submit, code, None)
    assert policy.duplicate_reason(plan, ApplyMode.hold, code, None) is None
    later = [_entry(key, ApplyStatus.fill_problem), _entry(key, ApplyStatus.dry_ok)]
    assert policy.duplicate_reason(plan, dry, later, None) is None


def test_cap_counts_sent_jobs_in_30_days_only() -> None:
    plan = _plan()
    prefs = policy.ApplyPrefs(per_company_cap=2)
    recent = [
        _entry("greenhouse:examplecorp:1002", ApplyStatus.submitted, 3),
        _entry("greenhouse:examplecorp:1003", ApplyStatus.needs_email_code, 10),
    ]
    assert policy.cap_reason(plan, prefs, recent, NOW)
    old = [recent[0], _entry("greenhouse:examplecorp:1003", ApplyStatus.submitted, 31)]
    assert policy.cap_reason(plan, prefs, old, NOW) is None
    not_sent = [recent[0], _entry("greenhouse:examplecorp:1003", ApplyStatus.dry_ok, 1)]
    assert policy.cap_reason(plan, prefs, not_sent, NOW) is None
    same_job = [recent[0], _entry(plan.job_key, ApplyStatus.awaiting_human, 1)]
    assert policy.cap_reason(plan, prefs, same_job, NOW) is None
    other = [_entry("x:other:1", ApplyStatus.submitted, 1, company="Other Co")] * 3
    assert policy.cap_reason(plan, prefs, other, NOW) is None
    assert policy.cap_reason(plan, policy.ApplyPrefs(per_company_cap=0), recent, NOW) is None


def test_not_ready_and_unreviewed_drafts() -> None:
    plan = _plan()
    assert policy.not_ready_reason(plan, ApplyMode.submit) is None
    plan.answers[0].needs_review = True
    assert policy.not_ready_reason(plan, ApplyMode.dry) is None
    assert "approve" in (policy.not_ready_reason(plan, ApplyMode.submit) or "")
    plan.status = PlanStatus.needs_answers
    assert "plan unknowns" in (policy.not_ready_reason(plan, ApplyMode.dry) or "")


def test_form_target_offline_mapping(tmp_path: Path) -> None:
    (tmp_path / "fixtures").mkdir()
    mock = tmp_path / "mock_forms" / "form.html"
    mock.parent.mkdir()
    mock.write_text("<form></form>", encoding="utf-8")
    url = "https://jobs.ashbyhq.com/org/1/application"
    mapping = {url: "mock_forms/form.html?code=1"}
    (tmp_path / "fixtures" / "forms.json").write_text(json.dumps(mapping), encoding="utf-8")
    settings = Settings(fixtures=tmp_path / "fixtures", offline=True)
    target = form_target(url + "/", settings)
    assert target == mock.resolve().as_uri() + "?code=1"
    with pytest.raises(FormUnavailable, match="no mock form"):
        form_target("https://jobs.ashbyhq.com/org/2/application", settings)
    with pytest.raises(FormUnavailable, match="offline"):
        form_target(url, Settings(offline=True))
    assert form_target(url, Settings()) == url
