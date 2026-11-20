"""Salary estimates: validation, import only for postings without a stated salary, shortlist line."""

import pytest
from pydantic import ValidationError

from conftest import make_job

from job_analyzer import cli, jobs
from job_analyzer.models import PayRange, SalaryEstimate
from job_analyzer.ranking import salary_line

MARKET = dict(gross_monthly_low=5000, gross_monthly_high=6500, net_monthly_low=3000, net_monthly_high=3600)
FOR_YOU = dict(gross_monthly_low=4500, gross_monthly_high=5500, net_monthly_low=2800, net_monthly_high=3200)
EST = dict(contract_type="employee", priced_as="employee", pay_market="Belgian market", currency="EUR",
           market=MARKET, for_you=FOR_YOU, months_per_year=13.92,
           basis="Belgian employee, single, no extras.",
           sources=[dict(name="Example salary survey", url="https://salaries.example.com/sre",
                         figure="€65k/year gross")],
           confidence="medium", reasoning="Mid-level SRE at a Brussels scale-up.")


def test_pay_range_must_be_consistent():
    PayRange(**MARKET)
    for bad in ({"gross_monthly_low": 7000}, {"net_monthly_high": 7000}, {"net_monthly_low": 0}):
        with pytest.raises(ValidationError):
            PayRange(**{**MARKET, **bad})


def test_estimate_without_sources_must_be_low_confidence():
    with pytest.raises(ValidationError, match="sources"):
        SalaryEstimate(**{**EST, "sources": []})
    SalaryEstimate(**{**EST, "sources": [], "confidence": "low"})


def test_import_estimate_for_job_without_salary(tmp_path):
    rec = jobs.add_job(make_job(salary=None), url="https://jobs.example.com/1")
    f = tmp_path / "s.json"
    f.write_text(SalaryEstimate(**EST).model_dump_json(), encoding="utf-8")
    assert cli.do_import("salary-estimate", f, job_id=rec.id) == 0
    saved = jobs.load_record(rec.id)
    assert saved.salary_estimate.for_you.gross_monthly_high == 5500
    text = salary_line(saved)
    assert "medium confidence, not an offer" in text
    assert "Market for this role: gross 5 000–6 500 EUR/month (≈ 69 600–90 500 EUR/year)" in text
    assert "For you: gross 4 500–5 500 EUR/month" in text
    assert "[Example salary survey](https://salaries.example.com/sre)" in text

    jobs.add_job(make_job(salary=None), url="https://jobs.example.com/1")  # re-import keeps it
    assert jobs.load_record(rec.id).salary_estimate is not None


def test_contractor_pay_shown_as_invoiced(tmp_path):
    rec = jobs.add_job(make_job(salary=None), url="https://jobs.example.com/3")
    est = SalaryEstimate(**{**EST, "contract_type": "unknown", "priced_as": "contractor", "months_per_year": 12})
    text = salary_line(jobs.attach_salary_estimate(rec.id, est))
    assert "contractor, contract not stated" in text and "invoiced 5 000–6 500 EUR/month" in text


def test_no_estimate_when_posting_states_salary(tmp_path):
    rec = jobs.add_job(make_job(), url="https://jobs.example.com/2")
    with pytest.raises(ValueError, match="states a salary"):
        jobs.attach_salary_estimate(rec.id, SalaryEstimate(**EST))
    assert salary_line(rec).startswith("Salary (stated): 4,500 - 6,000 EUR")


def test_import_estimate_needs_job_id(tmp_path):
    f = tmp_path / "s.json"
    f.write_text(SalaryEstimate(**EST).model_dump_json(), encoding="utf-8")
    with pytest.raises(ValueError, match="--job"):
        cli.do_import("salary-estimate", f)


def test_outdated_estimate_is_dropped_not_fatal():
    rec = jobs.add_job(make_job(salary=None), url="https://jobs.example.com/4")
    path = jobs.record_path(rec.id)
    path.write_text(path.read_text(encoding="utf-8").replace(
        '"salary_estimate": null', '"salary_estimate": {"contract_type": "employee"}'), encoding="utf-8")
    loaded = jobs.load_record(rec.id)
    assert loaded is not None and loaded.salary_estimate is None
