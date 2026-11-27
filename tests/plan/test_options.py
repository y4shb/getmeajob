from __future__ import annotations

from getmeajob.plan.options import match_many, match_option, match_years, polarity


def test_exact() -> None:
    result = match_option("Hybrid", ["Remote", "Hybrid", "Onsite"])
    assert (result.option, result.method) == ("Hybrid", "exact")
    assert match_option("hybrid ", ["Remote", "Hybrid*"]).option == "Hybrid*"


def test_yes_no_synonyms() -> None:
    assert match_option(True, ["Yes", "No"]).option == "Yes"
    assert match_option(False, ["Yes", "No"]).option == "No"
    assert match_option(True, ["I agree", "I do not agree"]).option == "I agree"
    assert match_option(False, ["I agree", "I do not agree"]).option == "I do not agree"
    assert match_option(True, ["Yes, I am authorized", "No, I am not"]).option == (
        "Yes, I am authorized"
    )
    assert match_option("yes", ["Yes - happy to", "No"]).option == "Yes - happy to"
    assert polarity("I'm not") == "no" and polarity("Yep") == "yes"


def test_decline_variants() -> None:
    for label in (
        "Decline to self-identify",
        "I don't wish to answer",
        "Prefer not to say",
        "I choose not to disclose",
        "I do not want to answer",
    ):
        options = ["Man", "Woman", label]
        result = match_option("", options, kind="decline")
        assert result.option == label, label
    assert match_option("", ["Man", "Woman"], kind="decline").option is None
    # "No, I don't have a disability" is a real answer, not a decline.
    assert polarity("No, I don't have a disability") == "no"


def test_years_ranges() -> None:
    options = ["0-2", "3-5", "6-9", "10+"]
    assert match_years(4, options).option == "3-5"
    assert match_years(12, options).option == "10+"
    assert match_years(1, options).option == "0-2"
    assert match_years(4.5, options).option == "3-5"
    assert match_option(4, options, kind="years").option == "3-5"
    assert match_years(0.5, ["Less than 1 year", "1-3 years", "More than 3 years"]).option == (
        "Less than 1 year"
    )
    assert match_years(4, ["1+ years", "3+ years", "5+ years"]).option == "3+ years"
    assert match_years(4, ["5-7", "8+"]).option is None


def test_ambiguous_returns_none() -> None:
    options = ["Yes, I will require sponsorship", "Yes, I have sponsorship", "No"]
    result = match_option(True, options)
    assert result.option is None
    assert result.method == "ambiguous"
    assert "not guessing" in result.reason
    assert match_option(False, options).option == "No"
    two_bachelors = match_option("Bachelor", ["Bachelor of Arts", "Bachelor of Science"])
    assert two_bachelors.option is None and two_bachelors.method == "ambiguous"
    assert match_years(2, ["0-2", "1-3"]).option is None


def test_never_first_option() -> None:
    for desired in ("Purple", "Springfield", "zzz"):
        result = match_option(desired, ["Red", "Green", "Blue"])
        assert result.option is None, desired
        assert result.method == "none" and result.reason
    assert match_option(True, ["Red", "Green"]).option is None
    assert match_option("Red", []).option is None


def test_fuzzy_needs_margin_and_containment() -> None:
    assert match_option("Bachelors degree", ["Bachelor's degree", "Master's degree"]).ok
    assert match_option("Canada", ["Canada (remote)", "United States"]).option == (
        "Canada (remote)"
    )
    chosen, problems = match_many(["Python", "Cobol"], ["Python", "Go"])
    assert chosen == ["Python"] and len(problems) == 1
