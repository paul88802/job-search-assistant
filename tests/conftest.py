"""Shared test helpers: a fake API client and a sample job posting."""

from types import SimpleNamespace

import pytest

from job_analyzer import paths
from job_analyzer.models import (
    JobRequirements,
    LanguageGroup,
    LanguageRequirement,
    Place,
    SalaryInfo,
)


@pytest.fixture(autouse=True)
def isolated_data(tmp_path, monkeypatch):
    """Every test gets its own empty data folder, so no test can touch the real CV or profile."""
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv(paths.ENV_VAR, str(data))
    return data


def lang(language: str, level: str = "unknown") -> LanguageRequirement:
    return LanguageRequirement(language=language, level=level)


def needs(*alternatives: LanguageRequirement) -> LanguageGroup:
    """One required-language group: needs('French', 'Dutch') means French OR Dutch."""
    return LanguageGroup(any_of=list(alternatives))


def make_job(**overrides) -> JobRequirements:
    fields = dict(
        title="Backend Python Developer",
        company="Northwind Analytics",
        seniority="mid",
        location=Place(city="Bucharest", country="Romania"),
        remote_policy="hybrid",
        years_experience_min=3,
        must_have_skills=["Python", "SQL", "Docker", "Git"],
        nice_to_have_skills=["LLM APIs", "AWS", "Kubernetes"],
        languages_required=[needs(lang("English", "B2"))],
        languages_nice_to_have=[],
        responsibilities=["Build REST APIs"],
        salary=SalaryInfo(minimum=4500, maximum=6000, currency="EUR", basis="gross",
                          period="month", raw_text="4,500 - 6,000 EUR gross/month"),
        red_flags=["Weekend availability expected"],
        summary="A mid-level backend role. Hybrid in Bucharest.",
    )
    fields.update(overrides)
    return JobRequirements(**fields)


class FakeClient:
    """Mimics client.beta.messages.parse(...) and records what was sent."""

    def __init__(self, parsed_output=None, stop_reason="end_turn"):
        self.calls = []
        response = SimpleNamespace(stop_reason=stop_reason, parsed_output=parsed_output)

        def parse(**kwargs):
            self.calls.append(kwargs)
            return response

        self.beta = SimpleNamespace(messages=SimpleNamespace(parse=parse))


@pytest.fixture
def sample_job() -> JobRequirements:
    return make_job()
