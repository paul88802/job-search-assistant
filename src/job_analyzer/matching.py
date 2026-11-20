"""Compare an extracted job posting with the user's profile. No AI in this file.

Claude *reads* the messy posting (extract.py); plain code *compares* the clean
result with the profile. Code comparisons are free, instant, and always give the
same answer, and every decision can be explained.

Every check has three possible outcomes:
  - match:    the posting meets the preference
  - mismatch: the posting clearly breaks it
  - unknown:  the posting doesn't say. The job is kept and flagged, with a smaller score penalty.
"""

from dataclasses import dataclass
from typing import Literal

from job_analyzer.models import LEVEL_ORDER, JobRequirements, LanguageRequirement
from job_analyzer.profile import Priority, Profile
from job_analyzer.search import open_to_ok

Outcome = Literal["match", "mismatch", "unknown"]

# How much each preference counts toward the 0-100 score.
WEIGHTS = {"work arrangement": 25, "salary": 30, "languages": 25, "location": 20}
UNKNOWN_CREDIT = 0.5


@dataclass
class Check:
    criterion: str
    outcome: Outcome
    priority: Priority
    detail: str
    credit: float  # 0.0-1.0 share of this criterion's weight


@dataclass
class MatchReport:
    checks: list[Check]
    excluded: bool  # True if any HARD preference is a clear mismatch
    score: int  # 0-100

    @property
    def exclusion_reasons(self) -> list[str]:
        return [c.detail for c in self.checks if c.priority == "hard" and c.outcome == "mismatch"]


def _same(a: str | None, b: str | None) -> bool:
    return a is not None and b is not None and a.strip().casefold() == b.strip().casefold()


def _check(criterion: str, outcome: Outcome, priority: Priority, detail: str,
           credit: float | None = None) -> Check:
    if credit is None:
        credit = {"match": 1.0, "unknown": UNKNOWN_CREDIT, "mismatch": 0.0}[outcome]
    return Check(criterion, outcome, priority, detail, credit)


def check_work_arrangement(job: JobRequirements, profile: Profile) -> Check:
    name, prio = "work arrangement", profile.work_arrangement_priority
    if job.remote_policy == "unknown":
        return _check(name, "unknown", prio, "Posting doesn't say if it's remote, hybrid or onsite")
    if job.remote_policy in profile.work_arrangements:
        return _check(name, "match", prio, f"{job.remote_policy.capitalize()} is acceptable")
    return _check(name, "mismatch", prio,
                  f"{job.remote_policy.capitalize()} role; you want {'/'.join(profile.work_arrangements)}")


def check_location(job: JobRequirements, profile: Profile) -> Check:
    name, prio = "location", profile.location_priority
    if not profile.locations:
        return _check(name, "match", prio, "No location preference")
    if job.remote_policy == "remote":
        places = [p for pl in profile.locations for p in (pl.city, pl.country) if p]
        if not open_to_ok(job.open_to, places):
            # Not a preference: the company can't hire someone living elsewhere, so always a must.
            return _check(name, "mismatch", "hard", f"Remote, but only for people in {', '.join(job.open_to)}")
        where = f" (open to {', '.join(job.open_to)})" if job.open_to else ""
        return _check(name, "match", prio, f"Remote role{where}")
    if job.location is None or job.location.country is None:
        return _check(name, "unknown", prio, "Posting doesn't state a location")

    city_unknown = False
    for place in profile.locations:
        if not _same(place.country, job.location.country):
            continue
        if place.city is None or _same(place.city, job.location.city):
            return _check(name, "match", prio, f"{job.location} matches {place}")
        if job.location.city is None:
            city_unknown = True
    if city_unknown:
        return _check(name, "unknown", prio, f"Right country ({job.location.country}), city not stated")
    wanted = "; ".join(str(p) for p in profile.locations)
    return _check(name, "mismatch", prio, f"Based in {job.location}; you want {wanted}")


def _monthly(amount: float, period: str) -> float | None:
    return {"month": amount, "year": amount / 12}.get(period)


def check_salary(job: JobRequirements, profile: Profile) -> Check:
    want = profile.salary
    if want is None:
        return _check("salary", "match", "soft", "No salary preference")
    name, prio = "salary", want.priority

    s = job.salary
    offered = None if s is None else (s.maximum if s.maximum is not None else s.minimum)
    if s is None or offered is None:
        return _check(name, "unknown", prio, "Salary not stated: ask about it early")
    if s.currency.upper() != want.currency.upper():
        return _check(name, "unknown", prio,
                      f"Paid in {s.currency} ({s.raw_text}); your minimum is in {want.currency}")
    if s.basis != "unknown" and s.basis != want.basis:
        return _check(name, "unknown", prio,
                      f"Posting gives {s.basis} pay ({s.raw_text}); your minimum is {want.basis}")
    period = want.period if s.period == "unknown" else s.period
    offered_monthly = _monthly(offered, period)
    if offered_monthly is None:
        return _check(name, "unknown", prio, f"Paid per {s.period} ({s.raw_text}): can't compare")

    want_monthly = _monthly(want.minimum, want.period)
    note = " (gross/net not stated)" if s.basis == "unknown" else ""
    if offered_monthly >= want_monthly:
        return _check(name, "match", prio, f"{s.raw_text} meets your minimum of {want}{note}")

    # Below minimum: partial credit, so a job slightly under your minimum ranks
    # lower but doesn't vanish (when salary is a soft preference).
    shortfall = 1 - offered_monthly / want_monthly
    credit = max(0.0, 1 - 4 * shortfall)  # 5% short -> 0.8, 25% short -> 0
    return _check(name, "mismatch", prio,
                  f"{s.raw_text} is {shortfall:.0%} below your minimum of {want}{note}", credit)


def _level_ok(have: str, need: str) -> bool:
    if need == "unknown" or have == "native":
        return True
    if have == "unknown":
        return False
    return LEVEL_ORDER.index(have) >= LEVEL_ORDER.index(need)


def _why_not(req: LanguageRequirement, profile: Profile) -> str | None:
    """None if the user meets this single requirement, else the reason they don't."""
    mine = next((l for l in profile.languages if _same(l.language, req.language)), None)
    if mine is None:
        return f"no {req.language}"
    if not _level_ok(mine.level, req.level):
        return f"{req.language} {mine.level}, needs {req.level}"
    return None


def check_languages(job: JobRequirements, profile: Profile) -> Check:
    """Every group must be satisfied by at least ONE of its languages ('French or Dutch')."""
    name, prio = "languages", profile.language_priority
    if not profile.languages:
        return _check(name, "match", prio, "No languages in your profile, so this isn't checked")
    if not job.languages_required:
        return _check(name, "match", prio, "No language requirements stated")

    problems = []
    for group in job.languages_required:
        reasons = [_why_not(req, profile) for req in group.any_of]
        if all(reasons):  # no language in this group is met
            problems.append(f"{group} required ({'; '.join(reasons)})")
    if problems:
        return _check(name, "mismatch", prio, "; ".join(problems))
    return _check(name, "match", prio,
                  "You meet: " + ", ".join(str(g) for g in job.languages_required))


def evaluate(job: JobRequirements, profile: Profile) -> MatchReport:
    checks = [
        check_work_arrangement(job, profile),
        check_location(job, profile),
        check_salary(job, profile),
        check_languages(job, profile),
    ]
    total = sum(WEIGHTS[c.criterion] for c in checks)
    earned = sum(WEIGHTS[c.criterion] * c.credit for c in checks)
    excluded = any(c.priority == "hard" and c.outcome == "mismatch" for c in checks)
    return MatchReport(checks=checks, excluded=excluded, score=round(100 * earned / total))
