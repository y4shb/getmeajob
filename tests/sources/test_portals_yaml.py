from __future__ import annotations

from pathlib import Path

import pytest

from getmeajob.errors import ConfigError
from getmeajob.sources.portals_yaml import import_portals, location_allowed, title_matches

FIXTURE = Path(__file__).parent / "fixtures" / "portals.yml"


def test_maps_entries_and_reports_unsupported() -> None:
    result = import_portals(FIXTURE)
    got = [(b.company, b.ats, b.slug, b.enabled, b.region) for b in result.boards]
    assert got == [
        ("Example Corp", "greenhouse", "examplecorp", True, None),
        ("Sample Systems", "ashby", "samplesystems", True, None),
        ("Demo Widgets", "lever", "demowidgets", False, "eu"),
    ]
    assert result.boards[1].notes == "hybrid in Springfield"
    assert result.boards[1].careers_url == "https://jobs.ashbyhq.com/samplesystems"
    reasons = dict(result.unsupported)
    assert "web-search" in reasons["Placeholder Labs"]
    assert "workday" in reasons["Widget Payroll"] and "not supported" in reasons["Widget Payroll"]
    assert "no greenhouse board URL" in reasons["Greenhouse Without Url"]
    assert "duplicate of ashby:samplesystems" in reasons["Sample Systems Again"]
    assert reasons["tracked_companies entry 8"] == "no name"
    assert "--feeds remotive" in reasons["Remote Board"]
    assert result.title_include == ["Backend", "word:SRE", "platform + engineer"]
    assert result.title_exclude == ["word:Manager", "Intern"]
    assert result.location_rules["block_hard"] == ["Onsite only"]
    assert result.aliases == {"Example Corp": ["ExampleCo", "Example Corporation"]}


def test_title_filter_semantics() -> None:
    include = ["Backend", "word:SRE", "stem:data", "platform + engineer", "ML"]
    exclude = ["word:Manager", "Intern"]
    assert title_matches("Senior Backend Engineer", include, exclude)
    assert title_matches("SRE, Payments", include, exclude)
    assert not title_matches("SREs Team Lead", ["word:SRE"], [])
    assert title_matches("Database Administrator", ["stem:data"], [])
    assert not title_matches("Big-Data-less role", ["stem:ata"], [])
    assert title_matches("Engineer, Platform", include, exclude)  # all of, any order
    assert not title_matches("Platform Designer", include, exclude)
    assert title_matches("ML Researcher", include, exclude)
    assert not title_matches("HTML Developer", ["ML"], [])  # short words match whole words
    assert not title_matches("Backend Engineering Manager", include, exclude)
    assert title_matches("Management Backend", include, exclude)  # word: means whole word
    assert not title_matches("Backend Internship", include, exclude)  # plain exclude: substring
    assert title_matches("Anything at all", [], exclude)


def test_location_filter_order() -> None:
    rules = {
        "always_allow": ["Springfield"],
        "allow": ["Remote", "Canada"],
        "block": ["United States"],
        "block_hard": ["Onsite only"],
    }
    assert location_allowed("", rules)
    assert not location_allowed("Springfield, Onsite only", rules)  # block_hard wins
    assert location_allowed("Springfield, United States", rules)  # always_allow beats block
    assert not location_allowed("Remote - United States", rules)
    assert location_allowed("Toronto, Canada", rules)
    assert not location_allowed("Lisbon, Portugal", rules)
    assert location_allowed("Lisbon, Portugal", {"block": ["Canada"]})


def test_bad_yaml_is_a_friendly_error(tmp_path: Path) -> None:
    bad = tmp_path / "portals.yml"
    bad.write_text("tracked_companies:\n  - name: [unclosed\n", encoding="utf-8")
    with pytest.raises(ConfigError) as info:
        import_portals(bad)
    assert "line" in info.value.message and info.value.hint
