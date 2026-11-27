from __future__ import annotations

from typing import Any

import pytest

from getmeajob.errors import ConfigError
from getmeajob.resume.bank import Bank, load_bank, parse_bank
from getmeajob.workspace import Workspace


def test_demo_bank_loads(demo_ws: Workspace) -> None:
    bank = load_bank(demo_ws)
    assert bank.header.name == "Alex Example"
    assert len(bank.experience) == 2
    assert len(bank.all_bullets()) == 8
    assert bank.skills["languages"] == ["Python", "SQL"]
    assert bank.education[0].school == "Example State University"
    assert bank.experience[0].bullets[0].short


def test_hash_is_stable_and_changes_with_content(bank: Bank) -> None:
    assert bank.hash and len(bank.hash) == 16
    changed = parse_bank(
        {"header": {"name": "Alex Example"}, "summaries": [{"id": "s", "text": "Hello."}]}
    )
    assert changed.hash != bank.hash


def test_missing_bank_file_is_friendly(tmp_ws: Workspace) -> None:
    with pytest.raises(ConfigError) as err:
        load_bank(tmp_ws)
    assert "fact bank" in err.value.message
    assert err.value.hint


@pytest.mark.parametrize(
    "data",
    [
        {},
        {"header": {"email": "a@example.com"}},
        {"header": {"name": "A"}, "experience": [{"company": "X", "bullets": [{"text": "t"}]}]},
        {
            "header": {"name": "A"},
            "experience": [
                {
                    "company": "X",
                    "bullets": [{"id": "a", "text": "one"}, {"id": "a", "text": "two"}],
                }
            ],
        },
        {"header": {"name": "A"}, "summaries": [{"text": "no id"}]},
        {"header": {"name": "A"}, "skills": ["python"]},
        {"header": {"name": "A"}, "experience": "none"},
    ],
)
def test_bad_banks_give_friendly_errors(data: dict[str, Any]) -> None:
    with pytest.raises(ConfigError) as err:
        parse_bank(data)
    assert err.value.hint


def test_numbers_in_dates_become_text() -> None:
    bank = parse_bank(
        {
            "header": {"name": "A"},
            "education": [{"school": "S", "start": 2017, "end": 2021}],
        }
    )
    assert (bank.education[0].start, bank.education[0].end) == ("2017", "2021")
