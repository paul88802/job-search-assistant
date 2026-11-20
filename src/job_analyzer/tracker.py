"""Application tracker: which jobs you applied to, and what happened next.

Plain code, no AI: one JSON file (data/applications.json), one entry per job, keyed by the
same job ID as the saved postings. Every status change is kept in a history, so the tracker
can say how long you've been waiting and when to follow up.

Used three ways, all through the functions below: the `job-analyzer track` command, the
tracker MCP server (so Claude can update it when you say "I applied to X"), and the shortlist,
which marks jobs you've already applied to.
"""

import hashlib
import json
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from job_analyzer import jobs, paths

Status = Literal["applied", "interviewing", "offer", "rejected", "withdrawn", "no_response"]
STATUSES: tuple[str, ...] = Status.__args__
OPEN_STATUSES = {"applied", "interviewing"}
FOLLOW_UP_DAYS = 14   # no answer after two weeks: send a follow-up
GIVE_UP_DAYS = 45     # no answer after six weeks: probably no_response


class StatusChange(BaseModel):
    on: str | None = Field(description="Date of the change, YYYY-MM-DD; null if unknown.")
    status: Status
    note: str | None = None


class Application(BaseModel):
    job_id: str
    title: str
    company: str | None
    url: str | None
    applied_on: str | None = Field(description="YYYY-MM-DD; null when you don't remember the date.")
    status: Status
    history: list[StatusChange]

    @property
    def last_change(self) -> str | None:
        return next((h.on for h in reversed(self.history) if h.on), None)


def _check_date(value: str | None, today: date) -> str | None:
    if value is None:
        return None
    try:
        d = date.fromisoformat(value)
    except ValueError:
        raise ValueError(f"'{value}' is not a date: use YYYY-MM-DD.") from None
    if d > today:
        raise ValueError(f"{value} is in the future.")
    return d.isoformat()


def load_applications() -> dict[str, Application]:
    f = paths.applications_file()
    if not f.exists():
        return {}
    return {k: Application.model_validate(v) for k, v in json.loads(f.read_text(encoding="utf-8")).items()}


def save_applications(apps: dict[str, Application]) -> None:
    f = paths.applications_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    data = {k: a.model_dump() for k, a in sorted(apps.items(), key=lambda kv: kv[1].applied_on or "")}
    f.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _resolve(job: str, apps: dict[str, Application]) -> str:
    """A job ID, or a posting link (any form of it), -> the job ID."""
    job = job.strip()
    if job in apps or jobs.load_record(job):
        return job
    if job.startswith("http"):
        return jobs.url_id(job)
    raise ValueError(f"No saved job with id '{job}'. Use the posting's link or its JOB_ID.")


def add_application(job: str, applied_on: str | None = None, note: str | None = None,
                    title: str | None = None, company: str | None = None,
                    today: date | None = None) -> Application:
    """Record that you applied. `job` is a saved job's ID or link.

    A job the tool never saved (e.g. found on LinkedIn yourself) needs its link, title and company.
    """
    today = today or date.today()
    apps = load_applications()
    if not job.startswith("http") and not jobs.load_record(job.strip()) and title:
        job_id = hashlib.sha1(f"{company}|{title}".casefold().encode()).hexdigest()[:12]
    else:
        job_id = _resolve(job, apps)
    if job_id in apps:
        raise ValueError(f"Already tracked: {apps[job_id].title} @ {apps[job_id].company}. "
                         "Use update to change its status.")
    rec = jobs.load_record(job_id)
    if rec is None and not title:
        raise ValueError("This job isn't saved in the tool, so give its title and company too.")
    applied_on = _check_date(applied_on, today)
    app = Application(
        job_id=job_id,
        title=rec.job.title if rec else title,
        company=rec.job.company if rec else company,
        url=rec.source_url if rec else (job if job.startswith("http") else None),
        applied_on=applied_on, status="applied",
        history=[StatusChange(on=applied_on, status="applied", note=note)],
    )
    apps[job_id] = app
    save_applications(apps)
    return app


def update_application(job: str, status: str, on: str | None = None, note: str | None = None,
                       today: date | None = None) -> Application:
    """Move an application to a new status (interviewing, offer, rejected, ...)."""
    today = today or date.today()
    if status not in STATUSES:
        raise ValueError(f"Unknown status '{status}'. Use one of: {', '.join(STATUSES)}.")
    apps = load_applications()
    job_id = _resolve(job, apps)
    if job_id not in apps:
        raise ValueError("You haven't recorded applying to this job yet. Add it first.")
    app = apps[job_id]
    app.status = status
    app.history.append(StatusChange(on=_check_date(on, today) or today.isoformat(), status=status, note=note))
    save_applications(apps)
    return app


def next_step(app: Application, today: date | None = None) -> str:
    """What to do about an application now. Plain rules, so they're predictable."""
    today = today or date.today()
    if app.status == "applied":
        if app.applied_on is None:
            return "Applied on an unknown date: follow up if you've heard nothing."
        days = (today - date.fromisoformat(app.applied_on)).days
        if days >= GIVE_UP_DAYS:
            return f"No answer after {days} days: probably mark it no_response."
        if days >= FOLLOW_UP_DAYS:
            return f"No answer after {days} days: send a short follow-up."
        return f"Waiting ({days} days). Follow up after {FOLLOW_UP_DAYS} days."
    if app.status == "interviewing":
        return "In process: prepare for the next round."
    if app.status == "offer":
        return "Offer: compare it with the salary estimate before answering."
    return "Closed."


def summary(include_closed: bool = True, today: date | None = None) -> list[dict]:
    """All applications as plain data, newest first, each with its next step."""
    today = today or date.today()
    apps = [a for a in load_applications().values() if include_closed or a.status in OPEN_STATUSES]
    apps.sort(key=lambda a: a.last_change or "", reverse=True)
    return [{**a.model_dump(exclude={"history"}), "last_change": a.last_change,
             "next_step": next_step(a, today), "history": [h.model_dump() for h in a.history]}
            for a in apps]
