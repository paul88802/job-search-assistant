"""The shortlist page: built by code, escaped, only safe links clickable, applied jobs marked."""

from conftest import make_job

from job_analyzer import cli, jobs, paths, tracker
from job_analyzer.models import FitAssessment, PayRange, SalaryEstimate
from job_analyzer.profile import Profile
from job_analyzer.ranking import rank
from job_analyzer.shortlist_page import build_page, safe_url

URL = "https://jobs.example.com/sre-1"


def ranked(**job_overrides):
    rec = jobs.add_job(make_job(**job_overrides), url=URL)
    jobs.attach_fit(rec.id, FitAssessment(fit_score=72, matching_skills=["Terraform (Acme Corp)"],
                                          gaps=["Kubernetes"], how_to_address="Mention EKS work.",
                                          summary="Good fit with one gap."))
    return rank(jobs.all_records(), Profile(), cv_text="")


def test_card_shows_fit_pay_and_actions():
    included, excluded = ranked()
    html = build_page(included, excluded)
    assert "Backend Python Developer" in html and "Northwind Analytics" in html
    assert 'value="72"' in html and "Good fit with one gap." in html
    assert "Terraform (Acme Corp)" in html and "Mention EKS work." in html
    assert "4,500 - 6,000 EUR gross/month" in html          # stated salary
    assert f'href="{URL}"' in html and 'rel="noopener noreferrer"' in html
    assert 'data-track="' in html                            # not applied yet: copy-command button


def test_estimate_and_applied_badge():
    rng = dict(gross_monthly_low=5000, gross_monthly_high=6000, net_monthly_low=2900, net_monthly_high=3300)
    included, excluded = ranked(salary=None)
    rec = included[0].record
    jobs.attach_salary_estimate(rec.id, SalaryEstimate(
        contract_type="employee", priced_as="employee", pay_market="Belgian market", currency="EUR",
        market=PayRange(**rng), for_you=PayRange(**rng), months_per_year=13.92, basis="Single.",
        sources=[], confidence="low", reasoning="Mid-level role."))
    tracker.add_application(URL, applied_on="2026-11-19")
    included, excluded = rank(jobs.all_records(), Profile(), cv_text="")
    html = build_page(included, excluded)
    assert "Estimate · low confidence" in html and "5 000–6 000 EUR/month gross" in html
    assert "net ≈ 40.4k–45.9k EUR/year" in html
    assert "✓ Applied 2026-11-19 · applied" in html and 'data-applied="1"' in html
    assert 'data-track="' not in html                        # already applied: no copy-command button
    assert "My applications (1)" in html


def test_posting_text_is_escaped_and_bad_links_not_clickable():
    included, excluded = ranked(title='<img src=x onerror="alert(1)">',
                                red_flags=['<script>alert("x")</script>'])
    included[0].record.source_url = "javascript:alert(1)"
    html = build_page(included, excluded)
    assert "<img src=x" not in html and "<script>alert" not in html
    assert "&lt;img src=x" in html and "&lt;script&gt;" in html
    assert "javascript:alert" not in html
    assert safe_url("javascript:alert(1)") is None and safe_url(" HTTPS://a.example/x") == " HTTPS://a.example/x"


def test_shortlist_command_writes_page_without_opening(monkeypatch):
    opened = []
    monkeypatch.setattr("webbrowser.open", lambda url: opened.append(url))
    paths.profile_path().parent.mkdir(parents=True, exist_ok=True)
    paths.profile_path().write_text(Profile().model_dump_json(), encoding="utf-8")
    ranked()
    assert cli.do_shortlist(10, True, open_page=False) == 0
    assert paths.shortlist_page().exists() and opened == []
    assert cli.do_shortlist(10, True, open_page=True) == 0
    assert opened and opened[0].startswith("file:")


def test_old_posting_gets_a_warning():
    from datetime import date
    included, excluded = ranked(posted_date="2026-07-09")
    html = build_page(included, excluded, today=date(2026, 11, 20))
    assert "posted 2026-07-09 (134 days ago)" in html
    assert "Posted 134 days ago: check it&#x27;s still open before applying" in html
