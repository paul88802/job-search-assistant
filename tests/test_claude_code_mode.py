"""Claude Code mode: shared specs, and validating JSON written outside the API."""

import json

import pytest
from conftest import make_job

from job_analyzer import cli, extract, jobs, paths
from job_analyzer.cv import cached_cv_details
from job_analyzer.models import CVDetails
from job_analyzer.specs import SPECS, spec_text


@pytest.fixture
def in_tmp(tmp_path, monkeypatch):
    """The data folder is tmp_path/data (see conftest). Run from a DIFFERENT folder
    to prove the tool finds its data regardless of the current directory."""
    elsewhere = tmp_path / "somewhere-else"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    return tmp_path


def test_data_dir_does_not_depend_on_current_folder(in_tmp):
    assert paths.data_dir() == in_tmp / "data"


def test_default_data_dir_is_project_folder(monkeypatch, tmp_path):
    monkeypatch.delenv(paths.ENV_VAR)
    monkeypatch.chdir(tmp_path)
    assert (paths.data_dir().parent / "pyproject.toml").exists()


def test_spec_uses_same_prompt_as_api_mode():
    text = spec_text("job")
    assert extract.SYSTEM_PROMPT in text  # one source of truth for both modes
    assert '"languages_required"' in text


@pytest.mark.parametrize("kind", sorted(SPECS))
def test_every_spec_renders(kind):
    assert "JSON Schema" in spec_text(kind)


def test_import_valid_job_is_saved(in_tmp, capsys):
    f = in_tmp / "job.json"
    f.write_text(make_job().model_dump_json())
    assert cli.do_import("job", f, url="https://jobs.example.com/123?utm_source=x") == 0
    saved = list((in_tmp / "data" / "jobs").glob("*.json"))
    assert len(saved) == 1
    rec = jobs.JobRecord.model_validate_json(saved[0].read_text())
    assert rec.source_url == "https://jobs.example.com/123?utm_source=x"
    assert rec.retrieved_at  # provenance: when it was found
    assert "JOB_ID=" + rec.id in capsys.readouterr().out


def test_import_invalid_json_lists_fields_to_fix(in_tmp, capsys):
    bad = json.loads(make_job().model_dump_json())
    bad["remote_policy"] = "sometimes"
    del bad["title"]
    f = in_tmp / "job.json"
    f.write_text(json.dumps(bad))
    assert cli.do_import("job", f) == 2
    err = capsys.readouterr().err
    assert "remote_policy" in err and "title" in err


def test_imported_cv_details_feed_the_copy_kit_without_api(in_tmp):
    cv_file = in_tmp / "data" / "cv.txt"
    cv_file.write_text("My CV")
    details = CVDetails(experience=[], education=[], certifications=[])
    f = in_tmp / "details.json"
    f.write_text(details.model_dump_json())

    assert cli.do_import("cv-details", f) == 0
    assert cached_cv_details(cv_file) == details
    assert cli.do_copy_kit(refresh=False, open_page=False, cache_only=True) == 0


def test_cache_only_reports_missing_extraction(in_tmp, capsys):
    (in_tmp / "data" / "cv.txt").write_text("My CV")
    assert cli.do_copy_kit(refresh=False, open_page=False, cache_only=True) == 3
    assert "NO_CACHE" in capsys.readouterr().err
