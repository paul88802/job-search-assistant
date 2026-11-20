"""`job-analyzer track`: record applications and see what to do next."""

from job_analyzer import tracker


def _line(a: dict) -> str:
    when = f"applied {a['applied_on']}" if a["applied_on"] else "applied (date unknown)"
    head = f"[{a['status']}] {a['title']} @ {a['company'] or '?'} · {when} · JOB_ID={a['job_id']}"
    return f"{head}\n    -> {a['next_step']}" + (f"\n    {a['url']}" if a["url"] else "")


def do_track(action: str, job: str | None, status: str | None, on: str | None, note: str | None,
             title: str | None, company: str | None, show_all: bool) -> int:
    if action == "add":
        if not job:
            raise ValueError("Give the job's link or JOB_ID.")
        a = tracker.add_application(job, applied_on=on, note=note, title=title, company=company)
        print(f"Tracked: {a.title} @ {a.company} (applied {a.applied_on or 'on an unknown date'})")
    elif action == "update":
        if not job or not status:
            raise ValueError("Give the job's link or JOB_ID and the new status.")
        a = tracker.update_application(job, status, on=on, note=note)
        print(f"Updated: {a.title} @ {a.company} -> {a.status}")
    else:
        rows = tracker.summary(include_closed=show_all)
        if not rows:
            print("No applications tracked yet." if show_all else "No open applications (use --all for closed ones).")
        for a in rows:
            print(_line(a))
    return 0
