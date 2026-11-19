"""Offline tests: a fake client stands in for the real API.

This is a common pattern: test YOUR logic (stop_reason handling, request shape)
without paying for API calls. Answer quality is measured separately with evals.
"""

import pytest
from conftest import FakeClient

from job_analyzer.extract import ExtractionError, extract_requirements
from job_analyzer.models import JobRequirements


def test_returns_parsed_output(sample_job):
    assert extract_requirements("Some posting", client=FakeClient(sample_job)) == sample_job


def test_posting_is_wrapped_in_xml_tags(sample_job):
    client = FakeClient(sample_job)
    extract_requirements("Hello world", client=client)
    call = client.calls[0]
    content = call["messages"][0]["content"]
    assert content.startswith("Today's date: ")  # for relative dates like "3 days ago"
    assert "<job_posting>\nHello world\n</job_posting>" in content and content.endswith("</job_posting>")
    assert call["output_format"] is JobRequirements
    assert call["fallbacks"] == "default"


def test_refusal_raises():
    with pytest.raises(ExtractionError, match="declined"):
        extract_requirements("x", client=FakeClient(stop_reason="refusal"))


def test_truncation_raises():
    with pytest.raises(ExtractionError, match="cut off"):
        extract_requirements("x", client=FakeClient(stop_reason="max_tokens"))


def test_empty_posting_rejected_before_any_api_call():
    client = FakeClient()
    with pytest.raises(ValueError):
        extract_requirements("   ", client=client)
    assert client.calls == []


def test_schema_has_required_fields():
    schema = JobRequirements.model_json_schema()
    assert {"title", "must_have_skills", "languages_required", "salary"} <= set(schema["required"])
