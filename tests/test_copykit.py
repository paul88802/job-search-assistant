"""Copy kit: verbatim CV sections, caching, and the generated page."""

from html import unescape

from conftest import FakeClient

from job_analyzer import cv as cv_module
from job_analyzer.copykit import build_html, experience_text
from job_analyzer.cv import load_cv_details
from job_analyzer.models import Certification, CVDetails, Education, WorkExperience

DETAILS = CVDetails(
    experience=[WorkExperience(
        job_title="Cloud Engineer", company="Acme & Sons", location="Bucharest",
        start_date="Mar 2021", end_date="Present",
        description="- Migrated 40 services to AWS\n- Cut costs by 30%",
    )],
    education=[Education(
        institution="Politehnica University", degree="BSc", field_of_study="Computer Science",
        location=None, start_date="2013", end_date="2017", details=None,
    )],
    certifications=[Certification(
        name="AWS Solutions Architect – Associate", issuer="Amazon Web Services",
        issue_date="2023", expiry_date="2026", credential_id="ABC123", url=None,
    )],
)


def test_experience_text_keeps_bullets():
    text = experience_text(DETAILS.experience[0])
    assert text.splitlines() == [
        "Cloud Engineer — Acme & Sons (Bucharest)",
        "Mar 2021 – Present",
        "- Migrated 40 services to AWS",
        "- Cut costs by 30%",
    ]


def test_page_has_copy_buttons_with_exact_text():
    html = build_html(DETAILS, "cv.pdf")
    assert 'data-copy="Acme &amp; Sons"' in html  # escaped in HTML...
    assert unescape('Acme &amp; Sons') == "Acme & Sons"  # ...but copies the original text
    assert html.count('class="copy"') >= 15
    for section in ("Work experience", "Education", "Certifications"):
        assert section in html


def test_page_escapes_injected_markup():
    evil = DETAILS.model_copy(deep=True)
    evil.experience[0].company = '<script>alert("x")</script>'
    html = build_html(evil, "cv.pdf")
    assert '<script>alert' not in html
    assert '&lt;script&gt;' in html


def test_empty_section_message():
    html = build_html(CVDetails(experience=[], education=[], certifications=[]), "cv.txt")
    assert html.count("None found in your CV.") == 3


def test_cv_read_once_then_cached(tmp_path):
    cv = tmp_path / "cv.txt"
    cv.write_text("My CV")
    cache = tmp_path / "cv_details.json"
    client = FakeClient(DETAILS)

    first, cached1 = load_cv_details(cv, cache=cache, client=client)
    second, cached2 = load_cv_details(cv, cache=cache, client=client)
    assert (cached1, cached2) == (False, True)
    assert first == second == DETAILS
    assert len(client.calls) == 1  # second call cost nothing


def test_changed_cv_is_read_again(tmp_path):
    cv = tmp_path / "cv.txt"
    cv.write_text("Version 1")
    cache = tmp_path / "cv_details.json"
    client = FakeClient(DETAILS)
    load_cv_details(cv, cache=cache, client=client)
    cv.write_text("Version 2")
    _, cached = load_cv_details(cv, cache=cache, client=client)
    assert cached is False and len(client.calls) == 2


def test_changed_rules_invalidate_saved_result(tmp_path, monkeypatch):
    cv = tmp_path / "cv.txt"
    cv.write_text("My CV")
    cache = tmp_path / "cv_details.json"
    client = FakeClient(DETAILS)
    load_cv_details(cv, cache=cache, client=client)
    # Same CV file, but the extraction prompt changed -> the old result must not be reused.
    monkeypatch.setattr(cv_module, "DETAILS_SYSTEM_PROMPT", cv_module.DETAILS_SYSTEM_PROMPT + "\n- new rule")
    _, cached = load_cv_details(cv, cache=cache, client=client)
    assert cached is False and len(client.calls) == 2


def test_refresh_forces_new_read(tmp_path):
    cv = tmp_path / "cv.txt"
    cv.write_text("My CV")
    cache = tmp_path / "cv_details.json"
    client = FakeClient(DETAILS)
    load_cv_details(cv, cache=cache, client=client)
    load_cv_details(cv, cache=cache, client=client, refresh=True)
    assert len(client.calls) == 2


def test_details_prompt_demands_verbatim(tmp_path):
    cv = tmp_path / "cv.txt"
    cv.write_text("My CV")
    client = FakeClient(DETAILS)
    load_cv_details(cv, cache=tmp_path / "c.json", client=client)
    assert "EXACTLY as written" in client.calls[0]["system"]
    assert client.calls[0]["output_format"] is CVDetails


def test_contact_section_first_with_phone():
    from job_analyzer.models import ContactInfo
    d = DETAILS.model_copy(deep=True)
    d.contact = ContactInfo(full_name="Jane Doe", email="jane@example.com", phone="+32 400 00 00 00",
                            address=None, linkedin=None, website=None)
    html = build_html(d, "cv.pdf")
    assert html.index("Contact details") < html.index("Work experience")
    assert 'data-copy="+32 400 00 00 00"' in html
    assert "Address" not in html  # empty fields get no row


def test_old_cache_without_contact_still_loads():
    assert CVDetails.model_validate({"experience": [], "education": [], "certifications": []}).contact is None
