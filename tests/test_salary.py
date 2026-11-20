"""Salary estimates: validation, import only for postings without a stated salary, shortlist line."""

import pytest
from pydantic import ValidationError

from conftest import make_job

from job_analyzer import cli, jobs
from job_analyzer.models import SalaryEstimate
from job_analyzer.ranking import salary_line

EST = dict(contract_type="employee", currency="EUR", gross_monthly_low=4500, gross_monthly_high=5500,
           net_monthly_low=2800, net_monthly_high=3200, basis="Belgian employee, single, no extras.",
           confidence="low", reasoning="Senior cloud role at a Brussels scale-up.")


def test_estimate_must_be_consistent():
    SalaryEstimate(**EST)
    for bad in ({"gross_monthly_low": 6000}, {"net_monthly_high": 6000}, {"net_monthly_low": 0}):
        with pytest.raises(ValidationError):
            SalaryEstimate(**{**EST, **bad})


def test_import_estimate_for_job_without_salary(tmp_path):
    rec = jobs.add_job(make_job(salary=None), url="https://jobs.example.com/1")
    f = tmp_path / "s.json"
    f.write_text(SalaryEstimate(**EST).model_dump_json(), encoding="utf-8")
    assert cli.do_import("salary-estimate", f, job_id=rec.id) == 0
    saved = jobs.load_record(rec.id)
    assert saved.salary_estimate.gross_monthly_high == 5500
    line = salary_line(saved)
    assert "estimate, low confidence, not an offer" in line and "4 500–5 500 EUR" in line

    jobs.add_job(make_job(salary=None), url="https://jobs.example.com/1")  # re-import keeps it
    assert jobs.load_record(rec.id).salary_estimate is not None


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
