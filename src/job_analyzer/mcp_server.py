"""MCP server for the application tracker, so Claude can update it when you mention an application.

A thin layer: every tool calls the same functions as `job-analyzer track` (tracker.py), so the
rules (valid statuses, no future dates, no duplicates) live in one place. A broken rule becomes
a ToolError: MCP returns it as an is_error result WITH the reason, so Claude can fix the call or
ask you. (Any other exception counts as a crash, and its text stays on the server.)

It only reads and writes the tracker file: no shell, no network, no other files.

Run: `job-analyzer-mcp` (stdio). Claude Code starts it from the project's .mcp.json.
Needs the optional dependency: pip install -e ".[mcp]"
"""

from typing import Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from job_analyzer import tracker

server = MCPServer(
    name="job-tracker",
    instructions=(
        "Tracks the user's job applications. When the user says they applied somewhere, heard "
        "back, got an interview, an offer or a rejection, record it. Identify a job by its "
        "posting link or JOB_ID (from the shortlist). Dates are YYYY-MM-DD; leave a date out "
        "rather than guessing it."
    ),
)


def _call(fn, *args, **kwargs):
    """Run a tracker function; a broken rule (ValueError) goes back to Claude as a ToolError."""
    try:
        return fn(*args, **kwargs)
    except ValueError as e:
        raise ToolError(str(e)) from e


@server.tool()
def list_applications(include_closed: bool = True) -> list[dict]:
    """List tracked applications, newest first, each with its status, history and suggested next step.

    include_closed: also show rejected, withdrawn, no_response and offer entries.
    """
    return tracker.summary(include_closed=include_closed)


@server.tool()
def add_application(job: str, applied_on: str | None = None, note: str | None = None,
                    title: str | None = None, company: str | None = None) -> dict:
    """Record that the user applied to a job.

    job: the posting's link or JOB_ID. For a job the tool never saved, also give title and company.
    applied_on: YYYY-MM-DD. Leave it out if the user doesn't know the date; never guess it.
    note: optional, e.g. "applied via referral".
    Fails if the job is already tracked (use update_application instead).
    """
    a = _call(tracker.add_application, job, applied_on=applied_on, note=note, title=title, company=company)
    return a.model_dump()


@server.tool()
def update_application(job: str,
                       status: Literal["applied", "interviewing", "offer", "rejected", "withdrawn", "no_response"],
                       on: str | None = None, note: str | None = None) -> dict:
    """Change an application's status, e.g. after an interview invite or a rejection.

    job: the posting's link or JOB_ID of a tracked application.
    on: YYYY-MM-DD of the change; defaults to today.
    note: optional, e.g. "first interview with the team lead on Tuesday".
    """
    a = _call(tracker.update_application, job, status, on=on, note=note)
    return a.model_dump()


def main() -> None:
    server.run("stdio")


if __name__ == "__main__":
    main()
