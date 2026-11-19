"""Live sources: parsing each official feed, relevance, discovery, and closed-link detection.

All network calls go through an injected `get`, so these tests run offline with small
samples shaped like the real responses (checked against the live APIs on 2026-11-19).
"""

import json
from datetime import date

from job_analyzer import live
from job_analyzer.models import Place
from job_analyzer.profile import Profile
from job_analyzer.search import SearchBatch, SearchResult, board_from_url, location_ok, merge_batches

GREENHOUSE = {"jobs": [{
    "absolute_url": "https://job-boards.eu.greenhouse.io/acme/jobs/1", "title": "Site Reliability Engineer",
    "company_name": "Acme", "location": {"name": "Europe - Remote"},
    "first_published": "2026-11-01T10:00:00-04:00", "content": "&lt;p&gt;Run &lt;b&gt;Prometheus&lt;/b&gt;&lt;/p&gt;"}]}
LEVER = [{"hostedUrl": "https://jobs.lever.co/Qover/abc", "text": "Site Reliability & Platform Engineer",
          "categories": {"location": "Brussels"}, "workplaceType": "hybrid", "createdAt": 1793534400000,
          "descriptionPlain": "We run GCP.", "lists": [{"text": "Requirements", "content": "<li>Terraform</li>"}],
          "additionalPlain": ""}]
ASHBY = {"jobs": [{"jobUrl": "https://jobs.ashbyhq.com/acme/x", "title": "DevOps Engineer", "location": "Germany",
                   "isRemote": True, "isListed": True, "publishedAt": "2026-11-10T06:40:24.278+00:00",
                   "descriptionPlain": "Kubernetes"}]}
REMOTEOK = [{"legal": "API Terms of Service: please link back"},
            {"position": "Senior DevOps Engineer", "company": "Lemon", "url": "https://remoteOK.com/remote-jobs/1",
             "date": "2026-11-12T00:00:00+00:00", "location": "", "description": "<p>AWS</p>"}]
WWR = b"""<?xml version="1.0"?><rss><channel><item>
<title>EPAM Systems: Senior DevOps Engineer</title><region>Anywhere in the World</region>
<pubDate>Mon, 16 Nov 2026 18:32:34 +0000</pubDate>
<link>https://weworkremotely.com/remote-jobs/epam-devops</link><description>&lt;p&gt;Terraform&lt;/p&gt;</description>
</item></channel></rss>"""


def fake_get(url: str) -> bytes:
    if "greenhouse" in url:
        return json.dumps(GREENHOUSE).encode()
    if "lever" in url:
        return json.dumps(LEVER).encode()
    if "ashbyhq" in url:
        return json.dumps(ASHBY).encode()
    if "remoteok" in url:
        return json.dumps(REMOTEOK).encode()
    if "weworkremotely" in url:
        return WWR
    raise OSError(f"unexpected URL {url}")


def profile(**kw) -> Profile:
    base = dict(target_titles=["Cloud Engineer (AWS)", "Site Reliability Engineer", "DevOps Engineer"],
                locations=[Place(city="Brussels", country="Belgium")],
                live_feeds=["remoteok", "wwr:remote-devops-sysadmin-jobs"])
    base.update(kw)
    return Profile(**base)


# --- parsing each source ---

def test_greenhouse_parsing_unescapes_html():
    j = live.fetch_greenhouse("acme", fake_get)[0]
    assert (j.title, j.location, j.posted_date) == ("Site Reliability Engineer", "Europe - Remote", "2026-11-01")
    assert "Run Prometheus" in j.text and "<" not in j.text


def test_lever_parsing_adds_workplace_and_lists():
    j = live.fetch_lever("Qover", fake_get)[0]
    assert j.location == "Brussels (hybrid)" and j.posted_date == "2026-11-01"
    assert "Terraform" in j.text and j.source == "lever:Qover"


def test_ashby_marks_remote_with_region():
    assert live.fetch_ashby("acme", fake_get)[0].location == "Remote - Germany"


def test_remoteok_skips_legal_notice():
    jobs = live.fetch_remoteok(fake_get)
    assert [j.title for j in jobs] == ["Senior DevOps Engineer"] and jobs[0].location == "Remote"


def test_wwr_rss_splits_company_and_title():
    j = live.fetch_wwr("remote-devops-sysadmin-jobs", fake_get)[0]
    assert (j.company, j.title, j.posted_date) == ("EPAM Systems", "Senior DevOps Engineer", "2026-11-16")


# --- relevance and discovery ---

def test_title_terms_and_relevance():
    terms = live.title_terms(profile())
    assert "sre" in terms and "cloud" in terms and "devops" in terms
    assert live.relevant("Senior SRE", terms)
    assert live.relevant("Cloud Platform Engineer", terms)
    assert not live.relevant("GTM Marketing Manager, Google Cloud", terms)  # no role word
    assert not live.relevant("Senior Node.js Back-End Engineer", terms)    # no target term


def test_board_tokens_keep_case_and_decode():
    assert board_from_url("https://jobs.lever.co/Qover/abc") == "lever:Qover"
    assert board_from_url("https://jobs.ashbyhq.com/coachhub%20careers/x") == "ashby:coachhub careers"
    assert board_from_url("https://www.linkedin.com/jobs/view/1") is None


def test_discover_boards_ignores_case_duplicates():
    b = SearchBatch(site_group="A", queries=[], errors=[], results=[
        SearchResult(url="https://jobs.lever.co/Qover/1", title="x", company=None, site="lever.co", snippet=None),
        SearchResult(url="https://jobs.lever.co/qover/2", title="y", company=None, site="lever.co", snippet=None)])
    assert live.discover_boards([b]) == ["lever:Qover"]


# --- a whole live collection ---

def test_collect_live_filters_and_reports_failed_sources():
    def flaky_get(url):
        if "ashbyhq" in url:
            raise OSError("timeout")
        return fake_get(url)

    r = live.collect_live(profile(), ["greenhouse:acme", "lever:Qover", "ashby:acme"], flaky_get,
                          today=date(2026, 11, 19))
    titles = sorted(x.title for x in r.batch.results)
    assert titles == ["Senior DevOps Engineer", "Senior DevOps Engineer", "Site Reliability & Platform Engineer",
                      "Site Reliability Engineer"]
    assert [e.site for e in r.batch.errors] == ["ashby:acme"]   # failure reported, run continues
    assert r.boards_ok == {"greenhouse:acme", "lever:Qover"}
    assert len(r.texts) == 4 and all(r.texts.values())          # full text saved for every kept job


# --- location filter: remote tied to another country ---

def test_remote_with_another_country_is_dropped():
    places = ["brussels", "belgium"]
    assert location_ok("Remote - Europe", places)
    assert location_ok("Remote - within CET timezone (+/- 3 hours)", places)
    assert location_ok("Belgium (remote)", places)
    assert not location_ok("Remote - Spain", places)
    assert not location_ok("Remote - Ireland", places)
    assert not location_ok("NAMER and LatAm", places)


# --- stale search hits are recognized as closed ---

def test_search_hit_missing_from_live_board_is_closed():
    hit = SearchResult(url="https://jobs.lever.co/qover/old-job", title="Old", company="Qover",
                       site="jobs.lever.co", snippet=None)
    open_hit = SearchResult(url="https://jobs.lever.co/Qover/abc", title="SRE", company="Qover",
                            site="jobs.lever.co", snippet=None)
    r = merge_batches([SearchBatch(site_group="A", queries=[], errors=[], results=[hit, open_hit])], set(),
                      live_boards={"lever:Qover"}, live_urls={"https://jobs.lever.co/qover/abc"})
    assert [c.url for c in r.queue] == ["https://jobs.lever.co/Qover/abc"]
    assert r.coverage["stats"]["closed"] == 1


# --- facts from the official source fill gaps in the extracted posting ---

def test_import_fills_date_and_remote_from_live_candidate(tmp_path):
    from conftest import make_job
    from job_analyzer import cli, jobs
    from job_analyzer.search import write_run_files
    url = "https://jobs.lever.co/Acme/1"
    hit = SearchResult(url=url, title="SRE", company="Acme", site="jobs.lever.co", snippet=None,
                       posted_date="2026-11-10", location="Remote - Europe")
    write_run_files(merge_batches([SearchBatch(site_group="Live sources", queries=[], errors=[], results=[hit])],
                                  set()), target=1)
    f = tmp_path / "job.json"
    f.write_text(make_job(posted_date=None, remote_policy="unknown").model_dump_json())
    assert cli.do_import("job", f, url=url, site="jobs.lever.co") == 0
    rec = jobs.load_record(jobs.url_id(url))
    assert rec.job.posted_date == "2026-11-10" and rec.job.remote_policy == "remote"


def test_import_never_overrides_what_the_posting_says(tmp_path):
    from conftest import make_job
    from job_analyzer import cli, jobs
    from job_analyzer.search import write_run_files
    url = "https://jobs.lever.co/Acme/2"
    hit = SearchResult(url=url, title="SRE", company="Acme", site="jobs.lever.co", snippet=None,
                       posted_date="2026-11-10", location="Remote")
    write_run_files(merge_batches([SearchBatch(site_group="A", queries=[], errors=[], results=[hit])], set()),
                    target=1)
    f = tmp_path / "job.json"
    f.write_text(make_job(posted_date="2026-11-01", remote_policy="hybrid").model_dump_json())
    cli.do_import("job", f, url=url)
    rec = jobs.load_record(jobs.url_id(url))
    assert rec.job.posted_date == "2026-11-01" and rec.job.remote_policy == "hybrid"
