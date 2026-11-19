"""The code side of /find-jobs: provenance, dedupe, coverage and ranking."""

import json

from conftest import make_job

from job_analyzer import cli, jobs, paths
from job_analyzer.brief import candidate_brief
from job_analyzer.models import FitAssessment
from job_analyzer.profile import Profile
from job_analyzer.ranking import keyword_score, rank, render_markdown
from job_analyzer.search import SearchBatch, SearchError, SearchResult, merge_batches


def result(url, title="Cloud Engineer", company="Acme", site="jobat.be"):
    return SearchResult(url=url, title=title, company=company, site=site, snippet=None)


def fit(score):
    return FitAssessment(fit_score=score, matching_skills=["AWS (Acme Corp)"], gaps=["Azure"],
                         how_to_address="Mention AWS certs.", summary="Good fit.")


def merge(batches, known=frozenset(), limit=None, known_keys=None, **kw):
    """All unique postings (analysis queue first, then the check-yourself list) + coverage."""
    r = merge_batches(batches, set(known), known_keys, **kw)
    everything = r.queue + r.manual
    return (everything[:limit] if limit else everything), r.coverage


# --- job records & IDs ---

def test_same_posting_with_tracking_params_gets_same_id():
    a = jobs.url_id("https://www.linkedin.com/jobs/view/123/?refId=abc&trk=x")
    b = jobs.url_id("https://WWW.LINKEDIN.COM/jobs/view/123")
    assert a == b


def test_reimport_updates_same_record_and_keeps_fit():
    rec = jobs.add_job(make_job(), url="https://x.com/job/1")
    jobs.attach_fit(rec.id, fit(80))
    again = jobs.add_job(make_job(title="Cloud Engineer II"), url="https://x.com/job/1")
    assert again.id == rec.id and again.fit.fit_score == 80
    assert len(jobs.all_records()) == 1


def test_fit_score_out_of_range_is_rejected():
    import pytest
    with pytest.raises(ValueError):
        fit(140)


# --- merging search batches ---

def test_merge_removes_duplicates_and_known_jobs():
    known = {jobs.url_id("https://a.be/job/1")}
    batches = [
        SearchBatch(site_group="Belgian", queries=["q"], errors=[], results=[
            result("https://a.be/job/1"),                          # already analyzed earlier
            result("https://a.be/job/2"),
            result("https://a.be/job/2?utm_source=google"),        # same URL, tracking param
        ]),
        SearchBatch(site_group="LinkedIn", queries=["q"], errors=[], results=[
            result("https://linkedin.com/jobs/view/9", company="Acme"),  # same company+title as job/2
            result("https://linkedin.com/jobs/view/10", title="SRE"),
        ]),
    ]
    picked, coverage = merge(batches, known, limit=10)
    assert [c.url for c in picked] == ["https://a.be/job/2", "https://linkedin.com/jobs/view/10"]
    assert coverage["stats"] == {"found": 5, "duplicates": 2, "already_analyzed": 1,
                                 "same_title_other_date": 0, "other_location": 0, "too_old": 0, "closed": 0,
                                 "new_unique": 2, "readable": 1, "manual_check": 1}


# --- duplicates by company + title + date posted ---

def batch(group, *results):
    return SearchBatch(site_group=group, queries=["q"], errors=[], results=list(results))


def dated(url, date, title="DevOps Engineer", company="Acme", site="jobat.be"):
    return SearchResult(url=url, title=title, company=company, site=site, snippet=None, posted_date=date)


def test_same_company_title_and_date_is_one_job():
    picked, cov = merge([batch("A", dated("https://a.be/1", "2026-11-10")),
                                 batch("B", dated("https://b.be/9", "2026-11-10"))], set(), 10)
    assert len(picked) == 1 and cov["stats"]["duplicates"] == 1


def test_same_company_title_different_dates_are_two_jobs():
    picked, cov = merge([batch("A", dated("https://a.be/1", "2026-10-01"),
                                       dated("https://a.be/2", "2026-11-10"))], set(), 10)
    assert len(picked) == 2 and cov["stats"]["same_title_other_date"] == 1


def test_missing_date_counts_as_same_job():
    picked, _ = merge([batch("A", dated("https://a.be/1", None)),
                               batch("B", dated("https://b.be/1", "2026-11-10"))], set(), 10)
    assert len(picked) == 1 and picked[0].posted_date == "2026-11-10"


def test_readable_copy_wins_and_linkedin_link_is_kept():
    li = dated("https://www.linkedin.com/jobs/view/42", "2026-11-10", site="linkedin.com")
    company_page = dated("https://jobs.lever.co/acme/7", "2026-11-10", site="lever.co")
    picked, _ = merge([batch("LinkedIn", li), batch("Company career pages", company_page)], set(), 10)
    assert len(picked) == 1
    assert picked[0].site == "lever.co"
    assert picked[0].also_seen_at == ["https://www.linkedin.com/jobs/view/42"]


def test_gender_tags_and_company_suffixes_are_ignored():
    a = dated("https://a.be/1", None, title="DevOps Engineer (m/f/x)", company="Acme NV")
    b = dated("https://b.be/1", None, title="DevOps engineer", company="ACME")
    picked, _ = merge([batch("A", a, b)], set(), 10)
    assert len(picked) == 1


def test_job_analyzed_in_earlier_run_is_skipped_by_key():
    known_keys = {("acme", "devops engineer"): ["2026-11-10"]}
    picked, cov = merge([batch("A", dated("https://new-link.be/5", "2026-11-10"))],
                                set(), 10, known_keys)
    assert picked == [] and cov["stats"]["already_analyzed"] == 1


# --- country job boards ---

def test_countries_to_research_missing_and_stale():
    from datetime import date
    from job_analyzer.models import Place
    from job_analyzer.profile import CountryBoards, countries_to_research
    p = Profile(locations=[Place(city="Brussels", country="Belgium"), Place(city=None, country="Netherlands")],
                country_job_boards={"Belgium": CountryBoards(domains=["jobat.be"], checked_at="2026-11-01")})
    assert countries_to_research(p, date(2026, 11, 19)) == ["Netherlands"]
    assert countries_to_research(p, date(2027, 3, 1)) == ["Belgium", "Netherlands"]  # Belgium is stale


def test_search_groups_add_one_group_per_country():
    from job_analyzer.profile import CountryBoards, search_groups
    p = Profile(country_job_boards={"Belgium": CountryBoards(domains=["jobat.be"], checked_at="2026-11-19")})
    groups = search_groups(p)
    assert groups["Belgium job boards"] == ["jobat.be"] and "LinkedIn" in groups


def test_import_country_boards_cleans_domains_and_skips_global_ones(tmp_path, capsys):
    from job_analyzer.profile import load_profile, save_profile
    save_profile(Profile())
    f = tmp_path / "boards.json"
    f.write_text(json.dumps({"country": "Belgium", "boards": [
        {"name": "Jobat", "domain": "https://www.jobat.be/", "why": "largest"},
        {"name": "ICTJob", "domain": "ictjob.be", "why": "IT"},
        {"name": "LinkedIn", "domain": "linkedin.com", "why": "global"},  # already searched globally
    ]}))
    assert cli.do_import("country-boards", f) == 0
    assert load_profile().country_job_boards["Belgium"].domains == ["jobat.be", "ictjob.be"]


def test_merge_takes_candidates_round_robin_across_sites():
    big = SearchBatch(site_group="Big", queries=["q"], errors=[],
                      results=[result(f"https://big.com/{i}", title=f"T{i}") for i in range(5)])
    small = SearchBatch(site_group="Small", queries=["q"], errors=[],
                        results=[result("https://small.com/1", title="S1")])
    picked, _ = merge([big, small], set(), limit=3)
    assert [c.site_group for c in picked] == ["Big", "Small", "Big"]


def test_failed_search_is_reported_not_hidden():
    failed = SearchBatch(site_group="LinkedIn", queries=["sre brussels"], results=[], errors=[
        SearchError(site="linkedin.com", query="sre brussels", error_type="blocked",
                    detail="Search tool returned an error", retryable=False)])
    empty_ok = SearchBatch(site_group="Remote", queries=["sre remote"], results=[], errors=[])
    _, coverage = merge([failed, empty_ok], set(), limit=10)
    assert coverage["groups"]["LinkedIn"]["errors"] == 1
    assert coverage["groups"]["Remote"] == {"queries": 1, "results": 0, "errors": 0}  # valid empty
    assert coverage["errors"][0]["error_type"] == "blocked"


def test_merge_command_rejects_invalid_batch(tmp_path, capsys):
    bad = tmp_path / "b.json"
    bad.write_text(json.dumps({"site_group": "X", "queries": [], "results": [{"url": "u"}]}))
    assert cli.do_merge([bad], None) == 2
    assert "INVALID" in capsys.readouterr().err


# --- ranking ---

def test_keyword_baseline():
    rec = jobs.add_job(make_job(must_have_skills=["Python", "Kubernetes"]), url="https://x.com/1")
    assert keyword_score(rec, "python, aws") == 50


def test_rank_orders_by_fit_and_separates_exclusions():
    p = Profile(work_arrangements=["remote", "hybrid"])
    strong = jobs.add_job(make_job(title="A"), url="https://x.com/a")
    weak = jobs.add_job(make_job(title="B"), url="https://x.com/b")
    onsite = jobs.add_job(make_job(title="C", remote_policy="onsite"), url="https://x.com/c")
    jobs.attach_fit(strong.id, fit(90))
    jobs.attach_fit(weak.id, fit(40))
    included, excluded = rank(jobs.all_records(), p, "aws")
    assert [r.record.job.title for r in included] == ["A", "B"]
    assert [r.record.job.title for r in excluded] == ["C"]


def test_shortlist_shows_links_gaps_and_coverage():
    paths.inbox_dir().mkdir(parents=True, exist_ok=True)
    paths.analysis_errors_file().write_text(json.dumps(
        [{"url": "https://linkedin.com/jobs/view/7", "error_type": "access_failure", "detail": "login wall"}]))
    rec = jobs.add_job(make_job(), url="https://x.com/a", site="jobat.be")
    jobs.attach_fit(rec.id, fit(85))
    included, excluded = rank(jobs.all_records(), Profile(), "")
    md = render_markdown(included, excluded, top=10)
    assert "https://x.com/a" in md and "Fit 85/100" in md and "Gaps: Azure" in md
    assert "Couldn't analyze https://linkedin.com/jobs/view/7" in md


def test_brief_contains_cv_experience():
    from conftest import FakeClient  # noqa: F401  (fixtures loaded)
    from test_copykit import DETAILS
    text = candidate_brief(Profile(target_titles=["SRE"]), DETAILS)
    assert "Cloud Engineer @ Acme & Sons" in text and "Migrated 40 services" in text


# --- fixes after the first real run ---

def located(url, location, site="lever.co", date=None, title="SRE", company="Acme"):
    return SearchResult(url=url, title=title, company=company, site=site, snippet=None,
                        posted_date=date, location=location)


def test_hard_to_read_sites_go_to_check_yourself_list():
    r = merge_batches([batch("LinkedIn", located("https://be.linkedin.com/jobs/view/1", None, site="be.linkedin.com")),
                       batch("Remote", located("https://weworkremotely.com/remote-jobs/x", None,
                                               site="weworkremotely.com", company="Other")),
                       batch("Company", located("https://jobs.lever.co/acme/2", None, company="Third"))], set())
    assert [c.site for c in r.queue] == ["lever.co"]
    assert {c.site for c in r.manual} == {"be.linkedin.com", "weworkremotely.com"}


def test_location_filter_keeps_home_country_remote_europe_and_unknown():
    places = ["brussels", "belgium"]
    r = merge_batches([batch("A",
        located("https://x.com/1", "Brussels, Belgium", company="A"),
        located("https://x.com/2", "Remote - Europe", company="B"),
        located("https://x.com/3", None, company="C"),
        located("https://x.com/4", "Remote - US", company="D"),
        located("https://x.com/5", "Toronto, Canada", company="E"),
        located("https://x.com/6", "Germany/Austria/UK", company="F"),
    )], set(), places=places)
    assert [c.company for c in r.queue] == ["A", "B", "C"]
    assert r.coverage["stats"]["other_location"] == 3


def test_old_postings_are_dropped():
    from datetime import date
    r = merge_batches([batch("A", located("https://x.com/1", None, date="2026-06-01", company="Old"),
                              located("https://x.com/2", None, date="2026-11-01", company="New"))],
                      set(), today=date(2026, 11, 19))
    assert [c.company for c in r.queue] == ["New"] and r.coverage["stats"]["too_old"] == 1


# --- backfill ---

def start_run(n_candidates, target):
    from job_analyzer.search import write_run_files
    results = [located(f"https://x.com/{i}", None, company=f"C{i}") for i in range(n_candidates)]
    write_run_files(merge_batches([batch("A", *results)], set()), target=target)
    return [jobs.url_id(f"https://x.com/{i}") for i in range(n_candidates)]


def write_status(job_id, status):
    paths.analysis_dir().mkdir(parents=True, exist_ok=True)
    (paths.analysis_dir() / f"{job_id}-status.json").write_text(json.dumps({"status": status}))


def test_next_gives_first_wave_then_backfills_failures():
    from job_analyzer.search import next_batch
    ids = start_run(n_candidates=8, target=3)
    batch1, info = next_batch(set(), wave=10)
    assert [c.id for c in batch1] == ids[:3] and not info["done"]

    # wave 1: one succeeded, two failed -> two replacements needed
    write_status(ids[0], "ok"); write_status(ids[1], "error"); write_status(ids[2], "error")
    batch2, info = next_batch({ids[0]}, wave=10)
    assert [c.id for c in batch2] == ids[3:5]
    assert info["succeeded"] == 1 and info["failed"] == 2


def test_next_is_done_when_target_reached():
    from job_analyzer.search import next_batch
    ids = start_run(n_candidates=5, target=2)
    for i in ids[:2]:
        write_status(i, "ok")
    batch, info = next_batch(set(ids[:2]), wave=10)
    assert batch == [] and info["done"]


def test_next_stops_after_attempt_budget():
    from job_analyzer.search import next_batch
    ids = start_run(n_candidates=20, target=2)  # budget = 3 x 2 = 6 attempts
    for i in ids[:6]:
        write_status(i, "error")
    batch, info = next_batch(set(), wave=10)
    assert batch == [] and info["done"] and info["failed"] == 6


def test_new_run_clears_old_statuses():
    ids = start_run(n_candidates=2, target=1)
    write_status(ids[0], "error")
    start_run(n_candidates=2, target=1)
    from job_analyzer.search import load_statuses
    assert load_statuses() == {}


def test_shortlist_lists_check_yourself_and_status_errors():
    from job_analyzer.search import write_run_files
    li = located("https://be.linkedin.com/jobs/view/77", "Brussels, Belgium", site="be.linkedin.com",
                 title="Cloud Ops Engineer", company="BigCo")
    ok = located("https://jobs.lever.co/acme/1", None, company="Readable")
    r = merge_batches([batch("A", li, ok)], set())
    write_run_files(r, target=1)
    write_status(jobs.url_id("https://jobs.lever.co/acme/1"), "error")
    md = render_markdown([], [], top=10)
    assert "Check these yourself" in md and "https://be.linkedin.com/jobs/view/77" in md
    assert "Couldn't analyze" in md
