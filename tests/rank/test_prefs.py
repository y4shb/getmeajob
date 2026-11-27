from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from getmeajob.errors import ConfigError
from getmeajob.rank.prefs import Preferences, parse_preferences
from getmeajob.yamlio import load_yaml

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    "path", ["examples/demo/preferences.yaml", "config/preferences.example.yaml"]
)
def test_shipped_files_have_the_documented_schema(path: str) -> None:
    data = load_yaml(ROOT / path)
    data.setdefault("candidate", {})["years_experience"] = 3  # the template leaves it blank
    prefs = parse_preferences(data)
    assert isinstance(prefs, Preferences)
    assert {t.kind for t in prefs.tiers} == {
        "remote_worldwide",
        "remote_home_country",
        "hybrid_home_city",
        "onsite_home_city",
        "home_country_other",
        "other",
    }


def test_demo_preferences_values(prefs: Preferences) -> None:
    assert prefs.years == 4
    assert prefs.home.city == "Springfield"
    assert [t.name for t in prefs.tracks] == ["backend", "platform"]
    assert prefs.skills_have["python"] == 3
    assert prefs.skills_lack == ["go", "rust", "scala"]
    assert prefs.needs_sponsorship_in == ["United States"]
    assert prefs.shortlist == 50


def test_years_are_required() -> None:
    with pytest.raises(ConfigError) as err:
        parse_preferences({"candidate": {"years_experience": None}})
    assert "years of experience" in err.value.message
    assert err.value.hint


@pytest.mark.parametrize(
    "data",
    [
        {"candidate": {"years_experience": "lots"}},
        {"candidate": {"years_experience": 3}, "tracks": "backend"},
        {"candidate": {"years_experience": 3}, "tracks": [{"title_any": ["x"]}]},
        {"candidate": {"years_experience": 3}, "locations": {"tiers": [{"kind": "mars"}]}},
        {"candidate": {"years_experience": 3}, "skills": {"have": 7}},
        {
            "candidate": {"years_experience": 3},
            "weights": {"title": 0, "experience": 0, "location": 0, "skills": 0},
        },
    ],
)
def test_bad_values_give_a_friendly_error(data: dict[str, Any]) -> None:
    with pytest.raises(ConfigError) as err:
        parse_preferences(data)
    assert err.value.hint


def test_missing_sections_use_defaults() -> None:
    prefs = parse_preferences({"candidate": {"years_experience": 5}})
    assert prefs.too_senior_over == 8
    assert prefs.tier_for("hybrid_home_city").score == 0.8
    assert prefs.weights["skills"] == 20
    assert prefs.shortlist == 60


def test_unknown_sections_are_ignored() -> None:
    prefs = parse_preferences(
        {"candidate": {"years_experience": 5}, "apply": {"per_company_cap": 2}}
    )
    assert prefs.years == 5


def test_skills_have_accepts_a_plain_list() -> None:
    prefs = parse_preferences(
        {"candidate": {"years_experience": 1}, "skills": {"have": ["Python"]}}
    )
    assert prefs.skills_have == {"python": 1.0}
