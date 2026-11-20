"""`spec` and `import`: the bridge between Claude Code mode and the shared data files.

Claude Code writes JSON; this module validates it against the same schemas API mode
uses, and stores it in the same place. Invalid JSON is rejected with a list of the
exact fields to fix, which the agent uses for a retry.
"""

import sys
from datetime import date
from pathlib import Path

from pydantic import ValidationError

from job_analyzer import jobs
from job_analyzer.commands.report import print_job, print_match
from job_analyzer.cv import find_cv, save_cv_details
from job_analyzer.matching import evaluate
from job_analyzer.profile import CountryBoards, load_profile, save_profile
from job_analyzer.setup import describe
from job_analyzer.search import load_candidates
from job_analyzer.specs import SPECS, validation_errors


def do_import(kind: str, file: Path, url: str | None = None, site: str | None = None,
              job_id: str | None = None) -> int:
    model = SPECS[kind][1]
    try:
        obj = model.model_validate_json(file.read_text(encoding="utf-8"))
    except ValidationError as e:
        print(f"INVALID {kind} JSON. Fix these fields and import again:\n{validation_errors(e)}",
              file=sys.stderr)
        return 2

    if kind == "job":
        if url:
            fill_from_source(obj, url)
        rec = jobs.add_job(obj, url=url, site=site)
        print(f"JOB_ID={rec.id}")
        print_job(obj)
        profile = load_profile()
        if profile:
            print_match(evaluate(obj, profile))
        else:
            print("\n(No profile yet, so preferences weren't checked.)")
    elif kind == "fit":
        if not job_id:
            raise ValueError("Importing a fit needs --job <JOB_ID> (printed when the job was imported).")
        rec = jobs.attach_fit(job_id, obj)
        print(f"Saved fit {obj.fit_score}/100 for {rec.job.title} @ {rec.job.company} (JOB_ID={rec.id})")
    elif kind == "salary-estimate":
        if not job_id:
            raise ValueError("Importing a salary estimate needs --job <JOB_ID>.")
        rec = jobs.attach_salary_estimate(job_id, obj)
        print(f"Saved salary estimate for {rec.job.title} @ {rec.job.company}: gross "
              f"{obj.gross_monthly_low:.0f}-{obj.gross_monthly_high:.0f} {obj.currency}/month, "
              f"net ~{obj.net_monthly_low:.0f}-{obj.net_monthly_high:.0f} ({obj.confidence} confidence)")
    elif kind == "profile":
        saved = save_profile(obj)
        print(f"Saved {saved}:\n{describe(obj)}")
    elif kind == "cv-details":
        cv_path = find_cv()
        if cv_path is None:
            raise ValueError("No CV found in data/.")
        save_cv_details(obj, cv_path)
        print(f"Saved CV sections for {cv_path}: {len(obj.experience)} jobs, "
              f"{len(obj.education)} education entries, {len(obj.certifications)} certifications")
    elif kind == "country-boards":
        _save_country_boards(obj)
    else:
        print(f"'{kind}' is valid (nothing to store).")
    return 0


def fill_from_source(job, url: str) -> None:
    """Fill facts the posting text didn't state from the run's candidate data.

    Official APIs/feeds give the publish date and remote status as data, but the job text
    an analyst reads often doesn't repeat them. Code copies them over; it never overrides
    what the posting itself says.
    """
    cand = next((c for c in load_candidates() if c.id == jobs.url_id(url)), None)
    if cand is None:
        return
    if job.posted_date is None and cand.posted_date:
        job.posted_date = cand.posted_date
    if job.remote_policy == "unknown" and cand.location:
        loc = cand.location.casefold()
        if "hybrid" in loc:
            job.remote_policy = "hybrid"
        elif "remote" in loc or "anywhere" in loc or "worldwide" in loc:
            job.remote_policy = "remote"


def _clean_domain(raw: str) -> str:
    d = raw.strip().lower().removeprefix("https://").removeprefix("http://")
    return d.removeprefix("www.").split("/")[0]


def _save_country_boards(report) -> None:
    profile = load_profile()
    if profile is None:
        raise ValueError("No profile yet. Run /setup-profile first.")
    global_domains = {d for ds in profile.search_sites.values() for d in ds}
    domains: list[str] = []
    for b in report.boards:
        d = _clean_domain(b.domain)
        if d and d not in domains and not any(d == g or d.endswith("." + g) for g in global_domains):
            domains.append(d)
    if not domains:
        raise ValueError("No new boards: every domain is already searched globally.")
    profile.country_job_boards[report.country] = CountryBoards(
        domains=domains, checked_at=date.today().isoformat())
    save_profile(profile)
    print(f"Saved {len(domains)} job boards for {report.country}: {', '.join(domains)}")
    for b in report.boards:
        print(f"  - {b.name} ({b.domain}): {b.why}")
