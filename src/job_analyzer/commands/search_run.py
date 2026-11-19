"""The deterministic steps of a /find-jobs run: plan, brief, merge, shortlist."""

import json
import sys
from datetime import datetime
from pathlib import Path

from pydantic import ValidationError

from job_analyzer import jobs, paths
from job_analyzer.brief import candidate_brief, cv_text, load_details
from job_analyzer.profile import Profile, countries_to_research, load_profile, search_groups
from job_analyzer.ranking import rank, records_from_latest_run, render_markdown
from job_analyzer.search import SearchBatch, job_key, merge_batches, next_batch, write_run_files
from job_analyzer.specs import validation_errors


def _require_profile() -> Profile:
    profile = load_profile()
    if profile is None:
        raise ValueError("No profile yet. Run /setup-profile (or job-analyzer setup) first.")
    return profile


def do_plan() -> int:
    """Everything the /find-jobs coordinator needs to plan a run, as JSON."""
    profile = _require_profile()
    print(json.dumps({
        "groups": search_groups(profile),
        "research_countries": countries_to_research(profile),
        "global_domains": sorted({d for ds in profile.search_sites.values() for d in ds}),
        "titles": profile.target_titles,
        "keywords": profile.keywords,
        "locations": [str(p) for p in profile.locations],
        "work_arrangements": profile.work_arrangements,
        "max_postings": profile.max_postings,
    }, indent=2, ensure_ascii=False))
    return 0


def do_brief() -> int:
    print(candidate_brief(_require_profile(), load_details()))
    return 0


def do_merge(files: list[Path], limit: int | None) -> int:
    """Validate every search batch, merge them, drop duplicates, pick candidates."""
    batches, invalid = [], 0
    for f in files:
        try:
            batches.append(SearchBatch.model_validate_json(f.read_text(encoding="utf-8")))
        except ValidationError as e:
            invalid += 1
            print(f"INVALID search batch {f}:\n{validation_errors(e)}", file=sys.stderr)
    if invalid:
        return 2

    profile = load_profile() or Profile()
    records = jobs.all_records()
    known_ids = {r.id for r in records}
    known_keys: dict = {}
    for r in records:
        key = job_key(r.job.company, r.job.title)
        if key:
            known_keys.setdefault(key, []).append(r.job.posted_date)
    places = [p for place in profile.locations for p in (place.city, place.country) if p]
    result = merge_batches(batches, known_ids, known_keys, places=places)
    write_run_files(result, target=limit or profile.max_postings)

    s = result.coverage["stats"]
    print(f"{s['found']} found · {s['duplicates']} duplicates · {s['already_analyzed']} already analyzed · "
          f"{s['other_location']} other location · {s['too_old']} too old · "
          f"{s['readable']} readable (queue) · {s['manual_check']} to check yourself")
    for e in result.coverage["errors"]:
        print(f"  search failed on {e['site']}: {e['error_type']} ({'retryable' if e['retryable'] else 'final'})")
    print("Next: run `job-analyzer next` to get the first wave of candidates.")
    return 0


def do_next(wave: int) -> int:
    """Print the next candidates to analyze (JSON), replacing failed ones (backfill)."""
    run_started = json.loads(paths.run_file().read_text(encoding="utf-8"))["started_at"]
    succeeded = {r.id for r in jobs.all_records() if r.fit and r.retrieved_at >= run_started}
    batch, info = next_batch(succeeded, wave)
    print(json.dumps({**info, "candidates": [c.model_dump() for c in batch]}, indent=2, ensure_ascii=False))
    return 0


def do_shortlist(top: int, all_runs: bool) -> int:
    profile = _require_profile()
    records = jobs.all_records()
    if not all_runs:
        records = records_from_latest_run(records)
    included, excluded = rank(records, profile, cv_text(profile, load_details()))
    text = render_markdown(included, excluded, top)
    folder = paths.shortlists_dir()
    folder.mkdir(parents=True, exist_ok=True)
    out = folder / f"{datetime.now():%Y-%m-%d-%H%M}.md"
    out.write_text(text, encoding="utf-8")
    print(text)
    print(f"\nSaved {out}")
    return 0
