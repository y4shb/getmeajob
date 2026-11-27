from __future__ import annotations

from pathlib import Path

import pytest

from getmeajob.errors import ConfigError
from getmeajob.sources.portals_yaml import import_portals

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


def test_bad_yaml_is_a_friendly_error(tmp_path: Path) -> None:
    bad = tmp_path / "portals.yml"
    bad.write_text("tracked_companies:\n  - name: [unclosed\n", encoding="utf-8")
    with pytest.raises(ConfigError) as info:
        import_portals(bad)
    assert "line" in info.value.message and info.value.hint
