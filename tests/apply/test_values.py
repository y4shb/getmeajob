"""Pure helpers: number, date and phone coercion, repeater rows, location choice."""

from __future__ import annotations

import copy

import pytest

from getmeajob.apply.values import (
    EducationRow,
    coerce_date,
    coerce_number,
    education_rows,
    employment_rows,
    local_phone,
    match_degree,
    month_name,
    pick_location,
)
from getmeajob.demo import examples_dir
from getmeajob.plan.profile import Profile
from getmeajob.yamlio import load_yaml

SPRINGFIELDS = [
    "Springfield, Illinois, United States",
    "Springfield, Ontario, Canada",
    "Springfield, Missouri, United States",
]


@pytest.fixture
def profile() -> Profile:
    return Profile(data=load_yaml(examples_dir() / "demo" / "profile.yaml"))


def _with(profile: Profile, **location: object) -> Profile:
    data = copy.deepcopy(profile.data)
    data["location"].update(location)
    return Profile(data=data)


@pytest.mark.parametrize(
    ("value", "label", "expected"),
    [
        ("4", "", "4"),
        ("4 years", "Years of experience", "4"),
        ("about 4.5", "", "4.5"),
        ("CAD 95,000 per year", "Expected salary", "95000"),
        ("none", "", None),
    ],
)
def test_coerce_number(value: str, label: str, expected: str | None) -> None:
    assert coerce_number(value, label) == expected


def test_coerce_date_and_month() -> None:
    assert coerce_date("2026-12") == "2026-12-01"
    assert coerce_date("2026-02-09") == "2026-02-09"
    assert coerce_date("next week") is None
    assert month_name("2021-06") == "June"
    assert month_name("13") is None


def test_local_phone(profile: Profile) -> None:
    assert local_phone("+1 555 0100", profile) == "5550100"
    data = copy.deepcopy(profile.data)
    data["contact"]["phone_local"] = None
    assert local_phone("+1 555 0100", Profile(data=data)) == "5550100"


def test_rows_from_plan_and_profile(profile: Profile) -> None:
    rows = education_rows(
        ["Example State University | Bachelor of Science | Computer Science | 2017-2021"], profile
    )
    assert rows == [
        EducationRow(
            school="Example State University",
            degree="Bachelor of Science",
            discipline="Computer Science",
            start_year="2017",
            end_year="2021",
            degree_level="bachelors",
        )
    ]
    jobs = employment_rows(profile)
    assert [(r.company, r.current, r.start_month, r.end_month) for r in jobs] == [
        ("Initech Example Ltd", True, "June", None),
        ("Globex Example Inc", False, "May", "August"),
    ]


def test_degree_by_level_when_the_name_differs(profile: Profile) -> None:
    row = education_rows(
        ["Example State University | Bachelor of Science | CS | 2017-2021"], profile
    )[0]
    options = ["High School", "Bachelor's Degree", "Master's Degree", "Other"]
    assert match_degree(row, options).option == "Bachelor's Degree"
    assert match_degree(row, ["Bachelor's Degree", "Bachelor of Arts (B.A.)"]).option is None


def test_pick_location_is_never_the_first_by_default(profile: Profile) -> None:
    assert pick_location(SPRINGFIELDS, profile).option == "Springfield, Ontario, Canada"
    no_region = _with(profile, state=None, country=None)
    assert pick_location(SPRINGFIELDS, no_region).method == "ambiguous"
    only_wrong = pick_location(SPRINGFIELDS[:1], profile)
    assert only_wrong.option is None and "state or country" in only_wrong.reason
    assert pick_location(["Toronto, Ontario, Canada"], profile).option is None
    assert pick_location([], profile).reason == "no suggestions appeared"
