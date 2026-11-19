"""Commands that call the Claude API directly (need ANTHROPIC_API_KEY)."""

import sys
from pathlib import Path

from job_analyzer import jobs
from job_analyzer.commands.report import print_job, print_match
from job_analyzer.cv import extract_cv_facts, find_cv
from job_analyzer.extract import extract_requirements
from job_analyzer.matching import evaluate
from job_analyzer.profile import Profile, load_profile, save_profile
from job_analyzer.setup import describe, run_setup


def do_setup() -> Profile:
    cv_path = find_cv()
    facts = None
    if cv_path:
        print(f"Reading your CV ({cv_path})...")
        facts = extract_cv_facts(cv_path)
    profile = run_setup(facts)
    saved = save_profile(profile)
    print(f"\nSaved to {saved}:\n{describe(profile)}\n")
    return profile


def do_analyze(posting: Path, as_json: bool) -> None:
    profile = load_profile()
    if profile is None:
        if not sys.stdin.isatty():
            raise SystemExit("No profile yet. Run: job-analyzer setup")
        print("No profile found. Let's create one first (only needed once).")
        profile = do_setup()

    job = extract_requirements(posting.read_text(encoding="utf-8"))
    jobs.add_job(job)
    report = evaluate(job, profile)
    if as_json:
        print(job.model_dump_json(indent=2))
    else:
        print_job(job)
        print_match(report)
