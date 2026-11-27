from __future__ import annotations

from collections.abc import Callable

import pytest

from getmeajob.models import Job
from getmeajob.rank.location import canon_region, location_tier, region_restrictions
from getmeajob.rank.prefs import Preferences

MakeJob = Callable[..., Job]


@pytest.mark.parametrize(
    ("location", "kind"),
    [
        ("Remote - Worldwide", "remote_worldwide"),
        ("Remote - Canada", "remote_home_country"),
        ("Springfield, Ontario, Canada (Hybrid)", "hybrid_home_city"),
        ("Toronto, Ontario, Canada", "home_country_other"),
        ("Remote - US", "other"),
        ("Berlin", "other"),
        ("Remote, Europe", "other"),
        ("", "other"),
    ],
)
def test_demo_locations_map_to_tiers(
    prefs: Preferences, make_job: MakeJob, location: str, kind: str
) -> None:
    assert location_tier(make_job(location=location), prefs).kind == kind


def test_remote_limited_to_a_region_names_it(prefs: Preferences, make_job: MakeJob) -> None:
    result = location_tier(make_job(location="Remote - US"), prefs)
    assert result.restricted_to == "US"


def test_tier_name_and_score_come_from_preferences(prefs: Preferences, make_job: MakeJob) -> None:
    result = location_tier(make_job(location="Springfield, Ontario, Canada (Hybrid)"), prefs)
    assert result.name == "Hybrid in Springfield"
    assert result.score == 0.9


def test_bare_remote_needs_the_text_to_name_your_region(
    prefs: Preferences, make_job: MakeJob
) -> None:
    job = make_job(location="Remote")
    assert location_tier(job, prefs).kind == "other"
    assert location_tier(job, prefs, "Work from anywhere in the world").kind == "remote_worldwide"
    limited = location_tier(job, prefs, "You must be based in Brazil for this role.")
    assert limited.kind == "other"


def test_remote_flag_on_the_job_counts(prefs: Preferences, make_job: MakeJob) -> None:
    job = make_job(location="Canada", remote=True)
    assert location_tier(job, prefs).kind == "remote_home_country"


def test_city_without_hybrid_word_is_on_site_unless_text_says_hybrid(
    prefs: Preferences, make_job: MakeJob
) -> None:
    job = make_job(location="Springfield, Ontario")
    assert location_tier(job, prefs).kind == "onsite_home_city"
    assert location_tier(job, prefs, "This is a hybrid role, 3 days in.").kind == "hybrid_home_city"


def test_best_of_several_places_wins(prefs: Preferences, make_job: MakeJob) -> None:
    job = make_job(location="Berlin; Remote - Canada")
    assert location_tier(job, prefs).kind == "remote_home_country"


def test_home_is_never_built_in(prefs: Preferences, make_job: MakeJob) -> None:
    prefs.home.city = "Shelbyville"
    prefs.home.region = ""
    prefs.home.country = "Freedonia"
    prefs.allowed_regions = []
    assert location_tier(make_job(location="Shelbyville (Hybrid)"), prefs).kind == (
        "hybrid_home_city"
    )
    assert location_tier(make_job(location="Remote - Canada"), prefs).kind == "other"
    assert location_tier(make_job(location="Remote - Freedonia"), prefs).kind == (
        "remote_home_country"
    )


def test_us_remote_plus_authorized_wording_is_region_restricted(prefs: Preferences) -> None:
    text = "Remote - US. You must be authorized to work in the United States."
    flags = region_restrictions(text, prefs)
    assert flags
    assert all(f.code == "region_restricted" and f.hard for f in flags)
    assert any("United States" in f.reason for f in flags)


@pytest.mark.parametrize(
    "text",
    [
        "Must be based in the US.",
        "This role is US only.",
        "We hire US-based candidates.",
        "Remote in the United States",
    ],
)
def test_restriction_wording_is_found(prefs: Preferences, text: str) -> None:
    assert any(f.hard for f in region_restrictions(text, prefs))


@pytest.mark.parametrize(
    "text",
    [
        "Must be authorized to work in Canada.",
        "Remote in Canada or the US",
        "Tell us what you think. We love hearing from us.",
        "Open to candidates worldwide.",
        "Candidates must be located in Springfield.",
    ],
)
def test_home_or_open_wording_is_not_a_restriction(prefs: Preferences, text: str) -> None:
    assert not [f for f in region_restrictions(text, prefs) if f.hard]


def test_time_zone_lock_is_a_soft_flag(prefs: Preferences) -> None:
    flags = region_restrictions("Overlap with PST hours is needed.", prefs)
    assert flags
    assert not flags[0].hard


def test_names_for_one_region_agree(prefs: Preferences) -> None:
    assert canon_region("U.S.", prefs) == canon_region("the United States", prefs)
    assert canon_region("CA", prefs) == canon_region("Canada", prefs)
