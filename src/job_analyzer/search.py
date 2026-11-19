"""What search subagents report, and the deterministic step that merges their results.

Two kinds of "nothing found" are kept apart on purpose:
  - results == [] and errors == []  -> the search WORKED and found nothing (valid empty result)
  - errors != []                    -> the search FAILED (access failure, blocked, ...)
Mixing them up would hide coverage gaps in the shortlist.

Duplicates: the same job is often posted on LinkedIn AND on the company page or a job board.
A posting is identified by company + job title + date posted:
  - same company + title, same date (or a date missing on either side) -> same job
  - same company + title, DIFFERENT known dates                         -> different jobs
When duplicates are found, the copy on a site that can be read automatically is analyzed,
and the other links are kept as "also on" (e.g. LinkedIn, for Easy Apply).
"""

import json
import re
from datetime import datetime, timezone
from itertools import zip_longest
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from job_analyzer import paths
from job_analyzer.jobs import normalize_url, url_id

ErrorType = Literal["access_failure", "blocked", "rate_limited", "other"]

# Sites that usually block automated reading (login walls). Used only to choose
# which copy of a duplicated posting to analyze.
HARD_TO_READ = ("linkedin.com", "indeed.", "glassdoor.")

GENDER_TAGS = re.compile(r"\((?:m|f|h|v|x|d|w)(?:\s*[/|,]\s*(?:m|f|h|v|x|d|w))+\)|\b(?:m|f|h)/(?:f|v|h|m)(?:/(?:x|d))?\b", re.I)
COMPANY_SUFFIXES = re.compile(r"\b(?:nv|sa|bv|bvba|srl|sprl|ltd|limited|inc|llc|gmbh|ag|plc|group)\b\.?", re.I)


class SearchResult(BaseModel):
    url: str = Field(description="Direct link to ONE job posting (not a search or list page).")
    title: str = Field(description="Job title as shown in the search result.")
    company: str | None = Field(description="Company name if shown, else null.")
    site: str = Field(description="Domain the posting is on, e.g. 'jobat.be'.")
    posted_date: str | None = Field(
        default=None,
        description="Date the job was posted as YYYY-MM-DD if shown ('3 days ago' -> compute from today), else null.",
    )
    snippet: str | None = Field(description="Short text from the search result, or null.")


class SearchError(BaseModel):
    site: str = Field(description="Domain or site group the failed search targeted.")
    query: str = Field(description="The exact search query that failed.")
    error_type: ErrorType
    detail: str = Field(description="What happened, in one sentence.")
    retryable: bool = Field(description="True for temporary problems (timeouts, rate limits).")


class SearchBatch(BaseModel):
    """Everything ONE search subagent found for ONE site group."""

    site_group: str
    queries: list[str] = Field(description="Every query that was run, including ones that found nothing.")
    results: list[SearchResult] = Field(description="Postings found. Empty list if the searches worked but found nothing.")
    errors: list[SearchError] = Field(description="Searches that FAILED. Empty list if all searches worked.")


class Candidate(SearchResult):
    id: str
    site_group: str
    also_seen_at: list[str] = Field(default_factory=list)


# ---- identifying "the same job" ----

def norm_company(name: str | None) -> str | None:
    if not name:
        return None
    s = COMPANY_SUFFIXES.sub(" ", name.casefold())
    s = re.sub(r"[^\w]+", " ", s).strip()
    return s or None


def norm_title(title: str) -> str:
    s = GENDER_TAGS.sub(" ", title.casefold())  # "DevOps Engineer (m/f/x)" == "DevOps Engineer"
    return re.sub(r"[^\w]+", " ", s).strip()


def job_key(company: str | None, title: str) -> tuple[str, str] | None:
    c = norm_company(company)
    return (c, norm_title(title)) if c else None


def same_date(a: str | None, b: str | None) -> bool:
    """Missing date on either side = can't tell them apart = treat as the same job."""
    return a is None or b is None or a == b


def readability(site: str) -> int:
    return 0 if any(h in site.casefold() for h in HARD_TO_READ) else 1


# ---- merging ----

def merge_batches(
    batches: list[SearchBatch],
    known_ids: set[str],
    limit: int,
    known_keys: dict[tuple[str, str], list[str | None]] | None = None,
) -> tuple[list[Candidate], dict]:
    """Remove duplicates and already-analyzed postings, then pick up to `limit` candidates.

    Candidates are taken round-robin across site groups, so one big site can't crowd out
    the others (coverage matters more than volume).
    """
    known_keys = known_keys or {}
    unique: list[Candidate] = []
    by_url: dict[str, int] = {}
    by_key: dict[tuple[str, str], list[int]] = {}
    stats = {"found": 0, "duplicates": 0, "already_analyzed": 0, "same_title_other_date": 0}

    for batch in batches:
        for r in batch.results:
            stats["found"] += 1
            url = normalize_url(r.url)
            key = job_key(r.company, r.title)

            if url_id(r.url) in known_ids or (
                key and any(same_date(r.posted_date, d) for d in known_keys.get(key, []))
            ):
                stats["already_analyzed"] += 1
                continue
            if url in by_url:
                stats["duplicates"] += 1
                continue

            match = None
            if key:
                match = next((i for i in by_key.get(key, []) if same_date(unique[i].posted_date, r.posted_date)), None)
            if match is not None:
                stats["duplicates"] += 1
                keeper = unique[match]
                if readability(r.site) > readability(keeper.site):
                    # Analyze the readable copy; keep the other link (e.g. LinkedIn) as "also on".
                    unique[match] = Candidate(
                        **{**r.model_dump(), "posted_date": r.posted_date or keeper.posted_date},
                        id=url_id(r.url), site_group=batch.site_group,
                        also_seen_at=[*keeper.also_seen_at, keeper.url],
                    )
                else:
                    keeper.also_seen_at.append(r.url)
                    keeper.posted_date = keeper.posted_date or r.posted_date
                by_url[url] = match
                continue

            if key and by_key.get(key):
                stats["same_title_other_date"] += 1  # same company + title, different date: kept
            unique.append(Candidate(**r.model_dump(), id=url_id(r.url), site_group=batch.site_group))
            by_url[url] = len(unique) - 1
            if key:
                by_key.setdefault(key, []).append(len(unique) - 1)

    per_group: dict[str, list[Candidate]] = {b.site_group: [] for b in batches}
    for c in unique:
        per_group[c.site_group].append(c)
    picked: list[Candidate] = []
    for round_ in zip_longest(*per_group.values()):
        for c in round_:
            if c is not None and len(picked) < limit:
                picked.append(c)

    coverage = {
        "groups": {
            b.site_group: {"queries": len(b.queries), "results": len(b.results), "errors": len(b.errors)}
            for b in batches
        },
        "errors": [e.model_dump() for b in batches for e in b.errors],
        "stats": {**stats, "new_unique": len(unique), "picked": len(picked)},
    }
    return picked, coverage


def write_run_files(candidates: list[Candidate], coverage: dict, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps([c.model_dump() for c in candidates], indent=2, ensure_ascii=False),
                   encoding="utf-8")
    paths.coverage_file().write_text(json.dumps(coverage, indent=2, ensure_ascii=False), encoding="utf-8")
    paths.run_file().write_text(json.dumps({
        "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "candidates": len(candidates),
    }, indent=2), encoding="utf-8")
    errors_file = paths.analysis_errors_file()
    if errors_file.exists():
        errors_file.unlink()  # a new run starts with a clean error list


def load_candidates() -> list[Candidate]:
    """Candidates of the latest run (for 'also on' links in the shortlist)."""
    f = paths.inbox_dir() / "candidates.json"
    if not f.exists():
        return []
    try:
        return [Candidate.model_validate(c) for c in json.loads(f.read_text(encoding="utf-8"))]
    except ValueError:
        return []
