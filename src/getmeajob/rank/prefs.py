"""Your preferences: what you are looking for, read from `preferences.yaml`.

Ranking reads everything from here. No place, title or skill is built into the code.
The file is documented in `config/preferences.example.yaml`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from getmeajob.errors import ConfigError
from getmeajob.workspace import Workspace
from getmeajob.yamlio import load_yaml, string_list

TIER_KINDS = (
    "remote_worldwide",
    "remote_home_country",
    "hybrid_home_city",
    "onsite_home_city",
    "home_country_other",
    "other",
)

DEFAULT_TIER_SCORES = {
    "remote_worldwide": 1.0,
    "remote_home_country": 1.0,
    "hybrid_home_city": 0.8,
    "onsite_home_city": 0.6,
    "home_country_other": 0.3,
    "other": 0.0,
}

DEFAULT_WEIGHTS = {"experience": 30.0, "title": 25.0, "location": 25.0, "skills": 20.0}


@dataclass(slots=True)
class Home:
    city: str = ""
    region: str = ""
    country: str = ""
    city_aliases: list[str] = field(default_factory=list)
    country_aliases: list[str] = field(default_factory=list)


@dataclass(slots=True)
class Track:
    name: str
    title_any: list[str] = field(default_factory=list)
    jd_any: list[str] = field(default_factory=list)
    weight: float = 1.0


@dataclass(slots=True)
class TierDef:
    name: str
    kind: str
    score: float


@dataclass(slots=True)
class Preferences:
    years: float
    home: Home = field(default_factory=Home)
    tracks: list[Track] = field(default_factory=list)
    title_exclude: list[str] = field(default_factory=list)
    title_too_senior: list[str] = field(default_factory=list)
    title_junior: list[str] = field(default_factory=list)
    stretch_years: float = 2.0
    too_senior_over: float = 0.0
    tiers: list[TierDef] = field(default_factory=list)
    allowed_regions: list[str] = field(default_factory=list)
    region_aliases: dict[str, list[str]] = field(default_factory=dict)
    skills_have: dict[str, float] = field(default_factory=dict)
    skills_lack: list[str] = field(default_factory=list)
    needs_sponsorship_in: list[str] = field(default_factory=list)
    authorized_in: list[str] = field(default_factory=list)
    has_clearance: bool = False
    citizenships: list[str] = field(default_factory=list)
    weights: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))
    shortlist: float = 60.0
    exclude_companies: list[str] = field(default_factory=list)

    def tier_for(self, kind: str) -> TierDef:
        for tier in self.tiers:
            if tier.kind == kind:
                return tier
        return TierDef(name=kind.replace("_", " "), kind=kind, score=DEFAULT_TIER_SCORES[kind])


def _strings(value: Any, where: str) -> list[str]:
    items = string_list(value)
    if items is None:
        raise ConfigError(
            f"preferences.yaml: '{where}' should be a list of words.",
            hint="Write it like `[one, two]` or as a list with one `- item` per line.",
        )
    return items


def _number(value: Any, where: str, default: float) -> float:
    if value is None or value == "":
        return default
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ConfigError(
            f"preferences.yaml: '{where}' should be a number, not {value!r}.",
            hint="Write plain numbers such as 4 or 0.8.",
        )
    return float(value)


def _mapping(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = data.get(key)
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ConfigError(
            f"preferences.yaml: '{key}' should hold named settings, not a {type(value).__name__}.",
            hint="Compare it with config/preferences.example.yaml.",
        )
    return value


def _tracks(raw: Any) -> list[Track]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ConfigError(
            "preferences.yaml: 'tracks' should be a list.",
            hint="Each track needs a name, title_any, jd_any and weight.",
        )
    tracks: list[Track] = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict) or not str(item.get("name") or "").strip():
            raise ConfigError(
                f"preferences.yaml: track number {i + 1} needs a name.",
                hint="Example: `- name: backend` with `title_any: [backend]` under it.",
            )
        weight = _number(item.get("weight"), f"tracks.{i}.weight", 1.0)
        tracks.append(
            Track(
                name=str(item["name"]).strip(),
                title_any=_strings(item.get("title_any"), f"tracks.{i}.title_any"),
                jd_any=_strings(item.get("jd_any"), f"tracks.{i}.jd_any"),
                weight=min(1.0, max(0.0, weight)),
            )
        )
    return tracks


def _tiers(raw: Any) -> list[TierDef]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ConfigError(
            "preferences.yaml: 'locations.tiers' should be a list.",
            hint="Each tier needs a name, a kind and a score from 0 to 1.",
        )
    tiers: list[TierDef] = []
    for i, item in enumerate(raw):
        kind = str(item.get("kind") or "").strip() if isinstance(item, dict) else ""
        if kind not in TIER_KINDS:
            raise ConfigError(
                f"preferences.yaml: location tier number {i + 1} has kind {kind!r}.",
                hint="Use one of: " + ", ".join(TIER_KINDS) + ".",
            )
        score = _number(item.get("score"), f"locations.tiers.{i}.score", DEFAULT_TIER_SCORES[kind])
        tiers.append(
            TierDef(
                name=str(item.get("name") or kind.replace("_", " ")),
                kind=kind,
                score=min(1.0, max(0.0, score)),
            )
        )
    return tiers


def _have(raw: Any) -> dict[str, float]:
    if raw is None:
        return {}
    if isinstance(raw, list):
        return {str(name).strip().lower(): 1.0 for name in raw if str(name).strip()}
    if isinstance(raw, dict):
        return {
            str(name).strip().lower(): max(0.0, _number(w, f"skills.have.{name}", 1.0))
            for name, w in raw.items()
            if str(name).strip()
        }
    raise ConfigError(
        "preferences.yaml: 'skills.have' should be a list or `name: weight` lines.",
        hint="Example: `have: {python: 3, postgres: 2}`.",
    )


def _aliases(raw: Any) -> dict[str, list[str]]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ConfigError(
            "preferences.yaml: 'locations.region_aliases' should be `name: [other names]` lines.",
            hint="Example: `region_aliases: {united kingdom: [uk, britain]}`.",
        )
    return {str(k).strip().lower(): _strings(v, f"region_aliases.{k}") for k, v in raw.items()}


def parse_preferences(data: dict[str, Any]) -> Preferences:
    """Build `Preferences` from the parsed YAML mapping, with friendly errors."""
    candidate = _mapping(data, "candidate")
    years_raw = candidate.get("years_experience")
    if years_raw is None or years_raw == "":
        raise ConfigError(
            "preferences.yaml does not say how many years of experience you have.",
            hint="Set `candidate: years_experience:` to a number, for example 4.",
        )
    years = _number(years_raw, "candidate.years_experience", 0.0)
    home_raw = _mapping(candidate, "home")
    home = Home(
        city=str(home_raw.get("city") or "").strip(),
        region=str(home_raw.get("region") or "").strip(),
        country=str(home_raw.get("country") or "").strip(),
        city_aliases=_strings(home_raw.get("city_aliases"), "candidate.home.city_aliases"),
        country_aliases=_strings(home_raw.get("country_aliases"), "candidate.home.country_aliases"),
    )
    title = _mapping(data, "title")
    experience = _mapping(data, "experience")
    stretch = _number(experience.get("stretch_years"), "experience.stretch_years", 2.0)
    too_senior = _number(experience.get("too_senior_over"), "experience.too_senior_over", years + 3)
    locations = _mapping(data, "locations")
    skills = _mapping(data, "skills")
    elig = _mapping(data, "eligibility")
    weights = dict(DEFAULT_WEIGHTS)
    for name, raw in _mapping(data, "weights").items():
        if name in weights:
            weights[name] = max(0.0, _number(raw, f"weights.{name}", weights[name]))
    if sum(weights.values()) <= 0:
        raise ConfigError(
            "preferences.yaml: all four weights are zero.",
            hint="Give at least one of experience, title, location, skills a weight above 0.",
        )
    thresholds = _mapping(data, "thresholds")
    return Preferences(
        years=years,
        home=home,
        tracks=_tracks(data.get("tracks")),
        title_exclude=_strings(title.get("exclude"), "title.exclude"),
        title_too_senior=_strings(title.get("too_senior"), "title.too_senior"),
        title_junior=_strings(title.get("junior"), "title.junior"),
        stretch_years=max(0.0, stretch),
        too_senior_over=too_senior,
        tiers=_tiers(locations.get("tiers")),
        allowed_regions=_strings(locations.get("allowed_regions"), "locations.allowed_regions"),
        region_aliases=_aliases(locations.get("region_aliases")),
        skills_have=_have(skills.get("have")),
        skills_lack=[s.lower() for s in _strings(skills.get("lack"), "skills.lack")],
        needs_sponsorship_in=_strings(elig.get("needs_sponsorship_in"), "needs_sponsorship_in"),
        authorized_in=_strings(elig.get("authorized_in"), "eligibility.authorized_in"),
        has_clearance=bool(elig.get("has_clearance")),
        citizenships=_strings(elig.get("citizenships"), "eligibility.citizenships"),
        weights=weights,
        shortlist=_number(thresholds.get("shortlist"), "thresholds.shortlist", 60.0),
        exclude_companies=_strings(data.get("exclude_companies"), "exclude_companies"),
    )


def load_preferences(ws: Workspace) -> Preferences:
    """Read `preferences.yaml` from the workspace."""
    return parse_preferences(load_yaml(ws.preferences_path))
