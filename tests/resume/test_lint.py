from __future__ import annotations

from getmeajob.resume.lint import lint_text


def test_clean_text_has_no_warnings() -> None:
    assert lint_text("- Built a billing API in Python.\n- Cut query time from 9 s to 400 ms.") == []


def test_weak_openers() -> None:
    warnings = lint_text("- Responsible for the billing API.\n* Worked on dashboards.")
    assert len(warnings) == 2
    assert warnings[0].startswith("line 1:") and "responsible for" in warnings[0]
    assert warnings[1].startswith("line 2:")


def test_weak_phrase_in_the_middle_is_fine() -> None:
    assert lint_text("- Built tools and worked on call rotations with the team.") == []


def test_stock_phrases() -> None:
    warnings = lint_text("Results-driven team player who leveraged synergy.")
    found = " ".join(warnings)
    for phrase in ("results-driven", "team player", "leveraged", "synergy"):
        assert phrase in found


def test_invisible_characters_and_em_dashes() -> None:
    warnings = lint_text("Built\u200b an API\n- Cut costs \u2014 a lot")
    assert any("invisible" in w and w.startswith("line 1") for w in warnings)
    assert any("em dash" in w and w.startswith("line 2") for w in warnings)


def test_en_dash_ranges_are_fine() -> None:
    assert lint_text("2021\u20132023") == []


def test_every_warning_is_one_short_line() -> None:
    for warning in lint_text("- Responsible for results-driven work \u2014 passionate about it"):
        assert "\n" not in warning and len(warning) < 100
