"""A compact, deterministic summary of the candidate for subagents.

Subagents start with an EMPTY context: they don't see the main conversation, the
profile or the CV. Everything they need must be put in their prompt explicitly.
This brief is that package. It's built by code from saved files, so every
subagent gets exactly the same facts.
"""

from job_analyzer.cv import cached_cv_details, find_cv
from job_analyzer.models import CVDetails
from job_analyzer.profile import Profile
from job_analyzer.setup import describe


def candidate_brief(profile: Profile, details: CVDetails | None) -> str:
    lines = ["# Candidate brief", "", "## Preferences (checked by code, don't re-judge them)", describe(profile)]
    if details is None:
        lines += ["", "## CV", "(CV sections not extracted yet: judge fit from the keywords above.)"]
        return "\n".join(lines)

    lines += ["", "## Experience (verbatim from the CV)"]
    for e in details.experience:
        dates = " – ".join(d for d in (e.start_date, e.end_date) if d)
        lines.append(f"### {e.job_title} @ {e.company} ({dates})")
        lines.append(e.description)
    if details.certifications:
        lines += ["", "## Certifications"]
        lines += [f"- {c.name}" + (f" ({c.issue_date})" if c.issue_date else "") for c in details.certifications]
    if details.education:
        lines += ["", "## Education"]
        lines += [f"- {e.degree or ''} {e.field_of_study or ''}, {e.institution}".strip() for e in details.education]
    return "\n".join(lines)


def cv_text(profile: Profile, details: CVDetails | None) -> str:
    """All CV text in one string, for the plain keyword baseline."""
    parts = [*profile.keywords, *profile.target_titles]
    if details:
        parts += [f"{e.job_title} {e.description}" for e in details.experience]
        parts += [c.name for c in details.certifications]
    return "\n".join(parts)


def load_details() -> CVDetails | None:
    cv_path = find_cv()
    return cached_cv_details(cv_path) if cv_path else None
