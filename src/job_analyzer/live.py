"""Live job sources: official, machine-readable feeds instead of search-engine results.

Why: search engines keep job pages indexed long after a job is filled, and many job sites
block automated page reading. In real runs most search hits were closed (404) or blocked
(403/429). The sources below are published for automated use and list jobs open NOW:

  - company job boards (ATS public APIs): Greenhouse, Lever, Ashby
  - Remote OK JSON API (its terms ask to link back to Remote OK; we keep its URLs)
  - We Work Remotely RSS feeds

Boards are DISCOVERED from search results: a search hit on jobs.lever.co/qover/... tells us
the company "qover" uses Lever, so all of Qover's current openings can be fetched, even if
the hit itself was a stale, closed posting.

All fetching is plain code (no AI). The full job text is saved locally, so analysts read a
file instead of fetching pages (no timeouts, no JavaScript-rendered pages).
"""

import html
import json
import re
import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote, urlsplit

from job_analyzer import paths
from job_analyzer.jobs import normalize_url, url_id
from job_analyzer.profile import Profile
from job_analyzer.search import (
    ATS_HOSTS,
    SearchBatch,
    SearchError,
    SearchResult,
    board_from_url,
    location_ok,
    too_old,
)

USER_AGENT = "job-search-assistant/0.1 (personal job search; +https://github.com/)"
Getter = Callable[[str], bytes]


def http_get(url: str, timeout: int = 20) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json, */*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


# ---- one live job ----

@dataclass
class LiveJob:
    url: str
    title: str
    company: str | None
    location: str | None
    posted_date: str | None
    text: str
    site: str
    source: str  # e.g. "lever:qover", "remoteok", "wwr:remote-devops-sysadmin-jobs"


def html_to_text(raw: str) -> str:
    s = html.unescape(html.unescape(raw or ""))  # Greenhouse content is double-escaped
    s = re.sub(r"<(br|/p|/li|/h\d)[^>]*>", "\n", s, flags=re.I)
    s = re.sub(r"<li[^>]*>", "- ", s, flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    s = re.sub(r"[ \t]+", " ", s)
    return re.sub(r"\n\s*\n+", "\n\n", s).strip()


def _iso_date(value) -> str | None:
    if value in (None, ""):
        return None
    try:
        if isinstance(value, (int, float)) or str(value).isdigit():
            ts = float(value)
            ts = ts / 1000 if ts > 1e11 else ts  # Lever uses milliseconds
            return datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat()
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date().isoformat()
    except (ValueError, OverflowError):
        try:
            return parsedate_to_datetime(str(value)).date().isoformat()  # RSS dates
        except (TypeError, ValueError):
            return None


def _site(url: str) -> str:
    return (urlsplit(url).hostname or "").removeprefix("www.")


# ---- fetchers (each takes an injectable `get`, so tests run offline) ----

def fetch_greenhouse(token: str, get: Getter) -> list[LiveJob]:
    data = json.loads(get(f"https://boards-api.greenhouse.io/v1/boards/{quote(token)}/jobs?content=true"))
    return [LiveJob(url=j["absolute_url"], title=j["title"], company=j.get("company_name"),
                    location=(j.get("location") or {}).get("name"),
                    posted_date=_iso_date(j.get("first_published") or j.get("updated_at")),
                    text=html_to_text(j.get("content", "")), site=_site(j["absolute_url"]),
                    source=f"greenhouse:{token}")
            for j in data.get("jobs", [])]


def fetch_lever(token: str, get: Getter) -> list[LiveJob]:
    data = json.loads(get(f"https://api.lever.co/v0/postings/{quote(token)}?mode=json"))
    jobs = []
    for j in data:
        cats = j.get("categories") or {}
        loc = "; ".join(cats.get("allLocations") or []) or cats.get("location")  # every place it's open to
        if j.get("workplaceType") in ("remote", "hybrid") and loc:
            loc = f"{loc} ({j['workplaceType']})"
        lists = "\n".join(f"{li.get('text', '')}\n{html_to_text(li.get('content', ''))}" for li in j.get("lists", []))
        text = "\n\n".join(p for p in (j.get("descriptionPlain"), lists, j.get("additionalPlain")) if p)
        jobs.append(LiveJob(url=j["hostedUrl"], title=j["text"], company=token, location=loc,
                            posted_date=_iso_date(j.get("createdAt")), text=text,
                            site=_site(j["hostedUrl"]), source=f"lever:{token}"))
    return jobs


def fetch_ashby(token: str, get: Getter) -> list[LiveJob]:
    data = json.loads(get(f"https://api.ashbyhq.com/posting-api/job-board/{quote(token)}"))
    jobs = []
    for j in data.get("jobs", []):
        if j.get("isListed") is False:
            continue
        places = [j.get("location")] + [s.get("location") for s in j.get("secondaryLocations") or []]
        loc = "; ".join(p for p in places if p) or None  # every place it's open to
        if j.get("isRemote") and loc and "remote" not in loc.lower():
            loc = f"Remote - {loc}"
        jobs.append(LiveJob(url=j["jobUrl"], title=j["title"], company=token, location=loc,
                            posted_date=_iso_date(j.get("publishedAt")),
                            text=j.get("descriptionPlain") or html_to_text(j.get("descriptionHtml", "")),
                            site=_site(j["jobUrl"]), source=f"ashby:{token}"))
    return jobs


def fetch_remoteok(get: Getter) -> list[LiveJob]:
    data = json.loads(get("https://remoteok.com/api"))
    jobs = []
    for j in data:
        if "position" not in j or "url" not in j:
            continue  # the first element is the API's legal notice
        loc = j.get("location") or "Remote"
        if "remote" not in loc.lower():
            loc = f"Remote - {loc}"
        jobs.append(LiveJob(url=j["url"], title=j["position"], company=j.get("company"), location=loc,
                            posted_date=_iso_date(j.get("date")), text=html_to_text(j.get("description", "")),
                            site="remoteok.com", source="remoteok"))
    return jobs


def fetch_wwr(category: str, get: Getter) -> list[LiveJob]:
    root = ET.fromstring(get(f"https://weworkremotely.com/categories/{category}.rss"))
    jobs = []
    for item in root.iter("item"):
        raw_title = item.findtext("title", "")
        company, _, title = raw_title.partition(": ")
        if not title:
            company, title = None, raw_title
        region = item.findtext("region") or "Remote"
        jobs.append(LiveJob(url=item.findtext("link", ""), title=title, company=company,
                            location=region if "remote" in region.lower() or "anywhere" in region.lower()
                            else f"Remote - {region}",
                            posted_date=_iso_date(item.findtext("pubDate")),
                            text=html_to_text(item.findtext("description", "")),
                            site="weworkremotely.com", source=f"wwr:{category}"))
    return jobs


# ---- relevance: does a live job title match what the user is looking for? ----

GENERIC_WORDS = {"engineer", "engineering", "senior", "junior", "lead", "staff", "principal",
                 "specialist", "medior", "aws", "and", "the", "of"}
# A title must also contain one of these, so "Marketing Manager, Google Cloud" doesn't match "cloud".
ROLE_WORDS = {"engineer", "engineering", "sre", "devops", "devsecops", "architect", "administrator",
              "admin", "reliability", "platform", "infrastructure", "operations", "ops", "cloudops",
              "sysops", "observability", "monitoring", "sysadmin"}


def title_terms(profile: Profile) -> list[str]:
    """'Cloud Operations Engineer' -> 'cloud operations'; 'Site Reliability Engineer' -> also 'sre'."""
    terms: list[str] = []
    for title in profile.target_titles:
        title = re.sub(r"\(.*?\)", " ", title.casefold())
        for part in re.split(r"[/,]", title):
            words = [w for w in re.findall(r"[a-z0-9]+", part) if w not in GENERIC_WORDS]
            if words:
                terms.append(" ".join(words))
    if any("site reliability" in t for t in terms):
        terms.append("sre")
    return list(dict.fromkeys(terms))


def relevant(title: str, terms: list[str]) -> bool:
    t = " " + re.sub(r"[^a-z0-9]+", " ", title.casefold()) + " "
    has_term = any(f" {term} " in t for term in terms)
    has_role = any(f" {w} " in t for w in ROLE_WORDS)
    return has_term and has_role


# ---- one live collection run ----

@dataclass
class LiveResult:
    batch: SearchBatch
    texts: dict[str, str] = field(default_factory=dict)       # candidate id -> full job text
    boards_ok: set[str] = field(default_factory=set)          # boards fetched successfully
    live_urls: dict[str, dict] = field(default_factory=dict)  # every open job on those boards -> official location/date
    stats: dict = field(default_factory=dict)


def collect_live(profile: Profile, boards: list[str], get: Getter = http_get,
                 today: date | None = None, max_age_days: int = 60) -> LiveResult:
    today = today or date.today()
    places = [p.casefold() for pl in profile.locations for p in (pl.city, pl.country) if p]
    terms = title_terms(profile)
    sources: list[tuple[str, Callable[[], list[LiveJob]]]] = []
    for board in boards:
        ats, _, token = board.partition(":")
        fetcher = {"greenhouse": fetch_greenhouse, "lever": fetch_lever, "ashby": fetch_ashby}.get(ats)
        if fetcher:
            sources.append((board, lambda f=fetcher, t=token: f(t, get)))
    for feed in profile.live_feeds:
        if feed == "remoteok":
            sources.append((feed, lambda: fetch_remoteok(get)))
        elif feed.startswith("wwr:"):
            sources.append((feed, lambda c=feed[4:]: fetch_wwr(c, get)))

    result = LiveResult(batch=SearchBatch(site_group="Live sources", queries=[], results=[], errors=[]))
    stats = {"sources": len(sources), "jobs_seen": 0, "relevant": 0, "kept": 0}
    for name, fetch in sources:
        result.batch.queries.append(name)
        try:
            jobs = fetch()
        except Exception as e:  # noqa: BLE001  (any network/parse failure = a coverage gap, not a crash)
            result.batch.errors.append(SearchError(
                site=name, query=name, error_type="access_failure",
                detail=f"{type(e).__name__}: {str(e)[:120]}", retryable=True))
            continue
        if name.split(":")[0] in ATS_HOSTS:
            result.boards_ok.add(name)
            result.live_urls.update({normalize_url(j.url): {"location": j.location, "posted_date": j.posted_date}
                                     for j in jobs})
        for j in jobs:
            stats["jobs_seen"] += 1
            result.texts[url_id(j.url)] = j.text  # every open job: search hits can use it too
            if not relevant(j.title, terms):
                continue
            stats["relevant"] += 1
            if not location_ok(j.location, places) or too_old(j.posted_date, today, max_age_days):
                continue
            stats["kept"] += 1
            result.batch.results.append(SearchResult(
                url=j.url, title=j.title, company=j.company, site=j.site,
                posted_date=j.posted_date, location=j.location,
                snippet=f"via {'Remote OK' if j.source == 'remoteok' else j.source}"))
    result.stats = stats
    return result


def discover_boards(batches: list[SearchBatch]) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for b in batches:
        for r in b.results:
            board = board_from_url(r.url)
            if board and board.casefold() not in seen:  # 'lever:Qover' and 'lever:qover' are one board
                seen.add(board.casefold())
                found.append(board)
    return found


def save_live_run(result: LiveResult, out_batch) -> None:
    """Write the live batch, the job texts, and the index merge uses to drop stale links."""
    folder = paths.live_dir()
    folder.mkdir(parents=True, exist_ok=True)
    for old in folder.glob("*.txt"):
        old.unlink()
    for job_id, text in result.texts.items():
        (folder / f"{job_id}.txt").write_text(text, encoding="utf-8")
    out_batch.parent.mkdir(parents=True, exist_ok=True)
    out_batch.write_text(result.batch.model_dump_json(indent=2), encoding="utf-8")
    paths.live_index_file().write_text(json.dumps({
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "boards_ok": sorted(result.boards_ok),
        "live_urls": dict(sorted(result.live_urls.items())),
    }, indent=2), encoding="utf-8")


def load_live_index(max_age_hours: int = 6) -> tuple[set[str], dict[str, dict]]:
    """(boards fetched OK, open job URL -> official location/date) from a recent `live` run.

    Empty if none or too old. An index from an older version (a plain URL list) has no details.
    """
    f = paths.live_index_file()
    if not f.exists():
        return set(), {}
    data = json.loads(f.read_text(encoding="utf-8"))
    age = datetime.now(timezone.utc) - datetime.fromisoformat(data["created_at"])
    if age.total_seconds() > max_age_hours * 3600:
        return set(), {}
    urls = data["live_urls"]
    return set(data["boards_ok"]), urls if isinstance(urls, dict) else {u: {} for u in urls}
