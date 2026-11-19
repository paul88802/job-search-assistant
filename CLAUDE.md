# CLAUDE.md

Guidance for Claude Code when working in this repository.

## Project

Job Search Assistant: a Python app on the Claude API that analyzes job postings, matches them
against the user's CV, finds postings online and helps with applications.

## Commands

On Windows, call the venv executables directly (no activation needed):

- Install: `.venv\Scripts\python -m pip install -e ".[dev]"`
- Tests: `.venv\Scripts\python -m pytest` (offline, no API key needed)
- Setup: `.venv\Scripts\job-analyzer setup` (needs `ANTHROPIC_API_KEY` if a CV is in `data/`)
- Run: `.venv\Scripts\job-analyzer analyze samples/sample_posting.txt` (needs `ANTHROPIC_API_KEY`)
- Copy kit: `.venv\Scripts\job-analyzer copy-kit` (writes `data/copy-kit.html`; cached in `data/cv_details.json`)

## Two modes

- **API mode:** the CLI calls the Claude API (`llm.py`). Covers setup, analyze, copy-kit.
- **Claude Code mode** (no API key): the skills in `.claude/skills/` do the AI step in the session.
  They read rules + schema from `job-analyzer spec <kind>`, write JSON to `data/inbox/`, and
  validate it with `job-analyzer import <kind> <file>`. Never write to `data/profile.json`,
  `data/cv_details.json` or `data/jobs/` directly; always go through `import`.
- Rules live in ONE place (`specs.py` → the prompts in `extract.py` / `cv.py`), so both modes match.

## /find-jobs (multi-agent, Claude Code mode only)

- The `/find-jobs` skill is the **coordinator**. It runs `job-analyzer plan`, then delegates in parallel to:
  - `.claude/agents/job-board-scout`: finds a country's top job boards when they're missing or
    older than 90 days; saves them via `import country-boards`
  - `.claude/agents/job-searcher`: one per site group; writes a `SearchBatch`
  - `.claude/agents/posting-analyst`: one per posting; imports the job and a fit judgement
- Code does the deterministic steps: `live` (open jobs from Greenhouse/Lever/Ashby public APIs,
  the Remote OK API and WWR RSS; boards discovered from search hits into `watch_boards`; full text
  saved to `data/inbox/live/`), `merge` (drop search hits their live board no longer lists, region/age
  filters, dedupe by company + title + date posted, readable queue vs. check-yourself list), `next`
  (backfill from analyst status files, max 3× target attempts) and `shortlist`.
- Prefer official APIs/feeds over scraping pages. Lever/Ashby board tokens are case-sensitive:
  keep their original case, compare with `.casefold()`.
- Sites that block reading are listed in `search.HARD_TO_READ`; add new ones there when a real run
  shows 403/429 responses.
- Subagents inherit no context: everything goes in their prompt (`job-analyzer brief`).
- **Security:** every subagent has a PreToolUse hook (`.claude/hooks/guard_subagent.py`) that only
  allows `job-analyzer spec|import` in Bash and writes inside `data/inbox/`; with
  `--fetch-only-profile-domains` (job-searcher) WebFetch is limited to the profile's job sites. Keep the hook in
  every new agent that reads untrusted web content. Changes to it need tests in `tests/test_guard.py`.

## Code layout

- `src/job_analyzer/`: domain logic (`models`, `matching`, `ranking`, `search`, `jobs`, `profile`, ...).
- `src/job_analyzer/commands/`: one module per command area; `cli.py` only parses arguments.
- `tests/`: offline tests.

## Conventions

- Use the official `anthropic` SDK. All Claude calls go through `llm.py` (`MODEL = "claude-opus-5-5"`),
  which handles structured outputs, `stop_reason` checks and refusal fallback.
- Output schemas are Pydantic models in `models.py`. Normalize values during extraction
  (English names, CEFR levels, ISO currencies, YYYY-MM-DD dates) so code can compare them.
- Claude extracts and judges; plain code compares and ranks (`matching.py`, `ranking.py`,
  `search.py` have no AI). Missing data is "unknown", never a rejection.
- Tests must not call the real API: inject a fake client. Tests also never touch the real
  `data/`: an autouse fixture points `JOB_ANALYZER_DATA` at a temp folder.
- All file locations come from `paths.py` (functions, not constants).
- Cached results must be keyed by everything that affects them (input file + rules version).
- Never commit secrets or personal data. API keys come from the environment; the CV and
  applications live in `data/` (git-ignored). Public examples use made-up names (e.g. "Acme Corp").
