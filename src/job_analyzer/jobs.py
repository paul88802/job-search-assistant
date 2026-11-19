"""Saved job postings: one record per posting, identified by its link.

Each record keeps WHERE and WHEN the posting was found (provenance), so a
shortlist can always link back to the original ad and the tracker can show
when it was seen.
"""

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import BaseModel

from job_analyzer import paths
from job_analyzer.models import FitAssessment, JobRequirements

TRACKING_PARAMS = {"refid", "trackingid", "trk", "gh_src", "source", "src", "ref", "lever-source"}


class JobRecord(BaseModel):
    id: str
    source_url: str | None
    site: str | None
    retrieved_at: str  # ISO 8601, UTC
    job: JobRequirements
    fit: FitAssessment | None = None


def normalize_url(url: str) -> str:
    """Same posting, same URL: lowercase host, no tracking parameters, no trailing slash."""
    parts = urlsplit(url.strip())
    query = [
        (k, v) for k, v in parse_qsl(parts.query)
        if k.lower() not in TRACKING_PARAMS and not k.lower().startswith("utm_")
    ]
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, urlencode(query), ""))


def _short_hash(text: str) -> str:
    return hashlib.sha1(text.encode()).hexdigest()[:12]


def url_id(url: str) -> str:
    """The job ID for a link. Search results and saved jobs use the same ID, so they can be matched."""
    return _short_hash(normalize_url(url))


def make_id(url: str | None, job: JobRequirements) -> str:
    if url:
        return url_id(url)
    return _short_hash(f"{job.company}|{job.title}|{job.summary}".casefold())


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def record_path(job_id: str) -> Path:
    return paths.jobs_dir() / f"{job_id}.json"


def save_record(rec: JobRecord) -> Path:
    path = record_path(rec.id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(rec.model_dump_json(indent=2), encoding="utf-8")
    return path


def add_job(job: JobRequirements, url: str | None = None, site: str | None = None) -> JobRecord:
    """Save a posting. Re-importing the same link updates the same record (no duplicates)."""
    rec = JobRecord(id=make_id(url, job), source_url=url, site=site, retrieved_at=now_iso(), job=job)
    old = load_record(rec.id)
    if old and old.fit:
        rec.fit = old.fit  # keep an earlier fit judgement unless replaced explicitly
    save_record(rec)
    return rec


def load_record(job_id: str) -> JobRecord | None:
    path = record_path(job_id)
    if not path.exists():
        return None
    return JobRecord.model_validate_json(path.read_text(encoding="utf-8"))


def attach_fit(job_id: str, fit: FitAssessment) -> JobRecord:
    rec = load_record(job_id)
    if rec is None:
        raise ValueError(f"No saved job with id {job_id}. Import the job first.")
    rec.fit = fit
    save_record(rec)
    return rec


def all_records() -> list[JobRecord]:
    folder = paths.jobs_dir()
    if not folder.exists():
        return []
    records = []
    for p in sorted(folder.glob("*.json")):
        try:
            records.append(JobRecord.model_validate_json(p.read_text(encoding="utf-8")))
        except ValueError:
            continue  # files from an older format are skipped, not fatal
    return records
