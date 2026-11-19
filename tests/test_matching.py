"""The matching rules are plain code, so they can be tested exhaustively and for free."""

from conftest import lang, make_job, needs

from job_analyzer.matching import (
    check_languages,
    check_location,
    check_salary,
    check_work_arrangement,
    evaluate,
)
from job_analyzer.models import LanguageRequirement, Place, SalaryInfo
from job_analyzer.profile import Profile, SalaryPreference


def profile(**overrides) -> Profile:
    fields = dict(
        locations=[Place(city="Bucharest", country="Romania")],
        work_arrangements=["remote", "hybrid"],
        salary=SalaryPreference(minimum=4000, currency="EUR", basis="gross", period="month"),
        languages=[LanguageRequirement(language="English", level="C1"),
                   LanguageRequirement(language="Romanian", level="native")],
    )
    fields.update(overrides)
    return Profile(**fields)


def salary(minimum, maximum=None, currency="EUR", basis="gross", period="month"):
    return SalaryInfo(minimum=minimum, maximum=maximum, currency=currency, basis=basis,
                      period=period, raw_text=f"{minimum}-{maximum} {currency}")


# --- work arrangement ---

def test_arrangement_match():
    assert check_work_arrangement(make_job(remote_policy="hybrid"), profile()).outcome == "match"


def test_arrangement_mismatch():
    assert check_work_arrangement(make_job(remote_policy="onsite"), profile()).outcome == "mismatch"


def test_arrangement_unknown():
    assert check_work_arrangement(make_job(remote_policy="unknown"), profile()).outcome == "unknown"


# --- location ---

def test_location_same_city_ignores_case():
    job = make_job(location=Place(city="BUCHAREST", country="romania"))
    assert check_location(job, profile()).outcome == "match"


def test_location_country_wide_preference():
    job = make_job(location=Place(city="Berlin", country="Germany"))
    p = profile(locations=[Place(city=None, country="Germany")])
    assert check_location(job, p).outcome == "match"


def test_location_other_city_is_mismatch():
    job = make_job(location=Place(city="Cluj-Napoca", country="Romania"))
    assert check_location(job, profile()).outcome == "mismatch"


def test_location_remote_always_matches():
    job = make_job(remote_policy="remote", location=Place(city="Lisbon", country="Portugal"))
    assert check_location(job, profile()).outcome == "match"


def test_location_missing_is_unknown():
    assert check_location(make_job(location=None), profile()).outcome == "unknown"


def test_location_city_not_stated_is_unknown():
    job = make_job(location=Place(city=None, country="Romania"))
    assert check_location(job, profile()).outcome == "unknown"


# --- salary ---

def test_salary_meets_minimum():
    assert check_salary(make_job(salary=salary(4500, 6000)), profile()).outcome == "match"


def test_salary_not_stated_is_unknown_not_rejected():
    c = check_salary(make_job(salary=None), profile())
    assert c.outcome == "unknown" and c.credit == 0.5


def test_salary_slightly_below_gets_partial_credit():
    c = check_salary(make_job(salary=salary(3800)), profile())  # 5% below 4000
    assert c.outcome == "mismatch"
    assert 0.75 < c.credit < 0.85


def test_salary_far_below_gets_no_credit():
    c = check_salary(make_job(salary=salary(2000)), profile())
    assert c.credit == 0.0


def test_salary_yearly_converted_to_monthly():
    assert check_salary(make_job(salary=salary(60000, period="year")), profile()).outcome == "match"


def test_salary_other_currency_is_unknown():
    assert check_salary(make_job(salary=salary(20000, currency="RON")), profile()).outcome == "unknown"


def test_salary_gross_vs_net_is_unknown():
    assert check_salary(make_job(salary=salary(9000, basis="net")), profile()).outcome == "unknown"


# --- languages ---

def test_languages_level_ok():
    assert check_languages(make_job(), profile()).outcome == "match"  # English B2 needed, have C1


def test_languages_level_too_low():
    job = make_job(languages_required=[needs(lang("English", "C2"))])
    c = check_languages(job, profile())
    assert c.outcome == "mismatch" and "English C1, needs C2" in c.detail


def test_languages_missing_language():
    job = make_job(languages_required=[needs(lang("German", "B1"))])
    c = check_languages(job, profile())
    assert c.outcome == "mismatch" and "German" in c.detail


def test_languages_french_or_dutch_without_either_is_mismatch():
    job = make_job(languages_required=[needs(lang("English")), needs(lang("French"), lang("Dutch"))])
    c = check_languages(job, profile())
    assert c.outcome == "mismatch"
    assert "French or Dutch required" in c.detail


def test_languages_french_or_dutch_with_one_of_them_is_match():
    job = make_job(languages_required=[needs(lang("English")), needs(lang("French"), lang("Dutch"))])
    p = profile(languages=[lang("English", "C1"), lang("Dutch", "B2")])
    assert check_languages(job, p).outcome == "match"


def test_no_languages_in_profile_means_not_checked():
    job = make_job(languages_required=[needs(lang("German", "C1"))])
    assert check_languages(job, profile(languages=[])).outcome == "match"


def test_languages_nice_to_have_never_excludes():
    job = make_job(languages_required=[needs(lang("English", "B2"))],
                   languages_nice_to_have=[lang("French")])
    assert check_languages(job, profile()).outcome == "match"


def test_languages_none_required():
    assert check_languages(make_job(languages_required=[]), profile()).outcome == "match"


# --- overall: hard vs soft ---

def test_everything_matches_scores_100():
    report = evaluate(make_job(), profile())
    assert not report.excluded and report.score == 100


def test_hard_mismatch_excludes():
    report = evaluate(make_job(remote_policy="onsite"), profile())  # arrangement is "hard" by default
    assert report.excluded
    assert "Onsite" in report.exclusion_reasons[0]


def test_soft_salary_shortfall_ranks_lower_but_stays():
    good = evaluate(make_job(salary=salary(4500)), profile())
    lower = evaluate(make_job(salary=salary(3800)), profile())
    assert not lower.excluded
    assert lower.score < good.score


def test_hard_salary_shortfall_excludes():
    p = profile(salary=SalaryPreference(minimum=4000, basis="gross", priority="hard"))
    assert evaluate(make_job(salary=salary(3800)), p).excluded


def test_unknowns_never_exclude():
    job = make_job(remote_policy="unknown", location=None, salary=None, languages_required=[])
    p = profile(work_arrangement_priority="hard", location_priority="hard")
    assert not evaluate(job, p).excluded
