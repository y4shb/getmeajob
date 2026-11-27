from __future__ import annotations

from collections.abc import Callable

from getmeajob.models import Flag, Job
from getmeajob.rank.eligibility import eligibility_flags
from getmeajob.rank.prefs import Preferences
from getmeajob.rank.yoe import YoeResult, parse_yoe

MakeJob = Callable[..., Job]
NO_YOE = YoeResult(None, None, "", False)


def codes(flags: list[Flag], *, hard: bool | None = None) -> set[str]:
    return {f.code for f in flags if hard is None or f.hard == hard}


def test_clean_job_has_no_flags(prefs: Preferences, make_job: MakeJob) -> None:
    text = "3-5 years of experience. Python and PostgreSQL."
    assert eligibility_flags(make_job(), text, prefs, parse_yoe(text)) == []


def test_title_excluded(prefs: Preferences, make_job: MakeJob) -> None:
    job = make_job(title="Engineering Manager, Infrastructure")
    flags = eligibility_flags(job, "", prefs, NO_YOE)
    assert "title_excluded" in codes(flags, hard=True)
    assert all(f.reason for f in flags)


def test_off_track_title(prefs: Preferences, make_job: MakeJob) -> None:
    flags = eligibility_flags(make_job(title="Data Analyst"), "", prefs, NO_YOE)
    assert codes(flags, hard=True) == {"off_track"}


def test_no_tracks_means_no_off_track_flag(prefs: Preferences, make_job: MakeJob) -> None:
    prefs.tracks = []
    assert not eligibility_flags(make_job(title="Data Analyst"), "", prefs, NO_YOE)


def test_too_senior_by_years(prefs: Preferences, make_job: MakeJob) -> None:
    text = "8+ years of experience"
    flags = eligibility_flags(make_job(), text, prefs, parse_yoe(text))
    assert codes(flags, hard=True) == {"too_senior"}


def test_big_stretch_is_a_soft_flag(prefs: Preferences, make_job: MakeJob) -> None:
    prefs.too_senior_over = 9
    text = "7 years of experience"
    flags = eligibility_flags(make_job(), text, prefs, parse_yoe(text))
    assert codes(flags, hard=True) == set()
    assert codes(flags, hard=False) == {"too_senior"}


def test_staff_title_is_too_senior_unless_it_asks_little(
    prefs: Preferences, make_job: MakeJob
) -> None:
    job = make_job(title="Staff Platform Engineer")
    assert "too_senior" in codes(eligibility_flags(job, "", prefs, NO_YOE), hard=True)
    text = "4 years of experience"
    soft = eligibility_flags(job, text, prefs, parse_yoe(text))
    assert codes(soft, hard=True) == set()
    assert codes(soft, hard=False) == {"too_senior"}


def test_member_of_technical_staff_is_not_staff(prefs: Preferences, make_job: MakeJob) -> None:
    job = make_job(title="Member of Technical Staff, Backend")
    assert "too_senior" not in codes(eligibility_flags(job, "", prefs, NO_YOE))


def test_region_and_sponsorship(prefs: Preferences, make_job: MakeJob) -> None:
    job = make_job(title="Backend Engineer, Payments", location="Remote - US")
    text = (
        "3+ years of experience. You must be authorized to work in the United States. "
        "We are unable to sponsor visas."
    )
    flags = eligibility_flags(job, text, prefs, parse_yoe(text))
    assert {"region_restricted", "no_sponsorship"} <= codes(flags, hard=True)
    sponsor = next(f for f in flags if f.code == "no_sponsorship")
    assert "United States" in sponsor.reason


def test_no_sponsorship_does_not_matter_where_you_are_authorized(
    prefs: Preferences, make_job: MakeJob
) -> None:
    job = make_job(location="Remote - Canada")
    flags = eligibility_flags(job, "We cannot sponsor visas.", prefs, NO_YOE)
    assert "no_sponsorship" not in codes(flags)


def test_no_sponsorship_wording_variants(prefs: Preferences, make_job: MakeJob) -> None:
    job = make_job(location="Remote - US")
    for text in (
        "No visa sponsorship available.",
        "Sponsorship is not available for this role.",
        "We do not offer visa sponsorship.",
        "Candidates must not require sponsorship now or in the future.",
    ):
        assert "no_sponsorship" in codes(eligibility_flags(job, text, prefs, NO_YOE)), text


def test_sponsorship_offered_is_fine(prefs: Preferences, make_job: MakeJob) -> None:
    job = make_job(location="Remote - US")
    flags = eligibility_flags(job, "Visa sponsorship is available.", prefs, NO_YOE)
    assert "no_sponsorship" not in codes(flags)


def test_clearance(prefs: Preferences, make_job: MakeJob) -> None:
    text = "Active TS/SCI clearance required. Subject to ITAR."
    flags = eligibility_flags(make_job(), text, prefs, NO_YOE)
    assert "clearance_required" in codes(flags, hard=True)
    prefs.has_clearance = True
    assert "clearance_required" not in codes(eligibility_flags(make_job(), text, prefs, NO_YOE))


def test_no_clearance_needed_is_not_flagged(prefs: Preferences, make_job: MakeJob) -> None:
    text = "No security clearance is needed."
    assert "clearance_required" not in codes(eligibility_flags(make_job(), text, prefs, NO_YOE))


def test_citizenship(prefs: Preferences, make_job: MakeJob) -> None:
    text = "Applicants must be a citizen of Freedonia."
    assert "citizenship_required" in codes(eligibility_flags(make_job(), text, prefs, NO_YOE))
    prefs.citizenships = ["Freedonia"]
    assert "citizenship_required" not in codes(eligibility_flags(make_job(), text, prefs, NO_YOE))


def test_equal_opportunity_boilerplate_is_not_a_citizenship_ask(
    prefs: Preferences, make_job: MakeJob
) -> None:
    text = "We hire regardless of race, religion, or citizenship status."
    assert "citizenship_required" not in codes(eligibility_flags(make_job(), text, prefs, NO_YOE))


def test_company_excluded_by_name_or_slug(prefs: Preferences, make_job: MakeJob) -> None:
    prefs.exclude_companies = ["Example Corp"]
    assert "company_excluded" in codes(eligibility_flags(make_job(), "", prefs, NO_YOE))
    prefs.exclude_companies = ["examplecorp"]
    assert "company_excluded" in codes(eligibility_flags(make_job(), "", prefs, NO_YOE))
    prefs.exclude_companies = ["Other"]
    assert "company_excluded" not in codes(eligibility_flags(make_job(), "", prefs, NO_YOE))


def test_reasons_are_plain_and_short(prefs: Preferences, make_job: MakeJob) -> None:
    job = make_job(title="Staff Manager", location="Remote - US")
    text = "10+ years of experience. Must be a US citizen. No visa sponsorship. TS/SCI."
    for flag in eligibility_flags(job, text, prefs, parse_yoe(text)):
        assert 0 < len(flag.reason) < 90
