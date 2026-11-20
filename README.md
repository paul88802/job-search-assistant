# Job Search Assistant

An AI job-search tool built on the Claude API. Give it your CV and it finds job postings online,
tells you how well you fit each one, and helps you apply.
I built it for my own job search.

> 🚧 Work in progress.

## Features

| Status | Feature |
|--------|---------|
| ✅ | **Posting analyzer:** turns a messy job posting into clean, typed data: title, seniority, skills, languages, location, remote policy, salary, red flags |
| ✅ | **Your profile, pre-filled from your CV:** a one-time setup reads your CV (PDF or text) and suggests job titles, keywords, location and languages; you add work arrangement and minimum salary |
| ✅ | **Preference check:** each posting is checked against your profile. Every preference is a *must* (a mismatch removes the job) or a *preference* (a mismatch only lowers the score). Missing information never removes a job, it's flagged instead |
| ✅ | **Application copy kit:** a local page with one-click *Copy* buttons for your contact details and every job, degree and certification in your CV (each field, each entry, or a whole section), copied word for word, for application forms that make you retype your CV |
| ✅ | **Salary estimate:** when a posting states no pay, Claude estimates a monthly gross and net range for your level and the contract offered (employee or contractor), with its assumptions and a confidence level, clearly marked as an estimate |
| ✅ | **Multi-agent job search** (`/find-jobs`, Claude Code): searches your chosen job sites in parallel, removes duplicates, reads the best postings in parallel, judges your CV fit with evidence, and returns a ranked shortlist with links, gaps and coverage |
| ✅ | **CV fit:** a 0-100 fit score with matching skills (with evidence), gaps and how to address them, shown next to a plain keyword-match baseline |
| ✅ | **Application tracker (CLI + MCP server):** records where you applied and each status change (interviewing, offer, rejected...), tells you when to follow up, and marks applied jobs in the shortlist. In Claude Code, just say "I applied to the Acme Corp job" |
| 🔜 | **Application helper:** tailored CV bullets and a cover-letter draft per posting |

## Two ways to run it

| | **A. Claude Code** (no API key) | **B. Standalone CLI** |
|---|---|---|
| You need | [Claude Code](https://claude.com/claude-code) | An [Anthropic API key](https://platform.claude.com/) |
| You type | `/setup-profile`, `/find-jobs`, `/analyze-job <file or URL>`, `/copy-kit` in Claude Code | `job-analyzer setup`, `job-analyzer analyze <file>`, `job-analyzer copy-kit` |
| The AI step runs | inside your Claude Code session | through the Claude API, billed per use |

Both modes share the same rules, schemas, checks and output files. In Claude Code mode the
skills in [`.claude/skills/`](.claude/skills/) get the rules from `job-analyzer spec <kind>`, and
everything Claude writes is validated by `job-analyzer import <kind> <file>` before it's used.

## How `/find-jobs` works

```
/find-jobs  (coordinator, main Claude Code session)
  ├─ job-analyzer plan             site groups; countries whose job boards need (re)research
  ├─ job-board-scout × N (if needed) finds a country's top job boards, saves them with a date
  ├─ job-analyzer brief            candidate brief built by code from your profile + CV
  ├─ job-searcher × N  (parallel)  one per site group · web search + list pages on YOUR job sites only
  │     └─ writes a validated SearchBatch: results (with location + date) + structured errors
  ├─ job-analyzer live             code: open jobs from official APIs/feeds (company boards found
  │                                in the search results + Remote OK + We Work Remotely), full text saved
  ├─ job-analyzer merge            code: drop closed links, filter region/age, dedupe,
  │                                split readable vs. check-yourself
  ├─ loop (max 3 waves):
  │    job-analyzer next           code: next candidates; failed postings are replaced (backfill)
  │    posting-analyst × N (parallel) one per posting · gets the brief in its prompt · writes a status file
  └─ job-analyzer shortlist        code: must-haves → preferences → fit → ranked list,
                                   + "check these yourself" links + coverage gaps
```

- **Live sources over search results.** Search engines keep job pages indexed long after a job is
  filled, and many job sites block automated reading. So `job-analyzer live` (plain code) reads
  sources published for automated use: the public job APIs of company boards (Greenhouse, Lever,
  Ashby), the [Remote OK](https://remoteok.com) API and We Work Remotely RSS feeds. Company boards
  are **discovered** from search hits (a hit on `jobs.lever.co/acme/...` means Acme's current
  openings can be fetched) and remembered in your profile. A search hit that its live board no
  longer lists is dropped as **closed**, and each live job's full text is saved, so analysts read
  a file instead of fetching a page.
- **Subagents start with no context.** The coordinator passes the candidate brief explicitly.
- **Each agent gets only the tools its role needs**, and a guard hook enforces it. Agents that read
  web content run with a PreToolUse hook
  ([`.claude/hooks/guard_subagent.py`](.claude/hooks/guard_subagent.py)): shell access is limited
  to `job-analyzer spec|import`, file writes to `data/inbox/`, and searchers may only open pages on
  the job sites in your profile. A prompt injection hidden in a job posting can't run commands or
  touch your CV. The prompt *asks* the agents to ignore injected instructions; the hook *guarantees* it.
- **Don't spend effort on postings that can't be read.** Postings only found on sites that block
  automated reading (LinkedIn, We Work Remotely pages), with no saved text from a feed, aren't sent
  to analysts. They appear as **"Check these yourself"** links (paste one into `/analyze-job` for a
  fit score).
- **Backfill:** when a posting fails (closed, blocked), the next one in the queue is analyzed, until
  the target number succeeded or 3× the target was tried. The progress is tracked by code from
  each analyst's status file, not by the coordinator's memory.
- **Failures are reported, never hidden.** Failed searches and unreadable or closed postings appear
  under *Coverage*. A search that simply found nothing is not an error.
- **Code does the deterministic parts** (dedupe, must-haves, ranking); Claude does the judgement (fit).
- **Duplicates = same company + job title + date posted** (ignoring "(m/f/x)" tags and "NV/SA/Ltd").
  When a job appears on several sites, the copy that can be read automatically is analyzed and the
  others (e.g. LinkedIn, for Easy Apply) are listed as "Also on". Same title with a different date is
  kept as a separate job.
- **Country job boards are researched automatically.** For each country in your profile, a
  `job-board-scout` subagent finds the top job boards once, saves them with a date, and refreshes
  them after ~3 months, so every run searches the same, reviewable list.

## Quick start

Requires Python 3.10+.

```bash
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"    # macOS/Linux: .venv/bin/python -m pip install -e ".[dev]"
```

Put your CV in `data/cv.pdf` (or `data/cv.txt`).

**A. With Claude Code:** open the folder in Claude Code and type `/setup-profile`, then
`/analyze-job <posting file or URL>` or `/copy-kit`.

**B. Standalone:** set your API key (never commit it):

```bash
$env:ANTHROPIC_API_KEY="sk-ant-..."     # PowerShell
export ANTHROPIC_API_KEY=sk-ant-...     # macOS/Linux
```

Create your profile (one time):

```bash
.venv\Scripts\job-analyzer setup
```

Analyze a posting:

```bash
.venv\Scripts\job-analyzer analyze samples/sample_posting.txt
```

Open the copy kit (reads the CV once, then reuses the result until the CV file changes):

```bash
.venv\Scripts\job-analyzer copy-kit
```

Example `analyze` output:

```
Your preferences
------------------------------------------------------------
  OK  work arrangement  (must)  Hybrid is acceptable
  OK  location          (pref)  Bucharest, Romania matches Bucharest, Romania
  ??  salary            (pref)  Posting gives gross pay (4,500 - 6,000 EUR gross/month); your minimum is net
  OK  languages         (must)  You meet: English B1

  Preference score: 85/100
```

Run the tests (no API key needed; they use a fake client):

```bash
.venv\Scripts\python -m pytest
```

Track your applications (a job's link or the JOB_ID from the shortlist):

```bash
.venv\Scripts\job-analyzer track add https://jobs.example.com/123 --on 2026-11-20
.venv\Scripts\job-analyzer track update https://jobs.example.com/123 interviewing --note "call on Tuesday"
.venv\Scripts\job-analyzer track            # open applications + what to do next
```

In Claude Code the tracker is also an MCP server (`.mcp.json`, starts `job-analyzer-mcp`), so
Claude can record applications when you mention them. Approve the `job-tracker` server when
Claude Code asks. On macOS/Linux, change `.venv/Scripts/` to `.venv/bin/` in `.mcp.json`.

Your own CV and applications go in `data/`, which is git-ignored, so personal data never gets committed.

## Project structure

```
src/job_analyzer/
  models.py     # Pydantic models = the output schemas Claude must follow
  llm.py        # The one place that calls Claude (structured outputs + refusal handling)
  extract.py    # Job posting -> JobRequirements
  cv.py         # CV (PDF/text) -> facts used as setup suggestions
  profile.py    # Your preferences (data/profile.json)
  setup.py      # First-run questions
  matching.py   # Posting vs. preferences: plain code, no AI
  copykit.py    # Builds the copy-button page (HTML-escaped, no AI)
  specs.py      # Shared rules + schemas for both modes (`spec` / `import` commands)
  jobs.py       # Saved postings: one record per link, with source + date
  search.py     # Search-batch format + merge/dedupe (no AI)
  live.py       # Live sources: company job-board APIs, Remote OK API, WWR feeds (no AI)
  brief.py      # Candidate brief handed to subagents
  ranking.py    # Shortlist ranking + coverage report (no AI)
  tracker.py    # Application tracker: statuses, history, follow-up rules (no AI)
  mcp_server.py # The tracker as MCP tools (thin wrapper over tracker.py)
  commands/     # The work behind each CLI command (cli.py only parses arguments)
.claude/skills/ # Claude Code mode: /setup-profile, /find-jobs, /analyze-job, /copy-kit
.claude/agents/ # Subagents: job-board-scout, job-searcher, posting-analyst
.claude/hooks/  # guard_subagent.py: PreToolUse guard for agents that read web content
  cli.py        # Command-line entry point
samples/        # Example job postings
tests/          # Offline tests
data/           # Your CV and applications (git-ignored)
```

## Design decisions

| Decision | Why |
|----------|-----|
| Structured outputs (`messages.parse` + Pydantic) instead of "please reply in JSON" | The API guarantees schema-valid output, so there's no fragile JSON parsing |
| Nullable fields and an `"unknown"` option in the schema | Gives the model an honest answer when a posting omits something, instead of inventing it |
| Tracker as a small MCP server that only wraps `tracker.py` | The CLI and Claude share one set of rules; the server can touch nothing but the tracker file, and a broken rule comes back to Claude as a tool error with the reason |
| Claude *extracts*, plain code *compares* | Reading messy text needs a language model; checking "is 4,500 ≥ 4,000" doesn't. The comparison is free, instant, testable and explainable |
| Values normalized during extraction (English place names, CEFR levels, ISO currencies, numeric salary) | So the comparison code can be simple and exact |
| Three outcomes per check: match / mismatch / unknown | A posting that doesn't mention salary shouldn't be thrown away |
| Must vs. preference per criterion | Lets a job slightly below your salary minimum rank lower instead of disappearing |
| CV PDFs sent directly as a `document` block | Claude reads the PDF itself, so no conversion step is needed |
| Salary estimates are a separate, labelled record with stated assumptions and confidence | An estimate must never look like the employer's offer; code refuses one when the posting already states pay |
| Copy kit text is extracted *verbatim* | Application text must be the candidate's own words, so the prompt and schema forbid rewriting |
| CV extraction cached by CV file hash **and** rules version (prompt + schema) | Same CV and same rules → no new API call; changing either re-reads the CV, so results are never stale |
| Required languages stored as "any of" groups | Expresses "English + French **or** Dutch", common in multilingual countries; "nice to have" languages never exclude a job |
| Data folder found from the project, not the current directory | Works from any folder; override with the `JOB_ANALYZER_DATA` environment variable |
| Job listings from official APIs and feeds, not search-engine results | Search engines list jobs long after they close; official sources list what is open now, with full text, and are meant for automated use |
| Company boards discovered from search hits | Even a stale search hit reveals which job board a company uses, so all its current openings can be fetched |
| The page is built by code with every value HTML-escaped | Model or CV text can't inject markup or scripts into the page |
| One spec (rules + schema) shared by API mode and Claude Code mode | The two modes can't drift apart |
| Claude Code output validated by code, with field-level errors fed back for a retry | Without the API's structured outputs nothing guarantees valid JSON, so code checks it and Claude fixes what's listed |
| Posting wrapped in `<job_posting>` tags | Separates untrusted input from instructions (helps against prompt injection) |
| Explicit `stop_reason` checks | A refused or truncated response is reported clearly instead of crashing |
| Server-side refusal fallback enabled | If the main model declines, the API retries on a fallback model in the same call |
| Tests use a fake client | Fast, free and deterministic; answer quality is checked separately with evals |

## Tech

Python · [Anthropic Python SDK](https://github.com/anthropics/anthropic-sdk-python) · Pydantic · pytest
