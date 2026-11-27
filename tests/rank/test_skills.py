from __future__ import annotations

import pytest

from getmeajob.rank.prefs import Preferences
from getmeajob.rank.skills import canonical_names, find_skills, mentions, skill_matches


@pytest.mark.parametrize(
    "text",
    [
        "Our go to market plan is ready.",
        "Go to market strategy for new products.",
        "A go-getter with a can-do attitude.",
        "Go-getter wanted.",
        "Let's go. Ready to go live next week.",
        "Go ahead and apply.",
    ],
)
def test_go_word_boundary(text: str) -> None:
    assert not mentions(text, "go")


@pytest.mark.parametrize(
    "text",
    [
        "We use Golang for services.",
        "Languages: Python, Go, Rust",
        "Experience with Go and Python",
        "You will write services in Go.",
        "Go (Golang) experience",
        "Strong Go programming skills",
        "Python/Go/Rust",
    ],
)
def test_go_as_a_language_matches(text: str) -> None:
    assert mentions(text, "go")


def test_java_is_not_javascript() -> None:
    assert not mentions("We write JavaScript and TypeScript.", "java")
    assert mentions("Java and Kotlin on the server", "java")


def test_aliases_find_the_same_text() -> None:
    assert mentions("We run PostgreSQL", "postgres")
    assert mentions("We run Postgres", "postgresql")
    assert mentions("We run k8s clusters", "kubernetes")


def test_unknown_skill_is_searched_as_plain_text() -> None:
    assert mentions("Experience with Elixir is welcome", "elixir")
    assert not mentions("A pelixirous plan", "elixir")


def test_special_characters() -> None:
    assert mentions("C++ and C# developers", "c++")
    assert mentions("C++ and C# developers", "c#")
    assert mentions("ASP.NET services", ".net")
    assert not mentions("Mail us at jobs@example.net", ".net")
    assert mentions("We use CI/CD pipelines", "ci/cd")


def test_react_the_library_not_the_verb() -> None:
    assert mentions("Build UIs with React and Vue", "react")
    assert not mentions("You react to incidents quickly", "react")


def test_catalog_has_about_sixty_skills() -> None:
    assert len(canonical_names()) >= 60


def test_find_skills_counts() -> None:
    found = find_skills("Python, Python and more Python. Also Docker.")
    assert found["python"] == 3
    assert found["docker"] == 1
    assert "go" not in found


def test_skill_matches_splits_have_and_gaps(prefs: Preferences) -> None:
    text = "We use Python, PostgreSQL, Kubernetes and Go for services."
    have, gaps = skill_matches(text, prefs)
    assert have == ["python", "kubernetes", "postgres"]
    assert gaps == ["go"]


def test_gaps_are_only_looked_for_near_the_top(prefs: Preferences) -> None:
    text = "x " * 4000 + " Rust experience"
    assert skill_matches(text, prefs)[1] == []
