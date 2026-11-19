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
    picked, coverage = merge_batches(batches, known, limit=10)
    assert [c.url for c in picked] == ["https://a.be/job/2", "https://linkedin.com/jobs/view/10"]
    assert coverage["stats"] == {"found": 5, "duplicates": 2, "already_analyzed": 1,
                                 "same_title_other_date": 0, "new_unique": 2, "picked": 2}


# --- duplicates by company + title + date posted ---

def batch(group, *results):
    return SearchBatch(site_group=group, queries=["q"], errors=[], results=list(results))


def dated(url, date, title="DevOps Engineer", company="Acme", site="jobat.be"):
    return SearchResult(url=url, title=title, company=company, site=site, snippet=None, posted_date=date)


def test_same_company_title_and_date_is_one_job():
    picked, cov = merge_batches([batch("A", dated("https://a.be/1", "2026-11-10")),
                                 batch("B", dated("https://b.be/9", "2026-11-10"))], set(), 10)
    assert len(picked) == 1 and cov["stats"]["duplicates"] == 1


def test_same_company_title_different_dates_are_two_jobs():
    picked, cov = merge_batches([batch("A", dated("https://a.be/1", "2026-10-01"),
                                       dated("https://a.be/2", "2026-11-10"))], set(), 10)
    assert len(picked) == 2 and cov["stats"]["same_title_other_date"] == 1


def test_missing_date_counts_as_same_job():
    picked, _ = merge_batches([batch("A", dated("https://a.be/1", None)),
                               batch("B", dated("https://b.be/1", "2026-11-10"))], set(), 10)
    assert len(picked) == 1 and picked[0].posted_date == "2026-11-10"


def test_readable_copy_wins_and_linkedin_link_is_kept():
    li = dated("https://www.linkedin.com/jobs/view/42", "2026-11-10", site="linkedin.com")
    company_page = dated("https://jobs.lever.co/acme/7", "2026-11-10", site="lever.co")
    picked, _ = merge_batches([batch("LinkedIn", li), batch("Company career pages", company_page)], set(), 10)
    assert len(picked) == 1
    assert picked[0].site == "lever.co"
    assert picked[0].also_seen_at == ["https://www.linkedin.com/jobs/view/42"]


def test_gender_tags_and_company_suffixes_are_ignored():
    a = dated("https://a.be/1", None, title="DevOps Engineer (m/f/x)", company="Acme NV")
    b = dated("https://b.be/1", None, title="DevOps engineer", company="ACME")
    picked, _ = merge_batches([batch("A", a, b)], set(), 10)
    assert len(picked) == 1


def test_job_analyzed_in_earlier_run_is_skipped_by_key():
    known_keys = {("acme", "devops engineer"): ["2026-11-10"]}
    picked, cov = merge_batches([batch("A", dated("https://new-link.be/5", "2026-11-10"))],
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
    picked, _ = merge_batches([big, small], set(), limit=3)
    assert [c.site_group for c in picked] == ["Big", "Small", "Big"]


def test_failed_search_is_reported_not_hidden():
    failed = SearchBatch(site_group="LinkedIn", queries=["sre brussels"], results=[], errors=[
        SearchError(site="linkedin.com", query="sre brussels", error_type="blocked",
                    detail="Search tool returned an error", retryable=False)])
    empty_ok = SearchBatch(site_group="Remote", queries=["sre remote"], results=[], errors=[])
    _, coverage = merge_batches([failed, empty_ok], set(), limit=10)
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
