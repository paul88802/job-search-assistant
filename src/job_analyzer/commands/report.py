"""Printing a posting and its preference check in the terminal."""

from job_analyzer.matching import MatchReport
from job_analyzer.models import JobRequirements

ICONS = {"match": "OK ", "mismatch": "NO ", "unknown": "?? "}


def print_job(job: JobRequirements) -> None:
    print(f"\n{job.title}" + (f" @ {job.company}" if job.company else ""))
    print("-" * 60)
    print(f"Seniority:    {job.seniority}")
    print(f"Location:     {job.location or 'not stated'} ({job.remote_policy})")
    if job.posted_date:
        print(f"Posted:       {job.posted_date}")
    if job.years_experience_min is not None:
        print(f"Experience:   {job.years_experience_min}+ years")
    print(f"Salary:       {job.salary.raw_text if job.salary else 'not stated'}")
    print(f"Languages:    {', '.join(str(g) for g in job.languages_required) or 'not stated'}")
    if job.languages_nice_to_have:
        print(f"  (a plus:    {', '.join(str(l) for l in job.languages_nice_to_have)})")
    print(f"\nMust have:    {', '.join(job.must_have_skills) or '-'}")
    print(f"Nice to have: {', '.join(job.nice_to_have_skills) or '-'}")
    if job.red_flags:
        print("\nRed flags:")
        for flag in job.red_flags:
            print(f"  ! {flag}")
    print(f"\n{job.summary}")


def print_match(report: MatchReport) -> None:
    print("\nYour preferences")
    print("-" * 60)
    for c in report.checks:
        tag = "must" if c.priority == "hard" else "pref"
        print(f"  {ICONS[c.outcome]} {c.criterion:<17} ({tag})  {c.detail}")
    if report.excluded:
        print(f"\n  EXCLUDED: breaks a must-have. Score would be {report.score}/100.\n")
    else:
        print(f"\n  Preference score: {report.score}/100\n")
