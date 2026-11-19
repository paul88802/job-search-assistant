"""Setup flow, profile storage and CV input, all offline."""

import base64

import pytest
from conftest import FakeClient

from job_analyzer.cv import cv_content, extract_cv_facts, find_cv
from job_analyzer.models import CVFacts, LanguageRequirement, Place
from job_analyzer.profile import Profile, load_profile, save_profile
from job_analyzer.setup import parse_languages, parse_places, parse_salary, run_setup

CV_FACTS = CVFacts(
    location=Place(city="Bucharest", country="Romania"),
    suggested_titles=["Cloud Engineer", "DevOps Engineer"],
    key_skills=["AWS", "Terraform", "Python"],
    languages=[LanguageRequirement(language="English", level="C1")],
    years_experience=5,
)


# --- parsers ---

def test_parse_places():
    assert parse_places("Bucharest, Romania; Germany") == [
        Place(city="Bucharest", country="Romania"),
        Place(city=None, country="Germany"),
    ]


def test_parse_languages_with_and_without_level():
    langs = parse_languages("english c1, Romanian native, German")
    assert [(l.language, l.level) for l in langs] == [
        ("English", "C1"), ("Romanian", "native"), ("German", "unknown")]


@pytest.mark.parametrize("text, expected", [
    ("4000 EUR net month", (4000, "EUR", "net", "month")),
    ("4.5k eur gross", (4500, "EUR", "gross", "month")),
    ("60,000 usd yearly", (60000, "USD", "net", "year")),
])
def test_parse_salary(text, expected):
    s = parse_salary(text)
    assert (s.minimum, s.currency, s.basis, s.period) == expected


def test_parse_salary_empty_means_no_minimum():
    assert parse_salary("") is None


def test_parse_salary_rejects_garbage():
    with pytest.raises(ValueError):
        parse_salary("a lot")


# --- interactive flow ---

def scripted(answers):
    it = iter(answers)
    return lambda prompt: next(it)


def test_setup_accepts_cv_suggestions_with_enter():
    # Enter for every question = accept defaults; one salary given.
    answers = ["", "", "", "", "", "", "4000 EUR net month", "", "", ""]
    p = run_setup(CV_FACTS, ask=scripted(answers), say=lambda _: None)
    assert p.target_titles == ["Cloud Engineer", "DevOps Engineer"]
    assert p.keywords == ["AWS", "Terraform", "Python"]
    assert p.locations == [Place(city="Bucharest", country="Romania")]
    assert p.work_arrangements == ["remote", "hybrid"]
    assert p.salary.minimum == 4000 and p.salary.priority == "soft"
    assert p.languages[0].language == "English"
    assert p.work_arrangement_priority == "hard"


def test_setup_reasks_after_bad_input():
    # titles, keywords, location (skip), arrangement (bad, then good), priority,
    # salary (skip), languages, priority
    answers = ["Data Engineer", "SQL", "", "office", "remote", "m", "", "German B1", "p"]
    messages = []
    p = run_setup(None, ask=scripted(answers), say=messages.append)
    assert p.work_arrangements == ["remote"]
    assert p.locations == [] and p.salary is None
    assert p.language_priority == "soft"
    assert any("Choose from" in m for m in messages)


# --- storage ---

def test_profile_round_trip(tmp_path):
    path = tmp_path / "profile.json"
    original = Profile(target_titles=["Cloud Engineer"], locations=[Place(city=None, country="Romania")])
    save_profile(original, path)
    assert load_profile(path) == original


def test_load_profile_missing_returns_none(tmp_path):
    assert load_profile(tmp_path / "nope.json") is None


# --- CV input ---

def test_find_cv_prefers_pdf(tmp_path):
    (tmp_path / "cv.txt").write_text("text cv")
    (tmp_path / "cv.pdf").write_bytes(b"%PDF-1.4")
    assert find_cv(tmp_path).name == "cv.pdf"


def test_pdf_cv_sent_as_document_block(tmp_path):
    pdf = tmp_path / "cv.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    content = cv_content(pdf)
    assert content[0]["type"] == "document"
    assert base64.b64decode(content[0]["source"]["data"]) == b"%PDF-1.4 fake"
    assert content[1]["type"] == "text"  # the instruction comes after the document


def test_text_cv_wrapped_in_tags(tmp_path):
    txt = tmp_path / "cv.txt"
    txt.write_text("Jane Doe, Cloud Engineer")
    client = FakeClient(CV_FACTS)
    assert extract_cv_facts(txt, client=client) == CV_FACTS
    assert client.calls[0]["messages"][0]["content"].startswith("<cv>")
