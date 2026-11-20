"""Application tracker: rules in plain code, the same through the CLI and the MCP server."""

from datetime import date

import pytest
from conftest import make_job

from job_analyzer import cli, jobs, tracker

TODAY = date(2026, 11, 20)
URL = "https://jobs.example.com/sre-1"


def saved_job(url=URL):
    return jobs.add_job(make_job(title="Site Reliability Engineer", company="Acme Corp"), url=url)


def test_add_by_link_or_id_uses_saved_job():
    rec = saved_job()
    a = tracker.add_application(URL + "?utm_source=x", applied_on="2026-11-20", today=TODAY)
    assert a.job_id == rec.id and a.title == "Site Reliability Engineer" and a.company == "Acme Corp"
    with pytest.raises(ValueError, match="Already tracked"):
        tracker.add_application(rec.id, today=TODAY)


def test_job_not_saved_needs_title_and_company():
    with pytest.raises(ValueError, match="title and company"):
        tracker.add_application("https://jobs.example.com/unknown", today=TODAY)
    a = tracker.add_application("https://jobs.example.com/unknown", title="Cloud Engineer", company="Acme Corp",
                                today=TODAY)
    assert a.url == "https://jobs.example.com/unknown" and a.applied_on is None


def test_dates_are_validated_never_guessed():
    saved_job()
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        tracker.add_application(URL, applied_on="last week", today=TODAY)
    with pytest.raises(ValueError, match="future"):
        tracker.add_application(URL, applied_on="2026-12-01", today=TODAY)
    assert tracker.add_application(URL, today=TODAY).applied_on is None  # unknown stays unknown


def test_status_history_and_next_step():
    saved_job()
    tracker.add_application(URL, applied_on="2026-11-01", today=TODAY)
    assert "follow-up" in tracker.summary(today=TODAY)[0]["next_step"]  # 19 days, no answer
    a = tracker.update_application(URL, "interviewing", note="call with the team lead", today=TODAY)
    assert [h.status for h in a.history] == ["applied", "interviewing"] and a.history[-1].on == "2026-11-20"
    with pytest.raises(ValueError, match="Unknown status"):
        tracker.update_application(URL, "hired", today=TODAY)


def test_next_step_rules():
    def app(status, applied_on):
        return tracker.Application(job_id="x", title="t", company=None, url=None, applied_on=applied_on,
                                   status=status, history=[])
    assert "Waiting (5 days)" in tracker.next_step(app("applied", "2026-11-15"), TODAY)
    assert "no_response" in tracker.next_step(app("applied", "2026-09-01"), TODAY)
    assert "unknown date" in tracker.next_step(app("applied", None), TODAY)
    assert tracker.next_step(app("rejected", "2026-11-01"), TODAY) == "Closed."


def test_closed_applications_hidden_unless_asked():
    saved_job()
    tracker.add_application(URL, applied_on="2026-11-10", today=TODAY)
    tracker.update_application(URL, "rejected", today=TODAY)
    assert tracker.summary(include_closed=False, today=TODAY) == []
    assert len(tracker.summary(today=TODAY)) == 1


def test_cli_track_add_and_list(capsys):
    saved_job()
    assert cli.do_track("add", URL, None, "2026-11-19", "via referral", None, None, False) == 0
    assert cli.do_track("list", None, None, None, None, None, None, False) == 0
    out = capsys.readouterr().out
    assert "[applied] Site Reliability Engineer @ Acme Corp · applied 2026-11-19" in out


def test_shortlist_marks_applied_jobs():
    from job_analyzer.models import FitAssessment
    from job_analyzer.profile import Profile
    from job_analyzer.ranking import rank, render_markdown
    rec = saved_job()
    jobs.attach_fit(rec.id, FitAssessment(fit_score=70, matching_skills=[], gaps=[], how_to_address="",
                                          summary="Good fit."))
    tracker.add_application(URL, applied_on="2026-11-19")
    included, excluded = rank(jobs.all_records(), Profile(), cv_text="")
    assert "**✓ Applied 2026-11-19 · status: applied**" in render_markdown(included, excluded, top=10)


# --- MCP server: same rules, errors returned to Claude with their reason ---

def test_mcp_tools_call_the_tracker():
    pytest.importorskip("mcp")
    import anyio
    from mcp.server.mcpserver.exceptions import ToolError

    from job_analyzer.mcp_server import server
    assert {t.name for t in anyio.run(server.list_tools)} == {
        "list_applications", "add_application", "update_application"}
    saved_job()
    anyio.run(server.call_tool, "add_application", {"job": URL, "applied_on": "2026-11-19"})
    assert tracker.load_applications()[jobs.url_id(URL)].status == "applied"
    with pytest.raises(ToolError, match="Already tracked"):  # the reason reaches the model
        anyio.run(server.call_tool, "add_application", {"job": URL})
