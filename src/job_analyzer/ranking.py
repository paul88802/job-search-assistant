"""Turn analyzed postings into a ranked shortlist. No AI in this file.

Order of decisions:
  1. must-haves (code, matching.py)        -> excluded jobs are listed separately with the reason
  2. preference score (code, matching.py)  -> 0-100
  3. fit score (Claude's judgement)        -> 0-100, with evidence and gaps
  overall = 60% fit + 40% preferences (fit not assessed -> preferences only, flagged)

A plain keyword score is shown next to Claude's fit score as a BASELINE, so we can
later measure whether Claude's judgement is actually better than word matching.
"""

import json
from dataclasses import dataclass
from datetime import datetime

from job_analyzer import paths
from job_analyzer.jobs import JobRecord
from job_analyzer.matching import MatchReport, evaluate
from job_analyzer.profile import Profile
from job_analyzer.search import load_candidates, load_manual_check, load_statuses

FIT_WEIGHT = 0.6


@dataclass
class Ranked:
    record: JobRecord
    report: MatchReport
    keyword_score: int | None
    overall: int


def keyword_score(record: JobRecord, cv_text: str) -> int | None:
    """Share of the posting's must-have skills that literally appear in the CV text."""
    skills = record.job.must_have_skills
    if not skills:
        return None
    text = cv_text.casefold()
    hits = sum(1 for s in skills if s.strip().casefold() in text)
    return round(100 * hits / len(skills))


def rank(records: list[JobRecord], profile: Profile, cv_text: str) -> tuple[list[Ranked], list[Ranked]]:
    included, excluded = [], []
    for rec in records:
        report = evaluate(rec.job, profile)
        fit = rec.fit.fit_score if rec.fit else None
        overall = report.score if fit is None else round(FIT_WEIGHT * fit + (1 - FIT_WEIGHT) * report.score)
        r = Ranked(rec, report, keyword_score(rec, cv_text), overall)
        (excluded if report.excluded else included).append(r)
    included.sort(key=lambda r: (r.record.fit is not None, r.overall), reverse=True)
    return included, excluded


def _read_json(path) -> object | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return None


def records_from_latest_run(records: list[JobRecord]) -> list[JobRecord]:
    run = _read_json(paths.run_file())
    if not run or "started_at" not in run:
        return records
    return [r for r in records if r.retrieved_at >= run["started_at"]]


def render_markdown(included: list[Ranked], excluded: list[Ranked], top: int) -> str:
    also_on = {c.id: c.also_seen_at for c in load_candidates()}
    out = [f"# Job shortlist ({datetime.now():%d %b %Y, %H:%M})", ""]
    if not included and not excluded:
        out.append("No analyzed postings in this run.")
    for i, r in enumerate(included[:top], 1):
        j, fit = r.record.job, r.record.fit
        where = f"{j.location or 'location not stated'}, {j.remote_policy}"
        out.append(f"## {i}. {j.title} @ {j.company or 'unknown company'} ({r.overall}/100)")
        posted = f"posted {j.posted_date}" if j.posted_date else "posting date not shown"
        out.append(f"{where} · {posted} · found on {r.record.site or 'pasted'} on {r.record.retrieved_at[:10]}")
        if r.record.source_url:
            out.append(f"Link: {r.record.source_url}")
        for other in also_on.get(r.record.id, []):
            out.append(f"Also on: {other}")
        kw = f"{r.keyword_score}" if r.keyword_score is not None else "n/a"
        if fit:
            out.append(f"- **Fit {fit.fit_score}/100** (keyword baseline {kw}): {fit.summary}")
            if fit.matching_skills:
                out.append(f"- Matches: {', '.join(fit.matching_skills)}")
            if fit.gaps:
                out.append(f"- Gaps: {', '.join(fit.gaps)}")
                out.append(f"- How to address: {fit.how_to_address}")
        else:
            out.append(f"- Fit not assessed (keyword baseline {kw})")
        flags = [c.detail for c in r.report.checks if c.outcome != "match"]
        out.append(f"- Preferences {r.report.score}/100" + (f". Check: {'; '.join(flags)}" if flags else ""))
        if j.red_flags:
            out.append(f"- Red flags: {'; '.join(j.red_flags)}")
        out.append("")

    if excluded:
        out += ["## Excluded (breaks a must-have)", ""]
        for r in excluded:
            j = r.record.job
            link = f" ({r.record.source_url})" if r.record.source_url else ""
            out.append(f"- {j.title} @ {j.company or '?'}{link}: {'; '.join(r.report.exclusion_reasons)}")
        out.append("")

    out += _manual_section()
    out += _coverage_section()
    return "\n".join(out)


def _manual_section() -> list[str]:
    """Postings only found on sites that block automated reading (e.g. LinkedIn)."""
    manual = load_manual_check()
    if not manual:
        return []
    lines = ["## Check these yourself (site blocks automated reading)", "",
             "Open the link; paste the text into /analyze-job to get a fit score.", ""]
    for c in manual:
        meta = ", ".join(x for x in (c.location, f"posted {c.posted_date}" if c.posted_date else None) if x)
        lines.append(f"- {c.title} @ {c.company or '?'}" + (f" ({meta})" if meta else "") + f": {c.url}")
    lines.append("")
    return lines


def _analysis_errors() -> list[dict]:
    errors = [{**s, "url": s.get("url", job_id)} for job_id, s in load_statuses().items()
              if s.get("status") == "error"]
    legacy = _read_json(paths.analysis_errors_file()) or []  # written by older coordinator versions
    return errors + [e for e in legacy if isinstance(e, dict)]


def _coverage_section() -> list[str]:
    """Report what could NOT be searched or read, so gaps are visible instead of silently missing."""
    coverage = _read_json(paths.coverage_file()) or {}
    lines = ["## Coverage", ""]
    for group, s in (coverage.get("groups") or {}).items():
        status = "searched" if not s["errors"] else f"{s['errors']} failed search(es)"
        lines.append(f"- {group}: {s['results']} result(s), {s['queries']} quer(ies), {status}")
    stats = coverage.get("stats")
    if stats:
        lines.append(
            f"- {stats.get('found', 0)} found · {stats.get('duplicates', 0)} duplicates · "
            f"{stats.get('already_analyzed', 0)} analyzed in earlier runs · "
            f"{stats.get('other_location', 0)} other location · {stats.get('too_old', 0)} too old · "
            f"{stats.get('readable', stats.get('picked', 0))} readable · "
            f"{stats.get('manual_check', 0)} to check yourself")
    for e in coverage.get("errors", []):
        retry = "temporary" if e.get("retryable") else "not retryable"
        lines.append(f"- ⚠ Search failed on {e['site']} ({e['error_type']}, {retry}): {e['detail']}")
    for e in _analysis_errors():
        lines.append(f"- ⚠ Couldn't analyze {e.get('url', '?')} ({e.get('error_type', 'error')}): {e.get('detail', '')}")
    if len(lines) == 2:
        lines.append("- No coverage data (run /find-jobs to search).")
    return lines
