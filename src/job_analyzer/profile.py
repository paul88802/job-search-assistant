"""The user's job-search preferences, saved privately in data/profile.json.

Each preference has a priority:
  - "hard": a clear mismatch removes the job from the results
  - "soft": a mismatch only lowers the job's score
"""

from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from job_analyzer import paths
from job_analyzer.models import LanguageRequirement, Place, WorkArrangement

Priority = Literal["hard", "soft"]

BOARDS_MAX_AGE_DAYS = 90  # re-check a country's top job boards about every 3 months


class CountryBoards(BaseModel):
    """The top job boards of one country, as researched by the job-board-scout agent."""

    domains: list[str]
    checked_at: str  # YYYY-MM-DD


class SalaryPreference(BaseModel):
    minimum: float
    currency: str = "EUR"
    basis: Literal["gross", "net"] = "net"
    period: Literal["month", "year"] = "month"
    priority: Priority = "soft"

    def __str__(self) -> str:
        return f"{self.minimum:,.0f} {self.currency} {self.basis}/{self.period}"


class Profile(BaseModel):
    target_titles: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)

    locations: list[Place] = Field(default_factory=list)
    location_priority: Priority = "soft"

    work_arrangements: list[WorkArrangement] = Field(
        default_factory=lambda: ["remote", "hybrid", "onsite"]
    )
    work_arrangement_priority: Priority = "hard"

    salary: SalaryPreference | None = None

    languages: list[LanguageRequirement] = Field(default_factory=list)
    language_priority: Priority = "hard"

    # Where /find-jobs searches. Global groups (same for every country) ...
    search_sites: dict[str, list[str]] = Field(default_factory=lambda: dict(DEFAULT_SEARCH_SITES))
    # ... plus the top job boards of each country in `locations`, researched automatically and
    # saved with a date (so every run uses the same list, refreshed every ~3 months).
    country_job_boards: dict[str, CountryBoards] = Field(default_factory=dict)
    max_postings: int = 10  # how many postings one search run analyzes in depth

    # Live sources (fetched by code from official APIs/feeds, see live.py).
    # Company job boards like "lever:qover"; new ones are discovered from search results.
    watch_boards: list[str] = Field(default_factory=list)
    live_feeds: list[str] = Field(default_factory=lambda: ["remoteok", "wwr:remote-devops-sysadmin-jobs"])


def search_groups(p: Profile) -> dict[str, list[str]]:
    """All site groups for one run: global groups + one group per researched country."""
    groups = dict(p.search_sites)
    for country, boards in p.country_job_boards.items():
        groups[f"{country} job boards"] = boards.domains
    return groups


def target_countries(p: Profile) -> list[str]:
    seen: list[str] = []
    for place in p.locations:
        if place.country and place.country not in seen:
            seen.append(place.country)
    return seen


def countries_to_research(p: Profile, today: date | None = None) -> list[str]:
    """Countries whose job boards are unknown or older than BOARDS_MAX_AGE_DAYS."""
    today = today or date.today()
    out = []
    for country in target_countries(p):
        boards = p.country_job_boards.get(country)
        if boards is None or (today - date.fromisoformat(boards.checked_at)).days > BOARDS_MAX_AGE_DAYS:
            out.append(country)
    return out


# Sensible defaults for any country; users add local job boards in their own profile.
DEFAULT_SEARCH_SITES = {
    "Company career pages": [
        "greenhouse.io", "lever.co", "workable.com", "ashbyhq.com",
        "smartrecruiters.com", "recruitee.com", "teamtailor.com",
    ],
    "LinkedIn": ["linkedin.com"],
    "Remote job boards": ["weworkremotely.com", "remoteok.com"],
}


def load_profile(path: Path | None = None) -> Profile | None:
    path = path or paths.profile_path()
    if not path.exists():
        return None
    return Profile.model_validate_json(path.read_text(encoding="utf-8"))


def save_profile(profile: Profile, path: Path | None = None) -> Path:
    path = path or paths.profile_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(profile.model_dump_json(indent=2), encoding="utf-8")
    return path
