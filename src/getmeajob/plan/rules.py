"""Answer rules as data: load them and apply the first one that fits a question.

A rule file (`rules_default.yaml` in this package, `rules.yaml` in the workspace) holds
`rules: [{id, match[], exclude[], types[], answer: {kind, field, options_pref[]}}]`.
User rules come first; a user rule with the same id replaces the default one.
The answer kinds live in `getmeajob.plan.kinds`.
"""

from __future__ import annotations

import dataclasses
import functools
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from importlib import resources
from typing import Any

import yaml

from getmeajob.errors import ConfigError
from getmeajob.models import Job, Question, QuestionType
from getmeajob.plan.profile import Profile
from getmeajob.textutil import html_to_text, norm_label
from getmeajob.workspace import Workspace
from getmeajob.yamlio import load_yaml

KINDS = frozenset(
    {
        "never",
        "field",
        "yes_no",
        "years",
        "years_threshold",
        "choice_from",
        "eeo",
        "consent",
        "skip_optional",
        "sponsorship",
        "work_authorization",
        "former_employer",
        "location",
        "compensation",
        "current_compensation",
        "file",
        "education",
        "primary_language",
        "skill_yes_no",
    }
)
DEFAULT_RULES_FILE = "rules_default.yaml"


@dataclass
class Rule:
    id: str
    match: list[re.Pattern[str]]
    exclude: list[re.Pattern[str]]
    types: set[QuestionType] | None
    kind: str
    field: str | None
    options_pref: list[str] = dataclasses.field(default_factory=list)

    def fits(self, q: Question, label: str, description: str = "") -> bool:
        if self.types is not None and q.type not in self.types:
            return False
        haystack = f"{label}\n{description}" if self.kind == "never" else label
        if self.match and not any(p.search(haystack) for p in self.match):
            return False
        return not any(p.search(label) for p in self.exclude)


@dataclass
class RuleOutcome:
    """`source` is `rule:<id>`, `file`, `skip` or `unknown`. `reason` explains it."""

    value: str | list[str] | None
    source: str
    reason: str

    @property
    def answered(self) -> bool:
        return self.source not in ("skip", "unknown")


# ------------------------------------------------------------------ loading


def _flatten(items: Any) -> list[str]:
    """YAML anchors can nest lists (`[*people, 'x']`); flatten them into strings."""
    if items is None:
        return []
    if isinstance(items, str):
        return [items]
    out: list[str] = []
    if isinstance(items, Iterable):
        for item in items:
            out.extend(_flatten(item))
    return out


def _compile(patterns: list[str], where: str) -> list[re.Pattern[str]]:
    compiled: list[re.Pattern[str]] = []
    for pattern in patterns:
        try:
            compiled.append(re.compile(pattern, re.IGNORECASE))
        except re.error as exc:
            raise ConfigError(
                f"{where}: the pattern {pattern!r} is not a valid regular expression ({exc}).",
                hint="Fix the pattern. Remember to write a literal dot as \\. in a pattern.",
            ) from exc
    return compiled


def parse_rule(raw: Mapping[str, Any], where: str) -> Rule:
    """One rule from its YAML mapping. Raises ConfigError naming the file and rule."""
    rule_id = str(raw.get("id") or "").strip()
    if not rule_id:
        raise ConfigError(f"{where}: a rule has no id.", hint="Give every rule an `id:`.")
    answer = raw.get("answer") or {}
    if not isinstance(answer, Mapping):
        raise ConfigError(
            f"{where}: rule '{rule_id}' has a bad `answer`.", hint="See docs/planning.md."
        )
    kind = str(answer.get("kind") or "").strip()
    if kind not in KINDS:
        raise ConfigError(
            f"{where}: rule '{rule_id}' has an unknown answer kind {kind!r}.",
            hint="Use one of: " + ", ".join(sorted(KINDS)) + ".",
        )
    types: set[QuestionType] | None = None
    if raw.get("types") is not None:
        types = set()
        for name in _flatten(raw.get("types")):
            try:
                types.add(QuestionType(str(name)))
            except ValueError as exc:
                raise ConfigError(
                    f"{where}: rule '{rule_id}' names an unknown question type {name!r}.",
                    hint="Use: " + ", ".join(t.value for t in QuestionType) + ".",
                ) from exc
    place = f"{where}, rule '{rule_id}'"
    raw_field = answer.get("field")
    return Rule(
        id=rule_id,
        match=_compile(_flatten(raw.get("match")), place),
        exclude=_compile(_flatten(raw.get("exclude")), place),
        types=types,
        kind=kind,
        field=str(raw_field).strip() if raw_field else None,
        options_pref=_flatten(answer.get("options_pref")),
    )


def parse_rules(data: Mapping[str, Any], where: str) -> list[Rule]:
    raw_rules = data.get("rules") or []
    if not isinstance(raw_rules, list):
        raise ConfigError(f"{where}: `rules` should be a list.", hint="See docs/planning.md.")
    return [parse_rule(r, where) for r in raw_rules if isinstance(r, Mapping)]


@functools.lru_cache(maxsize=1)
def default_rules_text() -> str:
    return (resources.files("getmeajob.plan") / DEFAULT_RULES_FILE).read_text(encoding="utf-8")


@functools.lru_cache(maxsize=1)
def _default_data() -> dict[str, Any]:
    loaded = yaml.safe_load(default_rules_text())
    return loaded if isinstance(loaded, dict) else {}


def default_rules() -> list[Rule]:
    return parse_rules(_default_data(), DEFAULT_RULES_FILE)


def default_country_aliases() -> dict[str, list[str]]:
    raw = _default_data().get("country_aliases") or {}
    return {str(k): _flatten(v) for k, v in raw.items()} if isinstance(raw, Mapping) else {}


def _user_data(ws: Workspace | None) -> dict[str, Any]:
    if ws is None:
        return {}
    return load_yaml(ws.user_rules_path, required=False)


def load_rules(ws: Workspace | None) -> list[Rule]:
    """User rules (`rules.yaml`) first, then the packaged defaults not replaced by id."""
    user = parse_rules(_user_data(ws), "rules.yaml") if ws is not None else []
    taken = {r.id for r in user}
    return user + [r for r in default_rules() if r.id not in taken]


# ----------------------------------------------------------------- applying


def find_rule(q: Question, rules: Sequence[Rule]) -> Rule | None:
    label = norm_label(q.label)
    description = html_to_text(q.description or "").casefold() if q.description else ""
    for rule in rules:
        if rule.fits(q, label, description):
            return rule
    return None


def answer_question(
    q: Question,
    profile: Profile,
    rules: Sequence[Rule],
    company: str,
    *,
    job: Job | None = None,
) -> RuleOutcome:
    """Answer one question from the profile with the first rule that fits.

    Returns a RuleOutcome whose source is `rule:<id>` (or `file`) when answered. When the
    rules cannot answer truthfully, a required question gives `unknown` and an optional
    one gives `skip`, each with a reason. `job` (optional) lets the sponsorship and
    work-permit rules read the job location when the question names no country.
    """
    from getmeajob.plan.kinds import apply_kind

    if q.type == QuestionType.hidden:
        return RuleOutcome(None, "skip", "hidden field")
    if q.type == QuestionType.unknown:
        what = q.board_type or "unknown"
        outcome = RuleOutcome(None, "unknown", f"getmeajob cannot read this field type ({what})")
        return _settle(q, outcome)
    rule = find_rule(q, rules)
    if rule is None and q.section in ("demographic", "compliance"):
        rule = Rule("eeo_section", [], [], None, "eeo", None)
    if rule is None:
        return _settle(q, RuleOutcome(None, "unknown", "no rule fits this question"))
    outcome = apply_kind(rule, q, profile, company, job)
    return _settle(q, outcome)


def _settle(q: Question, outcome: RuleOutcome) -> RuleOutcome:
    """An unanswerable optional question is left blank (skip), never guessed."""
    if outcome.source == "unknown" and not q.required:
        return RuleOutcome(None, "skip", outcome.reason)
    return outcome
