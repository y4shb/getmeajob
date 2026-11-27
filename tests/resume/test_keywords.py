from __future__ import annotations

from getmeajob.resume.keywords import coverage, jd_keywords, term_present


def test_known_skills_come_first_by_frequency() -> None:
    text = "Python everywhere. Python and more Python. Docker once."
    assert jd_keywords(text)[:2] == ["python", "docker"]


def test_extra_terms_only_when_the_text_has_them() -> None:
    text = "We run Helm charts on Kubernetes."
    keywords = jd_keywords(text, ["Helm", "Terraform", "billing"])
    assert "Helm" in keywords or "helm" in keywords
    assert "Terraform" not in keywords
    assert "billing" not in keywords


def test_aliases_are_not_repeated() -> None:
    keywords = jd_keywords("We use PostgreSQL and Postgres.", ["PostgreSQL", "postgres"])
    assert len([k for k in keywords if "postgres" in k.lower()]) == 1


def test_acronyms_and_camel_case_names() -> None:
    keywords = jd_keywords("You will join the SRE team and use OpenTelemetry. EEO employer.")
    assert "SRE" in keywords
    assert "OpenTelemetry" in keywords
    assert "EEO" not in keywords


def test_ci_cd_is_one_keyword() -> None:
    keywords = jd_keywords("We maintain our CI/CD pipeline.")
    assert "ci/cd" in keywords
    assert "CD" not in keywords and "CI" not in keywords


def test_coverage_splits_matched_and_missing() -> None:
    jd = "Python, PostgreSQL, Kubernetes and Terraform are used here."
    cover = coverage(jd, "I wrote Python with Postgres on Kubernetes.")
    assert cover.matched == ["python", "postgres", "kubernetes"] or set(cover.matched) == {
        "python",
        "postgres",
        "kubernetes",
    }
    assert cover.missing == ["terraform"]
    assert 0.7 < cover.ratio < 0.8


def test_coverage_of_a_job_with_no_keywords() -> None:
    cover = coverage("Come and join us.", "anything")
    assert cover.matched == [] and cover.missing == [] and cover.ratio == 0.0


def test_term_present_uses_word_boundaries() -> None:
    assert term_present("We love Go, Rust and Python", "go")
    assert not term_present("Let us go to market", "go")
    assert not term_present("javascript", "java")
