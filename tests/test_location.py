"""Where a job can be done from: official locations, remote eligibility, and stale LinkedIn links.

Cases come from real postings that slipped through: a remote job open only to Latin America
(Lever `allLocations`), one open only to the US and Canada (Ashby `secondaryLocations`), one
open only to Egypt, and LinkedIn pages that search engines kept indexed for years.
"""

import json
from datetime import date

from conftest import make_job

from job_analyzer import cli, live
from job_analyzer.commands.importing import official_places
from job_analyzer.matching import check_location, evaluate
from job_analyzer.models import Place
from job_analyzer.profile import Profile
from job_analyzer.search import (
    SearchBatch,
    SearchResult,
    linkedin_stale,
    location_ok,
    merge_batches,
    open_to_ok,
    write_run_files,
)

HOME = ["brussels", "belgium"]


def profile(**kw) -> Profile:
    base = dict(locations=[Place(city="Brussels", country="Belgium")], work_arrangements=["remote", "hybrid"])
    base.update(kw)
    return Profile(**base)


# --- official feeds: every place a job is open to ---

def test_lever_lists_all_locations():
    data = [{"hostedUrl": "https://jobs.lever.co/acme/1", "text": "Senior DevOps Engineer",
             "categories": {"location": "Bogotá", "allLocations": ["Bogotá", "Argentina", "Chile"]},
             "workplaceType": "remote", "createdAt": 1793534400000, "descriptionPlain": "AWS"}]
    j = live.fetch_lever("acme", lambda url: json.dumps(data).encode())[0]
    assert j.location == "Bogotá; Argentina; Chile (remote)"
    assert not location_ok(j.location, HOME)


def test_ashby_includes_secondary_locations():
    data = {"jobs": [{"jobUrl": "https://jobs.ashbyhq.com/acme/x", "title": "Sr. SRE", "location": "United States",
                      "secondaryLocations": [{"location": "Canada"}], "isRemote": True,
                      "publishedAt": "2026-11-10T06:40:24.278+00:00", "descriptionPlain": "Kubernetes"}]}
    j = live.fetch_ashby("acme", lambda url: json.dumps(data).encode())[0]
    assert j.location == "Remote - United States; Canada"
    assert not location_ok(j.location, HOME)


def test_several_locations_keep_job_if_any_fits():
    assert location_ok("Remote - Europe; United States", HOME)
    assert location_ok("Berlin; Brussels (hybrid)", HOME)
    assert not location_ok("Egypt (remote)", HOME)


# --- search hits take the official location and date ---

def test_search_hit_uses_official_location_and_date():
    url = "https://jobs.lever.co/acme/1"
    hit = SearchResult(url=url, title="Senior DevOps Engineer", company="Acme", site="jobs.lever.co", snippet=None)
    official = {url: {"location": "Bogotá; Argentina (remote)", "posted_date": "2026-11-01"}}
    r = merge_batches([SearchBatch(site_group="A", queries=[], errors=[], results=[hit])], set(),
                      places=HOME, today=date(2026, 11, 20), live_boards={"lever:acme"}, live_urls=official)
    assert r.queue == [] and r.coverage["stats"]["other_location"] == 1

    official[url] = {"location": "Remote - Europe", "posted_date": "2026-07-21"}
    r = merge_batches([SearchBatch(site_group="A", queries=[], errors=[], results=[hit])], set(),
                      places=HOME, today=date(2026, 11, 20), live_boards={"lever:acme"}, live_urls=official)
    assert r.queue == [] and r.coverage["stats"]["too_old"] == 1


# --- remote eligibility is checked in code, after extraction ---

def test_open_to_regions_and_countries():
    assert open_to_ok([], HOME)
    assert open_to_ok(["Europe"], HOME) and open_to_ok(["EMEA"], HOME) and open_to_ok(["Worldwide"], HOME)
    assert open_to_ok(["Belgium", "Netherlands"], HOME)
    assert open_to_ok(["CET time zone"], HOME)  # a time zone, not a place: can't tell, so keep
    assert not open_to_ok(["United States", "Canada"], HOME)
    assert not open_to_ok(["Egypt"], HOME)


def test_remote_job_for_other_countries_is_excluded_even_with_soft_location():
    job = make_job(remote_policy="remote", location=None, open_to=["United States", "Canada"])
    check = check_location(job, profile(location_priority="soft"))
    assert check.outcome == "mismatch" and check.priority == "hard"
    assert "United States, Canada" in evaluate(job, profile()).exclusion_reasons[0]


def test_remote_job_open_to_europe_matches():
    job = make_job(remote_policy="remote", location=None, open_to=["Europe"])
    assert check_location(job, profile()).outcome == "match"


def test_official_places_from_feed_location():
    assert official_places("Remote - United States; Canada") == ["United States", "Canada"]
    assert official_places("Bogotá; Argentina (remote)") == ["Bogotá", "Argentina"]
    assert official_places("Remote") == [] and official_places("Anywhere in the World") == []


def test_import_fills_open_to_from_live_candidate(tmp_path):
    url = "https://jobs.ashbyhq.com/acme/x"
    hit = SearchResult(url=url, title="SRE", company="Acme", site="jobs.ashbyhq.com", snippet=None,
                       location="Remote - United States; Canada", posted_date="2026-11-10")
    write_run_files(merge_batches([SearchBatch(site_group="A", queries=[], errors=[], results=[hit])], set()), 10)
    f = tmp_path / "job.json"
    f.write_text(make_job(remote_policy="remote", location=None, salary=None).model_dump_json(), encoding="utf-8")
    assert cli.do_import("job", f, url=url) == 0
    from job_analyzer import jobs
    assert jobs.load_record(jobs.url_id(url)).job.open_to == ["United States", "Canada"]


# --- LinkedIn: the job ID is the only date signal ---

def test_old_linkedin_ids_are_stale():
    assert linkedin_stale("https://www.linkedin.com/jobs/view/3366199870")
    assert linkedin_stale("https://be.linkedin.com/jobs/view/site-reliability-engineer-at-acme-3630007726")
    assert linkedin_stale("https://www.linkedin.com/jobs/search/?currentJobId=2466425826")
    assert not linkedin_stale("https://www.linkedin.com/jobs/view/4490672078")
    assert not linkedin_stale("https://jobs.lever.co/acme/3366199870")


def test_merge_drops_stale_linkedin_hits():
    old = SearchResult(url="https://www.linkedin.com/jobs/view/3366199870", title="Cloud Engineer",
                       company="Acme", site="linkedin.com", snippet=None)
    new = SearchResult(url="https://www.linkedin.com/jobs/view/4490672078", title="DevOps Engineer",
                       company="Acme", site="linkedin.com", snippet=None)
    r = merge_batches([SearchBatch(site_group="A", queries=[], errors=[], results=[old, new])], set())
    kept = [c.url for c in r.queue + r.manual]
    assert kept == ["https://www.linkedin.com/jobs/view/4490672078"]
    assert r.coverage["stats"]["too_old"] == 1
