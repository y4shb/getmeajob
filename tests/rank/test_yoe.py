from __future__ import annotations

import pytest

from getmeajob.rank.yoe import parse_yoe


@pytest.mark.parametrize(
    ("text", "low", "high"),
    [
        ("We want 3-5 years of experience.", 3, 5),
        ("5+ years of professional experience", 5, None),
        ("at least five years", 5, None),
        ("Between 3 and 5 years of experience", 3, 5),
        ("7 yrs experience building services", 7, None),
        ("Minimum of 2 years", 2, None),
        ("3 to 5 years' experience", 3, 5),
        ("2+ years of experience with Python", 2, None),
        ("5 or more years of experience", 5, None),
    ],
)
def test_ask_is_read(text: str, low: int, high: int | None) -> None:
    result = parse_yoe(text)
    assert (result.min, result.max) == (low, high)
    assert result.snippet


@pytest.mark.parametrize(
    "text",
    [
        "Founded 20 years ago, we are a small team.",
        "We are a 10 year old company with calm weekends.",
        "A 10-year-old company with 2 offices.",
        "We have been in business for 12 years.",
        "No numbers here at all.",
        "30 years of experience in the industry",
        "Over the past 5 years we grew a lot.",
    ],
)
def test_not_an_ask_is_ignored(text: str) -> None:
    result = parse_yoe(text)
    assert result.min is None
    assert result.required is False


def test_required_beats_preferred() -> None:
    text = "Preferred: 8 years of experience.\nRequired: 3 years of experience."
    result = parse_yoe(text)
    assert result.min == 3
    assert result.required is True


def test_preferred_listed_second_is_not_required() -> None:
    text = "3+ years of experience. Nice to have: 10 years of experience."
    assert parse_yoe(text).min == 3


def test_nice_to_have_heading_marks_the_bullets_under_it() -> None:
    text = "Requirements\n- 3+ years of experience\nNice to have\n- 10 years of experience"
    assert parse_yoe(text).min == 3


def test_only_preferred_is_used_when_nothing_is_required() -> None:
    result = parse_yoe("Ideally 6 years of experience.")
    assert result.min == 6
    assert result.required is False


def test_largest_minimum_among_required_wins() -> None:
    text = "2 years of experience with SQL. 5 years of experience building APIs."
    assert parse_yoe(text).min == 5


def test_numbers_above_25_are_ignored() -> None:
    assert parse_yoe("40 years of experience").min is None
    assert parse_yoe("2 years of experience, ideally 30+ years of experience").min == 2


def test_backwards_range_drops_the_top() -> None:
    result = parse_yoe("5-3 years of experience")
    assert (result.min, result.max) == (5, None)
