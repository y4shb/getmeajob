"""The eight demo jobs and the rules for scores and reasons."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from getmeajob.models import Job, RankResult
from getmeajob.rank.prefs import Preferences
from getmeajob.rank.score import experience_part, rank_job
from getmeajob.rank.yoe import YoeResult

MakeJob = Callable[..., Job]
NOW = "2026-11-27T10:00:00+00:00"

FILLER = (
    "About the team: we build calm, reliable software for small businesses and we care "
    "about clear writing and kind code review. "
)

GH = "greenhouse:examplecorp:"
ASHBY = "ashby:samplesystems:5a1e0000-0000-4000-8000-00000000000"
LEVER = "lever:demowidgets:7c0de000-0000-4000-8000-000000000001"
SR = "smartrecruiters:PlaceholderLabs:744000000000001"

# key, company, title, location, workplace, jd, expected eligible
DEMO: list[tuple[str, str, str, str, str | None, str, bool]] = [
    (
        GH + "1001",
        "Example Corp",
        "Senior Backend Engineer",
        "Remote - Worldwide",
        None,
        FILLER + "We are looking for 3-5 years of professional experience building APIs. "
        "You will work in Python with PostgreSQL and run services on Kubernetes.",
        True,
    ),
    (
        GH + "1002",
        "Example Corp",
        "Staff Platform Engineer",
        "Remote - Worldwide",
        None,
        FILLER + "You bring 8+ years of experience leading platform work on Kubernetes and AWS.",
        False,
    ),
    (
        GH + "1003",
        "Example Corp",
        "Backend Engineer, Payments",
        "Remote - US",
        None,
        FILLER + "3+ years of experience with Python. You must be authorized to work in the "
        "United States. We are unable to sponsor visas.",
        False,
    ),
    (
        GH + "1004",
        "Example Corp",
        "Engineering Manager, Infrastructure",
        "Remote - Worldwide",
        None,
        FILLER + "You will manage a team of platform engineers working with Kubernetes.",
        False,
    ),
    (
        ASHBY + "1",
        "Sample Systems",
        "Platform Engineer",
        "Springfield, Ontario, Canada (Hybrid)",
        "Hybrid",
        FILLER + "2+ years of experience with Kubernetes, AWS and Terraform.",
        True,
    ),
    (
        ASHBY + "2",
        "Sample Systems",
        "Data Analyst",
        "Remote - Canada",
        None,
        FILLER + "2 years of experience with SQL dashboards and Python notebooks.",
        False,
    ),
    (
        LEVER,
        "Demo Widgets",
        "Software Engineer II",
        "Toronto, Ontario, Canada",
        None,
        FILLER + "3+ years of experience. You will write Go and gRPC services, with Python tools.",
        True,
    ),
    (
        SR,
        "Placeholder Labs",
        "Backend Developer",
        "Remote - Canada",
        None,
        "Minimum of 2 years of experience in backend development.",
        True,
    ),
]


@pytest.fixture
def results(prefs: Preferences, make_job: MakeJob) -> dict[str, RankResult]:
    out: dict[str, RankResult] = {}
    for key, company, title, location, workplace, jd, _ in DEMO:
        job = make_job(title, location, key=key, company=company, workplace=workplace)
        out[key] = rank_job(job, jd, prefs, NOW)
    return out


def test_demo_jobs_expected_eligibility(results: dict[str, RankResult]) -> None:
    for key, *_rest, expected in DEMO:
        assert results[key].eligible is expected, (key, results[key].flags)


def test_ineligible_jobs_carry_flags_with_reasons(results: dict[str, RankResult]) -> None:
    def hard(key: str) -> set[str]:
        return {f.code for f in results[key].flags if f.hard}

    assert hard(GH + "1002") == {"too_senior"}
    assert hard(GH + "1003") == {"region_restricted", "no_sponsorship"}
    assert hard(GH + "1004") == {"title_excluded"}
    assert hard(ASHBY + "2") == {"off_track"}
    for result in results.values():
        assert all(f.reason for f in result.flags)


def test_top_score_and_tiers(results: dict[str, RankResult]) -> None:
    eligible = {k: r for k, r in results.items() if r.eligible}
    assert max(eligible, key=lambda k: eligible[k].score) == GH + "1001"
    assert results[ASHBY + "1"].tier == "Hybrid in Springfield"
    assert results[LEVER].score < results[GH + "1001"].score
    assert results[LEVER].score < results[SR].score
    assert results[LEVER].skills_missing == ["go"]
    assert results[GH + "1001"].skills_hit[:1] == ["python"]
    assert results[GH + "1001"].track == "backend"
    assert (results[GH + "1001"].yoe_min, results[GH + "1001"].yoe_max) == (3, 5)


def test_reasons_are_short_lines(results: dict[str, RankResult]) -> None:
    for result in results.values():
        assert len(result.reasons) == 4
        for reason in result.reasons:
            assert reason == " ".join(reason.split())
            assert "\n" not in reason
            assert 0 < len(reason) < 90


def test_reason_wording(results: dict[str, RankResult]) -> None:
    top = results[GH + "1001"].reasons
    assert top[0] == "needs 3-5 yrs (you: 4): fits"
    assert top[1] == "title matches track backend"
    assert top[2] == "location: remote worldwide"
    assert top[3].startswith("skills: python")
    assert results[LEVER].reasons[3].endswith("gaps: go")


def test_score_is_within_range_and_rank_job_is_pure(prefs: Preferences, make_job: MakeJob) -> None:
    job = make_job()
    first = rank_job(job, "x", prefs, NOW)
    second = rank_job(job, "x", prefs, NOW)
    assert first == second
    assert 0 <= first.score <= 100


def test_weights_are_normalised(prefs: Preferences, make_job: MakeJob) -> None:
    text = "3-5 years of experience. Python and PostgreSQL. " * 6
    base = rank_job(make_job("Senior Backend Engineer"), text, prefs, NOW).score
    prefs.weights = {k: v * 10 for k, v in prefs.weights.items()}
    assert rank_job(make_job("Senior Backend Engineer"), text, prefs, NOW).score == base


def test_experience_bands(prefs: Preferences) -> None:
    def part(low: int | None) -> tuple[float, str]:
        return experience_part(YoeResult(low, None, "", True), prefs)

    assert part(None)[0] == 0.6
    assert part(1)[1].endswith("below your level")
    assert part(2)[0] == 1.0
    assert part(4)[0] == 1.0
    assert part(5)[0] > part(6)[0] > 0.2
    assert part(7)[1].endswith("too senior")
    assert part(7)[0] == 0.0


def test_junior_title_is_a_soft_warning_not_a_block(prefs: Preferences, make_job: MakeJob) -> None:
    job = make_job("Backend Engineer Intern")
    result = rank_job(job, "1 year of experience", prefs, NOW)
    assert "below your level" in result.reasons[1]


def test_short_description_does_not_judge_skills(prefs: Preferences, make_job: MakeJob) -> None:
    result = rank_job(make_job(), "Backend role.", prefs, NOW)
    assert result.reasons[3] == "description too short to judge skills"


def test_result_round_trips_through_json(results: dict[str, RankResult]) -> None:
    for result in results.values():
        data: dict[str, Any] = result.to_dict()
        assert RankResult.from_dict(data) == result
