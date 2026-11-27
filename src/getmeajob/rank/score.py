"""Score jobs from 0 to 100 and explain each score.

The score is four parts, each worth 0 to 1, times the weights in your preferences:
experience (years asked against yours), title (how well it fits a track), location (your
tier for it) and skills (how many of yours the job names, minus the ones you lack).
Hard flags do not change the score. They set `eligible` to False.
"""

from __future__ import annotations

import re

from getmeajob.files import now_iso, read_jsonl, write_jsonl_atomic
from getmeajob.models import AppStatus, Flag, Job, RankResult
from getmeajob.rank.eligibility import eligibility_flags
from getmeajob.rank.location import location_tier
from getmeajob.rank.prefs import Preferences, load_preferences
from getmeajob.rank.skills import skill_matches
from getmeajob.rank.titles import best_track, check_title
from getmeajob.rank.yoe import YoeResult, parse_yoe
from getmeajob.store import JobStore, StatusLog
from getmeajob.textutil import html_to_text, truncate
from getmeajob.workspace import Workspace

MAX_REASON = 89
SHORT_TEXT = 200  # a description shorter than this tells us little about skills
GAP_PENALTY = 0.25
MAX_GAP_PENALTY = 0.5
HALF_OF_SKILLS = 0.5  # naming half of your weighted skills earns the full skills score
_TAG = re.compile(r"<\w+[^>]*>|&lt;\w+|&amp;")


def _line(text: str) -> str:
    return truncate(" ".join(text.split()), MAX_REASON)


def _years(yoe: YoeResult) -> str:
    if yoe.min is None:
        return "no years stated"
    if yoe.max is not None and yoe.max != yoe.min:
        return f"{yoe.min}-{yoe.max} yrs"
    return f"{yoe.min}+ yrs" if yoe.max is None else f"{yoe.min} yrs"


def experience_part(yoe: YoeResult, prefs: Preferences) -> tuple[float, str]:
    """(0 to 1, short reason) for the years the job asks against yours."""
    mine = f"you: {prefs.years:g}"
    if yoe.min is None:
        return 0.6, "no years stated, so a middling score"
    asked = yoe.min
    label = _years(yoe)
    if asked <= prefs.years - 3:
        return 0.45, f"needs {label} ({mine}): below your level"
    if asked <= prefs.years:
        return 1.0, f"needs {label} ({mine}): fits"
    over = asked - prefs.years
    if over <= prefs.stretch_years:
        return max(0.3, 0.8 - 0.3 * (over - 1)), f"needs {label} ({mine}): a stretch"
    if asked <= prefs.too_senior_over:
        return 0.2, f"needs {label} ({mine}): a big stretch"
    return 0.0, f"needs {label} ({mine}): too senior"


def title_part(job: Job, text: str, prefs: Preferences) -> tuple[float, str, str | None]:
    """(0 to 1, short reason, track name) for the title."""
    check = check_title(job.title, prefs)
    match = best_track(job.title, text, prefs)
    if check.junior:
        return 0.2, f"title says {check.junior}: below your level", match.name if match else None
    if match is not None:
        return match.score, f"title matches track {match.name}", match.name
    if not prefs.tracks:
        return 0.5, "no tracks set in your preferences", None
    return 0.2, "title fits none of your tracks", None


def skills_part(text: str, prefs: Preferences) -> tuple[float, str, list[str], list[str]]:
    """(0 to 1, short reason, skills you have, skills you lack) for the description."""
    have, gaps = skill_matches(text, prefs)
    if len(text) < SHORT_TEXT:
        return 0.5, "description too short to judge skills", have, gaps
    total = sum(prefs.skills_have.values())
    if total <= 0:
        base = 0.5
    else:
        base = min(1.0, sum(prefs.skills_have[n] for n in have) / total / HALF_OF_SKILLS)
    value = max(0.0, base - min(MAX_GAP_PENALTY, GAP_PENALTY * len(gaps)))
    named = ", ".join(have[:5]) if have else "none of yours named"
    reason = f"skills: {named}"
    if gaps:
        reason += f"; gaps: {', '.join(gaps[:4])}"
    return value, reason, have, gaps


def rank_job(job: Job, text: str, prefs: Preferences, now: str) -> RankResult:
    """Score one job. Pure: no files are read or written."""
    yoe = parse_yoe(text)
    exp, exp_reason = experience_part(yoe, prefs)
    title, title_reason, track = title_part(job, text, prefs)
    tier = location_tier(job, prefs, text)
    skills, skills_reason, have, gaps = skills_part(text, prefs)
    flags: list[Flag] = eligibility_flags(job, text, prefs, yoe)
    weights = prefs.weights
    parts = {"experience": exp, "title": title, "location": tier.score, "skills": skills}
    total_weight = sum(weights.values())
    raw = sum(weights[name] * value for name, value in parts.items()) / total_weight * 100
    score = max(0, min(100, round(raw)))
    reasons = [_line(r) for r in (exp_reason, title_reason, tier.reason, skills_reason)]
    return RankResult(
        key=job.key,
        score=score,
        eligible=not any(f.hard for f in flags),
        tier=tier.name,
        track=track,
        yoe_min=yoe.min,
        yoe_max=yoe.max,
        reasons=reasons,
        flags=flags,
        skills_hit=have,
        skills_missing=gaps,
        ranked_at=now,
    )


def job_text(ws: Workspace, job: Job) -> str:
    """The description to rank on: the saved JD file, else the text stored with the job."""
    path = ws.jd_path(job.key)
    if path.is_file():
        text = path.read_text(encoding="utf-8", errors="replace")
        if text.strip():
            return text
    description = job.description or ""
    return html_to_text(description) if _TAG.search(description) else description


def _order(result: RankResult) -> tuple[int, int, str]:
    return (0 if result.eligible else 1, -result.score, result.key)


def rank_all(ws: Workspace, *, min_score: int | None = None) -> list[RankResult]:
    """Rank every open job, write `data/ranked.jsonl` (all of them), shortlist the best.

    Returns the results (best first, eligible jobs before the rest), without those below
    `min_score` when it is given. Eligible jobs at or above `thresholds.shortlist` get a
    `shortlisted` status event.
    """
    prefs = load_preferences(ws)
    now = now_iso()
    previous = {str(r.get("key")): r for r in read_jsonl(ws.ranked_path)}
    results: list[RankResult] = []
    for job in JobStore(ws).all():
        if job.status == "closed":
            continue
        result = rank_job(job, job_text(ws, job), prefs, now)
        old = previous.get(job.key)
        if old is not None and {**old, "ranked_at": now} == result.to_dict():
            result.ranked_at = str(old.get("ranked_at") or now)
        results.append(result)
    results.sort(key=_order)
    write_jsonl_atomic(ws.ranked_path, (r.to_dict() for r in results))
    log = StatusLog(ws)
    for result in results:
        if result.eligible and result.score >= prefs.shortlist:
            log.record(result.key, AppStatus.shortlisted, "rank", f"score {result.score}")
    if min_score is not None:
        results = [r for r in results if r.score >= min_score]
    return results
