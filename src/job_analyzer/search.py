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
from dataclasses import dataclass
from datetime import date, datetime, timezone
from itertools import zip_longest
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from job_analyzer import paths
from urllib.parse import unquote, urlsplit

from job_analyzer.jobs import normalize_url, url_id

ErrorType = Literal["access_failure", "blocked", "rate_limited", "other"]

# Sites that block automated reading (login walls, 403/429 responses), as seen in real runs.
# Their postings are not sent to analysts: a readable copy is preferred when one exists,
# otherwise they go to the user's "check these yourself" list with the link.
HARD_TO_READ = ("linkedin.com", "indeed.", "glassdoor.", "weworkremotely.com",
                # Posting pages time out on every fetch (6 of 6 in real runs); their LIST pages
                # still work, so searchers find these postings and the user gets the links.
                "stepstone.", "ictjob.")

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
    location: str | None = Field(
        default=None,
        description="Job location as shown, in English (e.g. 'Brussels, Belgium', 'Remote - Europe', 'Remote - US'), else null.",
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


# Company job boards (ATS) whose public APIs list open jobs; see live.py.
ATS_HOSTS = {
    "greenhouse": ("boards.greenhouse.io", "job-boards.greenhouse.io", "job-boards.eu.greenhouse.io"),
    "lever": ("jobs.lever.co", "jobs.eu.lever.co"),
    "ashby": ("jobs.ashbyhq.com",),
}


def board_from_url(url: str) -> str | None:
    """'https://jobs.lever.co/Qover/abc' -> 'lever:Qover' (None if not a known job board).

    The company token keeps its original case: Lever and Ashby APIs are case-sensitive
    ('qover' returns 404, 'Qover' works). Compare boards with `.casefold()`.
    """
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    segments = [unquote(s) for s in parts.path.split("/") if s]
    for ats, hosts in ATS_HOSTS.items():
        if host in hosts and segments and segments[0].lower() not in ("embed", "v1", "api"):
            return f"{ats}:{segments[0]}"
    return None


def readability(r: SearchResult, readable_ids: frozenset | set = frozenset()) -> int:
    """0 if the posting lives on a site that blocks automated reading, else 1.

    Checks the link's real host too, not only the `site` label the searcher wrote.
    """
    if url_id(r.url) in readable_ids:
        return 1  # full text already saved from an official feed
    host = (urlsplit(r.url).hostname or "").casefold()
    return 0 if any(h in host or h in r.site.casefold() for h in HARD_TO_READ) else 1


# ---- filters (plain code, applied before any posting is analyzed) ----

REMOTE_OK = re.compile(r"\b(?:remote|europe|european|emea|eu|worldwide|anywhere|global)\b", re.I)
REGION_LOCKED = re.compile(
    r"\b(?:us|usa|u\.s\.|united states|canada|north america|namer|americas|latam|latin america|"
    r"apac|asia|australia|india|uk only|us only)\b", re.I)
# Words that may accompany "remote" without naming a specific place.
LOCATION_FILLER = {"remote", "europe", "european", "emea", "eu", "worldwide", "anywhere", "global",
                   "world", "in", "the", "of", "only", "based", "first", "friendly", "hybrid", "or",
                   "and", "within", "timezone", "timezones", "time", "zone", "cet", "cest", "utc",
                   "gmt", "hours", "hour", "fully", "work", "from", "home", "location", "flexible"}


def location_ok(location: str | None, places: list[str]) -> bool:
    """Keep a result unless its location clearly rules the user out.

    Unknown location -> keep (code can't tell; the analyst will read the posting).
    Mentions one of the user's countries/cities -> keep.
    Locked to another region ("Remote - US", "NAMER and LatAm") -> drop.
    Remote/Europe/EMEA/worldwide with nothing more specific -> keep.
    Remote but tied to another place ("Remote - Spain", "Remote - Ireland") -> drop.
    Any other specific place -> drop.
    """
    if not location or not places:
        return True
    loc = location.casefold()
    if any(p in loc for p in places):
        return True
    if REGION_LOCKED.search(loc):
        return False
    if not REMOTE_OK.search(loc):
        return False
    leftover = [w for w in re.findall(r"[a-z]+", loc) if w not in LOCATION_FILLER]
    return not leftover  # anything left names a specific other place


def too_old(posted_date: str | None, today: date, max_age_days: int) -> bool:
    if not posted_date:
        return False
    try:
        return (today - date.fromisoformat(posted_date)).days > max_age_days
    except ValueError:
        return False


@dataclass
class MergeResult:
    queue: list[Candidate]   # readable postings, in analysis order (round-robin across groups)
    manual: list[Candidate]  # postings only found on hard-to-read sites: the user checks these
    coverage: dict


# ---- merging ----

def merge_batches(
    batches: list[SearchBatch],
    known_ids: set[str],
    known_keys: dict[tuple[str, str], list[str | None]] | None = None,
    *,
    places: list[str] | None = None,
    today: date | None = None,
    max_age_days: int = 60,
    live_boards: set[str] | None = None,
    live_urls: set[str] | None = None,
    readable_ids: set[str] | None = None,
) -> MergeResult:
    """Filter, dedupe and order everything the searchers found.

    Nothing is analyzed here. The result is a QUEUE of readable postings: the coordinator
    takes candidates from it wave by wave (`job-analyzer next`) until enough postings have
    been analyzed successfully, so a failed posting is replaced by the next one (backfill).

    `live_boards` / `live_urls` come from `job-analyzer live`: a search hit on a company
    board that was fetched live, but which is NOT among that board's open jobs, is closed.
    Pass the live batch FIRST so live copies (with saved text) win over search duplicates.
    """
    known_keys = known_keys or {}
    places = [p.casefold() for p in (places or [])]
    today = today or date.today()
    live_boards = {b.casefold() for b in (live_boards or set())}
    ids = readable_ids or set()
    live_urls = {u.casefold() for u in (live_urls or set())}  # job-board paths: case-insensitive
    unique: list[Candidate] = []
    by_url: dict[str, int] = {}
    by_key: dict[tuple[str, str], list[int]] = {}
    stats = {"found": 0, "duplicates": 0, "already_analyzed": 0, "same_title_other_date": 0,
             "other_location": 0, "too_old": 0, "closed": 0}

    for batch in batches:
        for r in batch.results:
            stats["found"] += 1
            url = normalize_url(r.url)
            key = job_key(r.company, r.title)

            if (board_from_url(r.url) or "").casefold() in live_boards and url.casefold() not in live_urls:
                stats["closed"] += 1  # its company board is live and no longer lists it
                continue

            if not location_ok(r.location, places):
                stats["other_location"] += 1
                continue
            if too_old(r.posted_date, today, max_age_days):
                stats["too_old"] += 1
                continue
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
                if readability(r, ids) > readability(keeper, ids):
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

    readable = [c for c in unique if readability(c, ids)]
    manual = [c for c in unique if not readability(c, ids)]

    per_group: dict[str, list[Candidate]] = {b.site_group: [] for b in batches}
    for c in readable:
        per_group[c.site_group].append(c)
    queue = [c for round_ in zip_longest(*per_group.values()) for c in round_ if c is not None]

    coverage = {
        "groups": {
            b.site_group: {"queries": len(b.queries), "results": len(b.results), "errors": len(b.errors)}
            for b in batches
        },
        "errors": [e.model_dump() for b in batches for e in b.errors],
        "stats": {**stats, "new_unique": len(unique), "readable": len(queue), "manual_check": len(manual)},
    }
    return MergeResult(queue=queue, manual=manual, coverage=coverage)


# ---- run files ----

def _dump(items: list[Candidate]) -> str:
    return json.dumps([c.model_dump() for c in items], indent=2, ensure_ascii=False)


def write_run_files(result: MergeResult, target: int) -> None:
    """Start a new run: queue, check-yourself list, coverage, and a clean analysis folder."""
    inbox = paths.inbox_dir()
    inbox.mkdir(parents=True, exist_ok=True)
    (inbox / "candidates.json").write_text(_dump(result.queue), encoding="utf-8")
    paths.manual_check_file().write_text(_dump(result.manual), encoding="utf-8")
    paths.coverage_file().write_text(json.dumps(result.coverage, indent=2, ensure_ascii=False),
                                     encoding="utf-8")
    paths.run_file().write_text(json.dumps({
        "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "target": target,
        "queue": len(result.queue),
    }, indent=2), encoding="utf-8")
    analysis = paths.analysis_dir()
    if analysis.exists():
        for f in analysis.glob("*"):
            f.unlink()  # a new run starts with no statuses from the previous one
    old_errors = paths.analysis_errors_file()
    if old_errors.exists():
        old_errors.unlink()


def _load_list(path: Path) -> list[Candidate]:
    if not path.exists():
        return []
    try:
        return [Candidate.model_validate(c) for c in json.loads(path.read_text(encoding="utf-8"))]
    except ValueError:
        return []


def load_candidates() -> list[Candidate]:
    """The analysis queue of the latest run."""
    return _load_list(paths.inbox_dir() / "candidates.json")


def load_manual_check() -> list[Candidate]:
    """Postings of the latest run that only exist on hard-to-read sites."""
    return _load_list(paths.manual_check_file())


# ---- backfill: which candidates to analyze next ----

def load_statuses() -> dict[str, dict]:
    """Status lines the analysts wrote (`<id>-status.json`), by candidate id."""
    out: dict[str, dict] = {}
    folder = paths.analysis_dir()
    if not folder.exists():
        return out
    for f in folder.glob("*-status.json"):
        try:
            out[f.name.removesuffix("-status.json")] = json.loads(f.read_text(encoding="utf-8"))
        except ValueError:
            out[f.name.removesuffix("-status.json")] = {"status": "error", "error_type": "other",
                                                        "detail": "unreadable status file"}
    return out


def next_batch(succeeded_ids: set[str], wave: int, attempt_factor: int = 3) -> tuple[list[Candidate], dict]:
    """The next candidates to analyze, replacing failures until `target` postings succeeded.

    Stops when the target is reached, the queue is empty, or `attempt_factor * target`
    postings have been tried (so a run can't loop forever on a site that blocks everything).
    """
    run = json.loads(paths.run_file().read_text(encoding="utf-8"))
    target = run["target"]
    queue = load_candidates()
    statuses = load_statuses()
    queued_ids = {c.id for c in queue}
    succeeded = succeeded_ids & queued_ids
    attempted = succeeded | set(statuses)
    need = target - len(succeeded)
    budget = attempt_factor * target - len(attempted)
    remaining = [c for c in queue if c.id not in attempted]
    batch = remaining[: max(0, min(need, wave, budget))]
    info = {"target": target, "succeeded": len(succeeded),
            "failed": sum(1 for s in statuses.values() if s.get("status") == "error"),
            "remaining_in_queue": len(remaining), "next": len(batch),
            "done": not batch}
    return batch, info
